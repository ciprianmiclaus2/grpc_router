# History

## 0.5.0 (2026-11-27)

Client side discovery that keeps working when the router is down, live updates that scale to thousands of
clients, and a router on gRPC asyncio.

### Upgrading

This release changes the Python API of the router and the client options (the gRPC API only gains new calls:
0.4 clients work with a 0.5 router).

* The router runs on gRPC asyncio. `serve(config)` is now a coroutine (`asyncio.run(serve(config))`), and
  `create_server()` is replaced by `GRPCRouter` (`await start()`, `await stop(grace)`) and, for synchronous code,
  `BackgroundRouter`.
* `ConfigOptions.max_workers` and the `--max-workers` option are removed: requests no longer need threads.
  `hostname` and `port` now default to `[::]` and `50034`; port `0` picks a free port (`GRPCRouter.port`).
* `get_service()` now has a default deadline of 5 seconds (`timeout`, retries included); it used to wait for as long
  as the retry policy did (about a minute with the default policy when the router is unreachable).

### New

* `ListServiceInstances` RPC and `GRPCRouterClient.get_service_instances()`: all the instances a client in a region
  may use (the same choice as `GetRegisteredService`, as a list).
* `WatchServices` bidirectional streaming RPC and `GRPCRouterClient.watch_service_instances()`: one stream per
  client for all the services it watches, with the list of each straight away and on every change. On the router,
  a stream is a coroutine, not a thread, and a change only wakes the streams subscribed to that service: one
  router served 10,000 watching clients with 12 threads in our tests. While a client's stream is connected, its
  lookups for the watched services are answered locally, without asking the router.
* Clients reconnect their watch stream after a random delay of up to 10 seconds when the router shuts down (no
  reconnection storm on a router restart), and with jittered exponential backoff after errors.
* `ServiceChannelPool`: one gRPC channel per instance, kept up to date by a watch, round robin, with a grace period
  before closing the channels of instances that went away.
* Lookups fall back to the last known instances, round robin, when the router cannot be reached (`UNAVAILABLE`, or
  no answer within the lookup `timeout`), for up to `stale_cache_max_age` (default 1 hour). `GetRegisteredService`
  now also returns the instances list, so this costs no extra call.
* The router ends the watch streams at the start of a shutdown, so that their clients move to the next router.
* `GRPCRouterClient(channel_options=...)` for extra gRPC channel options, e.g. keepalive settings.
* `grpc-router` raises its soft limit of open files to the hard limit on start (each client connection uses one),
  and warns if it is below 4,096.

## 0.4.0 (2026-11-27)

The 0.3.0 package on PyPI was broken (see below): upgrade to 0.4.0. The gRPC API (`proto/grpc_router_service.proto`)
is unchanged, so 0.3.0 clients work with a 0.4.0 router and the reverse, but upgrade the clients too: 0.3.0 clients
stop sending heartbeats after 3 minutes (see Fixes).

### Upgrading

* Python 3.11+ is now required (3.9 and 3.10 are end of life).
* Minimum dependency versions are now declared: `grpcio>=1.66.2`, `grpcio-reflection>=1.66.2`,
  `grpcio-health-checking>=1.66.2`, `protobuf>=5.27.2` (tested up to protobuf 7).
* Reporting `HEALTH_STATUS_ERROR` now takes an `ACTIVE_CLIENT` service out of service; it used to be stored while the
  service was still handed out to clients. As after missed heartbeats, the service keeps its token and goes back in
  service as soon as it pushes any other status (`GOOD`, `WARNING`, `UNKNOWN`).
* Out of service instances are now forgotten after `ConfigOptions.unhealthy_expiry_timeout` seconds (default 900)
  without any health push; they used to be kept forever.
* A registration now replaces the entries for the same service_id, host and port that look dead: out of service,
  missed heartbeats, or no health checks. A restarted service no longer leaves stale or duplicate entries.
* The client now registers a service again, with a new token, when its heartbeat gets NOT_FOUND. A token kept from
  `register_service()` can therefore become outdated; the client itself always uses the current one.
