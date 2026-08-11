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

    def test_corrupt_config_is_moved_aside_not_overwritten(self, tmp_config_dir):
        config_file = tmp_config_dir / "config.json"
        config_file.write_text("{not json at all")

        with pytest.warns(UserWarning):
            load_config()

        kept = list(tmp_config_dir.glob("config.json.corrupt-*"))
        assert len(kept) == 1, kept
        assert kept[0].read_text() == "{not json at all"

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


class TestCorruptFilesArePreserved:
    """The fallback must not become the thing that destroys the data.

    Both loaders return defaults so a bad file cannot take the tool down, and
    the very next command saves those defaults back over the file. Renaming
    the bad copy aside first is what keeps that fallback non fatal.
    """

    CORRUPT_WATCHES = (
        '[{"query": "PS5", "retailers": ["amazon"], "enabled": true},\n'
        ' {"query": "RTX 4090", "retailers": ["neweg'
    )

    def _corrupt_copies(self, tmp_config_dir, name):
        return sorted(tmp_config_dir.glob(f"{name}.corrupt-*"))

    def test_corrupt_watches_are_preserved_and_load_returns_empty(self, tmp_config_dir):
        watches_file = tmp_config_dir / "watches.json"
        watches_file.write_text(self.CORRUPT_WATCHES)

        with pytest.warns(UserWarning):
            assert load_watches() == []

        kept = self._corrupt_copies(tmp_config_dir, "watches.json")
        assert len(kept) == 1, kept
        assert kept[0].read_text() == self.CORRUPT_WATCHES
        assert not watches_file.exists()

    def test_warning_names_the_path_the_copy_was_kept_at(self, tmp_config_dir):
        (tmp_config_dir / "watches.json").write_text(self.CORRUPT_WATCHES)

        with pytest.warns(UserWarning) as caught:
            load_watches()

        kept = self._corrupt_copies(tmp_config_dir, "watches.json")[0]
        messages = [str(w.message) for w in caught]
        assert any(str(kept) in m for m in messages), messages
        assert any("preserved at" in m for m in messages), messages

    def test_later_save_does_not_destroy_the_preserved_watches(self, tmp_config_dir):
        """The exact sequence `product-monitor list` then `add` used to run."""
        watches_file = tmp_config_dir / "watches.json"
        watches_file.write_text(self.CORRUPT_WATCHES)

        with pytest.warns(UserWarning):
            watches = load_watches()
        watches.append(WatchEntry(query="Nintendo Switch 2"))
        save_watches(watches)

        kept = self._corrupt_copies(tmp_config_dir, "watches.json")
        assert len(kept) == 1, kept
        assert kept[0].read_text() == self.CORRUPT_WATCHES
        assert [w.query for w in load_watches()] == ["Nintendo Switch 2"]

    def test_later_save_does_not_destroy_the_preserved_config(self, tmp_config_dir):
        """`product-monitor config` loads then unconditionally saves."""
        config_file = tmp_config_dir / "config.json"
        original = '{"check_interval_seconds": 300, "notifications": {"smtp_user": "me@exa'
        config_file.write_text(original)

        with pytest.warns(UserWarning):
            config = load_config()
        save_config(config)

        kept = self._corrupt_copies(tmp_config_dir, "config.json")
        assert len(kept) == 1, kept
        assert kept[0].read_text() == original
        assert load_config().check_interval_seconds == 60

    def test_repeated_reads_of_one_corruption_keep_one_copy(self, tmp_config_dir):
        """Reading twice must not spew a copy per read: the file is gone now."""
        (tmp_config_dir / "watches.json").write_text(self.CORRUPT_WATCHES)

        with pytest.warns(UserWarning):
            load_watches()
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            # Nothing left to warn about: an absent file is a clean empty state.
            assert load_watches() == []

        assert len(self._corrupt_copies(tmp_config_dir, "watches.json")) == 1

    def test_a_second_corruption_gets_its_own_copy(self, tmp_config_dir):
        watches_file = tmp_config_dir / "watches.json"
        watches_file.write_text(self.CORRUPT_WATCHES)
        with pytest.warns(UserWarning):
            load_watches()

        save_watches([WatchEntry(query="Steam Deck")])
        watches_file.write_text('[{"query": "Steam D')
        with pytest.warns(UserWarning):
            load_watches()

        kept = self._corrupt_copies(tmp_config_dir, "watches.json")
        assert len(kept) == 2, kept
        assert {p.read_text() for p in kept} == {
            self.CORRUPT_WATCHES,
            '[{"query": "Steam D',
        }

    def test_two_corruptions_in_one_second_do_not_clobber_each_other(self, tmp_config_dir):
        watches_file = tmp_config_dir / "watches.json"
        with patch("product_monitor.config.time.time", return_value=1_700_000_000):
            watches_file.write_text("first")
            with pytest.warns(UserWarning):
                load_watches()
            watches_file.write_text("second")
            with pytest.warns(UserWarning):
                load_watches()

        kept = self._corrupt_copies(tmp_config_dir, "watches.json")
        assert len(kept) == 2, kept
        assert {p.read_text() for p in kept} == {"first", "second"}

    def test_unmovable_file_still_loads_and_says_the_data_is_at_risk(self, tmp_config_dir):
        (tmp_config_dir / "watches.json").write_text(self.CORRUPT_WATCHES)

        with patch("product_monitor.config.Path.rename", side_effect=OSError("read-only")):
            with pytest.warns(UserWarning) as caught:
                assert load_watches() == []

        messages = [str(w.message) for w in caught]
        assert any("could NOT be moved aside" in m for m in messages), messages
        assert self._corrupt_copies(tmp_config_dir, "watches.json") == []


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
