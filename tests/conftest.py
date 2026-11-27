from collections.abc import Iterator

import pytest

from grpc_router.core.models import ConfigOptions
from grpc_router.server import BackgroundRouter


def _run_server(port: int, **config_kwargs) -> Iterator[None]:
    router = BackgroundRouter(ConfigOptions(hostname="localhost", port=port, **config_kwargs)).start()
    try:
        yield
    finally:
        router.stop()


@pytest.fixture(scope="session")
def grpc_router_server() -> Iterator[None]:
    yield from _run_server(7654, allow_global_region=True, allow_cross_region_connectivity=True)


@pytest.fixture(scope="session")
def grpc_router_server_no_allow_global_region() -> Iterator[None]:
    yield from _run_server(7653, allow_global_region=False, allow_cross_region_connectivity=True)


@pytest.fixture(scope="session")
def grpc_router_server_no_cross_region() -> Iterator[None]:
    yield from _run_server(7652, allow_global_region=True, allow_cross_region_connectivity=False)


@pytest.fixture(scope="session")
def grpc_router_server_no_global_region_no_cross_region() -> Iterator[None]:
    yield from _run_server(7651, allow_global_region=False, allow_cross_region_connectivity=False)


@pytest.fixture
def grpc_router_server_push_health_2s() -> Iterator[None]:
    # function scoped: each test gets a fresh register and health check thread
    yield from _run_server(
        7655, allow_global_region=True, allow_cross_region_connectivity=True, health_check_timeout=2
    )
