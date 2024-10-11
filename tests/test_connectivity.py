from grpc_router.client.client import GRPCRouterClient
import pytest


def test_connectivity(grpc_router_server):
    client = GRPCRouterClient("localhost", 7654)

    with pytest.raises(ValueError) as exc:
        client.get_service("my.test.service")
    assert str(exc.value) == "No service available."

    token = client.register_service(
        service_id="my.test.service",
        host="myhost.mydomain.com",
        port=9998
    )
    assert token is not None

    host, port = client.get_service("my.test.service")
    assert host == "myhost.mydomain.com"
    assert port == 9998

    client.deregister_service(
        service_id="my.test.service",
        service_token=token
    )

    with pytest.raises(ValueError) as exc:
        client.get_service("my.test.service")
    assert str(exc.value) == "No service available."
