"""Retailer search scrapers - search for products by name across shopping sites."""

import logging
import re
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from .config import MonitorConfig

logger = logging.getLogger(__name__)


@dataclass
class ProductResult:
    """A single product found on a retailer."""
    name: str
    retailer: str
    price: Optional[float]
    url: str
    available: bool
    availability_text: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "retailer": self.retailer,
            "price": self.price,
            "url": self.url,
            "available": self.available,
            "availability_text": self.availability_text,
        }


def _get_session(config: MonitorConfig) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": config.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    })
    return session


def _fetch(url: str, config: MonitorConfig) -> Optional[str]:
    """Fetch a URL with retries, return HTML or None on failure."""
    session = _get_session(config)
    for attempt in range(config.max_retries):
        try:
            resp = session.get(url, timeout=config.request_timeout_seconds, allow_redirects=True)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            logger.debug(f"Attempt {attempt + 1} failed for {url}: {e}")
            if attempt < config.max_retries - 1:
                time.sleep(2 ** (attempt + 1))
    return None


def _parse_price(text: str) -> Optional[float]:
    """Extract a price from text like '$1,299.99'."""
    if not text:
        return None
    match = re.search(r"\$?([\d,]+\.?\d*)", text.replace(",", ""))
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


UNAVAILABLE_SIGNALS = [
    "out of stock", "sold out", "currently unavailable", "unavailable",
    "not available", "notify me", "coming soon", "pre-order",
    "check back", "no longer available",
]

AVAILABLE_SIGNALS = [
    "add to cart", "buy now", "in stock", "add to bag",
    "available", "ship it", "pick up",
]


def _guess_availability(text: str) -> tuple[bool, str]:
    """Determine availability from surrounding text."""
    lower = text.lower()
    for signal in UNAVAILABLE_SIGNALS:
        if signal in lower:
            return False, signal
    for signal in AVAILABLE_SIGNALS:
        if signal in lower:
            return True, signal
    return False, "unknown"


# ---------------------------------------------------------------------------
# Retailer-specific scrapers
# ---------------------------------------------------------------------------

def search_amazon(query: str, config: MonitorConfig) -> list[ProductResult]:
    """Search Amazon for a product by name."""
    url = f"https://www.amazon.com/s?k={quote_plus(query)}"
    html = _fetch(url, config)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    results = []

    for item in soup.select("[data-component-type='s-search-result']")[:10]:
        # Product name
        title_el = item.select_one("h2 a span")
        if not title_el:
            continue
        name = title_el.get_text(strip=True)

        # URL
        link_el = item.select_one("h2 a")
        href = link_el.get("href", "") if link_el else ""
        product_url = f"https://www.amazon.com{href}" if href.startswith("/") else href

        # Price
        price_el = item.select_one(".a-price .a-offscreen")
        price = _parse_price(price_el.get_text(strip=True)) if price_el else None

        # Availability
        item_text = item.get_text(separator=" ", strip=True).lower()
        if price and "currently unavailable" not in item_text:
            available, avail_text = True, "has price listed"
        else:
            available, avail_text = _guess_availability(item_text)

        results.append(ProductResult(
            name=name, retailer="Amazon", price=price,
            url=product_url, available=available, availability_text=avail_text,
        ))

    return results


def search_bestbuy(query: str, config: MonitorConfig) -> list[ProductResult]:
    """Search Best Buy for a product by name."""
    url = f"https://www.bestbuy.com/site/searchpage.jsp?st={quote_plus(query)}"
    html = _fetch(url, config)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    results = []

    for item in soup.select(".sku-item")[:10]:
        title_el = item.select_one(".sku-title a")
        if not title_el:
            continue
        name = title_el.get_text(strip=True)
        product_url = title_el.get("href", "")
        if product_url.startswith("/"):
            product_url = f"https://www.bestbuy.com{product_url}"

        price_el = item.select_one(".priceView-customer-price span")
        price = _parse_price(price_el.get_text(strip=True)) if price_el else None

        # Check the add to cart button
        btn = item.select_one(".add-to-cart-button")
        btn_text = btn.get_text(strip=True).lower() if btn else ""
        if "add to cart" in btn_text:
            available, avail_text = True, "add to cart"
        elif "sold out" in btn_text:
            available, avail_text = False, "sold out"
        else:
            available, avail_text = _guess_availability(item.get_text(separator=" ", strip=True))

        results.append(ProductResult(
            name=name, retailer="Best Buy", price=price,
            url=product_url, available=available, availability_text=avail_text,
        ))

    return results


