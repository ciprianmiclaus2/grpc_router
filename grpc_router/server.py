import argparse
from concurrent.futures import ThreadPoolExecutor
import grpc
from grpc_health.v1 import health
from grpc_health.v1 import health_pb2
from grpc_health.v1 import health_pb2_grpc
from grpc_reflection.v1alpha import reflection

from grpc_router.stubs.grpc_router_service_pb2_grpc import add_GRPCRouterServiceServicer_to_server, GRPCRouterServiceServicer
from grpc_router.stubs.grpc_router_service_pb2 import (
    HEALTH_CHECK_ACTIVE_CLIENT,
    HEALTH_CHECK_PASSIVE_CLIENT,
    HEALTH_STATUS_GOOD,
    HEALTH_STATUS_WARNING,
    HEALTH_STATUS_ERROR,
    HealthInfoResponse,
    ServiceRegistrationResponse,
    ServiceDeregistrationResponse,
    GetRegisteredServiceResponse,
    DESCRIPTOR,
)

from grpc_router.core.models import ConfigOptions, HealthCheckType, HealthStatus
from grpc_router.core.register import ServiceRegister


def to_health_check_type(health_check_type: int) -> HealthCheckType:
    if health_check_type == HEALTH_CHECK_ACTIVE_CLIENT:
        return HealthCheckType.ACTIVE_CLIENT
    elif health_check_type == HEALTH_CHECK_PASSIVE_CLIENT:
        return HealthCheckType.PASSIVE_CLIENT
    return HealthCheckType.NONE


def to_health_status(health_status: int) -> HealthStatus:
    if health_status == HEALTH_STATUS_GOOD:
        return HealthStatus.GOOD
    elif health_status == HEALTH_STATUS_ERROR:
        return HealthStatus.ERROR
    elif health_status == HEALTH_STATUS_WARNING:
        return HealthStatus.WARNING
    return HealthStatus.UNKNOWN


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
            health_check_type=to_health_check_type(request.metadata.health_check_type),
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
                "The service_token cannot be empty."
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

    def _validate_PushHealthStatus(self, request, context) -> None:
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

    def PushHealthStatus(self, request, context) -> HealthInfoResponse:
        self._validate_PushHealthStatus(request, context)
        svc = self._register.push_health_status(
            service_id=request.service_id,
            service_token=request.service_token,
            health_status=to_health_status(request.status),
            description=request.description)
        if svc is None:
            context.abort(
                grpc.StatusCode.NOT_FOUND,
                "The service could not be found."
            )
        response = HealthInfoResponse()
        return response


def enable_reflection_service(server: grpc.Server) -> None:
    SERVICE_NAMES = (
        DESCRIPTOR.services_by_name["GRPCRouterService"].full_name,
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(SERVICE_NAMES, server)


def enable_health_service(server: grpc.Server) -> None:
    health_servicer = health.HealthServicer(
        experimental_non_blocking=True,
        experimental_thread_pool=ThreadPoolExecutor(max_workers=5),
    )
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    health_servicer.set(
        DESCRIPTOR.services_by_name["GRPCRouterService"].full_name,
        health_pb2.HealthCheckResponse.SERVING
    )


def serve(config: ConfigOptions) -> None:
    server = grpc.server(ThreadPoolExecutor(max_workers=config.max_workers))
    add_GRPCRouterServiceServicer_to_server(GRPCRouterServer(config), server)
    enable_reflection_service(server)
    enable_health_service(server)
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
