# GRPC Router

<p align="center">
<a href="https://pypi.python.org/pypi/grpc_router">
    <img src="https://img.shields.io/pypi/v/grpc_router.svg"
        alt = "Release Status">
</a>

<a href="http://github.com/ciprianmiclaus2/grpc_router/">

<img src="https://img.shields.io/pypi/pyversions/grpc_router.svg" alt="Python versions">
</a>

<a href="https://github.com/ciprianmiclaus2/grpc_router/actions">
    <img src="https://github.com/ciprianmiclaus2/grpc_router/actions/workflows/python-package.yml/badge.svg?branch=main" alt="CI Status">
</a>

<a href="https://codecov.io/gh/ciprianmiclaus2/grpc_router" > 
 <img src="https://codecov.io/gh/ciprianmiclaus2/grpc_router/graph/badge.svg?token=4N0N8XSVZY"/> 
 </a>

<a href="https://ciprianmiclaus2.github.io/grpc_router/">
    <img src="https://img.shields.io/website/https/ciprianmiclaus2.github.io/grpc_router/index.html.svg?label=docs&down_message=unavailable&up_message=available" alt="Documentation Status">
</a>

</p>

GRPC Router is a small component that implements a simple service register to be used for client side service discovery.
Services register with the GRPC router, clients request the details of such services in order to discover them and connect directly.

## Installation

```
pip install grpc_router
```

Requires Python 3.11 or newer.

## Usage

Start the router (defaults: bind to `[::]:50034`):

```
grpc-router --hostname 0.0.0.0 --port 50034 --shutdown-grace 5
```

On SIGTERM or SIGINT (Ctrl+C) the router shuts down gracefully: its health status turns `NOT_SERVING`,
new requests are rejected and in-flight requests get `--shutdown-grace` seconds to complete.
A second signal stops it immediately.

A service registers itself and a client looks it up:

```python
from grpc_router.client.client import GRPCRouterClient
from grpc_router.core.models import HealthCheckType

# in the service
with GRPCRouterClient("router.mydomain.com", 50034) as router:
    router.register_service(
        "myorg.billing.invoices", host="invoices1.mydomain.com", port=8080,
        region="us-east", health_check_type=HealthCheckType.ACTIVE_CLIENT,
    )
    ...  # serve requests; the client pushes heartbeats in the background
    router.deregister_service("myorg.billing.invoices")

# in a client of that service
router = GRPCRouterClient("router.mydomain.com", 50034)
host, port = router.get_service("myorg.billing.invoices", region="us-east")
```

Instances of the same service are returned round robin, preferring the client's own region. If the router
cannot be reached, lookups answer from the instances they last saw. To follow the instances of a service live,
or to get a channel per instance:

```python
watch = router.watch_service_instances("myorg.billing.invoices", region="us-east")  # lookups now local

from grpc_router.client.discovery import ServiceChannelPool
with ServiceChannelPool(router, "myorg.billing.invoices", region="us-east") as pool:
    channel = pool.next_channel()  # round robin over the instances
```

With `HealthCheckType.ACTIVE_CLIENT` the client sends heartbeats to the router. A service that misses
heartbeats, or reports an error with `set_health_status(service_id, HEALTH_STATUS_ERROR, "why")`, is taken
out of service until it reports a healthy status again (`HEALTH_STATUS_GOOD` or `HEALTH_STATUS_WARNING`,
from `grpc_router.stubs.grpc_router_service_pb2`).

If the router forgets a service (it restarted, or the service was out of service and silent for longer than
the expiry timeout), the client registers the service again on its next heartbeat.

### Keeping the register across router restarts

```
grpc-router --state-file /var/lib/grpc-router/state.json
```

The router saves its register to that JSON file in the background (at most once per `--state-save-interval`
seconds, default 1, plus on shutdown) and reloads it on start, so clients can find services straight away
after a restart, including services without health checks, which never re-register on their own. Restored
services have a full health check timeout to send a heartbeat. The file holds the service tokens, so it is
created readable by its owner only. Use one file per router.
The router also exposes the standard gRPC health checking service, and server reflection (both v1 and v1alpha)
so tools like `grpcurl` can list and describe its API.
