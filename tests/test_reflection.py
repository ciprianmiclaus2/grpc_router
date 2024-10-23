from grpc_router.client.client import GRPCRouterClient
from grpc_reflection.v1alpha import reflection_pb2
from grpc_reflection.v1alpha import reflection_pb2_grpc


def test_reflection(grpc_router_server):
    client = GRPCRouterClient("localhost", 7654)

    stub = reflection_pb2_grpc.ServerReflectionStub(client.channel)
    request = reflection_pb2.ServerReflectionRequest()
    request.host = ""
    request.list_services = ""
    res = stub.ServerReflectionInfo((r for r in (request,)))
    responses = list(res)
    assert len(responses) == 1
    response = responses[0]
    services = [r.name for r in response.list_services_response.service]
    assert services == [
        'grpc.reflection.v1alpha.ServerReflection',
        'grpcrouter.GRPCRouterService'
    ]
