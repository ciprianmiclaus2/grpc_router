from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

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
    __slots__ = ("service_id", "endpoint")
    SERVICE_ID_FIELD_NUMBER: _ClassVar[int]
    ENDPOINT_FIELD_NUMBER: _ClassVar[int]
    service_id: str
    endpoint: ServiceEndpoint
    def __init__(self, service_id: _Optional[str] = ..., endpoint: _Optional[_Union[ServiceEndpoint, _Mapping]] = ...) -> None: ...

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
