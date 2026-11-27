# Health checks

A service picks how the router checks that it is alive when it registers, with a
[`HealthCheckType`](api/server.md#grpc_router.core.models.HealthCheckType):

* `NONE`: no checks. The instance stays registered until it deregisters, or until an instance registers again at
  the same address.
* `ACTIVE_CLIENT`: the service sends heartbeats to the router. `GRPCRouterClient` sends them in a background thread
  every `HEALTH_PUSH_FREQUENCY_SECONDS` (3 minutes), and straight away when `set_health_status()` is called.
* `PASSIVE_CLIENT`: the router would poll the service. **Not implemented yet**: such instances are accepted but never
  checked, so they are taken out of service after the health check timeout.

## Lifecycle of an `ACTIVE_CLIENT` instance

An instance is either *in service* (the router hands it out to clients) or *out of service* (it is still known to
the router, with its token, but not handed out).

| Event | Result |
|---|---|
| Registration | In service. |
| Heartbeat with `GOOD`, `WARNING` or `UNKNOWN` | Stays in service, or goes back in service if it was out. |
| Heartbeat with `ERROR` | Taken out of service, or stays out. |
| No heartbeat for `health_check_timeout` (default 5 minutes) | Taken out of service. |
| Out of service and no heartbeat at all, `ERROR` included, for `unhealthy_expiry_timeout` (default 15 minutes) | Forgotten: the next heartbeat gets `NOT_FOUND`. |
| Deregistration | Removed, whether in or out of service. |

The router checks the timeouts every 30 seconds, so they can be exceeded by up to that much.

## Reporting a problem

```python
from grpc_router.core.models import HealthStatus

router.set_health_status("myorg.billing.invoices", HealthStatus.ERROR, "Database down.")
# ... later, once the problem is fixed
router.set_health_status("myorg.billing.invoices", HealthStatus.GOOD, "")
```

Keep the client running while the service is out of service: its `ERROR` heartbeats tell the router the instance is
still alive, so it is not forgotten. The router never probes the service itself, so the service has to report when
it is healthy again.

## When the router forgets an instance

If the router restarted without a [state file](router.md#keeping-the-register-across-restarts), or forgot an
instance that was out of service and silent for too long, the instance's next heartbeat gets `NOT_FOUND`.
`GRPCRouterClient` then registers the service again, with a new token, and sends its current status at once: an
instance in `ERROR` goes straight back out of service.

## When a service restarts

A restarted service registers again and gets a new token. The registration replaces the entries of the same
service_id, host and port that look dead: entries that are out of service, that missed their heartbeats, or that
have no health checks. An entry that still looks healthy is kept, as it could be another live process behind the
same address; if it is a leftover, it misses its heartbeats and drops out within the health check timeout.
