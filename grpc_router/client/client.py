import json
import logging
from collections.abc import Callable
from threading import Event, Lock, Thread
from types import TracebackType
from typing import Any, Self

import grpc

from grpc_router.client.discovery import (
    ROUTER_UNREACHABLE_CODES,
    CacheKey,
    Endpoint,
    InstanceCache,
    ServiceWatch,
    WatchStream,
    rpc_code,
)
from grpc_router.stubs.grpc_router_service_pb2 import (
    DESCRIPTOR,
    HEALTH_CHECK_ACTIVE_CLIENT,
    HEALTH_STATUS_GOOD,
    GetRegisteredServiceRequest,
    HealthInfoRequest,
    ListServiceInstancesRequest,
    ServiceDeregistrationRequest,
    ServiceRegistrationRequest,
)
from grpc_router.stubs.grpc_router_service_pb2_grpc import GRPCRouterServiceStub

logger = logging.getLogger(__name__)


class GRPCRouterClient:
    """Client of the grpc router, for services (to register) and for their clients (to look them up).

    Registered `ACTIVE_CLIENT` services get heartbeats sent in a background thread every
    `HEALTH_PUSH_FREQUENCY_SECONDS`, and straight away when `set_health_status` is called. If the
    router no longer knows a service (it restarted without a state file, or the service was out of
    service and silent for too long), the client registers it again on its next heartbeat.

    Lookups remember the instances the router answers with. If the router cannot be reached, lookups
    answer from those, round robin, for up to `stale_cache_max_age` seconds. With a watch
    (`watch_service_instances`), lookups are answered locally without asking the router at all.

    Use it as a context manager, or call `close` when done, to stop the heartbeats and the watches, and
    close the channel.

    Args:
        host: Host of the router.
        port: Port of the router.
        grpc_service_config: gRPC service config for the channel, e.g. its retry policy. Defaults to
            `DEFAULT_GRPC_SERVICE_CONFIG`, which retries failed calls up to 5 times with backoff.
        stale_cache_max_age: Maximum age in seconds of the instances lookups fall back to when the
            router cannot be reached.
        channel_options: Extra gRPC channel options (e.g. keepalive settings) for the channel to the router.
    """

    DEFAULT_GRPC_SERVICE_CONFIG = {
        "methodConfig": [{
            "name": [{"service": DESCRIPTOR.services_by_name["GRPCRouterService"].full_name}],
            "retryPolicy": {
                "maxAttempts": 5,
                "initialBackoff": "5s",
                "maxBackoff": "30s",
                "backoffMultiplier": 2,
                "retryableStatusCodes": [
                    "ABORTED", "CANCELLED", "DATA_LOSS", "DEADLINE_EXCEEDED",
                    "FAILED_PRECONDITION", "INTERNAL", "RESOURCE_EXHAUSTED",
                    "UNAVAILABLE", "UNKNOWN",
                ]
            }
        }]
    }

    HEALTH_PUSH_FREQUENCY_SECONDS = 60 * 3

    # Default deadline of lookups (retries included), after which they fall back to the cached instances.
    DEFAULT_LOOKUP_TIMEOUT_SECONDS = 5.0
    # Deprecated misspelled alias, kept for backwards compatibility.
    HEALTh_PUSh_FREQUENCY_SECONDS = HEALTH_PUSH_FREQUENCY_SECONDS

    def __init__(
        self,
        host: str,
        port: int,
        grpc_service_config: dict[str, Any] | None = None,
        stale_cache_max_age: float = 3600.0,
        channel_options: list[tuple[str, Any]] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self._channel: grpc.Channel | None = None
        self._stub: GRPCRouterServiceStub | None = None
        self._channel_options = list(channel_options or [])
        self._grpc_service_config = (
            grpc_service_config if grpc_service_config is not None else self.DEFAULT_GRPC_SERVICE_CONFIG
        )

        self._service_register: dict[str, dict[str, Any]] = {}
        self._register_lock = Lock()  # guards _service_register against the health push thread

        self._health_event = Event()
        self._health_push_stop = Event()
        self._health_push_thread: Thread | None = None

        self._instance_cache = InstanceCache(max_age=stale_cache_max_age)
        self._watch_stream: WatchStream | None = None
        self._watch_stream_lock = Lock()

    @property
    def channel(self) -> grpc.Channel:
        """The gRPC channel to the router, created on first use."""
        if self._channel is None:
            options = list(self._channel_options)
            if self._grpc_service_config:
                options.append(("grpc.service_config", json.dumps(self._grpc_service_config)))
            self._channel = grpc.insecure_channel(f"{self.host}:{self.port}", options=options or None)
        return self._channel

    @property
    def stub(self) -> GRPCRouterServiceStub:
        """The generated gRPC stub of the router service, for direct calls."""
        if self._stub is None:
            self._stub = GRPCRouterServiceStub(self.channel)
        return self._stub

    def close(self) -> None:
        """Stop the watches and the health pushes, and close the channel. Services are not deregistered."""
        with self._watch_stream_lock:
            stream, self._watch_stream = self._watch_stream, None
        if stream is not None:
            stream.close()
        thread = self._health_push_thread
        if thread is not None:
            self._health_push_stop.set()
            self._health_event.set()
        if self._channel is not None:
            self._channel.close()  # also cancels a push in flight, so the join below is quick
        if thread is not None:
            thread.join()
            self._health_push_thread = None
        # reset only after the push thread is gone, so it cannot reopen the channel
        self._channel = None
        self._stub = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _health_push_thread_entrypoint(self) -> None:
        # Push every HEALTH_PUSH_FREQUENCY_SECONDS (the heartbeat), or straight away when
        # set_health_status() changes a status, until the client is closed.
        while True:
            self._health_event.wait(self.HEALTH_PUSH_FREQUENCY_SECONDS)
            if self._health_push_stop.is_set():
                return
            self._health_event.clear()
            with self._register_lock:
                services = list(self._service_register.items())
            for service_id, svc in services:
                if self._health_push_stop.is_set():
                    return
                if svc["health_check_type"] == HEALTH_CHECK_ACTIVE_CLIENT:
                    try:
                        self._push_health_status(service_id, svc)
                    except grpc.RpcError as exc:
                        # the grpc.RpcError base class has no code(), the errors grpc raises do
                        code = exc.code() if isinstance(exc, grpc.Call) else None
                        if code != grpc.StatusCode.NOT_FOUND:
                            logger.exception("Failed to publish health status for %s", service_id)
                            continue
                        # the router forgot this instance (router restarted without its state,
                        # or the instance was out of service and silent for too long)
                        logger.warning("The grpc router no longer knows %s; registering it again", service_id)
                        try:
                            self._reregister(service_id, svc)
                        except Exception:
                            logger.exception("Failed to register %s again", service_id)
                    except Exception:
                        logger.exception("Failed to publish health status for %s", service_id)

    def _push_health_status(self, service_id: str, svc: dict[str, Any]) -> None:
        self.stub.PushHealthStatus(
            HealthInfoRequest(
                service_id=service_id,
                service_token=svc["token"],
                status=svc["health_status"],
                description=svc["description"]
            )
        )

    def _reregister(self, service_id: str, svc: dict[str, Any]) -> None:
        token = self.stub.RegisterService(svc["request"]).service_token
        with self._register_lock:
            current = self._service_register.get(service_id) is svc
            if current:
                svc["token"] = token
        if not current:
            # deregistered meanwhile: undo the registration we just made
            self.stub.DeregisterService(ServiceDeregistrationRequest(service_id=service_id, service_token=token))
            return
        # straight away, so that e.g. an instance in ERROR goes out of service again
        self._push_health_status(service_id, svc)

    def _start_health_push_thread(self) -> None:
        if self._health_push_thread is None:
            self._health_event.clear()
            self._health_push_stop.clear()
            self._health_push_thread = Thread(
                target=self._health_push_thread_entrypoint,
                name="grpc-router-health-push",
                daemon=True,
            )
            self._health_push_thread.start()

    def register_service(
        self, service_id: str, host: str, port: int, region: str = "", slots: int = 10, health_check_type: int = 0
    ) -> str:
        """Register a service instance with the router.

        Registering the same service_id again with the same client is a no-op that returns the
        existing token.

        Args:
            service_id: Name of the service, ideally a dot separated namespace, e.g. `"myorg.billing.invoices"`.
            host: Host clients connect to.
            port: Port clients connect to.
            region: Region of the instance; `""` is the global region.
            slots: Capacity hint of the instance (not used by the router yet).
            health_check_type: A `HealthCheckType`; `ACTIVE_CLIENT` starts sending heartbeats.

        Returns:
            The service token. It can change if the client has to register the service again.
        """
        with self._register_lock:
            svc = self._service_register.get(service_id)
        if svc is not None:
            return svc["token"]
        request = ServiceRegistrationRequest()
        request.service_id = service_id
        request.endpoint.host = host
        request.endpoint.port = port
        request.metadata.region = region
        request.metadata.slots = slots
        request.metadata.health_check_type = health_check_type
        if health_check_type == HEALTH_CHECK_ACTIVE_CLIENT:
            self._start_health_push_thread()
        res = self.stub.RegisterService(request)
        token = res.service_token
        with self._register_lock:
            self._service_register[service_id] = {
                "token": token,
                "request": request,  # to register again if the router forgets the instance
                "health_check_type": health_check_type,
                "health_status": HEALTH_STATUS_GOOD,
                "description": "",
            }
        return token

    def deregister_service(self, service_id: str) -> None:
        """Deregister a service registered by this client (no-op if it is not registered)."""
        with self._register_lock:
            svc = self._service_register.pop(service_id, None)
        if svc is None:
            return
        request = ServiceDeregistrationRequest()
        request.service_id = service_id
        request.service_token = svc["token"]
        self.stub.DeregisterService(request)

    def get_service(
        self, service_id: str, region: str = "", timeout: float | None = DEFAULT_LOOKUP_TIMEOUT_SECONDS
    ) -> tuple[str, int]:
        """Look up an instance of a service, round robin.

        The router prefers instances of the given region, then of the global region, then of any
        region, depending on its configuration.

        While `watch_service_instances` watches the service, the answer comes from the watched
        instances, round robin, without asking the router. If the router cannot be reached, it comes
        from the instances of the last answer (see `stale_cache_max_age`).

        Args:
            service_id: The service.
            region: The region of the caller.
            timeout: Deadline in seconds of the call to the router, retries included.

        Returns:
            The `(host, port)` to connect to.

        Raises:
            grpc.RpcError: With code `NOT_FOUND` if no instance is in service, or the router's error if
                it cannot be reached and no recent enough instances are known.
        """
        key: CacheKey = (service_id, region)
        if self._instance_cache.watched(key):
            endpoint = self._instance_cache.next(key)
            if endpoint is not None:
                return endpoint
        request = GetRegisteredServiceRequest(service_id=service_id)
        request.hints.region = region
        try:
            res = self.stub.GetRegisteredService(request, timeout=timeout)
        except grpc.RpcError as exc:
            if self._fall_back_to_cache(key, exc):
                endpoint = self._instance_cache.next(key)
                if endpoint is not None:
                    return endpoint
            raise
        # routers before 0.5 only return the chosen instance
        instances = [(i.endpoint.host, i.endpoint.port) for i in res.instances]
        self._instance_cache.update(key, instances or [(res.endpoint.host, res.endpoint.port)])
        return res.endpoint.host, res.endpoint.port

    def get_service_instances(
        self, service_id: str, region: str = "", timeout: float | None = DEFAULT_LOOKUP_TIMEOUT_SECONDS
    ) -> list[tuple[str, int]]:
        """All the instances of a service in service that a caller in region may use.

        The same choice of instances as `get_service`, as a list: the ones of the caller's region if
        any, else of the global region, else of any region, depending on the router's configuration.
        Like `get_service`, answers from a watch without asking the router, and falls back to the
        last known instances if the router cannot be reached.

        Returns:
            The `(host, port)` of each instance; an empty list if there are none.
        """
        key: CacheKey = (service_id, region)
        watched = self._instance_cache.watched(key)
        if watched is not None:
            return watched
        request = ListServiceInstancesRequest(service_id=service_id)
        request.hints.region = region
        try:
            res = self.stub.ListServiceInstances(request, timeout=timeout)
        except grpc.RpcError as exc:
            if self._fall_back_to_cache(key, exc):
                cached = self._instance_cache.fallback(key)
                if cached is not None:
                    return cached
            raise
        instances = [(i.endpoint.host, i.endpoint.port) for i in res.instances]
        self._instance_cache.update(key, instances)
        return instances

    def watch_service_instances(
        self,
        service_id: str,
        region: str = "",
        callback: Callable[[list[Endpoint]], None] | None = None,
    ) -> ServiceWatch:
        """Keep the instances of a service up to date from the router, in a background thread.

        The router sends the instances (as `get_service_instances`) straight away, then each time they
        change. All the watches of a client share one stream to the router (and one thread), which
        reconnects on its own if the router goes away. While it is connected, `get_service` and
        `get_service_instances` answer from it without asking the router.

        Args:
            service_id: The service.
            region: The region of the caller.
            callback: Called, in the watch thread, with the list of `(host, port)` on each update.

        Returns:
            The watch; call its `cancel()` to stop it (`close()` stops all the watches).
        """
        with self._watch_stream_lock:
            if self._watch_stream is None:
                self._watch_stream = WatchStream(self)
            stream = self._watch_stream
        watch = ServiceWatch(stream, service_id, region, callback)
        stream.add(watch)
        return watch

    def _fall_back_to_cache(self, key: CacheKey, exc: grpc.RpcError) -> bool:
        """Whether to answer from the cached instances after the router answered with exc."""
        code = rpc_code(exc)
        if code == grpc.StatusCode.NOT_FOUND:
            self._instance_cache.drop(key)  # an authoritative answer: no stale instances
            return False
        return code in ROUTER_UNREACHABLE_CODES and self._instance_cache.fallback(key) is not None

    def set_health_status(self, service_id: str, status: int, description: str) -> None:
        """Set the health status of a service registered by this client, and push it straight away.

        `HealthStatus.ERROR` takes the service out of service until a healthy status is set again.

        Args:
            service_id: The registered service.
            status: A `HealthStatus` (or the equivalent `HEALTH_STATUS_*` value of the generated stubs).
            description: Free text, e.g. why the service is unhealthy.
        """
        svc = self._service_register.get(service_id)
        if svc is None:
            return
        svc.update({
            "health_status": status,
            "description": description,
        })
        if svc["health_check_type"] == HEALTH_CHECK_ACTIVE_CLIENT:
            self._health_event.set()
