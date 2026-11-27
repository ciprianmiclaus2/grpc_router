"""The grpc router server, on gRPC asyncio.

All the request handlers run on one event loop: the register is in memory and its
operations are short, so no request needs a thread. Watch streams are coroutines, so a
router can serve thousands of watching clients. The health checks of the register and the
state file writer run in their own threads.
"""

import argparse
import asyncio
import contextlib
import logging
import signal
import threading
from collections import defaultdict
from pathlib import Path
from types import TracebackType
from typing import Self

import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from grpc_reflection.v1alpha import reflection, reflection_pb2, reflection_pb2_grpc

from grpc_router.core.models import ConfigOptions, HealthCheckType, HealthStatus, Service
from grpc_router.core.persistence import StateWriter
from grpc_router.core.register import ServiceRegister
from grpc_router.stubs.grpc_router_service_pb2 import (
    DESCRIPTOR,
    HEALTH_CHECK_ACTIVE_CLIENT,
    HEALTH_CHECK_PASSIVE_CLIENT,
    HEALTH_STATUS_ERROR,
    HEALTH_STATUS_GOOD,
    HEALTH_STATUS_WARNING,
    GetRegisteredServiceResponse,
    HealthInfoResponse,
    ListServiceInstancesResponse,
    ServiceDeregistrationResponse,
    ServiceEndpoint,
    ServiceInstance,
    ServiceInstancesUpdate,
    ServiceRegistrationResponse,
    ServiceSubscription,
    WatchServicesResponse,
)
from grpc_router.stubs.grpc_router_service_pb2_grpc import GRPCRouterServiceServicer, add_GRPCRouterServiceServicer_to_server

SERVICE_NAME = DESCRIPTOR.services_by_name["GRPCRouterService"].full_name

# grpcio-reflection only ships the v1alpha reflection service. The v1 protocol is a copy
# of it under a new package name (identical messages on the wire), so the v1alpha
# servicer also serves v1 clients, e.g. recent grpcurl/Postman versions.
REFLECTION_V1_SERVICE_NAME = "grpc.reflection.v1.ServerReflection"

# Maximum number of (service_id, region) subscriptions of one WatchServices stream.
MAX_SUBSCRIPTIONS_PER_WATCH = 1000

logger = logging.getLogger(__name__)

SubscriptionKey = tuple[str, str]  # (service_id, region)


def to_health_check_type(health_check_type: int) -> HealthCheckType:
    if health_check_type == HEALTH_CHECK_ACTIVE_CLIENT:
        return HealthCheckType.ACTIVE_CLIENT
    elif health_check_type == HEALTH_CHECK_PASSIVE_CLIENT:
        return HealthCheckType.PASSIVE_CLIENT
    return HealthCheckType.NONE


def to_health_status(health_status: int) -> HealthStatus:
    if health_status == HEALTH_STATUS_GOOD:
        return HealthStatus.GOOD
    elif health_status == HEALTH_STATUS_ERROR:
        return HealthStatus.ERROR
    elif health_status == HEALTH_STATUS_WARNING:
        return HealthStatus.WARNING
    return HealthStatus.UNKNOWN


def _to_instances(services: list[Service]) -> list[ServiceInstance]:
    return [
        ServiceInstance(endpoint=ServiceEndpoint(host=svc.host, port=svc.port), region=svc.region)
        for svc in services
    ]


# --- watches ---------------------------------------------------------------------------


class _Watcher:
    """The state of one WatchServices stream (event loop only)."""

    def __init__(self) -> None:
        # what was last sent for each subscription; None: nothing yet
        self.sent: dict[SubscriptionKey, tuple | None] = {}
        self.dirty: set[SubscriptionKey] = set()
        self.wakeup = asyncio.Event()
        self.error: tuple[grpc.StatusCode, str] | None = None

    def mark_dirty(self, key: SubscriptionKey) -> None:
        self.dirty.add(key)
        self.wakeup.set()

    def fail(self, code: grpc.StatusCode, details: str) -> None:
        self.error = (code, details)
        self.wakeup.set()


