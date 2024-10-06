# GRPC Router

<p align="center">
<a href="https://pypi.python.org/pypi/grpc_router">
    <img src="https://img.shields.io/pypi/v/grpc_router.svg"
        alt = "Release Status">
</a>

<a href="http://github.com/ciprianmiclaus2/grpc_router/">

<img src="https://img.shields.io/pypi/pyversions/grpc_router.svg" alt="Python versions">
</a>

<a href="https://github.com/ciprianmiclaus2/grpc_router/actions">
    <img src="https://github.com/ciprianmiclaus2/grpc_router/actions/workflows/python-package.yml/badge.svg?branch=main" alt="CI Status">
</a>

<a href="https://codecov.io/gh/ciprianmiclaus2/grpc_router" > 
 <img src="https://codecov.io/gh/ciprianmiclaus2/grpc_router/graph/badge.svg?token=4N0N8XSVZY"/> 
 </a>

<a href="https://ciprianmiclaus2.github.io/grpc_router/">
    <img src="https://img.shields.io/website/https/ciprianmiclaus2.github.io/grpc_router/index.html.svg?label=docs&down_message=unavailable&up_message=available" alt="Documentation Status">
</a>

</p>

GRPC Router is a small components that implements a simple service register to be used for client side service discovery.
Services register with the GRPC router, clients requests the details of such services in order to discover them and connect directly.
