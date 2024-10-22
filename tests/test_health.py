from grpc_router.client.client import GRPCRouterClient
from grpc_health.v1 import health_pb2
from grpc_health.v1 import health_pb2_grpc


def test_health_check(grpc_router_server):
    client = GRPCRouterClient("localhost", 7654)

    stub = health_pb2_grpc.HealthStub(client.channel)
    res = stub.Check(
        health_pb2.HealthCheckRequest(service="")
    )
    assert res.status == health_pb2.HealthCheckResponse.SERVING
    res = stub.Check(
        health_pb2.HealthCheckRequest(service="grpcrouter.GRPCRouterService")
    )
    assert res.status == health_pb2.HealthCheckResponse.SERVING
