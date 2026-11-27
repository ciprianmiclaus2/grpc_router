# Python API

* [Client](client.md): `GRPCRouterClient`, used by services to register and by their clients to look them up.
* [Watches and channel pool](discovery.md): `ServiceWatch` and `ServiceChannelPool`, see
  [Discovering services](../discovery.md).
* [Server and configuration](server.md): `serve`, `GRPCRouter`, `BackgroundRouter`, `ConfigOptions`, and the
  `HealthCheckType` and `HealthStatus` enums.

The generated protobuf and gRPC code is in `grpc_router.stubs` (see the [gRPC API](../grpc-api.md)).
