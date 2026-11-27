import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest import mock

import grpc
import pytest

from grpc_router.client.client import GRPCRouterClient
from grpc_router.client.discovery import ServiceChannelPool, WatchStream
from grpc_router.core.models import ConfigOptions, HealthCheckType, HealthStatus
from grpc_router.server import BackgroundRouter
from grpc_router.stubs.grpc_router_service_pb2 import (
    GetRegisteredServiceRequest,
    ListServiceInstancesRequest,
    ServiceSubscription,
    WatchServicesRequest,
)

ROUTER_PORT = 7654  # the session wide grpc_router_server fixture
OWN_ROUTER_PORT = 7659  # routers started and stopped by the tests here


def _request(cls, service_id: str, region: str = ""):
    request = cls(service_id=service_id)
    request.hints.region = region
    return request


def _endpoints(response) -> list[tuple[str, int]]:
    return [(i.endpoint.host, i.endpoint.port) for i in response.instances]


def _register(client: GRPCRouterClient, service_id: str, host: str, region: str = "", **kwargs) -> str:
    return client.register_service(service_id, host, 9000, region, **kwargs)


def _start_router(port: int = OWN_ROUTER_PORT, **config) -> BackgroundRouter:
    return BackgroundRouter(ConfigOptions(hostname="localhost", port=port, **config)).start()


FAST_RETRIES = {
    "methodConfig": [{
        "name": [{"service": "grpcrouter.GRPCRouterService"}],
        "retryPolicy": {
            "maxAttempts": 3, "initialBackoff": "0.1s", "maxBackoff": "0.2s", "backoffMultiplier": 2,
            "retryableStatusCodes": ["UNAVAILABLE"],
        },
    }]
}


def _wait_for(predicate, timeout: float = 5) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


# --- ListServiceInstances / GetRegisteredService ------------------------------------


def test_list_follows_the_region_preference_of_lookups(grpc_router_server):
    service_id = "list.regions.service"
    clients = [GRPCRouterClient("localhost", ROUTER_PORT) for _ in range(3)]
    _register(clients[0], service_id, "east1", "east")
    _register(clients[1], service_id, "west1", "west")
    _register(clients[2], service_id, "global1")
    stub = clients[0].stub
    try:
        assert _endpoints(stub.ListServiceInstances(_request(ListServiceInstancesRequest, service_id, "east"))) \
            == [("east1", 9000)]
        # no instance in EU: the global region's
        assert _endpoints(stub.ListServiceInstances(_request(ListServiceInstancesRequest, service_id, "EU"))) \
            == [("global1", 9000)]
        # GetRegisteredService picks from, and returns, the same list
        response = stub.GetRegisteredService(_request(GetRegisteredServiceRequest, service_id, "east"))
        assert (response.endpoint.host, _endpoints(response)) == ("east1", [("east1", 9000)])
        assert [i.region for i in response.instances] == ["east"]
    finally:
        for client in clients:
            client.deregister_service(service_id)
    # no instance: an empty list, not NOT_FOUND
    assert _endpoints(stub.ListServiceInstances(_request(ListServiceInstancesRequest, service_id))) == []


def test_list_cross_region(grpc_router_server_no_global_region_no_cross_region):
    client = GRPCRouterClient("localhost", 7651)
    _register(client, "list.no.cross.service", "east1", "east")
    try:
        assert client.get_service_instances("list.no.cross.service", "east") == [("east1", 9000)]
        assert client.get_service_instances("list.no.cross.service", "west") == []
    finally:
        client.deregister_service("list.no.cross.service")


def test_list_validation(grpc_router_server):
    with pytest.raises(grpc.RpcError) as exc:
        GRPCRouterClient("localhost", ROUTER_PORT).get_service_instances("")
    assert exc.value.code() == grpc.StatusCode.INVALID_ARGUMENT


# --- WatchServices ----------------------------------------------------------------


