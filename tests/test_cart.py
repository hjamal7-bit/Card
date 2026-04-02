"""Tests for the cart module (browser automation)."""

from unittest.mock import patch, MagicMock

import pytest

from product_monitor.cart import (
    ADD_TO_CART_SELECTORS,
    ADD_TO_CART_XPATHS,
    open_product_page,
    add_to_cart,
)
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
