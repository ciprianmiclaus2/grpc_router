import copy
import threading
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


@mock.patch('grpc_router.core.register.ServiceRegister.HEALTH_CHECK_LATENCY_SECONDS', new=1)
@mock.patch.object(GRPCRouterClient, 'HEALTH_PUSH_FREQUENCY_SECONDS', new=0.5)
def test_client_reports_error_then_recovers(grpc_router_server_push_health_2s, caplog):
    service_id = "client.error.service"
    service = GRPCRouterClient("localhost", 7655)
    service.register_service(service_id, "error.mydomain.com", 4324, '', 10, HealthCheckType.ACTIVE_CLIENT)
    client = GRPCRouterClient("localhost", 7655)
    assert client.get_service(service_id) == ("error.mydomain.com", 4324)

    service.set_health_status(service_id, HealthStatus.ERROR, "Database down.")
    time.sleep(3)  # several ERROR heartbeats, and past the 2s health check timeout
    with pytest.raises(grpc.RpcError) as exc:
        client.get_service(service_id)
    assert exc.value.code() == grpc.StatusCode.NOT_FOUND
    # the router accepts the heartbeats of an out of service instance
    assert "Failed to publish health status" not in caplog.text

    service.set_health_status(service_id, HealthStatus.GOOD, "")
    time.sleep(1)
    assert client.get_service(service_id) == ("error.mydomain.com", 4324)
    service.close()


ROUTER_RESTART_PORT = 7657


def _start_router():
    from grpc_router.core.models import ConfigOptions
    from grpc_router.server import BackgroundRouter
    return BackgroundRouter(ConfigOptions(hostname="localhost", port=ROUTER_RESTART_PORT)).start()


def _wait_for(predicate, timeout: float = 5) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def _available(client: GRPCRouterClient, service_id: str) -> bool:
    try:
        client.get_service(service_id)
        return True
    except grpc.RpcError as exc:
        # NOT_FOUND, or the router is not reachable (yet)
        assert exc.code() in (grpc.StatusCode.NOT_FOUND, grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED)
        return False


@mock.patch.object(GRPCRouterClient, 'HEALTH_PUSH_FREQUENCY_SECONDS', new=0.3)
@pytest.mark.parametrize("status_before_restart", [HealthStatus.GOOD, HealthStatus.ERROR])
def test_client_registers_again_when_router_forgets_it(status_before_restart):
    # a router restart without a state file: the heartbeats get NOT_FOUND
    service_id = "router.restart.service"
    router = _start_router()
    # the default retry policy backs off up to 5s, then 10s, when the router is down: shorten it
    fast_retries = copy.deepcopy(GRPCRouterClient.DEFAULT_GRPC_SERVICE_CONFIG)
    fast_retries["methodConfig"][0]["retryPolicy"].update(initialBackoff="0.1s", maxBackoff="0.2s")
    service = GRPCRouterClient("localhost", ROUTER_RESTART_PORT, grpc_service_config=fast_retries)
    client = None
    try:
        token = service.register_service(service_id, "restart.mydomain.com", 4325, '', 10, HealthCheckType.ACTIVE_CLIENT)
        service.set_health_status(service_id, status_before_restart, "")
        router.stop()
        router = _start_router()

        client = GRPCRouterClient("localhost", ROUTER_RESTART_PORT, grpc_service_config=fast_retries)
        if status_before_restart == HealthStatus.GOOD:
            assert _wait_for(lambda: _available(client, service_id))
            assert client.get_service(service_id) == ("restart.mydomain.com", 4325)
        else:
            # registered again, but its current ERROR status keeps it out of service
            assert _wait_for(lambda: service._service_register[service_id]["token"] != token)
            time.sleep(1)
            assert not _available(client, service_id)
            service.set_health_status(service_id, HealthStatus.GOOD, "")
            assert _wait_for(lambda: _available(client, service_id))
        assert service._service_register[service_id]["token"] != token
    finally:
        service.close()
        if client is not None:
            client.close()
        router.stop()


class _NotFound(grpc.RpcError, grpc.Call):
    def code(self):
        return grpc.StatusCode.NOT_FOUND

    def details(self):
        return "The service could not be found."

    def initial_metadata(self):
        return None

    def trailing_metadata(self):
        return None

    def is_active(self):
        return False

    def time_remaining(self):
        return None

    def cancel(self):
        return False

    def add_callback(self, callback):
        return False


@mock.patch.object(GRPCRouterClient, 'HEALTH_PUSH_FREQUENCY_SECONDS', new=0.05)
def test_deregister_during_reregistration_does_not_revive_the_service():
    client = GRPCRouterClient("localhost", 1)
    client._stub = stub = mock.Mock()
    stub.RegisterService.return_value.service_token = "token1"
    client.register_service("svc", "host", 1234, health_check_type=HealthCheckType.ACTIVE_CLIENT)

    reregistered = threading.Event()

    def register_while_deregistering(request):
        client.deregister_service("svc")  # the application deregisters while the thread re-registers
        reregistered.set()
        return mock.Mock(service_token="token2")

    stub.PushHealthStatus.side_effect = _NotFound()
    stub.RegisterService.side_effect = register_while_deregistering
    assert reregistered.wait(5)
    client.close()

    # token1 deregistered by the application, token2 undone by the push thread
    tokens = [c.args[0].service_token for c in stub.DeregisterService.call_args_list]
    assert tokens == ["token1", "token2"]
    assert client._service_register == {}
