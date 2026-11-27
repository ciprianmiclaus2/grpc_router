import signal
import subprocess
import sys
import time

import grpc
import pytest
from grpc_health.v1 import health_pb2, health_pb2_grpc

PORT = 7656
SERVICE = "grpcrouter.GRPCRouterService"


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_graceful_shutdown_on_signal(sig):
    proc = subprocess.Popen(
        [sys.executable, "-m", "grpc_router.server", "-n", "localhost", "-p", str(PORT), "--shutdown-grace", "2"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        with grpc.insecure_channel(f"localhost:{PORT}") as channel:
            grpc.channel_ready_future(channel).result(timeout=10)
            watch = health_pb2_grpc.HealthStub(channel).Watch(health_pb2.HealthCheckRequest(service=SERVICE))
            assert next(watch).status == health_pb2.HealthCheckResponse.SERVING

            proc.send_signal(sig)
            started = time.monotonic()
            # watchers are told the router is going away while in-flight calls drain
            assert next(watch).status == health_pb2.HealthCheckResponse.NOT_SERVING

            output, _ = proc.communicate(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
    assert proc.returncode == 0, output
    assert time.monotonic() - started < 5  # the 2s grace period, not a hang
    assert f"Received {sig.name}, shutting down (grace period 2.0s)" in output
    assert "grpc router stopped" in output
    assert "Traceback" not in output
