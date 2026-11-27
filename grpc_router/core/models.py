from dataclasses import dataclass
from enum import IntEnum


class HealthCheckType(IntEnum):
    NONE = 0
    ACTIVE_CLIENT = 1
    PASSIVE_CLIENT = 2


class HealthStatus(IntEnum):
    UNKNOWN = 0
    GOOD = 1
    WARNING = 2
    ERROR = 3


@dataclass
class ConfigOptions:
    hostname: str
    port: int
    max_workers: int

    allow_global_region: bool = True
    allow_cross_region_connectivity: bool = True

    health_check_timeout: int = 300  # in seconds

    shutdown_grace: float = 5.0  # in seconds, for in-flight requests on SIGTERM/SIGINT


@dataclass
class Service:
    service_id: str
    host: str
    port: int
    region: str
    slots: int
    health_check_type: HealthCheckType
    service_token: str
