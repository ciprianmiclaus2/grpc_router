"""Client side discovery: a cache of service instances, a watch stream that keeps it live, and a channel pool."""

import logging
import queue
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from types import TracebackType
from typing import TYPE_CHECKING, Self

import grpc

from grpc_router.stubs.grpc_router_service_pb2 import ServiceSubscription, WatchServicesRequest

if TYPE_CHECKING:
    from grpc_router.client.client import GRPCRouterClient

logger = logging.getLogger(__name__)

Endpoint = tuple[str, int]
CacheKey = tuple[str, str]  # (service_id, region)


def rpc_code(exc: grpc.RpcError) -> grpc.StatusCode | None:
    # the grpc.RpcError base class has no code(), the errors grpc raises do
    return exc.code() if isinstance(exc, grpc.Call) else None


# The router could not be reached (or answered too slowly): the cached instances are the best answer.
ROUTER_UNREACHABLE_CODES = frozenset({grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED})


@dataclass
class _CachedInstances:
    instances: list[Endpoint]
    updated: float  # time.monotonic()
    next_index: int = field(default_factory=lambda: random.randrange(1 << 30))  # spread clients' round robin
    watches: int = 0  # live watches keeping this entry up to date
    warned_stale: bool = False


class InstanceCache:
    """The last known instances of each (service_id, region), with the round robin over them."""

    def __init__(self, max_age: float) -> None:
        self._max_age = max_age
        self._entries: dict[CacheKey, _CachedInstances] = {}
        self._lock = threading.Lock()

    def update(self, key: CacheKey, instances: list[Endpoint]) -> None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._entries[key] = _CachedInstances(list(instances), time.monotonic())
            else:
                entry.instances, entry.updated, entry.warned_stale = list(instances), time.monotonic(), False

    def drop(self, key: CacheKey) -> None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and not entry.watches:
                del self._entries[key]

    def watched(self, key: CacheKey) -> list[Endpoint] | None:
        """The instances, if a live watch keeps them up to date."""
        with self._lock:
            entry = self._entries.get(key)
            return list(entry.instances) if entry is not None and entry.watches else None

    def set_watched(self, key: CacheKey, watched: bool) -> None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                entry.watches += 1 if watched else -1

    def fallback(self, key: CacheKey) -> list[Endpoint] | None:
        """The instances, if not older than the max age (for when the router cannot be reached)."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or time.monotonic() - entry.updated > self._max_age:
                return None
            if not entry.warned_stale:
                entry.warned_stale = True
                logger.warning(
                    "The grpc router cannot be reached; using the instances of %s last seen %.0fs ago",
                    key[0], time.monotonic() - entry.updated,
                )
            return list(entry.instances)

    def next(self, key: CacheKey) -> Endpoint | None:
        """The next instance, round robin."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or not entry.instances:
                return None
            entry.next_index += 1
            return entry.instances[entry.next_index % len(entry.instances)]


class ServiceWatch:
    """A subscription to the instances of a service, kept up to date by the client's watch stream.

    Created by `GRPCRouterClient.watch_service_instances`. All the watches of a client share one
    stream to the router.
    """

    def __init__(
        self,
        stream: "WatchStream",
        service_id: str,
        region: str,
        callback: Callable[[list[Endpoint]], None] | None,
    ) -> None:
        self.service_id = service_id
        self.region = region
        self.key: CacheKey = (service_id, region)
        self._stream = stream
        self._callback = callback
        self._instances: list[Endpoint] | None = None
        self._received = threading.Event()

    @property
    def instances(self) -> list[Endpoint] | None:
        """The latest instances received, or None until the first update."""
        return None if self._instances is None else list(self._instances)

    def wait_for_instances(self, timeout: float | None = None) -> list[Endpoint] | None:
        """Wait for the first update, then return `instances` (None on timeout)."""
        self._received.wait(timeout)
        return self.instances

    def _deliver(self, instances: list[Endpoint]) -> None:
        if instances == self._instances:
            return  # e.g. resent after a reconnection
        self._instances = instances
        self._received.set()
        if self._callback is not None:
            try:
                self._callback(list(instances))
            except Exception:
                logger.exception("The watch callback for %s failed", self.service_id)

    def cancel(self) -> None:
        """Stop watching."""
        self._stream.remove(self)