class _Subscriber:
    """A raw WatchServices stream, with a queue to (un)subscribe on it."""

    def __init__(self, stub, timeout: float = 20) -> None:
        self._requests: queue.SimpleQueue = queue.SimpleQueue()
        self.stream = stub.WatchServices(iter(self._requests.get, None), timeout=timeout)

    def subscribe(self, *keys: tuple[str, str]) -> None:
        self._requests.put(WatchServicesRequest(subscribe=[ServiceSubscription(service_id=s, region=r) for s, r in keys]))

    def unsubscribe(self, *keys: tuple[str, str]) -> None:
        self._requests.put(WatchServicesRequest(unsubscribe=[ServiceSubscription(service_id=s, region=r) for s, r in keys]))

    def next_updates(self) -> dict[tuple[str, str], list[tuple[str, int]]]:
        response = next(self.stream)
        return {(u.subscription.service_id, u.subscription.region): _endpoints(u) for u in response.updates}

    def close(self) -> None:
        self._requests.put(None)
        self.stream.cancel()


def test_watch_streams_changes(grpc_router_server):
    service_id = "watch.changes.service"
    key = (service_id, "")
    service = GRPCRouterClient("localhost", ROUTER_PORT)
    other = GRPCRouterClient("localhost", ROUTER_PORT)
    _register(service, service_id, "a", health_check_type=HealthCheckType.ACTIVE_CLIENT)
    watch = _Subscriber(service.stub)
    try:
        watch.subscribe(key)
        assert watch.next_updates() == {key: [("a", 9000)]}  # straight away
        _register(other, service_id, "b")
        assert watch.next_updates() == {key: [("a", 9000), ("b", 9000)]}
        service.set_health_status(service_id, HealthStatus.ERROR, "down")  # out of service
        assert watch.next_updates() == {key: [("b", 9000)]}
        other.deregister_service(service_id)
        assert watch.next_updates() == {key: []}
        service.set_health_status(service_id, HealthStatus.GOOD, "")
        assert watch.next_updates() == {key: [("a", 9000)]}
    finally:
        watch.close()
        service.deregister_service(service_id)
        service.close()


def test_one_watch_stream_for_many_services(grpc_router_server):
    east, west = ("multi.east.service", "east"), ("multi.west.service", "west")
    service = GRPCRouterClient("localhost", ROUTER_PORT)
    watch = _Subscriber(service.stub)
    try:
        watch.subscribe(east, west)
        assert watch.next_updates() == {east: [], west: []}
        # a change to one service only sends that service's update
        _register(service, east[0], "e1", "east")
        assert watch.next_updates() == {east: [("e1", 9000)]}
        _register(service, west[0], "w1", "west")
        assert watch.next_updates() == {west: [("w1", 9000)]}
        # unsubscribed: no more updates for it. The stream's messages are processed in order, but
        # not in order with other calls: wait until a probe subscribed after the unsubscription is answered
        probe = ("multi.probe.service", "")
        watch.unsubscribe(east)
        watch.subscribe(probe)
        assert watch.next_updates() == {probe: []}
        service.deregister_service(east[0])
        service.deregister_service(west[0])
        assert watch.next_updates() == {west: []}
    finally:
        watch.close()


def test_watch_validation_and_subscription_limit(grpc_router_server, monkeypatch):
    import grpc_router.server
    # the default retry policy retries RESOURCE_EXHAUSTED: see the router's answer instead
    stub = GRPCRouterClient("localhost", ROUTER_PORT, grpc_service_config=FAST_RETRIES).stub
    watch = _Subscriber(stub)
    watch.subscribe(("", ""))
    with pytest.raises(grpc.RpcError) as exc:
        watch.next_updates()
    assert exc.value.code() == grpc.StatusCode.INVALID_ARGUMENT

    monkeypatch.setattr(grpc_router.server, "MAX_SUBSCRIPTIONS_PER_WATCH", 2)
    watch = _Subscriber(stub)
    watch.subscribe(("limit.a", ""), ("limit.b", ""), ("limit.c", ""))
    with pytest.raises(grpc.RpcError) as exc:
        while True:
            watch.next_updates()
    assert exc.value.code() == grpc.StatusCode.RESOURCE_EXHAUSTED


