from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from ulanzi_tc002.server.apps.base import AppDisabled


def build_mcp(registry):
    mcp = MCPServer("tc002")

    @mcp.tool()
    def list_apps() -> list:
        """List clock apps and their enabled state."""
        return registry.list()

    @mcp.tool()
    def get_app(name: str) -> dict:
        """Get one app's status."""
        try:
            return registry.snapshot(name)
        except KeyError:
            raise ValueError(f"Unknown app: {name}") from None

    @mcp.tool()
    def enable_app(name: str) -> dict:
        """Enable a clock app."""
        try:
            return registry.enable(name)
        except KeyError:
            raise ValueError(f"Unknown app: {name}") from None

    @mcp.tool()
    def disable_app(name: str) -> dict:
        """Disable a clock app and clear its display."""
        try:
            return registry.disable(name)
        except KeyError:
            raise ValueError(f"Unknown app: {name}") from None

    @mcp.tool()
    def text_send(text: str, color: str = "white", ansi: bool = False) -> dict:
        """Send text to the clock. Empty text clears the screen."""
        try:
            return registry.get("text").update({"text": text, "color": color, "ansi": ansi})
        except KeyError:
            raise ValueError("Unknown app: text") from None
        except AppDisabled:
            raise ValueError("App is disabled") from None

    @mcp.tool()
    def text_get() -> dict:
        """Read the current text app message."""
        return registry.snapshot("text")

    return mcp


def mcp_asgi_app(registry):
    mcp = build_mcp(registry)
    asgi = mcp.streamable_http_app(
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return mcp, asgi
