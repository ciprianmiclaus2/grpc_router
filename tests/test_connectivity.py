import grpc

from grpc_router.client.client import GRPCRouterClient
import pytest


def test_connectivity(grpc_router_server):
    service_id = "my.test.service"
    client = GRPCRouterClient("localhost", 7654)

    with pytest.raises(grpc.RpcError) as exc:
        client.get_service(service_id)
    assert exc.value.code() == grpc.StatusCode.NOT_FOUND
    assert exc.value.details() == "The service_id has no registered instances."

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
        service_id=service_id
    )

    with pytest.raises(grpc.RpcError) as exc:
        client.get_service(service_id)
    assert exc.value.code() == grpc.StatusCode.NOT_FOUND
    assert exc.value.details() == "The service_id has no registered instances."


def test_multiple_services_round_robin(grpc_router_server):
    service_id = "my.own.test.service"

    client1 = GRPCRouterClient("localhost", 7654)
    client2 = GRPCRouterClient("localhost", 7654)
    client3 = GRPCRouterClient("localhost", 7654)

    client1.register_service(
        service_id=service_id,
        host="myhost1.mydomain.com",
        port=9990
    )
    client2.register_service(
        service_id=service_id,
        host="myhost2.mydomain.com",
        port=9991
    )
    client3.register_service(
        service_id=service_id,
        host="myhost3.mydomain.com",
        port=9992
    )

    client = GRPCRouterClient("localhost", 7654)
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

    client1.deregister_service(
        service_id=service_id
    )
    client2.deregister_service(
        service_id=service_id
    )
    client3.deregister_service(
        service_id=service_id
    )
