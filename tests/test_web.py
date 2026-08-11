"""Tests for the web dashboard routes."""

from unittest.mock import patch

import pytest

pytest.importorskip("flask", reason="web dashboard is an optional extra")

from product_monitor import web  # noqa: E402
from product_monitor.config import WatchEntry  # noqa: E402


@pytest.fixture
def client(tmp_path):
    with patch("product_monitor.config.CONFIG_DIR", tmp_path), \
         patch("product_monitor.config.CONFIG_FILE", tmp_path / "config.json"), \
         patch("product_monitor.config.WATCHES_FILE", tmp_path / "watches.json"):
        web.app.config["TESTING"] = True
        with web.app.test_client() as c:
            yield c


class TestAddWatch:
    def test_valid_price_is_stored(self, client):
        resp = client.post("/add", data={"query": "PS5", "max_price": "499.99"})
        assert resp.status_code == 302
        from product_monitor.config import load_watches
        watches = load_watches()
        assert len(watches) == 1
        assert watches[0].max_price == 499.99

    def test_blank_price_means_no_cap(self, client):
        client.post("/add", data={"query": "PS5", "max_price": "  "})
        from product_monitor.config import load_watches
        assert load_watches()[0].max_price is None

    def test_non_numeric_price_is_rejected_not_silently_dropped(self, client):
        resp = client.post("/add", data={"query": "PS5", "max_price": "1,200"})

        assert resp.status_code == 302
        assert "error=bad_price" in resp.headers["Location"]
        from product_monitor.config import load_watches
        assert load_watches() == []

    @pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
    def test_non_finite_price_is_rejected(self, client, value):
        resp = client.post("/add", data={"query": "PS5", "max_price": value})

        assert "error=bad_price" in resp.headers["Location"]
        from product_monitor.config import load_watches
        assert load_watches() == []

    def test_error_code_renders_a_message(self, client):
        body = client.get("/?error=bad_price").get_data(as_text=True)
        assert "Max price must be a number" in body

    def test_unknown_error_code_renders_nothing(self, client):
        body = client.get("/?error=<script>boom</script>").get_data(as_text=True)
        assert "<script>boom</script>" not in body
        assert "form-error" not in body.split("</style>")[1]


class TestBackgroundCheckerErrors:
    def test_error_list_is_capped(self):
        state = {"errors": []}
        for i in range(120):
            state["errors"].append(str(i))
            state["errors"] = state["errors"][-50:]
        assert len(state["errors"]) == 50
        assert state["errors"][-1] == "119"

    def test_checker_caps_errors_from_failing_searches(self, tmp_path):
        with patch("product_monitor.config.CONFIG_DIR", tmp_path), \
             patch("product_monitor.config.CONFIG_FILE", tmp_path / "config.json"), \
             patch("product_monitor.config.WATCHES_FILE", tmp_path / "watches.json"), \
             patch("product_monitor.web.search_product", side_effect=RuntimeError("network down")), \
             patch("product_monitor.web.load_watches",
                   return_value=[WatchEntry(query=f"q{i}") for i in range(80)]):
            web.monitor_state["errors"] = []
            web.monitor_state["running"] = True
            web.monitor_state["results"] = {}

            def stop_after_one_pass(*_a, **_k):
                web.monitor_state["running"] = False

            with patch("product_monitor.web.time.sleep", side_effect=stop_after_one_pass):
                web._run_background_checker()

        assert len(web.monitor_state["errors"]) == 50
        web.monitor_state["errors"] = []
        web.monitor_state["results"] = {}
