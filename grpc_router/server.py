import argparse
from concurrent.futures import ThreadPoolExecutor
import grpc
from grpc_reflection.v1alpha import reflection

from grpc_router.stubs.grpc_router_service_pb2_grpc import add_GRPCRouterServiceServicer_to_server, GRPCRouterServiceServicer
from grpc_router.stubs.grpc_router_service_pb2 import (
    ServiceRegistrationResponse,
    ServiceDeregistrationResponse,
    GetRegisteredServiceResponse,
    DESCRIPTOR,
)

from grpc_router.core.models import ConfigOptions
from grpc_router.core.register import ServiceRegister


class GRPCRouterServer(GRPCRouterServiceServicer):

    def __init__(self, config: ConfigOptions):
        self._config = config
        self._register = ServiceRegister(config)

    def _validate_RegisterService(self, request, context):
        service_id = request.service_id
        if not service_id:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "The service_id cannot be empty."
            )
        host = request.endpoint.host
        if not host:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "The host cannot be empty."
            )

        port = request.endpoint.port
        if port <= 0:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "The port cannot be negative or zero."
            )
        region = request.metadata.region
        if not region and not self._config.allow_global_region:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "The region cannot be empty in this current configuration."
            )

    def RegisterService(self, request, context) -> ServiceRegistrationResponse:
        self._validate_RegisterService(request, context)
        service_token, error = self._register.register_service(
            service_id=request.service_id,
            host=request.endpoint.host,
            port=request.endpoint.port,
            region=request.metadata.region,
            slots=request.metadata.slots,
        )
        return ServiceRegistrationResponse(
            service_token=service_token
        )

    def _validate_DeregisterService(self, request, context) -> None:
        service_id = request.service_id
        if not service_id:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "The service_id cannot be empty."
            )
        service_token = request.service_token
        if not service_token:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "The service_context cannot be empty."
            )

    def DeregisterService(self, request, context) -> ServiceDeregistrationResponse:
        self._validate_DeregisterService(request, context)
        self._register.deregister_service(
            service_id=request.service_id,
            service_token=request.service_token
        )
        return ServiceDeregistrationResponse()

    def _validate_GetRegisteredService(self, request, context) -> None:
        service_id = request.service_id
        if not service_id:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "The service_id cannot be empty."
            )

    def GetRegisteredService(self, request, context) -> GetRegisteredServiceResponse:
        self._validate_GetRegisteredService(request, context)
        service = self._register.get_service(
            service_id=request.service_id,
            region=request.hints.region
        )
        if service is None:
            context.abort(
                grpc.StatusCode.NOT_FOUND,
                "The service_id has no registered instances."
            )
        assert service is not None
        response = GetRegisteredServiceResponse()
        response.service_id = service.service_id
        response.endpoint.host = service.host
        response.endpoint.port = service.port
        return response


def serve(config: ConfigOptions) -> None:
    server = grpc.server(ThreadPoolExecutor(max_workers=config.max_workers))
    add_GRPCRouterServiceServicer_to_server(GRPCRouterServer(config), server)
    SERVICE_NAMES = (
        DESCRIPTOR.services_by_name["GRPCRouterService"].full_name,
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(SERVICE_NAMES, server)
    server.add_insecure_port(f"{config.hostname}:{config.port}")
    server.start()
    server.wait_for_termination()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-n', '--hostname', dest='hostname', default='[::]',
                        help='Hostname to bind the service to')
    parser.add_argument('-p', '--port', dest='port', default=50034, type=int,
                        help='Port to bind this service to')
    parser.add_argument('-w', '--max-workers', dest='max_workers',
                        type=int, default=10,
                        help='Maximum concurrent workers to handle requests.')

    args = parser.parse_args()
    config = ConfigOptions(
        hostname=args.hostname,
        port=args.port,
        max_workers=args.max_workers,
    )
    serve(config)


if __name__ == "__main__":
    main()
