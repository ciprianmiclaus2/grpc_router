import argparse
from concurrent.futures import ThreadPoolExecutor
import grpc

from grpc_router.stubs.grpc_router_service_pb2_grpc import add_GRPCRouterServiceServicer_to_server, GRPCRouterServiceServicer
from grpc_router.stubs.grpc_router_service_pb2 import (
    ServiceRegistrationResponse,
    ServiceDeregistrationResponse,
    GetRegisteredServiceResponse,
)

from grpc_router.core.register import ServiceRegister


class GRPCRouterServer(GRPCRouterServiceServicer):

    def __init__(self):
        self._register = ServiceRegister()

    def RegisterService(self, request, context):
        service_token, error = self._register.register_service(
            service_id=request.service_id,
            host=request.service_endpoint.host,
            port=request.service_endpoint.port
        )
        return ServiceRegistrationResponse(
            service_token=service_token,
            error=error
        )

    def DeregisterService(self, request, context):
        error = self._register.deregister_service(
            service_id=request.service_id,
            service_token=request.service_token
        )
        return ServiceDeregistrationResponse(
            error=error
        )

    def GetRegisteredService(self, request, context):
        service = self._register.get_service(
            service_id=request.service_id
        )
        if service is None:
            return GetRegisteredServiceResponse(
                error="No service available."
            )
        response = GetRegisteredServiceResponse()
        response.service_id = service.service_id
        response.service_endpoint.host = service.host
        response.service_endpoint.port = service.port
        response.error = ''
        return response


def serve(hostname: str="[::]", port: int=50034, max_workers: int=10):
    server = grpc.server(ThreadPoolExecutor(max_workers=max_workers))
    add_GRPCRouterServiceServicer_to_server(GRPCRouterServer(), server)
    server.add_insecure_port(f"{hostname}:{port}")
    server.start()
    server.wait_for_termination()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-h', '--hostname', dest='hostname', default='[::]',
                        help='Hostname to bind the service to')
    parser.add_argument('-p', '--port', dest='port', default=50034,
                        help='Port to bind this service to')
    parser.add_argument('-w', '--max-workers', dest='max_workers',
                        type=int, default=10,
                        help='Maximum concurrent workers to handle requests.')

    args = parser.parse_args()
    serve(
        hostname=args.hostname,
        port=args.port,
        max_workers=args.max_workers,
    )


if __name__ == "__main__":
    serve()
