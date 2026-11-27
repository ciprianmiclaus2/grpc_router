# Watches and channel pool

::: grpc_router.client.discovery.ServiceWatch
    options:
      members:
        - instances
        - wait_for_instances
        - cancel

::: grpc_router.client.discovery.ServiceChannelPool
    options:
      members:
        - next_channel
        - endpoints
        - close
