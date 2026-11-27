from dataclasses import dataclass
from enum import IntEnum


class HealthCheckType(IntEnum):
    """How the router checks that a registered service is alive.

    Attributes:
        NONE: No health checks: the service stays registered until it deregisters.
        ACTIVE_CLIENT: The service pushes heartbeats to the router (`GRPCRouterClient` does it).
        PASSIVE_CLIENT: The router polls the service. Not implemented yet.
    """

    NONE = 0
    ACTIVE_CLIENT = 1
    PASSIVE_CLIENT = 2


class HealthStatus(IntEnum):
    """Health status a service reports with its heartbeats.

    `ERROR` takes the service out of service; any other status keeps it in, or puts it back in, service.
    """

    UNKNOWN = 0
    GOOD = 1
    WARNING = 2
    ERROR = 3


@dataclass
class ConfigOptions:
    """Configuration of the router.

    Attributes:
        hostname: Hostname or address to bind to, e.g. `"[::]"` for all interfaces.
        port: Port to bind to; 0 picks a free port (see `GRPCRouter.port`).
        allow_global_region: Allow services to register without a region (the global region), and
            fall back to global services when a client's region has none.
        allow_cross_region_connectivity: Fall back to services of other regions when neither the
            client's region nor the global region has any.
        health_check_timeout: Seconds without a heartbeat after which an `ACTIVE_CLIENT` service is
            taken out of service.
        unhealthy_expiry_timeout: Seconds without any health push after which an out of service
            instance is forgotten; it then has to register again.
        shutdown_grace: Seconds in-flight requests get to complete on SIGTERM/SIGINT.
        state_file: Path of the JSON file to save the register to and reload it from on start;
            `None` disables persistence.
        state_save_interval: The state file is saved at most once per this many seconds.
    """

    hostname: str = "[::]"
    port: int = 50034

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
