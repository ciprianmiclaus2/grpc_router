from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class HealthCheckType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    HEALTH_CHECK_NONE: _ClassVar[HealthCheckType]
    HEALTH_CHECK_ACTIVE_CLIENT: _ClassVar[HealthCheckType]
    HEALTH_CHECK_PASSIVE_CLIENT: _ClassVar[HealthCheckType]

class HealthStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    HEALTH_STATUS_UNKNOWN: _ClassVar[HealthStatus]
    HEALTH_STATUS_GOOD: _ClassVar[HealthStatus]
    HEALTH_STATUS_WARNING: _ClassVar[HealthStatus]
    HEALTH_STATUS_ERROR: _ClassVar[HealthStatus]
HEALTH_CHECK_NONE: HealthCheckType
HEALTH_CHECK_ACTIVE_CLIENT: HealthCheckType
HEALTH_CHECK_PASSIVE_CLIENT: HealthCheckType
HEALTH_STATUS_UNKNOWN: HealthStatus
HEALTH_STATUS_GOOD: HealthStatus
HEALTH_STATUS_WARNING: HealthStatus
HEALTH_STATUS_ERROR: HealthStatus

class ServiceEndpoint(_message.Message):
    __slots__ = ("host", "port")
    HOST_FIELD_NUMBER: _ClassVar[int]
    PORT_FIELD_NUMBER: _ClassVar[int]
    host: str
    port: int
    def __init__(self, host: _Optional[str] = ..., port: _Optional[int] = ...) -> None: ...

class ServiceMetadata(_message.Message):
    __slots__ = ("region", "slots", "health_check_type")
    REGION_FIELD_NUMBER: _ClassVar[int]
    SLOTS_FIELD_NUMBER: _ClassVar[int]
    HEALTH_CHECK_TYPE_FIELD_NUMBER: _ClassVar[int]
    region: str
    slots: int
    health_check_type: HealthCheckType
    def __init__(self, region: _Optional[str] = ..., slots: _Optional[int] = ..., health_check_type: _Optional[_Union[HealthCheckType, str]] = ...) -> None: ...

class ServiceRegistrationRequest(_message.Message):
    __slots__ = ("service_id", "endpoint", "metadata")
    SERVICE_ID_FIELD_NUMBER: _ClassVar[int]
    ENDPOINT_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    service_id: str
    endpoint: ServiceEndpoint
    metadata: ServiceMetadata
    def __init__(self, service_id: _Optional[str] = ..., endpoint: _Optional[_Union[ServiceEndpoint, _Mapping]] = ..., metadata: _Optional[_Union[ServiceMetadata, _Mapping]] = ...) -> None: ...

class ServiceRegistrationResponse(_message.Message):
    __slots__ = ("service_token",)
    SERVICE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    service_token: str
    def __init__(self, service_token: _Optional[str] = ...) -> None: ...

class ServiceDeregistrationRequest(_message.Message):
    __slots__ = ("service_id", "service_token")
    SERVICE_ID_FIELD_NUMBER: _ClassVar[int]
    SERVICE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    service_id: str
    service_token: str
    def __init__(self, service_id: _Optional[str] = ..., service_token: _Optional[str] = ...) -> None: ...

class ServiceDeregistrationResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ServiceHints(_message.Message):
    __slots__ = ("region",)
    REGION_FIELD_NUMBER: _ClassVar[int]
    region: str
    def __init__(self, region: _Optional[str] = ...) -> None: ...

class GetRegisteredServiceRequest(_message.Message):
    __slots__ = ("service_id", "hints")
    SERVICE_ID_FIELD_NUMBER: _ClassVar[int]
    HINTS_FIELD_NUMBER: _ClassVar[int]
    service_id: str
    hints: ServiceHints
    def __init__(self, service_id: _Optional[str] = ..., hints: _Optional[_Union[ServiceHints, _Mapping]] = ...) -> None: ...

class GetRegisteredServiceResponse(_message.Message):
    __slots__ = ("service_id", "endpoint", "instances")
    SERVICE_ID_FIELD_NUMBER: _ClassVar[int]
    ENDPOINT_FIELD_NUMBER: _ClassVar[int]
    INSTANCES_FIELD_NUMBER: _ClassVar[int]
    service_id: str
    endpoint: ServiceEndpoint
    instances: _containers.RepeatedCompositeFieldContainer[ServiceInstance]
    def __init__(self, service_id: _Optional[str] = ..., endpoint: _Optional[_Union[ServiceEndpoint, _Mapping]] = ..., instances: _Optional[_Iterable[_Union[ServiceInstance, _Mapping]]] = ...) -> None: ...

