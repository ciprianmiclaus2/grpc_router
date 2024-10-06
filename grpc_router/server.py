import argparse
from concurrent.futures import ThreadPoolExecutor
import grpc

from grpc_router.stubs.grpc_router_service_pb2_grpc import add_GRPCRouterServiceServicer_to_server, GRPCRouterServiceServicer


class GRPCRouterServer(GRPCRouterServiceServicer):

    def RegisterService(self, request, context):
        print("register service")

    def DeregisterService(self, request, context):
        print("deregister service")

    def GetRegisteredService(self, request, context):
        print("get registered service")


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