def search_walmart(query: str, config: MonitorConfig) -> list[ProductResult]:
    """Search Walmart for a product by name."""
    url = f"https://www.walmart.com/search?q={quote_plus(query)}"
    html = _fetch(url, config)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    results = []

    for item in soup.select("[data-item-id]")[:10]:
        title_el = item.select_one("[data-automation-id='product-title']")
        if not title_el:
            # Fallback selector
            title_el = item.select_one("span.lh-title")
        if not title_el:
            continue
        name = title_el.get_text(strip=True)

        link_el = item.select_one("a[href*='/ip/']")
        href = link_el.get("href", "") if link_el else ""
        product_url = f"https://www.walmart.com{href}" if href.startswith("/") else href

        price_el = item.select_one("[data-automation-id='product-price'] .f2")
        if not price_el:
            price_el = item.select_one("[itemprop='price']")
        price = _parse_price(price_el.get_text(strip=True)) if price_el else None

        item_text = item.get_text(separator=" ", strip=True)
        available, avail_text = _guess_availability(item_text)
        if price and not available and avail_text == "unknown":
            available, avail_text = True, "has price listed"

        results.append(ProductResult(
            name=name, retailer="Walmart", price=price,
            url=product_url, available=available, availability_text=avail_text,
        ))

    return results


def search_target(query: str, config: MonitorConfig) -> list[ProductResult]:
    """Search Target for a product by name."""
    url = f"https://www.target.com/s?searchTerm={quote_plus(query)}"
    html = _fetch(url, config)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    results = []

    for item in soup.select("[data-test='product-grid'] a, .ProductCardWrapper a")[:10]:
        name = item.get_text(strip=True)
        if not name or len(name) < 5:
            continue
        href = item.get("href", "")
        product_url = f"https://www.target.com{href}" if href.startswith("/") else href

        # Target's search page is heavily JS-rendered, so results may be limited
        results.append(ProductResult(
            name=name, retailer="Target", price=None,
            url=product_url, available=False, availability_text="check page directly",
        ))

    return results


def search_newegg(query: str, config: MonitorConfig) -> list[ProductResult]:
    """Search Newegg for a product by name."""
    url = f"https://www.newegg.com/p/pl?d={quote_plus(query)}"
    html = _fetch(url, config)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    results = []

    for item in soup.select(".item-cell")[:10]:
        title_el = item.select_one(".item-title")
        if not title_el:
            continue
        name = title_el.get_text(strip=True)
        product_url = title_el.get("href", "")

        price_el = item.select_one(".price-current")
        price = _parse_price(price_el.get_text(strip=True)) if price_el else None

        btn = item.select_one(".item-button-area .btn")
        btn_text = btn.get_text(strip=True).lower() if btn else ""
        if "add to cart" in btn_text:
            available, avail_text = True, "add to cart"
        else:
            available, avail_text = _guess_availability(item.get_text(separator=" ", strip=True))

        results.append(ProductResult(
            name=name, retailer="Newegg", price=price,
            url=product_url, available=available, availability_text=avail_text,
        ))

    return results


def search_custom_url(query: str, url: str, config: MonitorConfig) -> list[ProductResult]:
    """Search a custom URL (user-provided) and look for availability signals."""
    html = _fetch(url, config)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    page_text = soup.get_text(separator=" ", strip=True)
    available, avail_text = _guess_availability(page_text)

    # Check if the query terms appear on the page
    query_lower = query.lower()
    query_words = query_lower.split()
    if not any(w in page_text.lower() for w in query_words):
        return []

    return [ProductResult(
        name=query,
        retailer=url,
        price=None,
        url=url,
        available=available,
        availability_text=avail_text,
    )]


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

RETAILER_MAP = {
    "amazon": search_amazon,
    "bestbuy": search_bestbuy,
    "walmart": search_walmart,
    "target": search_target,
    "newegg": search_newegg,
}


def search_product(query: str, retailers: list[str], config: MonitorConfig) -> list[ProductResult]:
    """Search for a product across specified retailers."""
    all_results = []

    for retailer in retailers:
        retailer_key = retailer.lower().replace(" ", "")
        if retailer_key in RETAILER_MAP:
            logger.debug(f"Searching {retailer} for '{query}'...")
            try:
                results = RETAILER_MAP[retailer_key](query, config)
                all_results.extend(results)
            except Exception as e:
                logger.warning(f"Error searching {retailer}: {e}")
        elif retailer.startswith("http"):
            # Treat as custom URL
            try:
                results = search_custom_url(query, retailer, config)
                all_results.extend(results)
            except Exception as e:
                logger.warning(f"Error searching {retailer}: {e}")
        else:
            logger.warning(f"Unknown retailer: {retailer}")

    return all_results


def filter_results(results: list[ProductResult], query: str, max_price: Optional[float] = None) -> list[ProductResult]:
    """Filter results by name relevance and optional price cap."""
    query_words = query.lower().split()
    filtered = []

    for r in results:
        name_lower = r.name.lower()
        # Require at least one query word to appear in the product name
        if any(word in name_lower for word in query_words):
            if max_price is not None and r.price is not None:
                if r.price > max_price:
                    continue
            filtered.append(r)

    return filtered