WATCH_CLIENTS = 1000
SCALE_ROUTER_PORT = 7672


def _thread_count(pid: int) -> int | None:
    try:
        return len(os.listdir(f"/proc/{pid}/task"))  # Linux
    except OSError:
        return None


def _open_files_hard_limit() -> int | None:
    try:
        import resource
    except ImportError:
        return None  # Windows
    hard = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
    return None if hard == resource.RLIM_INFINITY else hard


def test_many_watching_clients():
    # Each watch is a coroutine on the router, not a thread. The router and the simulated clients
    # (one connection and one watch stream each) run in their own processes, as in production.
    hard_limit = _open_files_hard_limit()
    clients = WATCH_CLIENTS if hard_limit is None else min(WATCH_CLIENTS, hard_limit - 200)
    if clients < 200:
        pytest.skip(f"the limit of open files ({hard_limit}) is too low for this test")

    router = subprocess.Popen(  # raises its own limit of open files on start
        [sys.executable, "-m", "grpc_router.server", "-n", "localhost", "-p", str(SCALE_ROUTER_PORT)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    helper = None
    try:
        with grpc.insecure_channel(f"localhost:{SCALE_ROUTER_PORT}") as channel:
            grpc.channel_ready_future(channel).result(timeout=10)
        threads_idle = _thread_count(router.pid)
        helper = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("watch_clients.py")), str(SCALE_ROUTER_PORT), str(clients), "4"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        assert helper.stdout is not None and helper.stdin is not None
        assert helper.stdout.readline().strip() == "ready"
        threads_watched = _thread_count(router.pid)
        helper.stdin.write("go\n")
        helper.stdin.flush()
        result = json.loads(helper.stdout.readline())
        assert helper.wait(timeout=30) == 0

        assert result["opened"] == result["seen"] == clients, result
        assert result["fan_out"] < 5, result
        if threads_idle is not None:
            assert threads_watched - threads_idle < 10, (threads_idle, threads_watched)  # no thread per watch
    finally:
        if helper is not None and helper.poll() is None:
            helper.kill()
            helper.communicate()
        router.send_signal(signal.SIGTERM)
        output, _ = router.communicate(timeout=20)
    assert router.returncode == 0, output


# --- client: falling back to the last known instances ---------------------------------


def test_lookups_fall_back_to_cached_instances_when_router_is_down():
    service_id = "fallback.service"
    router = _start_router()
    service = GRPCRouterClient("localhost", OWN_ROUTER_PORT)
    _register(service, service_id, "a")
    _register(GRPCRouterClient("localhost", OWN_ROUTER_PORT), service_id, "b")
    client = GRPCRouterClient("localhost", OWN_ROUTER_PORT, grpc_service_config=FAST_RETRIES)
    try:
        assert client.get_service(service_id)[0] in ("a", "b")
        router.stop()

        started = time.monotonic()
        hosts = {client.get_service(service_id, timeout=1)[0] for _ in range(4)}
        assert hosts == {"a", "b"}  # round robin over the cached instances
        assert time.monotonic() - started < 6  # each lookup gives up on the router within its timeout
        assert sorted(client.get_service_instances(service_id, timeout=1)) == [("a", 9000), ("b", 9000)]
        # a service never looked up has nothing to fall back to: the router's error
        with pytest.raises(grpc.RpcError) as exc:
            client.get_service("never.looked.up", timeout=1)
        assert exc.value.code() in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED)
    finally:
        client.close()
        router.stop()


