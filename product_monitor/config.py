"""Configuration management for product monitor."""

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


CONFIG_DIR = Path.home() / ".product-monitor"
CONFIG_FILE = CONFIG_DIR / "config.json"
WATCHES_FILE = CONFIG_DIR / "watches.json"


@dataclass
class NotificationConfig:
    desktop: bool = True
    sound: bool = True
    email: bool = False
    email_to: str = ""
    email_from: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""


@dataclass
class MonitorConfig:
    check_interval_seconds: int = 60
    request_timeout_seconds: int = 15
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    max_retries: int = 3
    notifications: NotificationConfig = field(default_factory=NotificationConfig)


@dataclass
class WatchEntry:
    """A product name to watch for availability."""
    query: str  # The product name / search term (partial or full)
    retailers: list[str] = field(default_factory=lambda: ["amazon", "bestbuy", "walmart", "target", "newegg"])
    max_price: Optional[float] = None  # Optional price cap
    auto_cart: str = "off"  # "off", "open", "prompt", or "auto"
    enabled: bool = True
    last_results: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "WatchEntry":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> MonitorConfig:
    ensure_config_dir()
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        notif_data = data.pop("notifications", {})
        return MonitorConfig(
            notifications=NotificationConfig(**notif_data),
            **data,
        )
    config = MonitorConfig()
    save_config(config)
    return config


def save_config(config: MonitorConfig):
    ensure_config_dir()
    with open(CONFIG_FILE, "w") as f:
        json.dump(asdict(config), f, indent=2)


def load_watches() -> list[WatchEntry]:
    ensure_config_dir()
    if WATCHES_FILE.exists():
        with open(WATCHES_FILE) as f:
            data = json.load(f)
        return [WatchEntry.from_dict(w) for w in data]
    return []


def save_watches(watches: list[WatchEntry]):
    ensure_config_dir()
    with open(WATCHES_FILE, "w") as f:
        json.dump([w.to_dict() for w in watches], f, indent=2)
