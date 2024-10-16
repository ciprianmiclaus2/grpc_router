import sys
from unittest import mock

from grpc_router.server import main


@mock.patch('grpc_router.server.serve')
def test_server_entrypoint(serve_mock):
    args = ["server.py", "--hostname", "localhost", "--port", "9567", "--max-workers", "10"]
    with mock.patch.object(sys, 'argv', args):
        main()
    serve_mock.assert_called_once()
    config_options = serve_mock.call_args[0][0]
    assert config_options.hostname == "localhost"
    assert config_options.port == 9567
    assert config_options.max_workers == 10
    assert config_options.allow_global_region is True
    assert config_options.allow_cross_region_connectivity is True