class WatchHub:
    """Wakes up the watch streams subscribed to a service when its instances change.

    Only the streams subscribed to the changed service are woken up, whatever the number of
    streams. Lives on the event loop; notify_threadsafe() can be called from any thread.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._by_service: dict[str, set[_Watcher]] = defaultdict(set)
        self._watchers: set[_Watcher] = set()
        self.stopping = False

    def notify_threadsafe(self, service_id: str) -> None:
        with contextlib.suppress(RuntimeError):  # the event loop is closed: the router is gone
            self._loop.call_soon_threadsafe(self._notify, service_id)

    def _notify(self, service_id: str) -> None:
        for watcher in self._by_service.get(service_id, ()):
            for key in watcher.sent:
                if key[0] == service_id:
                    watcher.mark_dirty(key)

    def add(self, watcher: _Watcher) -> None:
        self._watchers.add(watcher)

    def subscribe(self, watcher: _Watcher, key: SubscriptionKey) -> None:
        watcher.sent[key] = None  # (re)send the current list
        self._by_service[key[0]].add(watcher)
        watcher.mark_dirty(key)

    def unsubscribe(self, watcher: _Watcher, key: SubscriptionKey) -> None:
        watcher.sent.pop(key, None)
        watcher.dirty.discard(key)
        if not any(k[0] == key[0] for k in watcher.sent):
            self._discard(key[0], watcher)

    def remove(self, watcher: _Watcher) -> None:
        for service_id in {key[0] for key in watcher.sent}:
            self._discard(service_id, watcher)
        watcher.sent.clear()
        self._watchers.discard(watcher)

    def _discard(self, service_id: str, watcher: _Watcher) -> None:
        watchers = self._by_service.get(service_id)
        if watchers is not None:
            watchers.discard(watcher)
            if not watchers:
                del self._by_service[service_id]

    def stop(self) -> None:
        """End all the watch streams (on shutdown)."""
        self.stopping = True
        for watcher in self._watchers:
            watcher.wakeup.set()

    @property
    def watch_count(self) -> int:
        return len(self._watchers)


# --- the router service --------------------------------------------------------------


class GRPCRouterServicer(GRPCRouterServiceServicer):

    def __init__(self, config: ConfigOptions, register: ServiceRegister, hub: WatchHub) -> None:
        self._config = config
        self._register = register
        self._hub = hub

    @staticmethod
    async def _require(context: grpc.aio.ServicerContext, value, name: str) -> None:
        if not value:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"The {name} cannot be empty.")

    async def RegisterService(self, request, context) -> ServiceRegistrationResponse:
        await self._require(context, request.service_id, "service_id")
        await self._require(context, request.endpoint.host, "host")
        if request.endpoint.port <= 0:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "The port cannot be negative or zero.")
        if not request.metadata.region and not self._config.allow_global_region:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, "The region cannot be empty in this current configuration."
            )
        service_token, _error = self._register.register_service(
            service_id=request.service_id,
            host=request.endpoint.host,
            port=request.endpoint.port,
            region=request.metadata.region,
            slots=request.metadata.slots,
            health_check_type=to_health_check_type(request.metadata.health_check_type),
        )
        return ServiceRegistrationResponse(service_token=service_token)

    async def DeregisterService(self, request, context) -> ServiceDeregistrationResponse:
        await self._require(context, request.service_id, "service_id")
        await self._require(context, request.service_token, "service_token")
        self._register.deregister_service(service_id=request.service_id, service_token=request.service_token)
        return ServiceDeregistrationResponse()

    async def GetRegisteredService(self, request, context) -> GetRegisteredServiceResponse:
        await self._require(context, request.service_id, "service_id")
        service, instances = self._register.pick_service(service_id=request.service_id, region=request.hints.region)
        if service is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "The service_id has no registered instances.")
        assert service is not None
        response = GetRegisteredServiceResponse(service_id=service.service_id)
        response.endpoint.host = service.host
        response.endpoint.port = service.port
        response.instances.extend(_to_instances(instances))
        return response

    async def ListServiceInstances(self, request, context) -> ListServiceInstancesResponse:
        await self._require(context, request.service_id, "service_id")
        instances = self._register.get_service_instances(request.service_id, request.hints.region)
        return ListServiceInstancesResponse(service_id=request.service_id, instances=_to_instances(instances))

    async def PushHealthStatus(self, request, context) -> HealthInfoResponse:
        await self._require(context, request.service_id, "service_id")
        await self._require(context, request.service_token, "service_token")
        svc = self._register.push_health_status(
            service_id=request.service_id,
            service_token=request.service_token,
            health_status=to_health_status(request.status),
            description=request.description)
        if svc is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "The service could not be found.")
        return HealthInfoResponse()

    async def WatchServices(self, request_iterator, context) -> None:
        watcher = _Watcher()
        self._hub.add(watcher)
        reader = asyncio.ensure_future(self._read_subscriptions(context, watcher))
        try:
            while not self._hub.stopping:
                await watcher.wakeup.wait()
                watcher.wakeup.clear()
                if watcher.error is not None:
                    await context.abort(*watcher.error)
                if self._hub.stopping:
                    break
                updates = self._pending_updates(watcher)
                if updates:
                    await context.write(WatchServicesResponse(updates=updates))
            # returning ends the stream with OK: the client connects again (to the next router)
        finally:
            reader.cancel()
            self._hub.remove(watcher)

    def _pending_updates(self, watcher: _Watcher) -> list[ServiceInstancesUpdate]:
        updates = []
        dirty, watcher.dirty = watcher.dirty, set()
        for key in dirty:
            if key not in watcher.sent:
                continue  # unsubscribed meanwhile
            instances = _to_instances(self._register.get_service_instances(*key))
            fingerprint = tuple((i.endpoint.host, i.endpoint.port, i.region) for i in instances)
            if fingerprint != watcher.sent[key]:
                watcher.sent[key] = fingerprint
                updates.append(ServiceInstancesUpdate(
                    subscription=ServiceSubscription(service_id=key[0], region=key[1]), instances=instances,
                ))
        return updates

    async def _read_subscriptions(self, context: grpc.aio.ServicerContext, watcher: _Watcher) -> None:
        while True:
            request = await context.read()
            if request is grpc.aio.EOF:
                return  # the client sends no more (un)subscriptions; keep streaming updates
            for sub in request.unsubscribe:
                self._hub.unsubscribe(watcher, (sub.service_id, sub.region))
            for sub in request.subscribe:
                if not sub.service_id:
                    watcher.fail(grpc.StatusCode.INVALID_ARGUMENT, "The service_id cannot be empty.")
                    return
                key = (sub.service_id, sub.region)
                if key not in watcher.sent and len(watcher.sent) >= MAX_SUBSCRIPTIONS_PER_WATCH:
                    watcher.fail(
                        grpc.StatusCode.RESOURCE_EXHAUSTED,
                        f"A watch can have at most {MAX_SUBSCRIPTIONS_PER_WATCH} subscriptions.",
                    )
                    return
                self._hub.subscribe(watcher, key)


# --- the router ----------------------------------------------------------------------


class GRPCRouter:
    """The grpc router: its gRPC server, register, health and reflection services and state file.

    Runs on the asyncio event loop that calls start(). From synchronous code, use BackgroundRouter.
    """

    def __init__(self, config: ConfigOptions) -> None:
        self.config = config
        self.port: int | None = None  # the bound port, once started (useful with config.port 0)
        self._server: grpc.aio.Server | None = None
        self._health: health.aio.HealthServicer | None = None
        self._hub: WatchHub | None = None
        self._register: ServiceRegister | None = None
        self._state_writer: StateWriter | None = None
        self._stopped = False

    async def start(self) -> None:
        """Load the state file (if any), bind config.hostname:config.port and start serving.

        Raises:
            RuntimeError: If the address cannot be bound, e.g. another router uses the port.
        """
        config = self.config
        self._register = register = ServiceRegister(config)
        if config.state_file:
            self._state_writer = StateWriter(Path(config.state_file), register, config.state_save_interval)
            self._state_writer.start()
        self._hub = hub = WatchHub(asyncio.get_running_loop())
        register.on_rotation_change = hub.notify_threadsafe

        self._server = server = grpc.aio.server(
            # The router holds the service register in memory, so two routers sharing a
            # port (grpc enables SO_REUSEPORT by default on Linux) would split it.
            options=[("grpc.so_reuseport", 0)],
        )
        add_GRPCRouterServiceServicer_to_server(GRPCRouterServicer(config, register, hub), server)
        _enable_reflection_service(server)
        self._health = health.aio.HealthServicer()
        health_pb2_grpc.add_HealthServicer_to_server(self._health, server)
        await self._health.set(SERVICE_NAME, health_pb2.HealthCheckResponse.SERVING)
        try:
            self.port = server.add_insecure_port(f"{config.hostname}:{config.port}")
        except RuntimeError:
            self._close_state_writer()
            raise
        await server.start()
        logger.info("grpc router listening on %s:%s", config.hostname, self.port)

    async def stop(self, grace: float | None = None) -> None:
        """Stop gracefully: the health status turns NOT_SERVING, the watch streams end (so that their
        clients reconnect to the next router), new requests are rejected and in flight requests get
        grace seconds to complete; then the state file is saved. grace None stops immediately."""
        if self._server is None or self._stopped:
            return
        self._stopped = True
        assert self._health is not None and self._hub is not None
        await self._health.enter_graceful_shutdown()
        self._hub.stop()
        await self._server.stop(grace)
        # the final save writes a file: not on the event loop
        await asyncio.to_thread(self._close_state_writer)
        logger.info("grpc router stopped")

    async def stop_now(self) -> None:
        """Cancel the requests still in flight, e.g. during a graceful stop()."""
        if self._server is not None:
            await self._server.stop(None)

    def _close_state_writer(self) -> None:
        if self._state_writer is not None:
            self._state_writer.stop()
            self._state_writer = None

    async def wait_for_termination(self) -> None:
        assert self._server is not None
        await self._server.wait_for_termination()

    @property
    def watch_count(self) -> int:
        """The number of open WatchServices streams."""
        return self._hub.watch_count if self._hub is not None else 0


def _enable_reflection_service(server: grpc.aio.Server) -> None:
    """Serve gRPC server reflection, both the v1 and the v1alpha versions."""
    servicer = reflection.aio.ReflectionServicer(
        (SERVICE_NAME, REFLECTION_V1_SERVICE_NAME, reflection.SERVICE_NAME)
    )
    # v1alpha
    reflection_pb2_grpc.add_ServerReflectionServicer_to_server(servicer, server)
    # v1: the same servicer and (wire compatible) messages, on the v1 method path
    server.add_generic_rpc_handlers((
        grpc.method_handlers_generic_handler(REFLECTION_V1_SERVICE_NAME, {
            "ServerReflectionInfo": grpc.stream_stream_rpc_method_handler(
                servicer.ServerReflectionInfo,
                request_deserializer=reflection_pb2.ServerReflectionRequest.FromString,
                response_serializer=reflection_pb2.ServerReflectionResponse.SerializeToString,
            ),
        }),
    ))


async def serve(config: ConfigOptions) -> None:
    """Run the grpc router until it is stopped.

    When run on the main thread, SIGTERM and SIGINT trigger a graceful shutdown (see
    GRPCRouter.stop, with config.shutdown_grace); a second signal stops immediately.
    """
    router = GRPCRouter(config)
    await router.start()
    loop = asyncio.get_running_loop()
    stopping: list[asyncio.Task] = []

    def on_signal(sig: signal.Signals) -> None:
        if stopping:
            logger.info("Received %s again, stopping immediately", sig.name)
            stopping.append(loop.create_task(router.stop_now()))
            return
        logger.info("Received %s, shutting down (grace period %ss)", sig.name, config.shutdown_grace)
        stopping.append(loop.create_task(router.stop(config.shutdown_grace)))

    handled = []
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, on_signal, sig)
            handled.append(sig)
    try:
        await router.wait_for_termination()
        if stopping:
            await stopping[0]  # the final state save
    finally:
        for sig in handled:
            loop.remove_signal_handler(sig)
        await router.stop(0)  # no-op if already stopped


class BackgroundRouter:
    """Runs a GRPCRouter on an event loop in a background thread, for synchronous programs and tests.

    Example:
        ```python
        with BackgroundRouter(ConfigOptions(hostname="localhost", port=0)) as router:
            client = GRPCRouterClient("localhost", router.port)
        ```
    """

    def __init__(self, config: ConfigOptions) -> None:
        self.router = GRPCRouter(config)
        self._loop = asyncio.new_event_loop()
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        assert self.router.port is not None, "not started"
        return self.router.port

    def start(self) -> Self:
        """Start the router; raises what GRPCRouter.start raises, e.g. if the port is in use."""
        self._thread = threading.Thread(target=self._loop.run_forever, name="grpc-router-loop", daemon=True)
        self._thread.start()
        try:
            asyncio.run_coroutine_threadsafe(self.router.start(), self._loop).result()
        except BaseException:
            self._shutdown_loop()
            raise
        return self

    def stop(self, grace: float | None = None) -> None:
        """Stop the router (see GRPCRouter.stop) and its event loop."""
        if self._thread is None:
            return
        asyncio.run_coroutine_threadsafe(self.router.stop(grace), self._loop).result()
        self._shutdown_loop()

    def _shutdown_loop(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        self._loop.close()

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.stop()


# Each client connection uses a file descriptor of the router.
OPEN_FILES_WARNING_THRESHOLD = 4096


def raise_open_files_limit() -> int | None:
    """Raise the soft limit of open files to the hard limit (each client connection needs one).

    Returns the new soft limit, or None where the platform has no such limit (Windows).
    """
    try:
        import resource
    except ImportError:
        return None
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if hard == resource.RLIM_INFINITY or soft < hard:
        target = hard if hard != resource.RLIM_INFINITY else max(soft, 1 << 20)
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
            soft = target
        except (ValueError, OSError):
            pass
    if soft != resource.RLIM_INFINITY and soft < OPEN_FILES_WARNING_THRESHOLD:
        logger.warning(
            "The router can only open %d files, so it can serve fewer than %d clients; raise the limit of "
            "open files (e.g. ulimit -n, or LimitNOFILE= in a systemd unit)", soft, soft,
        )
    return soft


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('-n', '--hostname', dest='hostname', default='[::]',
                        help='Hostname to bind the service to')
    parser.add_argument('-p', '--port', dest='port', default=50034, type=int,
                        help='Port to bind this service to')
    parser.add_argument('-g', '--shutdown-grace', dest='shutdown_grace',
                        type=float, default=5.0,
                        help='Seconds to let in-flight requests complete on SIGTERM/SIGINT.')
    parser.add_argument('-s', '--state-file', dest='state_file', default=None,
                        help='JSON file to save the service register to (write behind) and to reload it from '
                             'on restart. Disabled by default. One file per router.')
    parser.add_argument('--state-save-interval', dest='state_save_interval', type=float, default=1.0,
                        help='Save the state file at most once per this many seconds.')

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    raise_open_files_limit()
    config = ConfigOptions(
        hostname=args.hostname,
        port=args.port,
        shutdown_grace=args.shutdown_grace,
        state_file=args.state_file,
        state_save_interval=args.state_save_interval,
    )
    asyncio.run(serve(config))


if __name__ == "__main__":
    main()
