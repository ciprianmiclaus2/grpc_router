import sys
from unittest import mock

import pytest

from grpc_router.core.models import ConfigOptions
from grpc_router.server import BackgroundRouter, main


@mock.patch('grpc_router.server.serve', new_callable=mock.AsyncMock)
def test_server_entrypoint(serve_mock):
    args = ["server.py", "--hostname", "localhost", "--port", "9567", "--shutdown-grace", "7.5"]
    with mock.patch.object(sys, 'argv', args):
        main()
    serve_mock.assert_called_once()
    config_options = serve_mock.call_args[0][0]
    assert config_options.hostname == "localhost"
    assert config_options.port == 9567
    assert config_options.shutdown_grace == 7.5
    assert config_options.allow_global_region is True
    assert config_options.allow_cross_region_connectivity is True


def test_server_refuses_shared_port(grpc_router_server):
    # a second router must not silently share the port (and split the register) with the first one
    config = ConfigOptions(hostname="localhost", port=7654)
    with pytest.raises(RuntimeError):
        BackgroundRouter(config).start()
