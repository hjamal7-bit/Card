"""Tests for configuration management."""

import json
import tempfile
import warnings
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


class TestCorruptFiles:
    """A half-written JSON file must not take the whole tool down."""

    def test_truncated_config_falls_back_to_defaults(self, tmp_config_dir):
        config_file = tmp_config_dir / "config.json"
        save_config(MonitorConfig(check_interval_seconds=30))
        # Simulate an interrupted write: valid prefix, no closing brace.
        config_file.write_text(config_file.read_text()[:40])

        with pytest.warns(UserWarning) as caught:
            config = load_config()

        assert config.check_interval_seconds == 60
        assert config.notifications.desktop is True
        assert any("invalid JSON" in str(w.message) for w in caught)
        assert any("config.json" in str(w.message) for w in caught)

    def test_corrupt_config_is_not_overwritten(self, tmp_config_dir):
        config_file = tmp_config_dir / "config.json"
        config_file.write_text("{not json at all")

        with pytest.warns(UserWarning):
            load_config()

        assert config_file.read_text() == "{not json at all"

    def test_truncated_watches_falls_back_to_empty(self, tmp_config_dir):
        watches_file = tmp_config_dir / "watches.json"
        save_watches([WatchEntry(query="PS5"), WatchEntry(query="RTX 4090")])
        watches_file.write_text(watches_file.read_text()[:30])

        with pytest.warns(UserWarning) as caught:
            watches = load_watches()

        assert watches == []
        assert any("invalid JSON" in str(w.message) for w in caught)
        assert any("watches.json" in str(w.message) for w in caught)

    def test_empty_watches_file_falls_back_to_empty(self, tmp_config_dir):
        (tmp_config_dir / "watches.json").write_text("")

        with pytest.warns(UserWarning):
            assert load_watches() == []


class TestUnknownKeys:
    """Unknown keys are tolerated, but never silently."""

    def test_unknown_config_key_is_named_in_the_warning(self, tmp_config_dir):
        (tmp_config_dir / "config.json").write_text(
            json.dumps({"check_interval_seconds": 45, "chek_intervl": 999})
        )

        with pytest.warns(UserWarning) as caught:
            config = load_config()

        messages = [str(w.message) for w in caught]
        assert config.check_interval_seconds == 45
        assert any("chek_intervl" in m for m in messages), messages
        assert not any("check_interval_seconds'" in m for m in messages), messages

    def test_unknown_notification_key_is_named_in_the_warning(self, tmp_config_dir):
        (tmp_config_dir / "config.json").write_text(
            json.dumps({"notifications": {"desktop": False, "emial": "typo@example.com"}})
        )

        with pytest.warns(UserWarning) as caught:
            config = load_config()

        assert config.notifications.desktop is False
        assert any("emial" in str(w.message) for w in caught)

    def test_known_keys_only_warns_about_nothing(self, tmp_config_dir):
        save_config(MonitorConfig(check_interval_seconds=15))

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert load_config().check_interval_seconds == 15


class TestAtomicWrites:
    """Saves swap the file in one step, so a failed save cannot truncate it."""

    def test_failed_save_leaves_previous_watches_intact(self, tmp_config_dir):
        watches_file = tmp_config_dir / "watches.json"
        save_watches([WatchEntry(query="PS5")])
        before = watches_file.read_text()

        # object() is not JSON serializable, so the write dies partway through.
        with pytest.raises(TypeError):
            save_watches([WatchEntry(query="PS5", last_results=[{"bad": object()}])])

        assert watches_file.read_text() == before
        assert load_watches()[0].query == "PS5"

    def test_failed_save_leaves_previous_config_intact(self, tmp_config_dir):
        config_file = tmp_config_dir / "config.json"
        save_config(MonitorConfig(check_interval_seconds=30))
        before = config_file.read_text()

        broken = MonitorConfig()
        broken.max_retries = object()
        with pytest.raises(TypeError):
            save_config(broken)

        assert config_file.read_text() == before

    def test_no_temp_files_are_left_behind(self, tmp_config_dir):
        save_config(MonitorConfig())
        save_watches([WatchEntry(query="PS5")])
        with pytest.raises(TypeError):
            save_watches([WatchEntry(query="PS5", last_results=[{"bad": object()}])])

        assert list(tmp_config_dir.glob("*.tmp")) == []
