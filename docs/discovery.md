# Discovering services

`GRPCRouterClient` offers three ways to find the instances of a service, from the simplest to the most dynamic.
All of them use the same choice of instances: those of the caller's region if any, else of the global region,
else of any region, depending on the [router's configuration](router.md#regions).

## One instance per lookup: `get_service`

```python
router = GRPCRouterClient("router.mydomain.com", 50034)
host, port = router.get_service("myorg.billing.invoices", region="us-east")
```

The router picks the instance, round robin across all its clients. Each answer also carries the full list of
instances, which the client keeps:

* **If the router cannot be reached** (`UNAVAILABLE`, or no answer within the lookup `timeout`, 5 seconds by
  default), the lookup answers from that list instead, round robin, as long as it is not older than
  `stale_cache_max_age` (1 hour by default). The client logs a warning the first time it does.
* **If the router answers `NOT_FOUND`**, that is the truth: the list is dropped and the error raised.

So a router outage does not stop clients that already know a service; it only stops them from learning about
changes.

## All the instances: `get_service_instances`

```python
instances = router.get_service_instances("myorg.billing.invoices", region="us-east")
# [("invoices1.mydomain.com", 8080), ("invoices2.mydomain.com", 8080)]
```

An empty list when there are none. Falls back to the last known list like `get_service`.

## Live updates: `watch_service_instances`

```python
def on_update(instances: list[tuple[str, int]]) -> None:
    print("now:", instances)

watch = router.watch_service_instances("myorg.billing.invoices", "us-east", callback=on_update)
...
watch.cancel()  # or router.close()
```

The router sends the list straight away, then again every time it changes: an instance registers, deregisters,
misses its heartbeats, or reports `ERROR` or recovers. The callback runs in the watch's thread.

* While a watch is connected, `get_service` and `get_service_instances` for that service and region answer from
  it, **without asking the router**: lookups become local and always up to date.
* The watch reconnects on its own if the router goes away or restarts, with a backoff of up to 30 seconds; while
  it is disconnected, lookups go back to asking the router (and falling back to the last known list).
* All the watches of a client share **one stream** to the router and one thread of the client, whatever the
  number of services. On the router, a stream is a coroutine, not a thread: one router serves thousands of
  watching clients (see [How it scales](router.md#how-it-scales)). A stream can have up to 1,000 subscriptions.
* When the router shuts down, it ends the streams; clients reconnect after a random delay of up to
  10 seconds, so that a restarted router is not hit by all its clients at once. After errors, they retry with
  exponential backoff (1 to 60 seconds) with jitter.

## A channel per instance: `ServiceChannelPool`

gRPC channels connect to one target. To spread calls over all the instances of a service, the pool keeps one
channel per instance, updated by a watch:

```python
from grpc_router.client.discovery import ServiceChannelPool

with ServiceChannelPool(router, "myorg.billing.invoices", region="us-east") as pool:
    stub = InvoicesStub(pool.next_channel())  # round robin over the instances
    stub.GetInvoice(request)
```

* New instances get a channel as soon as the router reports them. The channel of an instance that goes away is
  closed after `retire_grace_seconds` (30 by default), so that calls in flight on it can complete.
* `next_channel()` waits up to its `timeout` for the first list, and raises `LookupError` if no instance is in
  service.
* Pass a `channel_factory` for credentials or channel options, e.g.
  `channel_factory=lambda target: grpc.secure_channel(target, credentials)`.

!!! note "Why not gRPC's own load balancing?"
    gRPC Python can balance a channel over several addresses (`round_robin` over an `ipv4:` or `ipv6:` target),
    but only IP addresses, not host names, and it has no hook for a custom name resolver. The pool works with
    the host names services register with.
