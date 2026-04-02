"""Browser automation for add-to-cart functionality.

Uses Selenium to open product pages in a real browser and attempt to click
"Add to Cart" buttons automatically. Falls back to just opening the page
if auto-click fails.

Supports persistent browser profiles so you can log in once and stay logged in
across all future monitoring sessions.

Three cart modes:
  - "open"    : Just open the product URL in a browser (safest)
  - "prompt"  : Open the page and highlight the button, wait for user
  - "auto"    : Attempt to click "Add to Cart" automatically
"""

import logging
import time
import webbrowser
from pathlib import Path
from typing import Optional

from .config import PROFILES_DIR, get_profile_dir, get_retailer_for_url
from .scrapers import ProductResult

logger = logging.getLogger(__name__)

# CSS selectors commonly used for add-to-cart buttons, ordered by specificity
ADD_TO_CART_SELECTORS = [
    # Amazon
    "#add-to-cart-button",
    'input[name="submit.add-to-cart"]',
    "#buy-now-button",
    # Best Buy
    ".add-to-cart-button:not([disabled])",
    'button[data-button-state="ADD_TO_CART"]',
    # Walmart
    'button[data-tl-id="ProductPrimaryCTA-normal"]',
    '[data-automation-id="atc-button"]',
    # Target
    'button[data-test="shippingButton"]',
    'button[data-test="shipItButton"]',
    # Newegg
    ".btn-primary.btn-wide",
    "#ProductBuy .btn",
    # Generic patterns (broad fallbacks)
    'button[id*="add-to-cart" i]',
    'button[id*="addtocart" i]',
    'button[class*="add-to-cart" i]',
    'button[class*="addToCart" i]',
    'input[value*="Add to Cart" i]',
    'button[aria-label*="Add to Cart" i]',
    'button[data-testid*="add-to-cart" i]',
]

# XPath fallback: find buttons by visible text
ADD_TO_CART_XPATHS = [
    '//button[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "add to cart")]',
    '//input[contains(translate(@value, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "add to cart")]',
    '//button[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "buy now")]',
    '//a[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "add to cart")]',
]


