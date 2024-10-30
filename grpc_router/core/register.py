from collections import defaultdict
from dataclasses import dataclass
import datetime
import uuid
from threading import RLock, Thread
import time
from typing import Optional

from grpc_router.core.models import ConfigOptions, HealthCheckType, HealthStatus, Service


@dataclass
class HealthRegisterInfo:
    service: Service
    health_status: HealthStatus
    description: str
    last_health_update: datetime.datetime


class ServiceRegister:

    GLOBAL_REGION = ''

    HEALTH_CHECK_LATENCY_SECONDS = 30

    def __init__(self, config: ConfigOptions):
        self._config = config
        self._register: dict[str, dict[str, list[Service]]] = {}
        self._service_counters: dict[tuple[str, Optional[str]], int] = defaultdict(int)
        self._non_global_services: dict[str, list[Service]] = defaultdict(list)

        # health info
        self._health_register: dict[str, HealthRegisterInfo] = {}
        self._unhealthy_services: dict[str, Service] = {}

        self._health_check_thread: Optional[Thread] = None
        self._lock = RLock()

    def _health_check_thread_entrypoint(self):
        while True:
            health_check_timeout = self._config.health_check_timeout
            utc_time_now = datetime.datetime.now(datetime.timezone.utc)
            with self._lock:
                mark_unhealthy = []
                for _, health_info in self._health_register.items():
                    if (utc_time_now - health_info.last_health_update).total_seconds() > health_check_timeout:
                        mark_unhealthy.append((
                            health_info.service.service_id,
                            health_info.service.service_token
                        ))
                for service_id, service_token in mark_unhealthy:
                    self.mark_service_unhealthy(service_id, service_token)
            time.sleep(self.HEALTH_CHECK_LATENCY_SECONDS)

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
            if service.health_check_type != HealthCheckType.NONE:
                self._health_register[service.service_token] = HealthRegisterInfo(
                    service=service,
                    health_status=HealthStatus.GOOD,
                    description='',
                    last_health_update=datetime.datetime.now(datetime.timezone.utc)
                )
        if self._health_check_thread is None and self._health_register:
            self._health_check_thread = Thread(target=self._health_check_thread_entrypoint)
            self._health_check_thread.daemon = True
            self._health_check_thread.start()

    def register_service(self, service_id: str, host: str, port: int, region: str, slots: int, health_check_type: HealthCheckType) -> tuple[str, str]:
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

    def resolve_service(self, service_id: str, service_token: str) -> Optional[Service]:
        with self._lock:
            regional_entry = self._register.get(service_id)
            if not regional_entry:
                return
            for _, entry in regional_entry.items():
                idx = self._find_svc_idx(entry, service_token)
                if idx is not None:
                    return entry[idx]

    def _find_svc_idx(self, entry_lst: list[Service], service_token: str) -> Optional[int]:
        for idx, svc in enumerate(entry_lst):
            if svc.service_token == service_token:
                return idx

    def deregister_service(self, service_id: str, service_token: str) -> Optional[Service]:
        with self._lock:
            regional_entry = self._register.get(service_id)
            if not regional_entry:
                return
            svc: Optional[Service] = None
            for _, entry in regional_entry.items():
                idx = self._find_svc_idx(entry, service_token)
                if idx is not None:
                    svc = entry.pop(idx)
                    break
            entry = self._non_global_services[service_id]
            idx = self._find_svc_idx(entry, service_token)
            if idx is not None:
                svc = entry.pop(idx)
            if svc and svc.health_check_type != HealthCheckType.NONE:
                del self._health_register[svc.service_token]
            return svc

    def mark_service_unhealthy(self, service_id: str, service_token: str) -> None:
        with self._lock:
            svc = self.deregister_service(service_id, service_token)
            if svc:
                self._unhealthy_services[service_token] = svc

    def get_service(self, service_id: str, region: str) -> Optional[Service]:
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

    def push_health_status(self, service_id: str, service_token: str, health_status: HealthStatus, description: str) -> Optional[Service]:
        with self._lock:
            svc = self.resolve_service(service_id, service_token)
            if svc is None and health_status != HealthStatus.ERROR:
                # check if it's on the unhealthy list
                svc = self._unhealthy_services.get(service_token)
                if svc:
                    # re-register it
                    self._do_register_service(svc)
            if svc and svc.health_check_type != HealthCheckType.NONE:
                self._health_register[svc.service_token] = HealthRegisterInfo(
                    service=svc,
                    health_status=health_status,
                    description=description,
                    last_health_update=datetime.datetime.now(datetime.timezone.utc)
                )
            return svc
