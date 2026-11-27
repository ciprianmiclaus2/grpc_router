#!/usr/bin/env bash
# Regenerate the gRPC/protobuf stubs in grpc_router/stubs from proto/*.proto.
#
# Note: the generated *_pb2.py / *_pb2_grpc.py files embed the protobuf and grpcio
# versions of the grpcio-tools used here, and refuse to load on older runtimes.
# After regenerating, bump the protobuf/grpcio lower bounds in pyproject.toml to
# match (see "Protobuf Python Version" in the _pb2.py header and
# GRPC_GENERATED_VERSION in the _pb2_grpc.py file).
set -euo pipefail
cd "$(dirname "$0")"
python -m grpc_tools.protoc -Igrpc_router/stubs=./proto/ \
    --python_out=. --pyi_out=. --grpc_python_out=. \
    ./proto/*.proto
