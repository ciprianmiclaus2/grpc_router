import grpc
import unittest.mock as mock
import time

from grpc_router.client.client import GRPCRouterClient
from grpc_router.core.models import HealthCheckType, HealthStatus
import pytest


@mock.patch('grpc_router.core.register.ServiceRegister.HEALTH_CHECK_LATENCY_SECONDS', new=3)
def test_client_active_health_register_miss_heartbeat_reregister(grpc_router_server_push_health_2s):
    service_id = "client.active.health.service"
    service_id2 = "client.no.active.health.service"

    client1 = GRPCRouterClient("localhost", 7654)
    client1.register_service(
        service_id, "myhost2.mydomain3.com", 4321,
        '', 10,
        HealthCheckType.ACTIVE_CLIENT
    )
    # also register a service without health checks
    client1.register_service(
        service_id2, "myhost2.mydomain3.com", 4322,
        '', 10,
        HealthCheckType.NONE
    )

    client2 = GRPCRouterClient("localhost", 7654)
    host, port = client2.get_service(service_id)
    assert host == "myhost2.mydomain3.com"
    assert port == 4321
    host, port = client2.get_service(service_id2)
    assert host == "myhost2.mydomain3.com"
    assert port == 4322

    # sleep for a few secs to allow the client to miss a heathbeat
    # the server should deregister it
    time.sleep(4)

    client2 = GRPCRouterClient("localhost", 7654)
    with pytest.raises(grpc.RpcError) as exc:
        client2.get_service(service_id)
    assert exc.value.code() == grpc.StatusCode.NOT_FOUND
    assert exc.value.details() == "The service_id has no registered instances."
    # service_id2 is still available as it has no checks
    host, port = client2.get_service(service_id2)
    assert host == "myhost2.mydomain3.com"
    assert port == 4322

    # now push a heartbeat and check the server re-registers it
    client1.set_health_status(service_id, HealthStatus.GOOD, "")

    time.sleep(1)
    client2 = GRPCRouterClient("localhost", 7654)
    host, port = client2.get_service(service_id)
    assert host == "myhost2.mydomain3.com"
    assert port == 4321
    host, port = client2.get_service(service_id2)
    assert host == "myhost2.mydomain3.com"
    assert port == 4322


@mock.patch('grpc_router.core.register.ServiceRegister.HEALTH_CHECK_LATENCY_SECONDS', new=3)
def test_client_active_health_register_miss_heartbeat_no_reregister(grpc_router_server_push_health_2s):
    service_id = "client.active.health.service"

    client1 = GRPCRouterClient("localhost", 7654)
    client1.register_service(
        service_id, "myhost2.mydomain3.com", 4321,
        '', 10,
        HealthCheckType.ACTIVE_CLIENT
    )

    client2 = GRPCRouterClient("localhost", 7654)
    host, port = client2.get_service(service_id)
    assert host == "myhost2.mydomain3.com"
    assert port == 4321

    # sleep for a few secs to allow the client to miss a heathbeat
    # the server should deregister it
    time.sleep(4)

    client2 = GRPCRouterClient("localhost", 7654)
    with pytest.raises(grpc.RpcError) as exc:
        client2.get_service(service_id)
    assert exc.value.code() == grpc.StatusCode.NOT_FOUND
    assert exc.value.details() == "The service_id has no registered instances."

    # now push a heartbeat and check the server re-registers it
    client1.set_health_status(service_id, HealthStatus.ERROR, "Still not good.")

    time.sleep(2)
    with pytest.raises(grpc.RpcError) as exc:
        client2.get_service(service_id)
    assert exc.value.code() == grpc.StatusCode.NOT_FOUND
    assert exc.value.details() == "The service_id has no registered instances."

    # now push a heartbeat and check the server re-registers it
    client1.set_health_status(service_id, HealthStatus.GOOD, "")

    time.sleep(1)
    client2 = GRPCRouterClient("localhost", 7654)
    host, port = client2.get_service(service_id)
    assert host == "myhost2.mydomain3.com"
    assert port == 4321