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
    # seconds without any health push after which an out of service instance is forgotten
    unhealthy_expiry_timeout: int = 900

    shutdown_grace: float = 5.0  # in seconds, for in-flight requests on SIGTERM/SIGINT

    # write-behind persistence of the register: path of the JSON state file (None: disabled)
    state_file: str | None = None
    state_save_interval: float = 1.0  # in seconds, at most one save per interval


@dataclass
class Service:
    service_id: str
    host: str
    port: int
    region: str
    slots: int
    health_check_type: HealthCheckType
    service_token: str
