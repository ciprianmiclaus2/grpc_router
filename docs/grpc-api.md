# gRPC API

The router's API is defined in
[`proto/grpc_router_service.proto`](https://github.com/ciprianmiclaus2/grpc_router/blob/main/proto/grpc_router_service.proto).
Python services and clients can use [`GRPCRouterClient`](api/client.md); from other languages, generate a client
from the proto file, or explore the API of a running router with server reflection, e.g. with `grpcurl`.

A service written in another language has to do what `GRPCRouterClient` does for `ACTIVE_CLIENT` instances: call
`PushHealthStatus` regularly (well within the router's health check timeout, 5 minutes by default), and call
`RegisterService` again when `PushHealthStatus` returns `NOT_FOUND`. See [Health checks](health-checks.md).

```protobuf
{%
  include "../proto/grpc_router_service.proto"
%}
```