class WatchStream:
    """The one WatchServices stream of a client, for all its watches; reconnects as needed.

    Runs one thread, whatever the number of watched services.
    """

    # After an error: exponential backoff with full jitter (a random delay up to the backoff).
    RECONNECT_BACKOFF_SECONDS = (1.0, 60.0)  # initial, maximum
    # After the router ended the stream (it is shutting down): a random delay up to this, so that
    # the clients of a restarted router do not all reconnect at the same time.
    RECONNECT_SPREAD_SECONDS = 10.0

    def __init__(self, client: "GRPCRouterClient") -> None:
        self._client = client
        self._lock = threading.Lock()
        self._watches: dict[CacheKey, list[ServiceWatch]] = {}
        self._watched_keys: set[CacheKey] = set()  # marked as watched in the cache (connected, received)
        self._requests: queue.SimpleQueue | None = None  # of the current connection
        self._call: grpc.Future | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def add(self, watch: ServiceWatch) -> None:
        with self._lock:
            self._watches.setdefault(watch.key, []).append(watch)
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="grpc-router-watch", daemon=True)
                self._thread.start()
            elif self._requests is not None:
                # (re)subscribing makes the router (re)send the current list, for this new watch
                self._requests.put(WatchServicesRequest(subscribe=[_subscription(watch.key)]))

    def remove(self, watch: ServiceWatch) -> None:
        with self._lock:
            watches = self._watches.get(watch.key, [])
            if watch in watches:
                watches.remove(watch)
            if watches:
                return
            self._watches.pop(watch.key, None)
            if self._requests is not None:
                self._requests.put(WatchServicesRequest(unsubscribe=[_subscription(watch.key)]))
            if watch.key in self._watched_keys:
                self._watched_keys.discard(watch.key)
                self._client._instance_cache.set_watched(watch.key, False)

    def _requests_iterator(self, requests: queue.SimpleQueue, initial: WatchServicesRequest):
        yield initial
        while True:
            request = requests.get()
            if request is None:
                return
            yield request

    def _run(self) -> None:
        initial_backoff, max_backoff = self.RECONNECT_BACKOFF_SECONDS
        backoff = initial_backoff
        while not self._stop.is_set():
            requests: queue.SimpleQueue = queue.SimpleQueue()
            with self._lock:
                if self._stop.is_set():
                    return
                initial = WatchServicesRequest(subscribe=[_subscription(key) for key in self._watches])
                self._requests = requests
                self._call = call = self._client.stub.WatchServices(self._requests_iterator(requests, initial))
            error: str | None = None
            try:
                for response in call:
                    backoff = initial_backoff
                    for update in response.updates:
                        self._on_update(update)
                # the stream ended normally: the router is shutting down
            except grpc.RpcError as exc:
                error = str(rpc_code(exc))
            except Exception:
                logger.exception("Watch stream failed")
                error = "unexpected error"
            finally:
                requests.put(None)  # end the requests iterator
                with self._lock:
                    self._requests = self._call = None
                    # disconnected: lookups go back to the router (and fall back to the cache)
                    for key in self._watched_keys:
                        self._client._instance_cache.set_watched(key, False)
                    self._watched_keys.clear()
            if self._stop.is_set():
                return
            if error is None:
                delay = random.uniform(0, self.RECONNECT_SPREAD_SECONDS)
                logger.info("The grpc router ended the watch stream; reconnecting in %.1fs", delay)
                backoff = initial_backoff
            else:
                delay = random.uniform(0, backoff)
                logger.warning("Watch stream interrupted (%s); reconnecting in %.1fs", error, delay)
                backoff = min(backoff * 2, max_backoff)
            self._stop.wait(delay)

    def _on_update(self, update) -> None:
        key: CacheKey = (update.subscription.service_id, update.subscription.region)
        instances = [(i.endpoint.host, i.endpoint.port) for i in update.instances]
        with self._lock:
            watches = list(self._watches.get(key, ()))
            if not watches:
                return  # unsubscribed meanwhile
            cache = self._client._instance_cache
            cache.update(key, instances)
            if key not in self._watched_keys:
                self._watched_keys.add(key)
                cache.set_watched(key, True)
        for watch in watches:
            watch._deliver(instances)

    def close(self) -> None:
        """Stop the stream and its thread."""
        with self._lock:
            self._stop.set()
            if self._call is not None:
                self._call.cancel()
            if self._requests is not None:
                self._requests.put(None)
            thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join()
        with self._lock:
            self._watches.clear()


