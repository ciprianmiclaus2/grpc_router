import datetime
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock, Thread
from typing import Any

from grpc_router.core.models import ConfigOptions, HealthCheckType, HealthStatus, Service


@dataclass
class HealthRegisterInfo:
    service: Service
    health_status: HealthStatus
    description: str
    last_health_update: datetime.datetime


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class ServiceRegister:
    """In-memory register of the service instances.

    Instances are "in service" (handed out by get_service) or, for health checked
    instances only, "out of service": when they miss heartbeats for longer than
    config.health_check_timeout or report HealthStatus.ERROR. Out of service instances
    keep their token and go back in service as soon as they push a status other than
    ERROR. They are forgotten once they have not pushed anything (ERROR included) for
    config.unhealthy_expiry_timeout seconds; they then need to register again.

    A registration replaces the entries of the same service_id, host and port that look
    dead (a restarted service): out of service entries, entries that missed heartbeats
    and entries without health checks (the router cannot tell whether those are alive).

    on_change, when set, is called (under the register lock) after every change worth
    persisting: anything but a heartbeat that only refreshes the last health update.

    on_rotation_change, when set, is called (under the register lock, from any thread) with the
    service_id whose in service instances changed. It must be quick and must not block.
    """

    GLOBAL_REGION = ''

    HEALTH_CHECK_LATENCY_SECONDS = 30

    def __init__(self, config: ConfigOptions):
        self._config = config
        self._register: dict[str, dict[str, list[Service]]] = {}
        self._service_counters: dict[tuple[str, str | None], int] = defaultdict(int)
        self._non_global_services: dict[str, list[Service]] = defaultdict(list)

        # health info of the health checked instances, keyed by service token
        self._health_register: dict[str, HealthRegisterInfo] = {}  # in service
        self._unhealthy_services: dict[str, HealthRegisterInfo] = {}  # out of service

        self._health_check_thread: Thread | None = None
        self._lock = RLock()
        self.on_change: Callable[[], None] | None = None
        self.on_rotation_change: Callable[[str], None] | None = None

    def _changed(self) -> None:
        if self.on_change is not None:
            self.on_change()

    def _ensure_health_check_thread(self) -> None:
        with self._lock:
            if self._health_check_thread is None:
                self._health_check_thread = Thread(
                    target=self._health_check_thread_entrypoint,
                    name="grpc-router-health-check",
                    daemon=True,
                )
                self._health_check_thread.start()

    def _health_check_thread_entrypoint(self) -> None:
        while True:
            self.check_health()
            time.sleep(self.HEALTH_CHECK_LATENCY_SECONDS)

    def check_health(self, now: datetime.datetime | None = None) -> None:
        """Take out of service the instances that missed heartbeats and forget the
        out of service instances that went silent."""
        now = now or _utc_now()
        with self._lock:
            missed = [
                info for info in self._health_register.values()
                if (now - info.last_health_update).total_seconds() > self._config.health_check_timeout
            ]
            for info in missed:
                # keep the time of the last heartbeat: the expiry counts from it
                self._take_out_of_service(info)
            expired = [
                token for token, info in self._unhealthy_services.items()
                if (now - info.last_health_update).total_seconds() > self._config.unhealthy_expiry_timeout
            ]
            for token in expired:
                del self._unhealthy_services[token]
            if expired:
                self._changed()

    def _do_register_service(self, service: Service) -> None:
        service_id = service.service_id
        region = service.region
        with self._lock:
            entry = self._register.get(service_id)
            if entry is None:
                entry = {}
                self._register[service_id] = entry
            regional_entry = entry.get(region)
            if regional_entry is None:
                regional_entry = []
                entry[region] = regional_entry
            regional_entry.append(service)
            self._rotation_changed(service_id)
            if region != self.GLOBAL_REGION:
                self._non_global_services[service_id].append(service)
            if service.health_check_type == HealthCheckType.NONE:
                return
            self._health_register[service.service_token] = HealthRegisterInfo(
                service=service,
                health_status=HealthStatus.GOOD,
                description='',
                last_health_update=_utc_now()
            )
            self._ensure_health_check_thread()

    def register_service(
        self, service_id: str, host: str, port: int, region: str, slots: int, health_check_type: HealthCheckType
    ) -> tuple[str, str]:
        error_str = ''
        service_token = str(uuid.uuid4())
        service = Service(
            service_id=service_id,
            host=host,
            port=port,
            region=region,
            slots=slots,
            health_check_type=health_check_type,
            service_token=service_token
        )
        with self._lock:
            self._replace_dead_entries(service_id, host, port)
            self._do_register_service(service)
            self._changed()
        return service_token, error_str

    def _replace_dead_entries(self, service_id: str, host: str, port: int) -> None:
        now = _utc_now()

        def same_address(svc: Service) -> bool:
            return svc.host == host and svc.port == port

        for entry in list(self._register.get(service_id, {}).values()):
            for svc in [svc for svc in entry if same_address(svc)]:
                info = self._health_register.get(svc.service_token)
                if (
                    svc.health_check_type == HealthCheckType.NONE
                    or info is None
                    or (now - info.last_health_update).total_seconds() > self._config.health_check_timeout
                ):
                    self._remove_from_rotation(service_id, svc.service_token)
        for token, info in list(self._unhealthy_services.items()):
            if info.service.service_id == service_id and same_address(info.service):
                del self._unhealthy_services[token]

    def resolve_service(self, service_id: str, service_token: str) -> Service | None:
        with self._lock:
            regional_entry = self._register.get(service_id)
            if regional_entry:
                for _, entry in regional_entry.items():
                    idx = self._find_svc_idx(entry, service_token)
                    if idx is not None:
                        return entry[idx]
        return None

    def _find_svc_idx(self, entry_lst: list[Service], service_token: str) -> int | None:
        for idx, svc in enumerate(entry_lst):
            if svc.service_token == service_token:
                return idx
        return None

    def _remove_from_rotation(self, service_id: str, service_token: str) -> Service | None:
        with self._lock:
            regional_entry = self._register.get(service_id)
            if not regional_entry:
                return None
            svc: Service | None = None
            for _, entry in regional_entry.items():
                idx = self._find_svc_idx(entry, service_token)
                if idx is not None:
                    svc = entry.pop(idx)
                    break
            entry = self._non_global_services[service_id]
            idx = self._find_svc_idx(entry, service_token)
            if idx is not None:
                svc = entry.pop(idx)
            self._health_register.pop(service_token, None)
            if svc is not None:
                self._rotation_changed(service_id)
            return svc

    def _take_out_of_service(self, info: HealthRegisterInfo) -> None:
        with self._lock:
            if self._remove_from_rotation(info.service.service_id, info.service.service_token):
                self._unhealthy_services[info.service.service_token] = info
                self._ensure_health_check_thread()
                self._changed()

    def _get_out_of_service(self, service_id: str, service_token: str) -> HealthRegisterInfo | None:
        info = self._unhealthy_services.get(service_token)
        if info is None or info.service.service_id != service_id:
            return None
        return info

    def deregister_service(self, service_id: str, service_token: str) -> Service | None:
        """Remove an instance, whether it is in service or out of service."""
        with self._lock:
            svc = self._remove_from_rotation(service_id, service_token)
            info = self._get_out_of_service(service_id, service_token)
            if info is not None:
                del self._unhealthy_services[service_token]
                svc = info.service
            if svc is not None:
                self._changed()
            return svc

    def mark_service_unhealthy(self, service_id: str, service_token: str) -> None:
        """Take an in service, health checked instance out of service."""
        with self._lock:
            info = self._health_register.get(service_token)
            if info is not None and info.service.service_id == service_id:
                self._take_out_of_service(info)

    def _rotation_changed(self, service_id: str) -> None:
        if self.on_rotation_change is not None:
            self.on_rotation_change(service_id)

    def _eligible_instances(self, service_id: str, region: str) -> tuple[str | None, list[Service]]:
        """The in service instances a client in region may use, and the round robin key of that group:
        its region's, else the global region's (if allowed), else all the regions' (if allowed)."""
        regional_entry = self._register.get(service_id)
        if not regional_entry:
            return region, []
        entry = regional_entry.get(region)
        if entry:
            return region, entry
        if region != self.GLOBAL_REGION and self._config.allow_global_region:
            entry = regional_entry.get(self.GLOBAL_REGION)
            if entry:
                return self.GLOBAL_REGION, entry
        if self._config.allow_cross_region_connectivity:
            return None, self._non_global_services[service_id]
        return region, []

    def get_service(self, service_id: str, region: str) -> Service | None:
        """The next instance, round robin, among the ones a client in region may use."""
        return self.pick_service(service_id, region)[0]

    def pick_service(self, service_id: str, region: str) -> tuple[Service | None, list[Service]]:
        """get_service() and get_service_instances(), consistently with each other."""
        with self._lock:
            region_key, entry = self._eligible_instances(service_id, region)
            if not entry:
                return None, []
            entry_key = (service_id, region_key)
            counter = self._service_counters.get(entry_key, 0)
            self._service_counters[entry_key] = counter + 1
            return entry[counter % len(entry)], list(entry)

    def get_service_instances(self, service_id: str, region: str) -> list[Service]:
        """All the instances a client in region may use (the ones get_service picks from)."""
        with self._lock:
            return list(self._eligible_instances(service_id, region)[1])

    def push_health_status(
        self, service_id: str, service_token: str, health_status: HealthStatus, description: str
    ) -> Service | None:
        """Record a status pushed by an instance; None if the instance is unknown.

        For health checked instances: ERROR takes an in service instance out of service,
        and any other status puts an out of service instance back in service. Every push,
        ERROR included, counts as a sign of life for the expiry of out of service instances.
        """
        with self._lock:
            svc = self.resolve_service(service_id, service_token)
            in_service = svc is not None
            if svc is None:
                out_of_service = self._get_out_of_service(service_id, service_token)
                if out_of_service is None:
                    return None
                svc = out_of_service.service
            elif svc.health_check_type == HealthCheckType.NONE:
                return svc

            previous = self._health_register.get(service_token) if in_service else self._unhealthy_services[service_token]
            info = HealthRegisterInfo(
                service=svc, health_status=health_status, description=description, last_health_update=_utc_now()
            )
            if health_status == HealthStatus.ERROR:
                if in_service:
                    self._take_out_of_service(info)
                else:
                    self._unhealthy_services[service_token] = info
            else:
                if not in_service:
                    del self._unhealthy_services[service_token]
                    self._do_register_service(svc)
                    self._changed()
                self._health_register[service_token] = info
            if previous is None or (previous.health_status, previous.description) != (health_status, description):
                self._changed()
            return svc

    # --- persistence -----------------------------------------------------------------

    def snapshot(self) -> list[dict[str, Any]]:
        """All the instances as plain data, in service ones in round robin order."""
        def to_dict(svc: Service, in_service: bool, info: HealthRegisterInfo | None) -> dict[str, Any]:
            return {
                "service_id": svc.service_id,
                "host": svc.host,
                "port": svc.port,
                "region": svc.region,
                "slots": svc.slots,
                "health_check_type": HealthCheckType(svc.health_check_type).name,
                "service_token": svc.service_token,
                "in_service": in_service,
                "health_status": info.health_status.name if info else HealthStatus.UNKNOWN.name,
                "description": info.description if info else "",
            }

        with self._lock:
            instances = [
                to_dict(svc, True, self._health_register.get(svc.service_token))
                for regions in self._register.values()
                for entry in regions.values()
                for svc in entry
            ]
            instances += [to_dict(info.service, False, info) for info in self._unhealthy_services.values()]
            return instances

    def restore(self, instances: list[dict[str, Any]]) -> None:
        """Load instances from snapshot(). Health checked instances get a full
        health_check_timeout (in service) or unhealthy_expiry_timeout (out of service)
        from now to send a heartbeat, whatever the age of the snapshot."""
        # validate everything first, so that a bad entry does not leave a partial restore
        parsed = [
            (
                Service(
                    service_id=str(data["service_id"]),
                    host=str(data["host"]),
                    port=int(data["port"]),
                    region=str(data["region"]),
                    slots=int(data["slots"]),
                    health_check_type=HealthCheckType[data["health_check_type"]],
                    service_token=str(data["service_token"]),
                ),
                bool(data["in_service"]),
                HealthStatus[data["health_status"]],
                str(data["description"]),
            )
            for data in instances
        ]
        with self._lock:
            for svc, in_service, status, description in parsed:
                if in_service:
                    self._do_register_service(svc)
                    if svc.health_check_type != HealthCheckType.NONE:
                        info = self._health_register[svc.service_token]
                        info.health_status, info.description = status, description
                elif svc.health_check_type != HealthCheckType.NONE:
                    self._unhealthy_services[svc.service_token] = HealthRegisterInfo(
                        service=svc, health_status=status, description=description, last_health_update=_utc_now(),
                    )
                    self._ensure_health_check_thread()
