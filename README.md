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

Start the router (defaults: bind to `[::]:50034` with 10 workers):

```
grpc-router --hostname 0.0.0.0 --port 50034 --max-workers 10 --shutdown-grace 5
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

Instances of the same service are returned round robin, preferring the client's own region.
The router also exposes the standard gRPC health checking service, and server reflection (both v1 and v1alpha)
so tools like `grpcurl` can list and describe its API.
