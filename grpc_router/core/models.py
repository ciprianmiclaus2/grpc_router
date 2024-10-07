from dataclasses import dataclass


@dataclass
class Service:
    service_id: str
    host: str
    port: int
    service_token: str

