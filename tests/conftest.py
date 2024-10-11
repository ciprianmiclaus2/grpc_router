import pytest
from threading import Thread

from grpc_router.server import serve


@pytest.fixture(scope="session")
def grpc_router_server():
    thread = Thread(target=serve, args=("localhost", 7654, 1))
    thread.daemon = True
    thread.start()
    yield