def test_not_found_clears_the_cache():
    service_id = "not.found.service"
    router = _start_router()
    service = GRPCRouterClient("localhost", OWN_ROUTER_PORT)
    client = GRPCRouterClient("localhost", OWN_ROUTER_PORT, grpc_service_config=FAST_RETRIES)
    try:
        _register(service, service_id, "a")
        client.get_service(service_id)
        service.deregister_service(service_id)
        with pytest.raises(grpc.RpcError) as exc:
            client.get_service(service_id)
        assert exc.value.code() == grpc.StatusCode.NOT_FOUND
        router.stop()
        # the router said there are none: no stale instance afterwards
        with pytest.raises(grpc.RpcError) as exc:
            client.get_service(service_id, timeout=1)
        assert exc.value.code() != grpc.StatusCode.OK
    finally:
        client.close()
        router.stop()


def test_cached_instances_expire():
    service_id = "expiry.service"
    router = _start_router()
    service = GRPCRouterClient("localhost", OWN_ROUTER_PORT)
    client = GRPCRouterClient("localhost", OWN_ROUTER_PORT, grpc_service_config=FAST_RETRIES, stale_cache_max_age=0.5)
    try:
        _register(service, service_id, "a")
        client.get_service(service_id)
        router.stop()
        time.sleep(1)
        with pytest.raises(grpc.RpcError):
            client.get_service(service_id, timeout=1)
    finally:
        client.close()
        router.stop()


# --- client: watches -----------------------------------------------------------------


def test_client_watch(grpc_router_server):
    service_id = "client.watch.service"
    service = GRPCRouterClient("localhost", ROUTER_PORT)
    client = GRPCRouterClient("localhost", ROUTER_PORT)
    updates: list[list[tuple[str, int]]] = []
    try:
        watch = client.watch_service_instances(service_id, callback=updates.append)
        assert watch.wait_for_instances(5) == []
        _register(service, service_id, "a")
        assert _wait_for(lambda: watch.instances == [("a", 9000)])

        # watched: lookups are answered without asking the router
        client.stub.GetRegisteredService = mock.Mock(side_effect=AssertionError("asked the router"))
        client.stub.ListServiceInstances = mock.Mock(side_effect=AssertionError("asked the router"))
        assert client.get_service(service_id) == ("a", 9000)
        assert client.get_service_instances(service_id) == [("a", 9000)]

        service.deregister_service(service_id)
        assert _wait_for(lambda: watch.instances == [])
        assert updates == [[], [("a", 9000)], []]
        watch.cancel()
    finally:
        client.close()


@mock.patch.object(WatchStream, "RECONNECT_SPREAD_SECONDS", 0.2)
@mock.patch.object(WatchStream, "RECONNECT_BACKOFF_SECONDS", (0.1, 0.5))
def test_client_watch_reconnects_after_router_restart():
    service_id = "watch.reconnect.service"
    router = _start_router()
    client = GRPCRouterClient("localhost", OWN_ROUTER_PORT, grpc_service_config=FAST_RETRIES)
    try:
        _register(GRPCRouterClient("localhost", OWN_ROUTER_PORT), service_id, "a")
        watch = client.watch_service_instances(service_id)
        assert _wait_for(lambda: watch.instances == [("a", 9000)])
        router.stop()

        router = _start_router()  # empty register
        _register(GRPCRouterClient("localhost", OWN_ROUTER_PORT), service_id, "b")
        assert _wait_for(lambda: watch.instances == [("b", 9000)], timeout=10)
    finally:
        client.close()
        router.stop()


# --- ServiceChannelPool -------------------------------------------------------------


def _is_closed(channel: grpc.Channel) -> bool:
    try:
        channel.unary_unary("/x/y")(b"", timeout=0.01)
    except ValueError:
        return True  # "Cannot invoke RPC on closed channel!"
    except grpc.RpcError:
        return False
    return False


