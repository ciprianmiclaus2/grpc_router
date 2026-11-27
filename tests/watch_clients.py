"""Helper process for test_many_watching_clients: simulated clients, one connection and one watch each.

It runs in its own process so that its asyncio event loop does not share gRPC's per-process asyncio
poller with the routers the other tests run in background event loops, and so that its many sockets
count against its own limit of open files.

Usage: python watch_clients.py PORT CLIENTS RAMP_SECONDS. Prints "ready", waits for a line on stdin,
registers an instance, then prints a JSON line with the results.
"""

import asyncio
import json
import sys
import time

import grpc

from grpc_router.server import raise_open_files_limit
from grpc_router.stubs.grpc_router_service_pb2 import (
    ServiceEndpoint,
    ServiceRegistrationRequest,
    ServiceSubscription,
    WatchServicesRequest,
)
from grpc_router.stubs.grpc_router_service_pb2_grpc import GRPCRouterServiceStub

SERVICE_ID = "many.watchers.service"


async def main(port: int, clients: int, ramp_seconds: float) -> dict:
    subscribe = WatchServicesRequest(subscribe=[ServiceSubscription(service_id=SERVICE_ID)])

    async def open_watch(delay: float):
        await asyncio.sleep(delay)  # connect over a few seconds, as real clients do
        channel = grpc.aio.insecure_channel(f"localhost:{port}", options=[("grpc.use_local_subchannel_pool", 1)])
        call = GRPCRouterServiceStub(channel).WatchServices()
        await call.write(subscribe)
        await asyncio.wait_for(call.read(), 30)
        return channel, call

    watches = await asyncio.gather(*(open_watch(ramp_seconds * n / clients) for n in range(clients)))
    print("ready", flush=True)
    await asyncio.to_thread(sys.stdin.readline)

    async with grpc.aio.insecure_channel(f"localhost:{port}") as control:
        started = time.monotonic()
        await GRPCRouterServiceStub(control).RegisterService(ServiceRegistrationRequest(
            service_id=SERVICE_ID, endpoint=ServiceEndpoint(host="a", port=9000)))
        updates = await asyncio.gather(*(asyncio.wait_for(call.read(), 30) for _, call in watches))
        fan_out = time.monotonic() - started
    seen = sum(1 for u in updates if [i.endpoint.host for i in u.updates[0].instances] == ["a"])
    for _, call in watches:
        call.cancel()
    await asyncio.gather(*(channel.close() for channel, _ in watches))
    return {"opened": len(watches), "seen": seen, "fan_out": fan_out}


if __name__ == "__main__":
    raise_open_files_limit()
    print(json.dumps(asyncio.run(main(int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3])))), flush=True)
