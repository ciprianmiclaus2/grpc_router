import pytest
from google.protobuf import descriptor_pb2
from grpc_reflection.v1alpha import reflection_pb2

from grpc_router.client.client import GRPCRouterClient

# v1 messages are wire compatible with v1alpha, so the v1alpha classes work for both
REFLECTION_METHODS = [
    "/grpc.reflection.v1alpha.ServerReflection/ServerReflectionInfo",
    "/grpc.reflection.v1.ServerReflection/ServerReflectionInfo",
]


def _reflect(method: str, request: reflection_pb2.ServerReflectionRequest) -> reflection_pb2.ServerReflectionResponse:
    client = GRPCRouterClient("localhost", 7654)
    call = client.channel.stream_stream(
        method,
        request_serializer=reflection_pb2.ServerReflectionRequest.SerializeToString,
        response_deserializer=reflection_pb2.ServerReflectionResponse.FromString,
    )
    responses = list(call(iter([request])))
    assert len(responses) == 1
    return responses[0]


@pytest.mark.parametrize("method", REFLECTION_METHODS)
def test_reflection_list_services(method, grpc_router_server):
    response = _reflect(method, reflection_pb2.ServerReflectionRequest(host="", list_services=""))
    services = [r.name for r in response.list_services_response.service]
    assert services == [
        'grpc.reflection.v1.ServerReflection',
        'grpc.reflection.v1alpha.ServerReflection',
        'grpcrouter.GRPCRouterService',
    ]


@pytest.mark.parametrize("method", REFLECTION_METHODS)
def test_reflection_file_containing_symbol(method, grpc_router_server):
    response = _reflect(method, reflection_pb2.ServerReflectionRequest(
        file_containing_symbol="grpcrouter.GRPCRouterService"
    ))
    files = [
        descriptor_pb2.FileDescriptorProto.FromString(f)
        for f in response.file_descriptor_response.file_descriptor_proto
    ]
    service_names = [svc.name for f in files for svc in f.service]
    assert "GRPCRouterService" in service_names
