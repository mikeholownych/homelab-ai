from .server import GatewayServer, create_gateway


def __getattr__(name: str):
    if name in ("AsgiServerWrapper", "create_asgi_gateway"):
        from . import asgi
        return getattr(asgi, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["GatewayServer", "create_gateway", "create_asgi_gateway", "AsgiServerWrapper"]