def test_service_channel_pool(grpc_router_server):
    service_id = "pool.service"
    service_a = GRPCRouterClient("localhost", ROUTER_PORT)
    service_b = GRPCRouterClient("localhost", ROUTER_PORT)
    router = GRPCRouterClient("localhost", ROUTER_PORT)
    _register(service_a, service_id, "a")
    _register(service_b, service_id, "b")
    created: dict[str, grpc.Channel] = {}

    def factory(target: str) -> grpc.Channel:
        created[target] = grpc.insecure_channel(target)
        return created[target]

    pool = ServiceChannelPool(router, service_id, channel_factory=factory, retire_grace_seconds=0.2)
    try:
        channels = [pool.next_channel() for _ in range(4)]
        assert sorted(created) == ["a:9000", "b:9000"]
        assert channels[0] is channels[2] and channels[1] is channels[3] and channels[0] is not channels[1]

        service_a.deregister_service(service_id)
        assert _wait_for(lambda: pool.endpoints == [("b", 9000)])
        assert all(pool.next_channel() is created["b:9000"] for _ in range(3))
        # the retired channel stays open for calls in flight, then is closed
        assert not _is_closed(created["a:9000"])
        assert _wait_for(lambda: _is_closed(created["a:9000"]))

        service_b.deregister_service(service_id)
        assert _wait_for(lambda: pool.endpoints == [])
        with pytest.raises(LookupError):
            pool.next_channel()
    finally:
        pool.close()
        router.close()
    assert all(_is_closed(channel) for channel in created.values())


def test_service_channel_pool_closes_retired_channels_on_close(grpc_router_server):
    service_id = "pool.close.service"
    service = GRPCRouterClient("localhost", ROUTER_PORT)
    _register(service, service_id, "a")
    router = GRPCRouterClient("localhost", ROUTER_PORT)
    with ServiceChannelPool(router, service_id, retire_grace_seconds=60) as pool:
        channel = pool.next_channel()
        service.deregister_service(service_id)
        assert _wait_for(lambda: pool.endpoints == [])
        assert not _is_closed(channel)
    assert _is_closed(channel)
    assert not [t for t in threading.enumerate() if t.name.startswith("grpc-router-watch-pool")]
    router.close()


def test_failing_watch_callback_does_not_stop_the_watch(grpc_router_server, caplog):
    service_id = "watch.bad.callback.service"
    service = GRPCRouterClient("localhost", ROUTER_PORT)
    client = GRPCRouterClient("localhost", ROUTER_PORT)

    def bad_callback(instances):
        raise RuntimeError("bug in the application's callback")

    try:
        watch = client.watch_service_instances(service_id, callback=bad_callback)
        assert watch.wait_for_instances(5) == []
        _register(service, service_id, "a")
        assert _wait_for(lambda: watch.instances == [("a", 9000)])  # still receiving updates
        assert client.get_service(service_id) == ("a", 9000)
        assert "The watch callback for watch.bad.callback.service failed" in caplog.text
    finally:
        service.deregister_service(service_id)
        client.close()


def test_client_uses_one_stream_and_thread_for_all_its_watches(grpc_router_server):
    client = GRPCRouterClient("localhost", ROUTER_PORT)
    try:
        watches = [client.watch_service_instances(f"one.thread.service.{n}") for n in range(20)]
        assert all(w.wait_for_instances(5) == [] for w in watches)
        assert len([t for t in threading.enumerate() if t.name == "grpc-router-watch"]) == 1
        # two watches of the same service both get its updates
        again = client.watch_service_instances("one.thread.service.0")
        assert again.wait_for_instances(5) == []
        _register(GRPCRouterClient("localhost", ROUTER_PORT), "one.thread.service.0", "a")
        assert _wait_for(lambda: watches[0].instances == again.instances == [("a", 9000)])
        # cancelling one keeps the other
        again.cancel()
        assert client.get_service_instances("one.thread.service.0") == [("a", 9000)]
    finally:
        client.close()
    assert not [t for t in threading.enumerate() if t.name == "grpc-router-watch"]
