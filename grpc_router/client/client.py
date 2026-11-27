import json
import logging
from threading import Event, Thread
from types import TracebackType
from typing import Any, Self

import grpc

from grpc_router.stubs.grpc_router_service_pb2 import (
    DESCRIPTOR,
    HEALTH_CHECK_ACTIVE_CLIENT,
    HEALTH_STATUS_GOOD,
    GetRegisteredServiceRequest,
    HealthInfoRequest,
    ServiceDeregistrationRequest,
    ServiceRegistrationRequest,
)
from grpc_router.stubs.grpc_router_service_pb2_grpc import GRPCRouterServiceStub

logger = logging.getLogger(__name__)


class GRPCRouterClient:

    DEFAULT_GRPC_SERVICE_CONFIG = {
        "methodConfig": [{
            "name": [{"service": DESCRIPTOR.services_by_name["GRPCRouterService"].full_name}],
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

    HEALTH_PUSH_FREQUENCY_SECONDS = 60 * 3
    # Deprecated misspelled alias, kept for backwards compatibility.
    HEALTh_PUSh_FREQUENCY_SECONDS = HEALTH_PUSH_FREQUENCY_SECONDS

    def __init__(self, host: str, port: int, grpc_service_config: dict[str, Any] | None = None) -> None:
        self.host = host
        self.port = port
        self._channel: grpc.Channel | None = None
        self._stub: GRPCRouterServiceStub | None = None
        self._grpc_service_config = (
            grpc_service_config if grpc_service_config is not None else self.DEFAULT_GRPC_SERVICE_CONFIG
        )

        self._service_register: dict[str, dict[str, Any]] = {}

        self._health_event = Event()
        self._health_push_stop = Event()
        self._health_push_thread: Thread | None = None

    @property
    def channel(self) -> grpc.Channel:
        if self._channel is None:
            options = None
            if self._grpc_service_config:
                options = [("grpc.service_config", json.dumps(self._grpc_service_config))]
            self._channel = grpc.insecure_channel(f"{self.host}:{self.port}", options=options)
        return self._channel

    @property
    def stub(self) -> GRPCRouterServiceStub:
        if self._stub is None:
            self._stub = GRPCRouterServiceStub(self.channel)
        return self._stub

    def close(self) -> None:
        """Stop pushing health statuses and close the channel. Services are not deregistered."""
        thread = self._health_push_thread
        if thread is not None:
            self._health_push_stop.set()
            self._health_event.set()
        if self._channel is not None:
            self._channel.close()  # also cancels a push in flight, so the join below is quick
        if thread is not None:
            thread.join()
            self._health_push_thread = None
        # reset only after the push thread is gone, so it cannot reopen the channel
        self._channel = None
        self._stub = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _health_push_thread_entrypoint(self) -> None:
        # Push every HEALTH_PUSH_FREQUENCY_SECONDS (the heartbeat), or straight away when
        # set_health_status() changes a status, until the client is closed.
        while True:
            self._health_event.wait(self.HEALTH_PUSH_FREQUENCY_SECONDS)
            if self._health_push_stop.is_set():
                return
            self._health_event.clear()
            for service_id, svc in list(self._service_register.items()):
                if self._health_push_stop.is_set():
                    return
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
                    except Exception:
                        logger.exception("Failed to publish health status for %s", service_id)

    def _start_health_push_thread(self) -> None:
        if self._health_push_thread is None:
            self._health_event.clear()
            self._health_push_stop.clear()
            self._health_push_thread = Thread(
                target=self._health_push_thread_entrypoint,
                name="grpc-router-health-push",
                daemon=True,
            )
            self._health_push_thread.start()

    def register_service(
        self, service_id: str, host: str, port: int, region: str = "", slots: int = 10, health_check_type: int = 0
    ) -> str:
        svc = self._service_register.get(service_id)
        if svc is not None:
            return svc["token"]
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

    def get_service(self, service_id: str, region: str = "") -> tuple[str, int]:
        request = GetRegisteredServiceRequest(service_id=service_id)
        request.hints.region = region
        res = self.stub.GetRegisteredService(request)
        return res.endpoint.host, res.endpoint.port

    def set_health_status(self, service_id: str, status: int, description: str) -> None:
        svc = self._service_register.get(service_id)
        if svc is None:
            return
        svc.update({
            "health_status": status,
            "description": description,
        })
        if svc["health_check_type"] == HEALTH_CHECK_ACTIVE_CLIENT:
            self._health_event.set()
