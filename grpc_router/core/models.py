from dataclasses import dataclass
import datetime
from enum import Enum
from typing import Optional


class HealthCheckType(Enum):
    NONE = 0
    ACTIVE_CLIENT = 1
    PASSIVE_CLIENT = 2


class HealthStatus(Enum):
    UNKNOWN = 0
    GOOD = 1
    WARNING = 2
    ERROR = 3


@dataclass
class ConfigOptions:
    hostname: str
    port: int
    max_workers: int

    allow_global_region: bool=True
    allow_cross_region_connectivity: bool=True


@dataclass
class ServiceHealthStatus:
    status: HealthStatus
    description: str
    timestamp: datetime.datetime


@dataclass
class Service:
    service_id: str
    host: str
    port: int
    region: str
    slots: int
    health_check_type: HealthCheckType
    service_token: str

    health_status: Optional[ServiceHealthStatus] = None


    def set_health_status(self, status: HealthStatus, description: str, timestamp: datetime.datetime) -> None:
        self.health_status = ServiceHealthStatus(
            status=status,
            description=description,
            timestamp=timestamp
        )
