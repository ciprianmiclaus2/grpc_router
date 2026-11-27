# Running the router

## From the command line

```
grpc-router --hostname 0.0.0.0 --port 50034
```

| Option | Default | |
|---|---|---|
| `-n`, `--hostname` | `[::]` | Hostname or address to bind to (`[::]`: all interfaces). |
| `-p`, `--port` | `50034` | Port to bind to. |
| `-w`, `--max-workers` | `10` | Maximum number of requests handled concurrently. |
| `-g`, `--shutdown-grace` | `5` | Seconds in-flight requests get to complete on SIGTERM/SIGINT. |
| `-s`, `--state-file` | | JSON file to persist the register to (see below). Disabled by default. |
| `--state-save-interval` | `1` | The state file is saved at most once per this many seconds. |

`python -m grpc_router.server` takes the same options.

The router logs to stderr, including the start, the shutdown and the restore of a state file.

## From Python

Some settings are only available from Python, through [`ConfigOptions`](api/server.md#grpc_router.core.models.ConfigOptions):
the region fallbacks, `health_check_timeout` and `unhealthy_expiry_timeout`.

```python
from grpc_router.core.models import ConfigOptions
from grpc_router.server import serve

serve(ConfigOptions(
    hostname="[::]", port=50034, max_workers=10,
    allow_cross_region_connectivity=False,  # never route a client to another region
    health_check_timeout=60,
    state_file="/var/lib/grpc-router/state.json",
))
```

`serve()` blocks until the router stops. `create_server()` returns a router that is not started yet, e.g. to run
it inside another program or in tests.

## Regions

Each instance registers with a region; the empty string is the *global* region. A client asking for a service in
a region gets, in order of preference:

1. an instance of its own region;
2. an instance of the global region, unless `allow_global_region` is off;
3. an instance of any other region, unless `allow_cross_region_connectivity` is off.

With `allow_global_region` off, registering without a region is rejected. Instances are returned round robin
within each of these groups.

## Shutting down

On SIGTERM or SIGINT (Ctrl+C) the router shuts down gracefully:

1. its [gRPC health](https://grpc.io/docs/guides/health-checking/) status turns `NOT_SERVING`, so health checking
   load balancers and watchers stop sending it traffic;
2. it rejects new requests and gives in-flight requests `--shutdown-grace` seconds to complete;
3. it saves the state file, if any, and exits with status 0.

A second signal stops it immediately.

## Keeping the register across restarts

The register lives in memory. With `--state-file`, the router also saves it to a JSON file and reloads it on start:

```
grpc-router --state-file /var/lib/grpc-router/state.json
```

* **Write behind**: registrations, deregistrations, services going in or out of service and status changes are
  saved in the background, at most once per `--state-save-interval`, and once more on shutdown. Plain heartbeats
  do not rewrite the file.
* **On start**, every restored instance gets a full health check timeout to send its next heartbeat, however old
  the file is: instances that died while the router was down then drop out through the normal health checks.
  Out of service instances stay out of service.
* **Recovery without the file**: a crash can lose the changes of the last save interval, and a router started
  without a state file knows nothing. Services with health checks recover on their own: when a heartbeat gets
  `NOT_FOUND`, `GRPCRouterClient` registers the service again. Services without health checks only come back
  with the state file, or when they register again.
* The file is written atomically (a temporary file renamed over it) and is only readable by its owner, as it holds
  the service tokens.
* A file that cannot be loaded is moved aside to `<name>.bad-<timestamp>` and the router starts empty. If the file
  cannot be written, the router does not start.
* Use **one file per router**: two routers sharing a file overwrite each other's state.

The file is meant to be readable:

```json
{
  "version": 1,
  "saved_at": "2026-11-27T13:17:34.555810+00:00",
  "instances": [
    {
      "service_id": "myorg.billing.invoices",
      "host": "invoices2.mydomain.com",
      "port": 8080,
      "region": "us-east",
      "slots": 10,
      "health_check_type": "ACTIVE_CLIENT",
      "service_token": "4b93c187-edc2-4116-afca-95ede07b603e",
      "in_service": false,
      "health_status": "ERROR",
      "description": "Database down."
    }
  ]
}
```

## Health and reflection

Besides its own API, the router serves:

* the standard [gRPC health checking](https://grpc.io/docs/guides/health-checking/) service
  (`grpc.health.v1.Health`), for the service `grpcrouter.GRPCRouterService` and for the server as a whole (`""`);
* [server reflection](https://grpc.io/docs/guides/reflection/), in both the `v1` and `v1alpha` versions, so tools
  like `grpcurl` can list and describe its API:

```
grpcurl -plaintext localhost:50034 list
grpcurl -plaintext localhost:50034 describe grpcrouter.GRPCRouterService
```

Only one router can listen on a port: a second router started on a port already in use fails to start, instead of
silently splitting the register between the two processes.
