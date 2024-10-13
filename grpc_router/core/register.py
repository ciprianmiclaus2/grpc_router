from collections import defaultdict
import uuid
from typing import Optional

from grpc_router.core.models import ConfigOptions, Service


class ServiceRegister:

    GLOBAL_REGION = ''

    def __init__(self, config: ConfigOptions):
        self._config = config
        self._register: dict[str, dict[str, list[Service]]] = {}
        self._service_counters: dict[tuple[str, Optional[str]], int] = defaultdict(int)
        self._non_global_services: dict[str, list[Service]] = defaultdict(list)

    def register_service(self, service_id: str, host: str, port: int, region: str, slots: int) -> tuple[str, str]:
        error_str = ''
        entry = self._register.get(service_id)
        if entry is None:
            entry = {}
            self._register[service_id] = entry
        regional_entry = entry.get(region)
        if regional_entry is None:
            regional_entry = []
            entry[region] = regional_entry
        service_token = str(uuid.uuid4())
        service = Service(
            service_id=service_id,
            host=host,
            port=port,
            region=region,
            slots=slots,
            service_token=service_token
        )
        regional_entry.append(service)
        if region != self.GLOBAL_REGION:
            self._non_global_services[service_id].append(service)
        return service_token, error_str

    def deregister_service(self, service_id: str, service_token: str) -> None:
        regional_entry = self._register.get(service_id)
        if not regional_entry:
            return
        for _, entry in regional_entry.items():
            for idx, svc in enumerate(entry):
                if svc.service_token == service_token:
                    entry.pop(idx)
        entry = self._non_global_services[service_id]
        for idx, svc in enumerate(entry):
            if svc.service_token == service_token:
                entry.pop(idx)

    def get_service(self, service_id: str, region: str) -> Optional[Service]:
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
