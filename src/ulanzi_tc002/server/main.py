"""Shared TC002 widget server."""
import argparse
from contextlib import asynccontextmanager
from pathlib import Path

from ulanzi_tc002.colors import COLORS
from ulanzi_tc002.device import Device
from ulanzi_tc002.http import request
from ulanzi_tc002.server.config import Settings
from ulanzi_tc002.server.mcp import mcp_asgi_app
from ulanzi_tc002.server.registry import AppExists, Registry

UI = Path(__file__).parent / "ui"
PUBLIC_PREFIXES = ("/docs", "/redoc", "/openapi.json", "/app.js", "/style.css")
PUBLIC_PATHS = {"/", "/api/health"}


def create_app(settings=None, device=None):
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import FileResponse, JSONResponse

    settings = settings or Settings.from_env()
    if device is None:
        device = Device(
            address=settings.device_ip,
            cache=settings.data_dir / "device.json",
            mac=settings.device_mac,
            network=settings.device_network,
        )
    registry = Registry(settings, device)
    mcp, mcp_asgi = mcp_asgi_app(registry)

    @asynccontextmanager
    async def lifespan(app):
        registry.start()
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            registry.stop()

    app = FastAPI(title="tc002", lifespan=lifespan)
    app.state.settings = settings
    app.state.registry = registry
    app.state.mcp = mcp
    app.mount("/mcp", mcp_asgi)

    @app.middleware("http")
    async def bearer_auth(request: Request, call_next):
        token = request.app.state.settings.token
        path = request.url.path
        if not token or path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)
        header = request.headers.get("authorization", "")
        if header == f"Bearer {token}":
            return await call_next(request)
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    def require_app(name):
        try:
            return registry.get(name)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown app") from None

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/colors")
    def colors():
        return COLORS

    @app.get("/api/apps")
    def list_apps():
        return registry.list()

    @app.post("/api/apps")
    def add_app(payload: dict):
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Provide name and type")
        name, kind = payload.get("name"), payload.get("type")
        if not isinstance(name, str) or not isinstance(kind, str):
            raise HTTPException(status_code=400, detail="Provide name and type")
        try:
            return registry.create(name, kind)
        except AppExists:
            raise HTTPException(status_code=409, detail="App already exists") from None
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/apps/{name}")
    def show_app(name: str):
        return require_app(name).snapshot()

    @app.post("/api/apps/{name}")
    def update_app(name: str, payload: dict):
        require_app(name)
        try:
            return registry.update(name, payload)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except ConnectionError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.delete("/api/apps/{name}")
    def remove_app(name: str):
        require_app(name)
        return registry.delete(name)

    @app.get("/api/device")
    def device_status():
        try:
            device.ensure_address()
            return request(f"http://{device.address}/api/customList", timeout=5)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    def ui_file(name, media_type=None):
        return FileResponse(
            UI / name,
            media_type=media_type,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/")
    def index():
        return ui_file("index.html")

    @app.get("/app.js")
    def app_js():
        return ui_file("app.js", "text/javascript")

    @app.get("/style.css")
    def app_css():
        return ui_file("style.css", "text/css")

    return app


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", help="Bind host (default: TC002_HOST or 127.0.0.1)")
    parser.add_argument("--port", type=int, help="Bind port (default: 8008)")
    parser.add_argument("--device", help="Clock IP")
    parser.add_argument("--tick", type=float, help="Seconds between scrolling frames")
    args = parser.parse_args()
    try:
        import uvicorn
    except ImportError:
        raise SystemExit("Install server extras: pip install 'ulanzi-tc002[server]'")
    settings = Settings.from_env()
    if args.host is not None:
        settings.host = args.host
    if args.port is not None:
        settings.port = args.port
    if args.device is not None:
        settings.device_ip = args.device
    if args.tick is not None:
        settings.tick = args.tick
    if not 1 <= settings.port <= 65535:
        parser.error("--port must be 1..65535")
    if not 0 < settings.tick < float("inf"):
        parser.error("--tick must be positive and finite")
    print(f"TC002 server at http://{settings.host}:{settings.port}/ ; "
          f"MCP at /mcp. Ctrl+C stops.", flush=True)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, lifespan="on")
