import datetime
import grpc
import json
import logging
import time
from threading import Thread, Event
from typing import Any, Optional

from grpc_router.stubs.grpc_router_service_pb2_grpc import GRPCRouterServiceStub
from grpc_router.stubs.grpc_router_service_pb2 import (
    HEALTH_CHECK_ACTIVE_CLIENT,
    HEALTH_CHECK_PASSIVE_CLIENT,
    HEALTH_STATUS_GOOD,
    HealthInfoRequest,
    HealthStatus,
    GetRegisteredServiceRequest,
    ServiceDeregistrationRequest,
    ServiceRegistrationRequest,
    DESCRIPTOR,
)


logger = logging.getLogger(__name__)


class GRPCRouterClient:

    DEFAULT_GRPC_SERVICE_CONFIG = {
        "methodConfig": [{
            "name": [{"service": DESCRIPTOR.services_by_name["GRPCRouterService"].full_name,}],
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

    HEALTh_PUSh_FREQUENCY_SECONDS = 60 * 3

    def __init__(self, host: str, port: int, grpc_service_config: Optional[dict[str, Any]]=None):
        self.host = host
        self.port = port
        self._channel = None
        self._grpc_service_config = grpc_service_config if grpc_service_config is not None else self.DEFAULT_GRPC_SERVICE_CONFIG

        self._service_register = {}

        self._health_event = Event()
        self._health_push_thread: Optional[Thread] = None

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

    def _health_push_thread_entrypoint(self):
        while self._health_event.wait(self.HEALTh_PUSh_FREQUENCY_SECONDS):
            self._health_event.clear()
            for service_id, svc in self._service_register.items():
                if svc["health_check_type"] == HEALTH_CHECK_ACTIVE_CLIENT:
                    try:
                        self.stub.PushHealthStatus(
                            HealthInfoRequest(
                                service_id=service_id,
                                service_token=svc["token"],
                                status=svc["health_status"],
                                description=svc["description"]
                            )
                        )
                    except Exception as exc:
                        logger.error(f"Failed for publish health status for {service_id} due to {exc}")

    def _start_health_push_thread(self):
        if self._health_push_thread is None:
            self._health_event.clear()
            self._health_push_thread = Thread(target=self._health_push_thread_entrypoint)
            self._health_push_thread.daemon = True
            self._health_push_thread.start()

    def register_service(self, service_id: str, host: str, port: int, region: str='', slots: int=10, health_check_type: int=0) -> str:
        svc = self._service_register.get(service_id)
        if svc is not None:
            return svc['token']
        request = ServiceRegistrationRequest()
        request.service_id = service_id
        request.endpoint.host = host
        request.endpoint.port = port
        request.metadata.region = region
        request.metadata.slots = slots
        request.metadata.health_check_type = health_check_type
        if health_check_type == HEALTH_CHECK_ACTIVE_CLIENT:
            self._start_health_push_thread()
        res = self.stub.RegisterService(request)
        token = res.service_token
        self._service_register[service_id] = {
            "token": token,
            "health_check_type": health_check_type,
            "health_status": HEALTH_STATUS_GOOD,
            "description": "",
        }
        return token

    def deregister_service(self, service_id: str) -> None:
        svc = self._service_register.pop(service_id, None)
        if svc is None:
            return
        request = ServiceDeregistrationRequest()
        request.service_id = service_id
        request.service_token = svc["token"]
        self.stub.DeregisterService(request)

    def get_service(self, service_id: str, region: str='') -> tuple[str, int]:
        request = GetRegisteredServiceRequest(
            service_id=service_id
        )
        request.hints.region = region
        res = self.stub.GetRegisteredService(
            request
        )
        return res.endpoint.host, res.endpoint.port

    def set_health_status(self, service_id: str, status: HealthStatus, description: str):
        svc = self._service_register.get(service_id)
        if svc is None:
            return
        svc.update({
            "health_status": status,
            "description": description,
        })
        if svc["health_check_type"] == HEALTH_CHECK_ACTIVE_CLIENT:
            self._health_event.set()