def _subscription(key: CacheKey) -> ServiceSubscription:
    return ServiceSubscription(service_id=key[0], region=key[1])


class ServiceChannelPool:
    """One gRPC channel per in service instance of a service, kept up to date by a watch.

    gRPC Python's own multi-address load balancing only takes IP addresses; this pool works with any
    host name. `next_channel` returns the channels round robin. When an instance goes away, its channel
    is closed after `retire_grace_seconds`, so that calls in flight on it can complete.

    Args:
        router: The router client to watch the service with.
        service_id: The service.
        region: The region of the caller.
        channel_factory: Creates the channel to an instance from its `"host:port"` target; defaults to
            `grpc.insecure_channel`. Use it for credentials or channel options.
        retire_grace_seconds: Delay before closing the channel of an instance that went away.
    """

    def __init__(
        self,
        router: "GRPCRouterClient",
        service_id: str,
        region: str = "",
        channel_factory: Callable[[str], grpc.Channel] | None = None,
        retire_grace_seconds: float = 30.0,
    ) -> None:
        self.service_id = service_id
        self._channel_factory = channel_factory or grpc.insecure_channel
        self._retire_grace_seconds = retire_grace_seconds
        self._lock = threading.Lock()
        self._channels: dict[Endpoint, grpc.Channel] = {}
        self._order: list[Endpoint] = []
        self._next_index = random.randrange(1 << 30)
        self._retired: list[tuple[threading.Timer, grpc.Channel]] = []
        self._closed = False
        self._watch = router.watch_service_instances(service_id, region, self._on_update)

    def _on_update(self, instances: list[Endpoint]) -> None:
        with self._lock:
            if self._closed:
                return
            for endpoint in instances:
                if endpoint not in self._channels:
                    self._channels[endpoint] = self._channel_factory(f"{endpoint[0]}:{endpoint[1]}")
            for endpoint in set(self._channels) - set(instances):
                channel = self._channels.pop(endpoint)
                timer = threading.Timer(self._retire_grace_seconds, channel.close)
                timer.daemon = True
                timer.start()
                self._retired = [(t, c) for t, c in self._retired if t.is_alive()] + [(timer, channel)]
            self._order = list(dict.fromkeys(instances))

    @property
    def endpoints(self) -> list[Endpoint]:
        """The instances the pool currently has channels to."""
        with self._lock:
            return list(self._order)

    def next_channel(self, timeout: float | None = 5.0) -> grpc.Channel:
        """The channel to the next instance, round robin.

        Waits up to timeout for the first list of instances from the router.

        Raises:
            LookupError: If the service has no instance in service (or none was received in time).
        """
        self._watch.wait_for_instances(timeout)
        with self._lock:
            if not self._order:
                raise LookupError(f"No instance of {self.service_id} is in service")
            self._next_index += 1
            return self._channels[self._order[self._next_index % len(self._order)]]

    def close(self) -> None:
        """Stop watching and close all the channels."""
        self._watch.cancel()
        with self._lock:
            self._closed = True
            channels = list(self._channels.values())
            for timer, channel in self._retired:
                timer.cancel()
                channels.append(channel)
            self._channels.clear()
            self._retired = []
            self._order = []
        for channel in channels:
            channel.close()  # closing an already closed channel is a no-op

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
