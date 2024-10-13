from dataclasses import dataclass


@dataclass
class ConfigOptions:
    hostname: str
    port: int
    max_workers: int

    allow_global_region: bool=True
    allow_cross_region_connectivity: bool=True


@dataclass
class Service:
    service_id: str
    host: str
    port: int
    region: str
    slots: int
    service_token: str
