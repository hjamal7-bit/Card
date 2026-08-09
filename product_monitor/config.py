"""Configuration management for product monitor."""

import json
import warnings
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


CONFIG_DIR = Path.home() / ".product-monitor"
CONFIG_FILE = CONFIG_DIR / "config.json"
WATCHES_FILE = CONFIG_DIR / "watches.json"
PROFILES_DIR = CONFIG_DIR / "profiles"


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


RETAILER_LOGIN_URLS = {
    "amazon": "https://www.amazon.com/ap/signin?openid.pape.max_auth_age=0&openid.return_to=https%3A%2F%2Fwww.amazon.com%2F",
    "bestbuy": "https://www.bestbuy.com/identity/global/signin",
    "walmart": "https://www.walmart.com/account/login",
    "target": "https://www.target.com/login",
    "newegg": "https://secure.newegg.com/identity/signin",
}


def ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def get_profile_dir(retailer: str) -> Path:
    """Get the browser profile directory for a retailer."""
    profile_dir = PROFILES_DIR / retailer.lower().replace(" ", "_")
    profile_dir.mkdir(parents=True, exist_ok=True)
    return profile_dir


def get_retailer_for_url(url: str) -> Optional[str]:
    """Determine which retailer a URL belongs to, for profile matching."""
    url_lower = url.lower()
    for retailer in RETAILER_LOGIN_URLS:
        if retailer in url_lower:
            return retailer
    return None


def _drop_unknown(raw: dict, cls, label: str) -> dict:
    """Keep only keys ``cls`` declares, warning about each one dropped."""
    known = cls.__dataclass_fields__
    unknown = [k for k in raw if k not in known]
    for k in unknown:
        warnings.warn(
            f"{CONFIG_FILE}: ignoring unknown {label} key {k!r} "
            f"(not a field of {cls.__name__}); it will have no effect",
            stacklevel=3,
        )
    return {k: v for k, v in raw.items() if k in known}


def load_config() -> MonitorConfig:
    ensure_config_dir()
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        notif_data = data.pop("notifications", {})
        # Drop keys the dataclasses do not define, so one stale or misspelled
        # field in the config file cannot TypeError the whole monitor at start.
        # Every drop is WARNED, never silent: a typo'd key that vanished
        # quietly would run the monitor on defaults and look like a config
        # that simply had no effect.
        notif_data = _drop_unknown(notif_data, NotificationConfig, "notifications")
        data = _drop_unknown(data, MonitorConfig, "config")
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
