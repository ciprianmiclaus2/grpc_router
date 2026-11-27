import datetime
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from threading import RLock, Thread

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
            if self._health_check_thread is None:
                self._health_check_thread = Thread(
                    target=self._health_check_thread_entrypoint,
                    name="grpc-router-health-check",
                    daemon=True,
                )
                self._health_check_thread.start()

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
        self._do_register_service(service)
        return service_token, error_str

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
            return svc

    def _take_out_of_service(self, info: HealthRegisterInfo) -> None:
        with self._lock:
            if self._remove_from_rotation(info.service.service_id, info.service.service_token):
                self._unhealthy_services[info.service.service_token] = info

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
            return svc

    def mark_service_unhealthy(self, service_id: str, service_token: str) -> None:
        """Take an in service, health checked instance out of service."""
        with self._lock:
            info = self._health_register.get(service_token)
            if info is not None and info.service.service_id == service_id:
                self._take_out_of_service(info)

    def get_service(self, service_id: str, region: str) -> Service | None:
        with self._lock:
            regional_entry = self._register.get(service_id)
            if regional_entry:
                region_key = region
                entry = regional_entry.get(region)
                if not entry and region != self.GLOBAL_REGION and self._config.allow_global_region:
                    # lookup in the global region
                    entry = regional_entry.get(self.GLOBAL_REGION)
                    region_key = self.GLOBAL_REGION
                if not entry and self._config.allow_cross_region_connectivity:
                    entry = self._non_global_services[service_id]
                    region_key = None
                if entry:
                    entry_key = (service_id, region_key)
                    counter = self._service_counters.get(entry_key, 0)
                    self._service_counters[entry_key] = counter + 1
                    return entry[counter % len(entry)]
        return None

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
                self._health_register[service_token] = info
            return svc
