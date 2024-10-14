import grpc
import pytest

from grpc_router.client.client import GRPCRouterClient


def register_svc(client: GRPCRouterClient, service_id: str, region: str, instance: int, port: int) -> str:
    token = client.register_service(
        service_id=service_id,
        host=f"{region}{instance}.mydomain.com",
        port=port,
        region=region
    )
    assert token is not None
    return token


@pytest.mark.parametrize('region,expected_host,expected_port', [
    ["USWest", "USWest1.mydomain.com", 9002],
    ["USWest", "USWest2.mydomain.com", 9003],
    ["USWest", "USWest3.mydomain.com", 9004],
    ["USEast", "USEast1.mydomain.com", 9000],
    ["USEast", "USEast2.mydomain.com", 9001],
    ["USWest", "USWest1.mydomain.com", 9002],
    ["USEast", "USEast1.mydomain.com", 9000],
    ["", "1.mydomain.com", 9005],
    ["", "2.mydomain.com", 9006],
    ["", "1.mydomain.com", 9005],
    ["UNKNOWN", "2.mydomain.com", 9006],
    ["UNKNOWN2", "1.mydomain.com", 9005],
])
def test_region_stickiness(region, expected_host, expected_port, grpc_router_server):
    # the instance in the same region is preferred over other regions
    service_id = "my.region.stickiness.test.service"

    client = GRPCRouterClient("localhost", 7654)

    tokens = [
        register_svc(client, service_id, "USEast", 1, 9000),
        register_svc(client, service_id, "USEast", 2, 9001),
        register_svc(client, service_id, "USWest", 1, 9002),
        register_svc(client, service_id, "USWest", 2, 9003),
        register_svc(client, service_id, "USWest", 3, 9004),
        register_svc(client, service_id, "", 1, 9005),
        register_svc(client, service_id, "", 2, 9006),
    ]

    try:
        host, port = client.get_service(service_id, region=region)
        assert host == expected_host
        assert port == expected_port
    finally:
        for token in tokens:
            client.deregister_service(
                service_id=service_id,
                service_token=token
            )


@pytest.mark.parametrize('region,expected_host,expected_port', [
    ["USWest", "USWest1.mydomain.com", 9002],
    ["USWest", "USWest2.mydomain.com", 9003],
    ["USWest", "USWest3.mydomain.com", 9004],
    ["USEast", "USEast1.mydomain.com", 9000],
    ["", "USEast1.mydomain.com", 9000],
    ["USEast", "USEast2.mydomain.com", 9001],
    ["USCentral", "USCentral1.mydomain.com", 9005],
    ["", "USEast2.mydomain.com", 9001],
    ["", "USWest1.mydomain.com", 9002],
    ["USWest", "USWest1.mydomain.com", 9002],
    ["USEast", "USEast1.mydomain.com", 9000],
    ["UNKNOWN", "USWest2.mydomain.com", 9003],
    ["UNKNOWN2", "USWest3.mydomain.com", 9004],
    ["USCentral", "USCentral2.mydomain.com", 9006],
    ["UNKNOWN", "USCentral1.mydomain.com", 9005],
    ["UNKNOWN", "USCentral2.mydomain.com", 9006],
    ["NOREGION", "USEast1.mydomain.com", 9000],
])
def test_region_no_global_region(region, expected_host, expected_port, grpc_router_server):
    # the instance in the same region is preferred over other regions
    service_id = "my.region.noglobal.test.service"

    client = GRPCRouterClient("localhost", 7654)

    tokens = []

    tokens = [
        register_svc(client, service_id, "USEast", 1, 9000),
        register_svc(client, service_id, "USEast", 2, 9001),
        register_svc(client, service_id, "USWest", 1, 9002),
        register_svc(client, service_id, "USWest", 2, 9003),
        register_svc(client, service_id, "USWest", 3, 9004),
        register_svc(client, service_id, "USCentral", 1, 9005),
        register_svc(client, service_id, "USCentral", 2, 9006),
    ]

    try:
        host, port = client.get_service(service_id, region=region)
        assert host == expected_host
        assert port == expected_port
    finally:
        for token in tokens:
            client.deregister_service(
                service_id=service_id,
                service_token=token
            )


def test_region_cross_region(grpc_router_server):
    service_id = "my.region.cross_region.test.service"

    client = GRPCRouterClient("localhost", 7654)

    tokens = []

    tokens = [
        register_svc(client, service_id, "USEast", 1, 9000),
        register_svc(client, service_id, "USEast", 2, 9001),
        register_svc(client, service_id, "USWest", 1, 9002),
    ]
    try:
        host, port = client.get_service(service_id, region="USMidWest")
        assert host == "USEast1.mydomain.com"
        assert port == 9000
    finally:
        for token in tokens:
            client.deregister_service(
                service_id=service_id,
                service_token=token
            )


def test_region_no_cross_region(grpc_router_server_no_global_region_no_cross_region):
    service_id = "my.region.no_cross_region.test.service"

    client = GRPCRouterClient("localhost", 7652)

    tokens = []

    tokens = [
        register_svc(client, service_id, "USEast", 1, 9000),
        register_svc(client, service_id, "USEast", 2, 9001),
        register_svc(client, service_id, "USWest", 1, 9002),
    ]
    try:
        with pytest.raises(grpc.RpcError) as exc:
            client.get_service(service_id, region="USMidWest")
        assert exc.value.code() == grpc.StatusCode.NOT_FOUND
        assert exc.value.details() == "The service_id has no registered instances."
    finally:
        for token in tokens:
            client.deregister_service(
                service_id=service_id,
                service_token=token
            )
