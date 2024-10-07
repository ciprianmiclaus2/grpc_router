import uuid
from typing import Optional

from grpc_router.core.models import Service


class ServiceRegister:

    def __init__(self):
        self._register: dict[str, list[Service]] = {}
        self._service_counters = dict[str, int]

    def register_service(self, service_id: str, host: str, port: int) -> tuple[str, str]:
        error_str = ''
        entry = self._register.get(service_id)
        if entry is None:
            entry = []
            self._register[service_id] = entry
        service_token = str(uuid.uuid4())
        entry.append(
            Service(
                service_id=service_id,
                host=host,
                port=port,
                service_token=service_token
            )
        )
        return service_token, error_str

    def deregister_service(self, service_id: str, service_token: str) -> str:
        entry = self._register.get(service_id)
        if entry is None:
            return 'Cannot find service_id: {service_id}'
        for idx, svc in enumerate(entry):
            if svc.service_token == service_token:
                entry.pop(idx)
                return ''
        return f'Cannot find a service with {service_token=} for {service_id}'

    def get_service(self, service_id: str) -> Optional[Service]:
        entry = self._register.get(service_id)
        if entry is not None:
            # separate this simplistic round-robin in its own allocation algo class
            counter = self._service_counters.get(service_id, 0)
            self._service_counters[service_id] = counter + 1
            return entry[counter % len(entry)]
