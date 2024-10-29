import grpc
import pytest

from grpc_router.client.client import GRPCRouterClient


@pytest.mark.parametrize("service_id,host,port,region,expected_err_code,expected_err_str", [
    ["", "myhost", 1234, "NYC", grpc.StatusCode.INVALID_ARGUMENT, "The service_id cannot be empty."],
    ["my,svc", "", 1234, "NYC", grpc.StatusCode.INVALID_ARGUMENT, "The host cannot be empty."],
    ["my,svc", "myhost", -10, "NYC", grpc.StatusCode.INVALID_ARGUMENT, "The port cannot be negative or zero."],
    ["my,svc", "myhost", 0, "NYC", grpc.StatusCode.INVALID_ARGUMENT, "The port cannot be negative or zero."],
])
def test_register_service_validation_errors(service_id, host, port, region, expected_err_code, expected_err_str, grpc_router_server):
    client = GRPCRouterClient("localhost", 7654)
    with pytest.raises(grpc.RpcError) as exc:
        client.register_service(
            service_id=service_id,
            host=host,
            port=port,
            region=region
        )
    assert exc.value.code() == expected_err_code
    assert exc.value.details() == expected_err_str


@pytest.mark.parametrize("service_id,host,port,region,expected_err_code,expected_err_str", [
    ["my,svc", "myhost", 1234, "", grpc.StatusCode.INVALID_ARGUMENT, "The region cannot be empty in this current configuration."],
])
def test_register_service_validation_errors_no_global_region(service_id, host, port, region, expected_err_code, expected_err_str, grpc_router_server_no_allow_global_region):
    client = GRPCRouterClient("localhost", 7653)
    with pytest.raises(grpc.RpcError) as exc:
        client.register_service(
            service_id=service_id,
            host=host,
            port=port,
            region=region
        )
    assert exc.value.code() == expected_err_code
    assert exc.value.details() == expected_err_str


@pytest.mark.parametrize("service_id,service_token,expected_err_code,expected_err_str", [
    ["", "token", grpc.StatusCode.INVALID_ARGUMENT, "The service_id cannot be empty."],
    ["svc", "", grpc.StatusCode.INVALID_ARGUMENT, "The service_token cannot be empty."],
])
def test_deregister_service_validation_errors(service_id, service_token, expected_err_code, expected_err_str, grpc_router_server):
    client = GRPCRouterClient("localhost", 7654)
    client._service_register[service_id] = {
        "token": service_token
    }
    with pytest.raises(grpc.RpcError) as exc:
        client.deregister_service(
            service_id=service_id,
        )
    assert exc.value.code() == expected_err_code
    assert exc.value.details() == expected_err_str


@pytest.mark.parametrize("service_id,expected_err_code,expected_err_str", [
    ["", grpc.StatusCode.INVALID_ARGUMENT, "The service_id cannot be empty."],
])
def test_get_registered_service_validation_errors(service_id, expected_err_code, expected_err_str, grpc_router_server):
    client = GRPCRouterClient("localhost", 7654)
    with pytest.raises(grpc.RpcError) as exc:
        client.get_service(
            service_id=service_id
        )
    assert exc.value.code() == expected_err_code
    assert exc.value.details() == expected_err_str
