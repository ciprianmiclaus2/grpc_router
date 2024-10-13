import pytest
from threading import Thread

from grpc_router.core.models import ConfigOptions
from grpc_router.server import serve


@pytest.fixture(scope="session")
def grpc_router_server():
    config = ConfigOptions(
        hostname="localhost",
        port=7654,
        max_workers=1
    )
    thread = Thread(target=serve, args=(config, ))
    thread.daemon = True
    thread.start()
    yield
