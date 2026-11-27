import datetime

import pytest

from grpc_router.core import register as register_module
from grpc_router.core.models import ConfigOptions, HealthCheckType, HealthStatus
from grpc_router.core.register import ServiceRegister

HEALTH_CHECK_TIMEOUT = 10
EXPIRY_TIMEOUT = 60
SERVICE_ID = "my.service"


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)

    def __call__(self) -> datetime.datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += datetime.timedelta(seconds=seconds)


@pytest.fixture
def clock(monkeypatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(register_module, "_utc_now", fake)
    return fake


@pytest.fixture
def register(clock) -> ServiceRegister:
    return ServiceRegister(ConfigOptions(
        hostname="localhost", port=0, max_workers=1,
        health_check_timeout=HEALTH_CHECK_TIMEOUT, unhealthy_expiry_timeout=EXPIRY_TIMEOUT,
    ))


def _register(register: ServiceRegister, host: str, health_check_type=HealthCheckType.ACTIVE_CLIENT) -> str:
    token, _ = register.register_service(SERVICE_ID, host, 1234, "", 10, health_check_type)
    return token


def _hosts(register: ServiceRegister, n: int = 4) -> list[str | None]:
    hosts = []
    for _ in range(n):
        svc = register.get_service(SERVICE_ID, "")
        hosts.append(svc.host if svc else None)
    return hosts


def _push(register: ServiceRegister, token: str, status: HealthStatus, service_id: str = SERVICE_ID):
    return register.push_health_status(service_id, token, status, "")


@pytest.mark.parametrize("recovery_status", [HealthStatus.GOOD, HealthStatus.WARNING])
def test_error_takes_instance_out_of_service_until_it_recovers(register, recovery_status):
    token_a = _register(register, "a")
    _register(register, "b")

    assert _push(register, token_a, HealthStatus.ERROR).host == "a"
    assert _hosts(register) == ["b"] * 4
    # further ERROR heartbeats are accepted (not NOT_FOUND) and keep it out of service
    assert _push(register, token_a, HealthStatus.ERROR).host == "a"
    assert _hosts(register) == ["b"] * 4

    # recovering puts it back, with the same token
    assert _push(register, token_a, recovery_status).host == "a"
    assert sorted(_hosts(register)) == ["a", "a", "b", "b"]
    assert register.resolve_service(SERVICE_ID, token_a).service_token == token_a


def test_warning_keeps_instance_in_service(register):
    token = _register(register, "a")
    assert _push(register, token, HealthStatus.WARNING).host == "a"
    assert _hosts(register) == ["a"] * 4


def test_error_is_ignored_without_health_checks(register):
    # PushHealthStatus is meant for ACTIVE_CLIENT instances; others are not health checked
    token = _register(register, "a", HealthCheckType.NONE)
    assert _push(register, token, HealthStatus.ERROR).host == "a"
    register.check_health()
    assert _hosts(register) == ["a"] * 4


def test_error_heartbeats_keep_out_of_service_instance_known(register, clock):
    token_a = _register(register, "a")
    token_b = _register(register, "b")
    _push(register, token_a, HealthStatus.ERROR)
    _push(register, token_b, HealthStatus.ERROR)

    clock.advance(EXPIRY_TIMEOUT - 10)
    _push(register, token_a, HealthStatus.ERROR)  # a keeps sending heartbeats, b went silent
    clock.advance(20)
    register.check_health()

    assert _push(register, token_b, HealthStatus.GOOD) is None  # forgotten: must register again
    assert _push(register, token_a, HealthStatus.GOOD).host == "a"
    assert _hosts(register) == ["a"] * 4


def test_missed_heartbeats_take_out_of_service_then_expire(register, clock):
    token = _register(register, "a")

    clock.advance(HEALTH_CHECK_TIMEOUT + 1)
    register.check_health()
    assert _hosts(register) == [None] * 4

    # the expiry counts from the last heartbeat (the registration here), not from the eviction
    clock.advance(EXPIRY_TIMEOUT - HEALTH_CHECK_TIMEOUT - 2)
    register.check_health()
    assert register.deregister_service(SERVICE_ID, token) is not None  # still known
    token = _register(register, "a")
    clock.advance(EXPIRY_TIMEOUT + 1)
    register.check_health()
    assert _push(register, token, HealthStatus.GOOD) is None


def test_deregister_out_of_service_instance(register):
    token = _register(register, "a")
    _push(register, token, HealthStatus.ERROR)
    assert register.deregister_service(SERVICE_ID, token).host == "a"
    assert _push(register, token, HealthStatus.GOOD) is None
    assert _hosts(register) == [None] * 4


def test_out_of_service_token_only_valid_for_its_service_id(register):
    token = _register(register, "a")
    _push(register, token, HealthStatus.ERROR)
    assert _push(register, token, HealthStatus.GOOD, service_id="other.service") is None
    assert register.deregister_service("other.service", token) is None
    assert _hosts(register) == [None] * 4
    assert _push(register, token, HealthStatus.GOOD).host == "a"
