from dataclasses import dataclass


@dataclass
class Service:
    service_id: str
    host: str
    port: int
    region: str
    slots: int
    service_token: str
