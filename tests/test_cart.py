"""Tests for the cart module (browser automation)."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from product_monitor.cart import (
    ADD_TO_CART_SELECTORS,
    ADD_TO_CART_XPATHS,
    _resolve_profile_for_result,
    login_to_retailer,
    open_product_page,
    add_to_cart,
)
from product_monitor.config import RETAILER_LOGIN_URLS, get_profile_dir, get_retailer_for_url
from product_monitor.scrapers import ProductResult


def _make_result(name="Test Product", url="https://example.com/product", retailer="Amazon"):
    return ProductResult(
        name=name, retailer=retailer, price=29.99,
        url=url, available=True, availability_text="in stock",
    )


class TestOpenProductPage:
    @patch("product_monitor.cart.webbrowser.open")
    def test_opens_url(self, mock_open):
        result = _make_result()
        assert open_product_page(result) is True
        mock_open.assert_called_once_with(result.url)

    @patch("product_monitor.cart.webbrowser.open", side_effect=Exception("no browser"))
    def test_handles_failure(self, mock_open):
        result = _make_result()
        assert open_product_page(result) is False


class TestAddToCartOpenMode:
    @patch("product_monitor.cart.webbrowser.open")
    def test_open_mode_uses_webbrowser(self, mock_open):
        result = _make_result()
        cart_result = add_to_cart(result, mode="open")
        assert cart_result["success"] is True
        assert cart_result["action"] == "opened_browser"
        mock_open.assert_called_once()


class TestAddToCartFallback:
    @patch("product_monitor.cart.webbrowser.open")
    def test_falls_back_when_selenium_missing(self, mock_open):
        """When selenium is not importable, should fall back to opening browser."""
        result = _make_result()
        # Simulate selenium not being installed by patching the import
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name.startswith("selenium"):
                raise ImportError("No module named 'selenium'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            cart_result = add_to_cart(result, mode="auto")
            assert cart_result["action"] == "opened_browser_fallback"
            assert "Selenium not installed" in cart_result["message"]


class TestLoginSession:
    def test_login_urls_defined_for_all_retailers(self):
        expected = {"amazon", "bestbuy", "walmart", "target", "newegg"}
        assert set(RETAILER_LOGIN_URLS.keys()) == expected

    def test_login_fails_without_selenium(self):
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name.startswith("selenium"):
                raise ImportError("No module named 'selenium'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = login_to_retailer("amazon", "https://amazon.com/login")
            assert result["success"] is False
            assert "Selenium not installed" in result["message"]

    def test_get_retailer_for_url(self):
        assert get_retailer_for_url("https://www.amazon.com/dp/B09V3KXJPB") == "amazon"
        assert get_retailer_for_url("https://www.bestbuy.com/site/product") == "bestbuy"
        assert get_retailer_for_url("https://www.walmart.com/ip/12345") == "walmart"
        assert get_retailer_for_url("https://www.target.com/p/thing") == "target"
        assert get_retailer_for_url("https://www.newegg.com/p/abc") == "newegg"
        assert get_retailer_for_url("https://www.random-shop.com") is None

    @patch("product_monitor.config.PROFILES_DIR")
    def test_get_profile_dir_creates_dir(self, mock_profiles_dir, tmp_path):
        mock_profiles_dir.__truediv__ = lambda self, key: tmp_path / key
        with patch("product_monitor.config.PROFILES_DIR", tmp_path):
            profile = get_profile_dir("amazon")
            assert profile.exists()
            assert "amazon" in str(profile)

    def test_resolve_profile_for_amazon(self, tmp_path):
        result = _make_result(retailer="Amazon", url="https://www.amazon.com/dp/B123")
        with patch("product_monitor.cart.get_profile_dir") as mock_gpd:
            mock_profile = tmp_path / "amazon"
            mock_profile.mkdir()
            mock_gpd.return_value = mock_profile
            profile = _resolve_profile_for_result(result)
            assert profile == mock_profile


class TestSelectors:
    def test_has_selectors_for_major_retailers(self):
        """Verify we have selectors that target major retailers."""
        all_selectors = " ".join(ADD_TO_CART_SELECTORS)
        # Amazon
        assert "add-to-cart-button" in all_selectors
        # Best Buy
        assert "add-to-cart-button" in all_selectors
        # Generic
        assert "addToCart" in all_selectors

    def test_has_xpath_fallbacks(self):
        assert len(ADD_TO_CART_XPATHS) > 0
        assert any("add to cart" in x.lower() for x in ADD_TO_CART_XPATHS)

    def test_selectors_are_strings(self):
        for s in ADD_TO_CART_SELECTORS:
            assert isinstance(s, str)
        for x in ADD_TO_CART_XPATHS:
            assert isinstance(x, str)
