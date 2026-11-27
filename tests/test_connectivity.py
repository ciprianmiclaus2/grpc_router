import grpc
import pytest

from grpc_router.client.client import GRPCRouterClient


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


def test_client_context_manager(grpc_router_server):
    with GRPCRouterClient("localhost", 7654) as client:
        client.register_service("ctx.manager.service", "ctxhost", 5555)
        assert client.get_service("ctx.manager.service") == ("ctxhost", 5555)
        client.deregister_service("ctx.manager.service")
    assert client._channel is None


def test_deregister_one_instance_keeps_the_others(grpc_router_server):
    service_id = "partial.deregistration.service"
    east = GRPCRouterClient("localhost", 7654)
    west = GRPCRouterClient("localhost", 7654)
    east.register_service(service_id, "east.mydomain.com", 9101, region="USEast")
    west.register_service(service_id, "west.mydomain.com", 9102, region="USWest")

    east.deregister_service(service_id)

    client = GRPCRouterClient("localhost", 7654)
    # the deregistered instance is gone from its region and from the cross region fallback
    for region in ("USWest", "USEast", "EU", "EU", ""):
        assert client.get_service(service_id, region=region) == ("west.mydomain.com", 9102)
    west.deregister_service(service_id)


def test_register_same_service_twice_is_idempotent(grpc_router_server):
    service_id = "idempotent.registration.service"
    client1 = GRPCRouterClient("localhost", 7654)
    client2 = GRPCRouterClient("localhost", 7654)
    token = client1.register_service(service_id, "host1.mydomain.com", 9201)
    assert client1.register_service(service_id, "host1.mydomain.com", 9201) == token
    client2.register_service(service_id, "host2.mydomain.com", 9202)

    # a duplicate registration would give host1 two slots in the round robin
    client = GRPCRouterClient("localhost", 7654)
    hosts = [client.get_service(service_id)[0] for _ in range(4)]
    assert hosts == ["host1.mydomain.com", "host2.mydomain.com"] * 2
    client1.deregister_service(service_id)
    client2.deregister_service(service_id)
