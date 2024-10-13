import uuid
from typing import Optional

from grpc_router.core.models import Service


class ServiceRegister:

    GLOBAL_REGION = ''

    def __init__(self):
        self._register: dict[str, dict[str, list[Service]]] = {}
        self._service_counters: dict[str, int] = {}

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
        regional_entry.append(
            Service(
                service_id=service_id,
                host=host,
                port=port,
                region=region,
                slots=slots,
                service_token=service_token
            )
        )
        return service_token, error_str

    def deregister_service(self, service_id: str, service_token: str) -> str:
        regional_entry = self._register.get(service_id)
        if not regional_entry:
            return 'Cannot find service_id: {service_id}'
        for _, entry in regional_entry.items():
            for idx, svc in enumerate(entry):
                if svc.service_token == service_token:
                    entry.pop(idx)
                    return ''
        return f'Cannot find a service with {service_token=} for {service_id}'

    def get_service(self, service_id: str, region: str) -> Optional[Service]:
        regional_entry = self._register.get(service_id)
        if regional_entry:
            entry = regional_entry.get(region)
            if not entry and region != self.GLOBAL_REGION:
                # lookup in the generic region
                entry = regional_entry.get(self.GLOBAL_REGION)
            if entry:
                counter = self._service_counters.get(service_id, 0)
                self._service_counters[service_id] = counter + 1
                return entry[counter % len(entry)]
