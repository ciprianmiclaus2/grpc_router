import argparse
import logging
import signal
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import FrameType

import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from grpc_reflection.v1alpha import reflection, reflection_pb2, reflection_pb2_grpc

from grpc_router.core.models import ConfigOptions, HealthCheckType, HealthStatus
from grpc_router.core.persistence import StateWriter
from grpc_router.core.register import ServiceRegister
from grpc_router.stubs.grpc_router_service_pb2 import (
    DESCRIPTOR,
    HEALTH_CHECK_ACTIVE_CLIENT,
    HEALTH_CHECK_PASSIVE_CLIENT,
    HEALTH_STATUS_ERROR,
    HEALTH_STATUS_GOOD,
    HEALTH_STATUS_WARNING,
    GetRegisteredServiceResponse,
    HealthInfoResponse,
    ServiceDeregistrationResponse,
    ServiceRegistrationResponse,
)
from grpc_router.stubs.grpc_router_service_pb2_grpc import GRPCRouterServiceServicer, add_GRPCRouterServiceServicer_to_server

SERVICE_NAME = DESCRIPTOR.services_by_name["GRPCRouterService"].full_name

# grpcio-reflection only ships the v1alpha reflection service. The v1 protocol is a copy
# of it under a new package name (identical messages on the wire), so the v1alpha
# servicer also serves v1 clients, e.g. recent grpcurl/Postman versions.
REFLECTION_V1_SERVICE_NAME = "grpc.reflection.v1.ServerReflection"

logger = logging.getLogger(__name__)


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

    def __init__(self, config: ConfigOptions) -> None:
        self._config = config
        self._register = ServiceRegister(config)
        self._state_writer: StateWriter | None = None
        if config.state_file:
            self._state_writer = StateWriter(Path(config.state_file), self._register, config.state_save_interval)
            self._state_writer.start()

    def close(self) -> None:
        """Save any pending change of the register to the state file."""
        if self._state_writer is not None:
            self._state_writer.stop()
            self._state_writer = None

    def _validate_RegisterService(self, request, context) -> None:
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
        service_token, _error = self._register.register_service(
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
                "The service_token cannot be empty."
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
    """Serve gRPC server reflection, both the v1 and the v1alpha versions."""
    servicer = reflection.ReflectionServicer(
        (SERVICE_NAME, REFLECTION_V1_SERVICE_NAME, reflection.SERVICE_NAME)
    )
    # v1alpha
    reflection_pb2_grpc.add_ServerReflectionServicer_to_server(servicer, server)
    # v1: the same servicer and (wire compatible) messages, on the v1 method path
    server.add_generic_rpc_handlers((
        grpc.method_handlers_generic_handler(REFLECTION_V1_SERVICE_NAME, {
            "ServerReflectionInfo": grpc.stream_stream_rpc_method_handler(
                servicer.ServerReflectionInfo,
                request_deserializer=reflection_pb2.ServerReflectionRequest.FromString,
                response_serializer=reflection_pb2.ServerReflectionResponse.SerializeToString,
            ),
        }),
    ))


def enable_health_service(server: grpc.Server) -> health.HealthServicer:
    health_servicer = health.HealthServicer(
        experimental_non_blocking=True,
        experimental_thread_pool=ThreadPoolExecutor(max_workers=5),
    )
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    health_servicer.set(SERVICE_NAME, health_pb2.HealthCheckResponse.SERVING)
    return health_servicer


def _build_server(config: ConfigOptions) -> tuple[grpc.Server, health.HealthServicer, GRPCRouterServer]:
    server = grpc.server(
        ThreadPoolExecutor(max_workers=config.max_workers),
        # The router holds the service register in memory, so two routers sharing a
        # port (grpc enables SO_REUSEPORT by default on Linux) would split it.
        options=[("grpc.so_reuseport", 0)],
    )
    router = GRPCRouterServer(config)
    add_GRPCRouterServiceServicer_to_server(router, server)
    enable_reflection_service(server)
    health_servicer = enable_health_service(server)
    server.add_insecure_port(f"{config.hostname}:{config.port}")
    return server, health_servicer, router


def create_server(config: ConfigOptions) -> grpc.Server:
    """Create a (not yet started) grpc router server bound to config.hostname:config.port.

    With config.state_file the register is loaded from it now and saved in the background;
    use serve() to also get the final save on shutdown.
    """
    server, _, _ = _build_server(config)
    return server


def serve(config: ConfigOptions) -> None:
    """Run the grpc router until it is stopped.

    When called from the main thread, SIGTERM and SIGINT trigger a graceful shutdown:
    the health status turns NOT_SERVING, new RPCs are rejected and in-flight RPCs get
    config.shutdown_grace seconds to complete. A second signal stops immediately.
    """
    server, health_servicer, router = _build_server(config)
    server.start()
    logger.info("grpc router listening on %s:%s", config.hostname, config.port)

    stopping = False

    def _shutdown(signum: int, frame: FrameType | None) -> None:
        nonlocal stopping
        name = signal.Signals(signum).name
        if stopping:
            logger.info("Received %s again, stopping immediately", name)
            server.stop(None)
            return
        stopping = True
        logger.info("Received %s, shutting down (grace period %ss)", name, config.shutdown_grace)
        health_servicer.enter_graceful_shutdown()
        server.stop(config.shutdown_grace)

    previous_handlers = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[sig] = signal.signal(sig, _shutdown)
    try:
        server.wait_for_termination()
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        router.close()
    logger.info("grpc router stopped")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('-n', '--hostname', dest='hostname', default='[::]',
                        help='Hostname to bind the service to')
    parser.add_argument('-p', '--port', dest='port', default=50034, type=int,
                        help='Port to bind this service to')
    parser.add_argument('-w', '--max-workers', dest='max_workers',
                        type=int, default=10,
                        help='Maximum concurrent workers to handle requests.')
    parser.add_argument('-g', '--shutdown-grace', dest='shutdown_grace',
                        type=float, default=5.0,
                        help='Seconds to let in-flight requests complete on SIGTERM/SIGINT.')
    parser.add_argument('-s', '--state-file', dest='state_file', default=None,
                        help='JSON file to save the service register to (write behind) and to reload it from '
                             'on restart. Disabled by default. One file per router.')
    parser.add_argument('--state-save-interval', dest='state_save_interval', type=float, default=1.0,
                        help='Save the state file at most once per this many seconds.')

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = ConfigOptions(
        hostname=args.hostname,
        port=args.port,
        max_workers=args.max_workers,
        shutdown_grace=args.shutdown_grace,
        state_file=args.state_file,
        state_save_interval=args.state_save_interval,
    )
    serve(config)


if __name__ == "__main__":
    main()
