from grpc_router.client.client import GRPCRouterClient
import pytest


def test_connectivity(grpc_router_server):
    service_id = "my.test.service"
    client = GRPCRouterClient("localhost", 7654)

    with pytest.raises(ValueError) as exc:
        client.get_service(service_id)
    assert str(exc.value) == "No service available."

    token = client.register_service(
        service_id=service_id,
        host="myhost.mydomain.com",
        port=9998
    )
    assert token is not None

    host, port = client.get_service(service_id)
    assert host == "myhost.mydomain.com"
    assert port == 9998

    client.deregister_service(
        service_id=service_id,
        service_token=token
    )

    with pytest.raises(ValueError) as exc:
        client.get_service(service_id)
    assert str(exc.value) == "No service available."


def test_multiple_services_round_robin(grpc_router_server):
    service_id = "my.own.test.service"

    client = GRPCRouterClient("localhost", 7654)

    token1 = client.register_service(
        service_id=service_id,
        host="myhost1.mydomain.com",
        port=9990
    )
    token2 = client.register_service(
        service_id=service_id,
        host="myhost2.mydomain.com",
        port=9991
    )
    token3 = client.register_service(
        service_id=service_id,
        host="myhost3.mydomain.com",
        port=9992
    )

    host, port = client.get_service(service_id)
    assert host == "myhost1.mydomain.com"
    assert port == 9990
    host, port = client.get_service(service_id)
    assert host == "myhost2.mydomain.com"
    assert port == 9991
    host, port = client.get_service(service_id)
    assert host == "myhost3.mydomain.com"
    assert port == 9992
    host, port = client.get_service(service_id)
    assert host == "myhost1.mydomain.com"
    assert port == 9990

    client.deregister_service(
        service_id=service_id,
        service_token=token1
    )
    client.deregister_service(
        service_id=service_id,
        service_token=token2
    )
    client.deregister_service(
        service_id=service_id,
        service_token=token3
    )
