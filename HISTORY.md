# History

## 0.4.0 (unreleased)

* Fix the published package: the 0.3.0 wheel only contained `grpc_router/server.py` and was missing the
  `client`, `core` and `stubs` subpackages, so it could not be imported. CI now builds the wheel and runs the
  test suite against the installed wheel.
* Python 3.11+ is now required (3.9 and 3.10 are end of life). Python 3.14 and 3.15 are supported.
* Declare the minimum dependency versions required by the generated code: `grpcio>=1.66.2`,
  `grpcio-reflection>=1.66.2`, `grpcio-health-checking>=1.66.2`, `protobuf>=5.27.2` (tested up to protobuf 7).
* New `grpc-router` command line entry point to start the server.
* Graceful shutdown on SIGTERM/SIGINT: the health status turns NOT_SERVING, new RPCs are rejected and in-flight
  RPCs get a grace period (`--shutdown-grace`, `ConfigOptions.shutdown_grace`, default 5s) to complete; a second
  signal stops immediately. The server now logs startup and shutdown.
* Server reflection is now served as both `grpc.reflection.v1` and `grpc.reflection.v1alpha`, so clients that only
  speak v1 (recent grpcurl, Postman, etc.) work.
* The server no longer enables `SO_REUSEPORT`: starting a second router on a port already in use now fails
  instead of silently splitting the service register between the two processes.
* New `grpc_router.server.create_server(config)` to build a server without blocking (`serve` still blocks).
* `GRPCRouterClient` caches its stub, and gains `close()` and context manager support.
* `GRPCRouterClient.HEALTh_PUSh_FREQUENCY_SECONDS` renamed to `HEALTH_PUSH_FREQUENCY_SECONDS`
  (the old name is kept as a deprecated alias).
* Optional write-behind persistence of the register (`--state-file`, `--state-save-interval`;
  `ConfigOptions.state_file`, `state_save_interval`): a human readable JSON file with the time of the last save,
  written atomically, reloaded on start. Restored instances get a fresh health check timeout. A file that cannot be
  loaded is moved aside to `<name>.bad-<timestamp>` and the router starts empty.
* The client registers a service again when its heartbeat gets NOT_FOUND (the router restarted without a state
  file, or forgot an out of service instance that went silent), and re-sends its current status at once.
* A registration replaces the dead looking entries for the same service_id, host and port (out of service, missed
  heartbeats, or no health checks), so a restarted service no longer leaves stale or duplicate entries.
* Reporting `HEALTH_STATUS_ERROR` now takes an `ACTIVE_CLIENT` service out of service (previously the status was
  stored but the service was still handed out). As after missed heartbeats, it keeps its token and goes back in service
  when it pushes any other status. Its `ERROR` heartbeats are now accepted while it is out of service (they used to
  fail with NOT_FOUND).
* Out of service instances are forgotten after `ConfigOptions.unhealthy_expiry_timeout` seconds (default 900) without
  any health push; they used to be kept forever (a memory leak). Deregistering an out of service instance now removes it.
* Re-registration by health push now checks that the token belongs to the pushed `service_id`.
* Fix `ACTIVE_CLIENT` heartbeats: the client's heartbeat thread exited the first time `HEALTH_PUSH_FREQUENCY_SECONDS`
  (3 minutes) passed without a `set_health_status()` call, so services that did not keep calling it stopped sending
  heartbeats and were evicted by the router after `health_check_timeout` (5 minutes). The client now pushes
  heartbeats periodically until `close()`, which also stops the heartbeat thread.
* Fix the PushHealthStatus error message for an empty token ("service_token", was "service_context").
* Fix a race where concurrent registrations could start more than one health check thread.
* Ship type information (`py.typed` and generated `.pyi` stubs for the protobuf messages).
* Packaging/tooling: `[build-system]` table, SPDX license metadata, PEP 735 dependency groups (`test`, `dev`),
  ruff replaces flake8, updated GitHub Actions.

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
