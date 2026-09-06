from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from ulanzi_tc002.server.registry import AppExists


def build_mcp(registry):
    mcp = MCPServer("tc002")

    @mcp.tool()
    def list_apps() -> list:
        """List clock apps."""
        return registry.list()

    @mcp.tool()
    def get_app(name: str) -> dict:
        """Get one app's status."""
        try:
            return registry.snapshot(name)
        except KeyError:
            raise ValueError(f"Unknown app: {name}") from None

    @mcp.tool()
    def create_app(name: str, type: str) -> dict:
        """Create a clock app. Type is text or image. The name is the DIY app on the clock."""
        try:
            return registry.create(name, type)
        except AppExists:
            raise ValueError(f"App already exists: {name}") from None
        except ValueError as error:
            raise ValueError(str(error)) from error

    @mcp.tool()
    def delete_app(name: str) -> dict:
        """Delete a clock app and remove it from the device."""
        try:
            return registry.delete(name)
        except ValueError as error:
            raise ValueError(str(error)) from error

    @mcp.tool()
    def text_send(name: str, text: str, color: str = "white", ansi: bool = False) -> dict:
        """Send text to a text app. Empty text clears the screen."""
        try:
            app = registry.get(name)
        except KeyError:
            raise ValueError(f"Unknown app: {name}") from None
        if app.type != "text":
            raise ValueError(f"App {name} is not a text app")
        return registry.update(name, {"text": text, "color": color, "ansi": ansi})

    @mcp.tool()
    def text_get(name: str) -> dict:
        """Read a text app's current message."""
        try:
            app = registry.get(name)
        except KeyError:
            raise ValueError(f"Unknown app: {name}") from None
        if app.type != "text":
            raise ValueError(f"App {name} is not a text app")
        return app.snapshot()

    @mcp.tool()
    def image_send(name: str, image: str, duration: float = 10) -> dict:
        """Send a GIF or PNG to an image app. Image is a data URI or base64 string. Empty image clears."""
        try:
            app = registry.get(name)
        except KeyError:
            raise ValueError(f"Unknown app: {name}") from None
        if app.type != "image":
            raise ValueError(f"App {name} is not an image app")
        return registry.update(name, {"image": image, "duration": duration})

    @mcp.tool()
    def image_get(name: str) -> dict:
        """Read an image app's current image."""
        try:
            app = registry.get(name)
        except KeyError:
            raise ValueError(f"Unknown app: {name}") from None
        if app.type != "image":
            raise ValueError(f"App {name} is not an image app")
        return app.snapshot()

    return mcp


def mcp_asgi_app(registry):
    mcp = build_mcp(registry)
    asgi = mcp.streamable_http_app(
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return mcp, asgi
