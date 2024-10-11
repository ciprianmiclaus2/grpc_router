# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# NO CHECKED-IN PROTOBUF GENCODE
# source: grpc_router/stubs/grpc_router_service.proto
# Protobuf Python Version: 5.27.2
"""Generated protocol buffer code."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import runtime_version as _runtime_version
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder
_runtime_version.ValidateProtobufRuntimeVersion(
    _runtime_version.Domain.PUBLIC,
    5,
    27,
    2,
    '',
    'grpc_router/stubs/grpc_router_service.proto'
)
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()




DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n+grpc_router/stubs/grpc_router_service.proto\x12\ngrpcrouter\"-\n\x0fServiceEndpoint\x12\x0c\n\x04host\x18\x01 \x01(\t\x12\x0c\n\x04port\x18\x02 \x01(\x05\"g\n\x1aServiceRegistrationRequest\x12\x12\n\nservice_id\x18\x01 \x01(\t\x12\x35\n\x10service_endpoint\x18\x02 \x01(\x0b\x32\x1b.grpcrouter.ServiceEndpoint\"C\n\x1bServiceRegistrationResponse\x12\x15\n\rservice_token\x18\x01 \x01(\t\x12\r\n\x05\x65rror\x18\x02 \x01(\t\"I\n\x1cServiceDeregistrationRequest\x12\x12\n\nservice_id\x18\x01 \x01(\t\x12\x15\n\rservice_token\x18\x02 \x01(\t\".\n\x1dServiceDeregistrationResponse\x12\r\n\x05\x65rror\x18\x01 \x01(\t\"1\n\x1bGetRegisteredServiceRequest\x12\x12\n\nservice_id\x18\x01 \x01(\t\"x\n\x1cGetRegisteredServiceResponse\x12\x12\n\nservice_id\x18\x01 \x01(\t\x12\x35\n\x10service_endpoint\x18\x02 \x01(\x0b\x32\x1b.grpcrouter.ServiceEndpoint\x12\r\n\x05\x65rror\x18\x03 \x01(\t2\xd2\x02\n\x11GRPCRouterService\x12\x64\n\x0fRegisterService\x12&.grpcrouter.ServiceRegistrationRequest\x1a\'.grpcrouter.ServiceRegistrationResponse\"\x00\x12j\n\x11\x44\x65registerService\x12(.grpcrouter.ServiceDeregistrationRequest\x1a).grpcrouter.ServiceDeregistrationResponse\"\x00\x12k\n\x14GetRegisteredService\x12\'.grpcrouter.GetRegisteredServiceRequest\x1a(.grpcrouter.GetRegisteredServiceResponse\"\x00\x42\x1a\n\x16\x63om.grpcrouter.serviceP\x01\x62\x06proto3')

_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'grpc_router.stubs.grpc_router_service_pb2', _globals)
if not _descriptor._USE_C_DESCRIPTORS:
  _globals['DESCRIPTOR']._loaded_options = None
  _globals['DESCRIPTOR']._serialized_options = b'\n\026com.grpcrouter.serviceP\001'
  _globals['_SERVICEENDPOINT']._serialized_start=59
  _globals['_SERVICEENDPOINT']._serialized_end=104
  _globals['_SERVICEREGISTRATIONREQUEST']._serialized_start=106
  _globals['_SERVICEREGISTRATIONREQUEST']._serialized_end=209
  _globals['_SERVICEREGISTRATIONRESPONSE']._serialized_start=211
  _globals['_SERVICEREGISTRATIONRESPONSE']._serialized_end=278
  _globals['_SERVICEDEREGISTRATIONREQUEST']._serialized_start=280
  _globals['_SERVICEDEREGISTRATIONREQUEST']._serialized_end=353
  _globals['_SERVICEDEREGISTRATIONRESPONSE']._serialized_start=355
  _globals['_SERVICEDEREGISTRATIONRESPONSE']._serialized_end=401
  _globals['_GETREGISTEREDSERVICEREQUEST']._serialized_start=403
  _globals['_GETREGISTEREDSERVICEREQUEST']._serialized_end=452
  _globals['_GETREGISTEREDSERVICERESPONSE']._serialized_start=454
  _globals['_GETREGISTEREDSERVICERESPONSE']._serialized_end=574
  _globals['_GRPCROUTERSERVICE']._serialized_start=577
  _globals['_GRPCROUTERSERVICE']._serialized_end=915
# @@protoc_insertion_point(module_scope)
