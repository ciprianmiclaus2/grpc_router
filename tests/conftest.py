import pytest
from threading import Thread

from grpc_router.core.models import ConfigOptions
from grpc_router.server import serve


@pytest.fixture(scope="session")
def grpc_router_server():
    config = ConfigOptions(
        hostname="localhost",
        port=7654,
        max_workers=1,
        allow_global_region=True,
        allow_cross_region_connectivity=True
    )
    thread = Thread(target=serve, args=(config, ))
    thread.daemon = True
    thread.start()
    yield


@pytest.fixture(scope="session")
def grpc_router_server_no_allow_global_region():
    config = ConfigOptions(
        hostname="localhost",
        port=7653,
        max_workers=1,
        allow_global_region=False,
        allow_cross_region_connectivity=True
    )
    thread = Thread(target=serve, args=(config, ))
    thread.daemon = True
    thread.start()
    yield


@pytest.fixture(scope="session")
def grpc_router_server_no_cross_region():
    config = ConfigOptions(
        hostname="localhost",
        port=7652,
        max_workers=1,
        allow_global_region=True,
        allow_cross_region_connectivity=False
    )
    thread = Thread(target=serve, args=(config, ))
    thread.daemon = True
    thread.start()
    yield


@pytest.fixture(scope="session")
def grpc_router_server_no_global_region_no_cross_region():
    config = ConfigOptions(
        hostname="localhost",
        port=7652,
        max_workers=1,
        allow_global_region=False,
        allow_cross_region_connectivity=False
    )
    thread = Thread(target=serve, args=(config, ))
    thread.daemon = True
    thread.start()
    yield