* The router no longer enables `SO_REUSEPORT`: starting a second router on a port already in use now fails instead
  of silently splitting the service register between the two processes.
* `GRPCRouterClient.HEALTh_PUSh_FREQUENCY_SECONDS` is renamed to `HEALTH_PUSH_FREQUENCY_SECONDS`; the old name is
  kept as a deprecated alias.

### Fixes

* The published package: the 0.3.0 wheel only contained `grpc_router/server.py` and was missing the `client`,
  `core` and `stubs` subpackages, so it could not be imported. CI now tests the installed wheel and the sdist.
* `ACTIVE_CLIENT` heartbeats: the client's heartbeat thread exited the first time `HEALTH_PUSH_FREQUENCY_SECONDS`
  (3 minutes) passed without a `set_health_status()` call, so services that did not keep calling it were evicted
  after `health_check_timeout` (5 minutes) and never came back. The client now sends heartbeats until `close()`.
* `ERROR` heartbeats from an out of service instance are now accepted; they used to fail with NOT_FOUND.
* Deregistering an out of service instance now removes it.
* Re-registration by health push now checks that the token belongs to the pushed `service_id`.
* The PushHealthStatus error message for an empty token ("service_token", was "service_context").
* A race where concurrent registrations could start more than one health check thread.

### New

* Optional write-behind persistence of the register (`--state-file`, `--state-save-interval`;
  `ConfigOptions.state_file`, `state_save_interval`): a human readable JSON file with the time of the last save,
  written atomically and readable by its owner only, reloaded on start. Restored instances get a fresh health check
  timeout. A file that cannot be loaded is moved aside to `<name>.bad-<timestamp>` and the router starts empty.
* Graceful shutdown on SIGTERM/SIGINT: the health status turns NOT_SERVING, new RPCs are rejected and in-flight
  RPCs get a grace period (`--shutdown-grace`, `ConfigOptions.shutdown_grace`, default 5s) to complete; a second
  signal stops immediately. The router now logs startup, shutdown and state restores.
* Server reflection is served as both `grpc.reflection.v1` and `grpc.reflection.v1alpha`, so clients that only
  speak v1 (recent grpcurl, Postman, etc.) work.
* Documentation site: https://ciprianmiclaus2.github.io/grpc_router/ (running the router, health checks, gRPC and
  Python API).
* `grpc-router` command line entry point to start the router.
* `grpc_router.server.create_server(config)` builds a router without blocking (`serve` still blocks).
* `GRPCRouterClient` caches its stub, and gains `close()` and context manager support.
* Type information: `py.typed` and generated `.pyi` stubs for the protobuf messages.

### Packaging and tooling

* `[build-system]` table, SPDX license metadata, PEP 735 dependency groups (`pip install -e . --group dev`),
  sdist with the tests, proto and stub generation script.
* ruff replaces flake8; GitHub Actions updated, with a test matrix for Python 3.11 to 3.15, a minimum versions job,
  a packaging job and a docs build; the docs are published to GitHub Pages on each release.

## 0.3.0 (2024-11-02)

* Support for active client health check type (passive not yet implemented)
    - This is when the client pushes heathbeats into the server
    - If the server detects a missed client heartbeat, it automatically marks the client as unhealthy and does not return it
    - If the same client recovers, the server marks it back healthy
* Fix the service registration implementation to be thread safe

## 0.2.0 (2024-10-23)

* Enable health checking service on the grpc router
* Enable reflection in the server
* Fix the server cli -h conflicting with --help and the port not being parsed as an int

## 0.1.0 (2024-10-13)

Initial release of the grpc_router, a service discovery tool for grpc services.
Allows grpc services to register/deregister and clients to lookup services based on a service_id which
should ideally consist of a dot separated namespace, e.g. domain.scope.service. In practice, the service_id
can be any string, there is no inherent limitation.
Services operate with a concept of region, which can allow clients to connect preferentially to the services
in their own region, with a fallback to another region if there's no services running in their own region.