def _get_driver(headless: bool = False, profile_dir: Optional[Path] = None):
    """Create a Selenium WebDriver instance, optionally with a persistent profile.

    Args:
        headless: Run browser without a visible window.
        profile_dir: Path to a Chrome user data directory for session persistence.
                     When set, cookies/logins/local storage survive between runs.
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    options = Options()
    if headless:
        options.add_argument("--headless=new")

    # Persistent profile — this is what keeps you logged in
    if profile_dir:
        profile_dir.mkdir(parents=True, exist_ok=True)
        options.add_argument(f"--user-data-dir={profile_dir}")

    # Common anti-detection flags
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    # Avoid "Chrome is being controlled by automated test software" infobar
    options.add_argument("--disable-infobars")

    try:
        driver = webdriver.Chrome(options=options)
    except Exception:
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
        except ImportError:
            raise RuntimeError(
                "Chrome/ChromeDriver not found. Install with:\n"
                "  pip install webdriver-manager\n"
                "Or install ChromeDriver manually and ensure it's on your PATH."
            )

    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


def _resolve_profile_for_result(result: ProductResult) -> Optional[Path]:
    """Find the right browser profile for a product result based on its retailer/URL."""
    # Try matching by retailer name
    retailer_key = result.retailer.lower().replace(" ", "")
    profile = get_profile_dir(retailer_key)
    if profile.exists() and any(profile.iterdir()):
        return profile

    # Try matching by URL
    matched = get_retailer_for_url(result.url)
    if matched:
        profile = get_profile_dir(matched)
        if profile.exists() and any(profile.iterdir()):
            return profile

    # Return the profile dir anyway (will be created on first use)
    if matched:
        return get_profile_dir(matched)
    return get_profile_dir(retailer_key)


def _find_add_to_cart_button(driver):
    """Find the add-to-cart button on the current page."""
    from selenium.webdriver.common.by import By

    for selector in ADD_TO_CART_SELECTORS:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for el in elements:
                if el.is_displayed() and el.is_enabled():
                    return el
        except Exception:
            continue

    for xpath in ADD_TO_CART_XPATHS:
        try:
            elements = driver.find_elements(By.XPATH, xpath)
            for el in elements:
                if el.is_displayed() and el.is_enabled():
                    return el
        except Exception:
            continue

    return None


def _highlight_element(driver, element):
    """Highlight an element with a pulsing border to draw user attention."""
    driver.execute_script("""
        var el = arguments[0];
        el.style.outline = '4px solid #00ff00';
        el.style.outlineOffset = '2px';
        el.scrollIntoView({behavior: 'smooth', block: 'center'});
        setInterval(function() {
            el.style.outline = el.style.outline ? '' : '4px solid #00ff00';
        }, 500);
    """, element)


def open_product_page(result: ProductResult) -> bool:
    """Open the product URL in the default browser. Always works, no dependencies."""
    try:
        webbrowser.open(result.url)
        logger.info(f"Opened {result.url} in browser")
        return True
    except Exception as e:
        logger.error(f"Failed to open browser: {e}")
        return False


def login_to_retailer(retailer: str, login_url: str) -> dict:
    """Open a browser with a persistent profile so the user can log in.

    The session is saved to ~/.product-monitor/profiles/<retailer>/ and will
    be reused automatically by add_to_cart() in future runs.

    Args:
        retailer: Retailer key (e.g. "amazon", "bestbuy").
        login_url: The retailer's login page URL.

    Returns:
        dict with keys: success (bool), profile_dir (str), message (str)
    """
    try:
        from selenium.webdriver.support.ui import WebDriverWait
    except ImportError:
        return {
            "success": False,
            "profile_dir": "",
            "message": "Selenium not installed. Install with: pip install selenium",
        }

    profile = get_profile_dir(retailer)

    try:
        driver = _get_driver(headless=False, profile_dir=profile)
        driver.get(login_url)

        return {
            "success": True,
            "profile_dir": str(profile),
            "message": (
                f"Browser opened to {retailer} login page.\n"
                f"Log in normally — your session will be saved to:\n"
                f"  {profile}\n\n"
                f"When you're done, close the browser window.\n"
                f"Future auto-cart actions for {retailer} will reuse this login."
            ),
        }
    except RuntimeError as e:
        return {"success": False, "profile_dir": "", "message": str(e)}
    except Exception as e:
        return {"success": False, "profile_dir": "", "message": f"Error: {e}"}


def add_to_cart(result: ProductResult, mode: str = "auto", wait_seconds: int = 10) -> dict:
    """Attempt to add a product to cart using browser automation.

    Uses a persistent browser profile (if available) so the user is already
    logged in from a previous `product-monitor login` session.

    Args:
        result: The ProductResult to add to cart.
        mode: "open" (just open page), "prompt" (highlight button), "auto" (click it).
        wait_seconds: How long to wait for page load before looking for the button.

    Returns:
        dict with keys: success (bool), action (str), message (str)
    """
    if mode == "open":
        opened = open_product_page(result)
        return {
            "success": opened,
            "action": "opened_browser",
            "message": f"Opened {result.url} in your browser" if opened else "Failed to open browser",
        }

    # Modes "prompt" and "auto" need Selenium
    try:
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
    except ImportError:
        logger.warning("Selenium not installed, falling back to opening browser")
        opened = open_product_page(result)
        return {
            "success": opened,
            "action": "opened_browser_fallback",
            "message": "Selenium not installed. Opened page in browser instead. Install with: pip install selenium",
        }

    driver = None
    try:
        # Use persistent profile so the user is already logged in
        profile = _resolve_profile_for_result(result)
        logger.info(f"Using browser profile: {profile}")
        driver = _get_driver(headless=False, profile_dir=profile)
        driver.get(result.url)

        # Wait for page to load
        time.sleep(min(wait_seconds, 30))

        button = _find_add_to_cart_button(driver)

        if not button:
            return {
                "success": False,
                "action": "button_not_found",
                "message": (
                    f"Could not find 'Add to Cart' button on {result.url}. "
                    "The page is open in your browser — add it manually."
                ),
            }

        if mode == "prompt":
            _highlight_element(driver, button)
            return {
                "success": True,
                "action": "highlighted",
                "message": (
                    f"Found 'Add to Cart' button on {result.retailer}. "
                    "It's highlighted in green in your browser — click it to purchase!"
                ),
            }

        # mode == "auto"
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
            time.sleep(0.5)
            button.click()
            time.sleep(2)

            return {
                "success": True,
                "action": "clicked",
                "message": (
                    f"Clicked 'Add to Cart' on {result.retailer}! "
                    "Check your browser to complete checkout."
                ),
            }
        except Exception as e:
            try:
                driver.execute_script("arguments[0].click();", button)
                time.sleep(2)
                return {
                    "success": True,
                    "action": "js_clicked",
                    "message": (
                        f"Added to cart on {result.retailer} (via JS click). "
                        "Check your browser to complete checkout."
                    ),
                }
            except Exception:
                _highlight_element(driver, button)
                return {
                    "success": False,
                    "action": "click_failed",
                    "message": (
                        f"Found the button but couldn't click it automatically. "
                        f"It's highlighted in your browser — click it manually. Error: {e}"
                    ),
                }

    except RuntimeError as e:
        logger.warning(str(e))
        opened = open_product_page(result)
        return {
            "success": opened,
            "action": "opened_browser_fallback",
            "message": str(e) + " Opened page in browser instead.",
        }
    except Exception as e:
        logger.error(f"Browser automation error: {e}")
        opened = open_product_page(result)
        return {
            "success": opened,
            "action": "error_fallback",
            "message": f"Automation error: {e}. Opened page in browser instead.",
        }
    finally:
        # Never close the browser — user needs it to complete checkout
        pass
