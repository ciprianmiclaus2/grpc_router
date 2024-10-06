python -m grpc_tools.protoc -Igrpc_router/stubs=./proto/ --python_out=. --grpc_python_out=. ./proto/*.proto
