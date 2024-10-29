from collections import defaultdict
import datetime
import uuid
from threading import RLock
from typing import Optional

from grpc_router.core.models import ConfigOptions, HealthCheckType, HealthStatus, Service


class ServiceRegister:

    GLOBAL_REGION = ''

    def __init__(self, config: ConfigOptions):
        self._config = config
        self._register: dict[str, dict[str, list[Service]]] = {}
        self._service_counters: dict[tuple[str, Optional[str]], int] = defaultdict(int)
        self._non_global_services: dict[str, list[Service]] = defaultdict(list)
        self._lock = RLock()

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

    def deregister_service(self, service_id: str, service_token: str) -> None:
        with self._lock:
            regional_entry = self._register.get(service_id)
            if not regional_entry:
                return
            for _, entry in regional_entry.items():
                idx = self._find_svc_idx(entry, service_token)
                if idx is not None:
                    entry.pop(idx)
                    break
            entry = self._non_global_services[service_id]
            idx = self._find_svc_idx(entry, service_token)
            if idx is not None:
                entry.pop(idx)

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
            if svc:
                svc.set_health_status(
                    status=health_status,
                    description=description,
                    timestamp=datetime.datetime.now(datetime.timezone.utc)
                )
            return svc
