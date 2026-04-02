"""Tests for configuration management."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from product_monitor.config import (
    MonitorConfig,
    NotificationConfig,
    WatchEntry,
    load_config,
    load_watches,
    save_config,
    save_watches,
)


@pytest.fixture
def tmp_config_dir(tmp_path):
    """Use a temporary directory for config files."""
    with patch("product_monitor.config.CONFIG_DIR", tmp_path), \
         patch("product_monitor.config.CONFIG_FILE", tmp_path / "config.json"), \
         patch("product_monitor.config.WATCHES_FILE", tmp_path / "watches.json"):
        yield tmp_path


class TestMonitorConfig:
    def test_defaults(self):
        config = MonitorConfig()
        assert config.check_interval_seconds == 60
        assert config.notifications.desktop is True
        assert config.notifications.email is False

    def test_save_and_load(self, tmp_config_dir):
        config = MonitorConfig(check_interval_seconds=30)
        config.notifications.email = True
        config.notifications.email_to = "test@example.com"
        save_config(config)

        loaded = load_config()
        assert loaded.check_interval_seconds == 30
        assert loaded.notifications.email is True
        assert loaded.notifications.email_to == "test@example.com"

    def test_load_creates_default(self, tmp_config_dir):
        config = load_config()
        assert config.check_interval_seconds == 60
        assert (tmp_config_dir / "config.json").exists()


class TestWatchEntry:
    def test_to_dict_and_back(self):
        watch = WatchEntry(query="PS5", retailers=["amazon", "bestbuy"], max_price=500.0)
        d = watch.to_dict()
        restored = WatchEntry.from_dict(d)
        assert restored.query == "PS5"
        assert restored.retailers == ["amazon", "bestbuy"]
        assert restored.max_price == 500.0

    def test_default_retailers(self):
        watch = WatchEntry(query="test")
        assert "amazon" in watch.retailers
        assert len(watch.retailers) == 5

    def test_save_and_load_watches(self, tmp_config_dir):
        watches = [
            WatchEntry(query="RTX 4090", max_price=1800.0),
            WatchEntry(query="PS5", retailers=["amazon"]),
        ]
        save_watches(watches)

        loaded = load_watches()
        assert len(loaded) == 2
        assert loaded[0].query == "RTX 4090"
        assert loaded[1].retailers == ["amazon"]

    def test_load_empty(self, tmp_config_dir):
        assert load_watches() == []
