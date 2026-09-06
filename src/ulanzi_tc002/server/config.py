from dataclasses import dataclass, field
import os
from pathlib import Path

from ulanzi_tc002.device import CONFIG_DIR


def default_data_dir():
    return Path(os.environ["TC002_DATA_DIR"]) if os.environ.get("TC002_DATA_DIR") else CONFIG_DIR


@dataclass
class Settings:
    host: str = "127.0.0.1"
    port: int = 8008
    token: str | None = None
    http_proxy: str | None = None
    data_dir: Path = field(default_factory=default_data_dir)
    device_ip: str | None = None
    device_mac: str | None = None
    device_network: str | None = None
    tick: float = 0.4

    @classmethod
    def from_env(cls):
        def env(name, default=None):
            value = os.environ.get(name)
            return default if value is None or value == "" else value

        port = env("TC002_PORT", "8008")
        tick = env("TC002_TICK", "0.4")
        data_dir = env("TC002_DATA_DIR")
        return cls(
            host=env("TC002_HOST", "127.0.0.1"),
            port=int(port),
            token=env("TC002_TOKEN"),
            http_proxy=env("TC002_HTTP_PROXY"),
            data_dir=Path(data_dir) if data_dir else default_data_dir(),
            device_ip=env("TC002_DEVICE_IP"),
            device_mac=env("TC002_DEVICE_MAC"),
            device_network=env("TC002_DEVICE_NETWORK"),
            tick=float(tick),
        )
