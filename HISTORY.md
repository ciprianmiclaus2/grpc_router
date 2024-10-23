# History

## 0.2.0 (2024-10-23)

* Enable health checking service on the grpc router
* Enable reflection in the server
* Fix the server cli -h conflicting with --help and the port not being parsed as an int

## 0.1.0 (2024-10-13)

Initial release of the grpc_router, a service discovery tool for grpc services.
Allows grpc services to register/deregister and clients to lookup services based on a service_id which
should ideally consist of a dot separated namespace, e.g. domain.scope.service. In practice, the service_id
can be any string, there is no inherent limitation.
Services operate with a concept of region, which can allow clients to connect preferentially to the services
in their own region, with a fallback to another region if there's no services running in their own region.
