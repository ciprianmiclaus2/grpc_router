import grpc
import json
from typing import Any, Optional

from grpc_router.stubs.grpc_router_service_pb2_grpc import GRPCRouterServiceStub
from grpc_router.stubs.grpc_router_service_pb2 import (
    GetRegisteredServiceRequest,
    ServiceDeregistrationRequest,
    ServiceRegistrationRequest,
)


class GRPCRouterClient:

    DEFAULT_GRPC_SERVICE_CONFIG = {
        "methodConfig": [{
            "name": [{"service": ""}],
            "retryPolicy": {
                "maxAttempts": 5,
                "initialBackoff": "5s",
                "maxBackoff": "30s",
                "backoffMultiplier": 2,
                "retryableStatusCodes": [
                    "ABORTED", "CANCELLED", "DATA_LOSS", "DEADLINE_EXCEEDED",
                    "FAILED_PRECONDITION", "INTERNAL", "RESOURCE_EXHAUSTED",
                    "UNAVAILABLE", "UNKNOWN",
                ]
            }
        }]
    }

    def __init__(self, host: str, port: int, grpc_service_config: Optional[dict[str, Any]]=None):
        self.host = host
        self.port = port
        self._channel = None
        self._grpc_service_config = grpc_service_config if grpc_service_config is not None else self.DEFAULT_GRPC_SERVICE_CONFIG

    @property
    def channel(self):
        if self._channel is None:
            if self._grpc_service_config:
                options = [
                    ("grpc.service_config", json.dumps(self._grpc_service_config))
                ]
            else:
                options = None
            self._channel = grpc.insecure_channel(
                f'{self.host}:{self.port}',
                options=options
            )
        return self._channel

    @property
    def stub(self):
        return GRPCRouterServiceStub(self.channel)

    def register_service(self, service_id: str, host: str, port: int) -> str:
        res = self.stub.RegisterService(
            ServiceRegistrationRequest(
                service_id=service_id,
                host=host,
                port=port
            )
        )
        if res.error:
            raise ValueError(res.error)
        return res.service_token

    def deregister_service(self, service_id: str, service_token: str):
        res = self.stub.DeregisterService(
            ServiceDeregistrationRequest(
                service_id=service_id,
                service_token=service_token
            )
        )
        if res.error:
            raise ValueError(res.error)

    def get_service(self, service_id: str) -> tuple[str, int]:
        res = self.stub.GetRegisteredService(
            GetRegisteredServiceRequest(service_id=service_id)
        )
        if res.error:
            raise ValueError(res.error)
        return res.host, res.port