class HealthInfoRequest(_message.Message):
    __slots__ = ("service_id", "service_token", "status", "description")
    SERVICE_ID_FIELD_NUMBER: _ClassVar[int]
    SERVICE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    service_id: str
    service_token: str
    status: HealthStatus
    description: str
    def __init__(self, service_id: _Optional[str] = ..., service_token: _Optional[str] = ..., status: _Optional[_Union[HealthStatus, str]] = ..., description: _Optional[str] = ...) -> None: ...

class HealthInfoResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ServiceInstance(_message.Message):
    __slots__ = ("endpoint", "region")
    ENDPOINT_FIELD_NUMBER: _ClassVar[int]
    REGION_FIELD_NUMBER: _ClassVar[int]
    endpoint: ServiceEndpoint
    region: str
    def __init__(self, endpoint: _Optional[_Union[ServiceEndpoint, _Mapping]] = ..., region: _Optional[str] = ...) -> None: ...

class ListServiceInstancesRequest(_message.Message):
    __slots__ = ("service_id", "hints")
    SERVICE_ID_FIELD_NUMBER: _ClassVar[int]
    HINTS_FIELD_NUMBER: _ClassVar[int]
    service_id: str
    hints: ServiceHints
    def __init__(self, service_id: _Optional[str] = ..., hints: _Optional[_Union[ServiceHints, _Mapping]] = ...) -> None: ...

class ListServiceInstancesResponse(_message.Message):
    __slots__ = ("service_id", "instances")
    SERVICE_ID_FIELD_NUMBER: _ClassVar[int]
    INSTANCES_FIELD_NUMBER: _ClassVar[int]
    service_id: str
    instances: _containers.RepeatedCompositeFieldContainer[ServiceInstance]
    def __init__(self, service_id: _Optional[str] = ..., instances: _Optional[_Iterable[_Union[ServiceInstance, _Mapping]]] = ...) -> None: ...

class ServiceSubscription(_message.Message):
    __slots__ = ("service_id", "region")
    SERVICE_ID_FIELD_NUMBER: _ClassVar[int]
    REGION_FIELD_NUMBER: _ClassVar[int]
    service_id: str
    region: str
    def __init__(self, service_id: _Optional[str] = ..., region: _Optional[str] = ...) -> None: ...

class WatchServicesRequest(_message.Message):
    __slots__ = ("subscribe", "unsubscribe")
    SUBSCRIBE_FIELD_NUMBER: _ClassVar[int]
    UNSUBSCRIBE_FIELD_NUMBER: _ClassVar[int]
    subscribe: _containers.RepeatedCompositeFieldContainer[ServiceSubscription]
    unsubscribe: _containers.RepeatedCompositeFieldContainer[ServiceSubscription]
    def __init__(self, subscribe: _Optional[_Iterable[_Union[ServiceSubscription, _Mapping]]] = ..., unsubscribe: _Optional[_Iterable[_Union[ServiceSubscription, _Mapping]]] = ...) -> None: ...

class ServiceInstancesUpdate(_message.Message):
    __slots__ = ("subscription", "instances")
    SUBSCRIPTION_FIELD_NUMBER: _ClassVar[int]
    INSTANCES_FIELD_NUMBER: _ClassVar[int]
    subscription: ServiceSubscription
    instances: _containers.RepeatedCompositeFieldContainer[ServiceInstance]
    def __init__(self, subscription: _Optional[_Union[ServiceSubscription, _Mapping]] = ..., instances: _Optional[_Iterable[_Union[ServiceInstance, _Mapping]]] = ...) -> None: ...

class WatchServicesResponse(_message.Message):
    __slots__ = ("updates",)
    UPDATES_FIELD_NUMBER: _ClassVar[int]
    updates: _containers.RepeatedCompositeFieldContainer[ServiceInstancesUpdate]
    def __init__(self, updates: _Optional[_Iterable[_Union[ServiceInstancesUpdate, _Mapping]]] = ...) -> None: ...
