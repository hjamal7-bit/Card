"""Main monitoring loop - searches for products by name and dispatches alerts."""

import logging
import signal
import time
from datetime import datetime

from rich.console import Console
from rich.table import Table

from .cart import add_to_cart
from .config import MonitorConfig, WatchEntry, load_watches, save_watches
from .notifier import send_notifications
from .scrapers import ProductResult, filter_results, search_product

logger = logging.getLogger(__name__)
console = Console()

_running = True


def _handle_signal(signum, frame):
    global _running
    _running = False
    console.print("\n[yellow]Stopping monitor...[/yellow]")


def build_status_table(watch_results: dict[str, list[ProductResult]], watches: list[WatchEntry]) -> Table:
    """Build a rich table showing current status."""
    table = Table(title=f"Product Availability Monitor  ({datetime.now().strftime('%H:%M:%S')})", show_lines=True)
    table.add_column("Search Query", style="bold cyan", min_width=20)
    table.add_column("Retailer", min_width=10)
    table.add_column("Product Found", min_width=30, max_width=60)
    table.add_column("Price", min_width=8)
    table.add_column("Status", min_width=12)
    table.add_column("Auto-Cart", min_width=8)

    for watch in watches:
        cart_mode = watch.auto_cart if watch.auto_cart != "off" else "[dim]off[/dim]"

        if not watch.enabled:
            table.add_row(watch.query, "[dim]-[/dim]", "[dim]DISABLED[/dim]", "-", "-", cart_mode)
            continue

        results = watch_results.get(watch.query, [])
        if not results:
            table.add_row(watch.query, "-", "[dim]No results found[/dim]", "-", "[dim]--[/dim]", cart_mode)
            continue

        for r in results:
            price_str = f"${r.price:.2f}" if r.price else "-"
            if r.available:
                status = "[bold green]IN STOCK[/bold green]"
            else:
                status = f"[red]{r.availability_text}[/red]"
            table.add_row(watch.query, r.retailer, r.name[:60], price_str, status, cart_mode)

    return table


def run_monitor(config: MonitorConfig, one_shot: bool = False):
    """Run the monitoring loop."""
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    watches = load_watches()
    active = [w for w in watches if w.enabled]

    if not active:
        console.print("[red]No products to monitor. Add one first:[/red]")
        console.print('  product-monitor add "PlayStation 5"')
        return

    console.print(f"[green]Searching for {len(active)} product(s) every {config.check_interval_seconds}s[/green]")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")

    previously_available: dict[str, set[str]] = {}  # query -> set of (retailer+name) seen available

    global _running
    _running = True

    while _running:
        watch_results: dict[str, list[ProductResult]] = {}

        for watch in active:
            if not _running:
                break

            console.print(f"[dim]Searching for '{watch.query}'...[/dim]")
            raw_results = search_product(watch.query, watch.retailers, config)
            filtered = filter_results(raw_results, watch.query, watch.max_price)
            watch_results[watch.query] = filtered

            # Track new availability
            prev = previously_available.setdefault(watch.query, set())
            for result in filtered:
                key = f"{result.retailer}::{result.name}"
                if result.available and key not in prev:
                    console.print(f"\n[bold green]*** FOUND: {result.name} ***[/bold green]")
                    console.print(f"[green]    {result.retailer} - ${result.price or '?'}[/green]")
                    console.print(f"[green]    {result.url}[/green]\n")
                    send_notifications(result, config)

                    # Auto-cart action
                    if watch.auto_cart != "off":
                        console.print(f"[bold cyan]  Cart mode: {watch.auto_cart}[/bold cyan]")
                        cart_result = add_to_cart(result, mode=watch.auto_cart)
                        if cart_result["success"]:
                            console.print(f"[bold green]  {cart_result['message']}[/bold green]")
                        else:
                            console.print(f"[yellow]  {cart_result['message']}[/yellow]")

                    prev.add(key)
                elif not result.available:
                    prev.discard(key)

            # Save results
            watch.last_results = [r.to_dict() for r in filtered]

        save_watches(watches)

        # Display
        table = build_status_table(watch_results, watches)
        console.clear()
        console.print(table)

        if one_shot:
            break

        console.print(f"\n[dim]Next check in {config.check_interval_seconds}s... (Ctrl+C to stop)[/dim]")
        for _ in range(config.check_interval_seconds * 2):
            if not _running:
                break
            time.sleep(0.5)

    console.print("[yellow]Monitor stopped.[/yellow]")
