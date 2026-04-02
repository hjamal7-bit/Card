"""Tests for the scraper and filtering logic."""

import pytest

from product_monitor.scrapers import (
    ProductResult,
    _guess_availability,
    _parse_price,
    filter_results,
)


class TestParsePrice:
    def test_standard_price(self):
        assert _parse_price("$29.99") == 29.99

    def test_price_with_commas(self):
        assert _parse_price("$1,299.99") == 1299.99

    def test_price_no_dollar_sign(self):
        assert _parse_price("499.99") == 499.99

    def test_price_whole_number(self):
        assert _parse_price("$50") == 50.0

    def test_empty_string(self):
        assert _parse_price("") is None

    def test_no_price(self):
        assert _parse_price("free shipping") is None

    def test_none(self):
        assert _parse_price(None) is None


class TestGuessAvailability:
    def test_out_of_stock(self):
        available, text = _guess_availability("This item is Out of Stock")
        assert not available
        assert "out of stock" in text

    def test_sold_out(self):
        available, _ = _guess_availability("Sorry, Sold Out")
        assert not available

    def test_add_to_cart(self):
        available, text = _guess_availability("Add to Cart - Ships in 2 days")
        assert available
        assert "add to cart" in text

    def test_buy_now(self):
        available, _ = _guess_availability("Buy Now for $29.99")
        assert available

    def test_unknown(self):
        available, text = _guess_availability("Some random text about a product")
        assert not available
        assert text == "unknown"


class TestFilterResults:
    def _make_result(self, name, price=None, available=True):
        return ProductResult(
            name=name,
            retailer="TestStore",
            price=price,
            url="https://example.com",
            available=available,
            availability_text="in stock" if available else "out of stock",
        )

    def test_filters_by_query_word(self):
        results = [
            self._make_result("PlayStation 5 Console"),
            self._make_result("Xbox Series X"),
            self._make_result("HDMI Cable 6ft"),
        ]
        filtered = filter_results(results, "PlayStation 5")
        assert len(filtered) == 1
        assert filtered[0].name == "PlayStation 5 Console"

    def test_partial_name_match(self):
        results = [
            self._make_result("NVIDIA GeForce RTX 4090"),
            self._make_result("AMD Radeon RX 7900"),
        ]
        filtered = filter_results(results, "RTX 4090")
        assert len(filtered) == 1

    def test_max_price_filter(self):
        results = [
            self._make_result("Widget A", price=50.0),
            self._make_result("Widget B", price=150.0),
            self._make_result("Widget C", price=75.0),
        ]
        filtered = filter_results(results, "Widget", max_price=100.0)
        assert len(filtered) == 2
        assert all(r.price <= 100.0 for r in filtered)

    def test_no_price_passes_max_price_filter(self):
        results = [self._make_result("Widget X", price=None)]
        filtered = filter_results(results, "Widget", max_price=100.0)
        assert len(filtered) == 1

    def test_empty_results(self):
        assert filter_results([], "anything") == []


class TestProductResultDict:
    def test_to_dict(self):
        r = ProductResult(
            name="Test", retailer="Store", price=9.99,
            url="https://example.com", available=True, availability_text="in stock",
        )
        d = r.to_dict()
        assert d["name"] == "Test"
        assert d["price"] == 9.99
        assert d["available"] is True
