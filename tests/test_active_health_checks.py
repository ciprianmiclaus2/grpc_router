import time
import unittest.mock as mock

import grpc
import pytest

from grpc_router.client.client import GRPCRouterClient
from grpc_router.core.models import HealthCheckType, HealthStatus


@mock.patch('grpc_router.core.register.ServiceRegister.HEALTH_CHECK_LATENCY_SECONDS', new=3)
def test_client_active_health_register_miss_heartbeat_reregister(grpc_router_server_push_health_2s):
    service_id = "client.active.health.service"
    service_id2 = "client.no.active.health.service"

    client1 = GRPCRouterClient("localhost", 7655)
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

    client2 = GRPCRouterClient("localhost", 7655)
    host, port = client2.get_service(service_id)
    assert host == "myhost2.mydomain3.com"
    assert port == 4321
    host, port = client2.get_service(service_id2)
    assert host == "myhost2.mydomain3.com"
    assert port == 4322

    # sleep for a few secs to allow the client to miss a heathbeat
    # the server should deregister it
    time.sleep(4)

    client2 = GRPCRouterClient("localhost", 7655)
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
    client2 = GRPCRouterClient("localhost", 7655)
    host, port = client2.get_service(service_id)
    assert host == "myhost2.mydomain3.com"
    assert port == 4321
    host, port = client2.get_service(service_id2)
    assert host == "myhost2.mydomain3.com"
    assert port == 4322


@mock.patch('grpc_router.core.register.ServiceRegister.HEALTH_CHECK_LATENCY_SECONDS', new=3)
def test_client_active_health_register_miss_heartbeat_no_reregister(grpc_router_server_push_health_2s):
    service_id = "client.active.health.service"

    client1 = GRPCRouterClient("localhost", 7655)
    client1.register_service(
        service_id, "myhost2.mydomain3.com", 4321,
        '', 10,
        HealthCheckType.ACTIVE_CLIENT
    )

    client2 = GRPCRouterClient("localhost", 7655)
    host, port = client2.get_service(service_id)
    assert host == "myhost2.mydomain3.com"
    assert port == 4321

    # sleep for a few secs to allow the client to miss a heathbeat
    # the server should deregister it
    time.sleep(4)

    client2 = GRPCRouterClient("localhost", 7655)
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
    client2 = GRPCRouterClient("localhost", 7655)
    host, port = client2.get_service(service_id)
    assert host == "myhost2.mydomain3.com"
    assert port == 4321


@mock.patch('grpc_router.core.register.ServiceRegister.HEALTH_CHECK_LATENCY_SECONDS', new=1)
@mock.patch.object(GRPCRouterClient, 'HEALTH_PUSH_FREQUENCY_SECONDS', new=0.5)
def test_client_heartbeats_keep_service_registered(grpc_router_server_push_health_2s):
    # the client pushes periodic heartbeats on its own, without set_health_status() calls
    service_id = "client.heartbeat.service"
    client1 = GRPCRouterClient("localhost", 7655)
    client1.register_service(service_id, "heartbeat.mydomain.com", 4323, '', 10, HealthCheckType.ACTIVE_CLIENT)

    client2 = GRPCRouterClient("localhost", 7655)
    for _ in range(5):
        time.sleep(1)  # well past the 2s health check timeout overall
        assert client2.get_service(service_id) == ("heartbeat.mydomain.com", 4323)

    # closing the client stops the heartbeats, so the server evicts the service
    push_thread = client1._health_push_thread
    client1.close()
    assert not push_thread.is_alive()
    time.sleep(4)
    with pytest.raises(grpc.RpcError) as exc:
        client2.get_service(service_id)
    assert exc.value.code() == grpc.StatusCode.NOT_FOUND


@mock.patch.object(GRPCRouterClient, 'HEALTH_PUSH_FREQUENCY_SECONDS', new=0.05)
def test_client_heartbeats_survive_push_failures():
    # e.g. the router is restarting: a failed push must not stop later heartbeats
    client = GRPCRouterClient("localhost", 1)
    client._stub = stub = mock.Mock()
    stub.RegisterService.return_value.service_token = "token1"
    stub.PushHealthStatus.side_effect = [grpc.RpcError(), RuntimeError("boom"), None, None]
    client.register_service("svc", "host", 1234, health_check_type=HealthCheckType.ACTIVE_CLIENT)

    deadline = time.monotonic() + 5
    while stub.PushHealthStatus.call_count < 4 and time.monotonic() < deadline:
        time.sleep(0.05)
    client.close()
    assert stub.PushHealthStatus.call_count >= 4
    assert stub.PushHealthStatus.call_args.args[0].service_token == "token1"
