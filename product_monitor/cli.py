"""Command-line interface for Product Availability Monitor."""

import argparse
import json
import logging

from rich.console import Console
from rich.table import Table

from .config import (
    MonitorConfig,
    PROFILES_DIR,
    RETAILER_LOGIN_URLS,
    WatchEntry,
    get_profile_dir,
    load_config,
    load_watches,
    save_config,
    save_watches,
)
from .cart import login_to_retailer
from .monitor import run_monitor

console = Console()

VALID_RETAILERS = ["amazon", "bestbuy", "walmart", "target", "newegg"]
VALID_CART_MODES = ["off", "open", "prompt", "auto"]


def cmd_add(args):
    """Add a product name to watch."""
    watches = load_watches()

    for w in watches:
        if w.query.lower() == args.query.lower():
            console.print(f"[yellow]Already watching '{w.query}'[/yellow]")
            return

    retailers = args.retailers or VALID_RETAILERS
    # Also allow custom URLs
    final_retailers = []
    for r in retailers:
        if r.startswith("http"):
            final_retailers.append(r)
        elif r.lower() in VALID_RETAILERS:
            final_retailers.append(r.lower())
        else:
            console.print(f"[yellow]Unknown retailer '{r}', skipping. Valid: {', '.join(VALID_RETAILERS)}[/yellow]")

    cart_mode = args.auto_cart or "off"
    if cart_mode not in VALID_CART_MODES:
        console.print(f"[red]Invalid cart mode '{cart_mode}'. Valid: {', '.join(VALID_CART_MODES)}[/red]")
        return

    watch = WatchEntry(
        query=args.query,
        retailers=final_retailers,
        max_price=args.max_price,
        auto_cart=cart_mode,
    )
    watches.append(watch)
    save_watches(watches)

    retailer_str = ", ".join(final_retailers)
    console.print(f"[green]Now watching for '{args.query}' on: {retailer_str}[/green]")
    if args.max_price:
        console.print(f"[green]  Max price: ${args.max_price:.2f}[/green]")
    if cart_mode != "off":
        console.print(f"[green]  Auto-cart: {cart_mode}[/green]")


def cmd_remove(args):
    """Remove a product from the watch list."""
    watches = load_watches()
    original = len(watches)
    watches = [w for w in watches if w.query.lower() != args.query.lower()]

    if len(watches) == original:
        console.print(f"[red]'{args.query}' not found in watch list.[/red]")
        return

    save_watches(watches)
    console.print(f"[green]Removed '{args.query}' from watch list.[/green]")


def cmd_list(args):
    """List all watched products."""
    watches = load_watches()

    if not watches:
        console.print("[yellow]No products being watched. Add one:[/yellow]")
        console.print('  product-monitor add "PlayStation 5"')
        return

    table = Table(title="Watched Products")
    table.add_column("#", style="dim")
    table.add_column("Search Query", style="bold")
    table.add_column("Retailers")
    table.add_column("Max Price")
    table.add_column("Auto-Cart")
    table.add_column("Enabled")
    table.add_column("Last Results")

    for i, w in enumerate(watches, 1):
        retailers = ", ".join(w.retailers)
        price = f"${w.max_price:.2f}" if w.max_price else "any"
        enabled = "[green]Yes[/green]" if w.enabled else "[red]No[/red]"
        n_results = len(w.last_results)
        available = sum(1 for r in w.last_results if r.get("available"))
        results_str = f"{available} available / {n_results} found" if n_results else "not checked yet"
        cart = w.auto_cart if w.auto_cart != "off" else "-"
        table.add_row(str(i), w.query, retailers, price, cart, enabled, results_str)

    console.print(table)


def cmd_check(args):
    """One-time check of all watched products."""
    config = load_config()
    run_monitor(config, one_shot=True)


def cmd_watch(args):
    """Start continuous monitoring."""
    config = load_config()
    if args.interval:
        config.check_interval_seconds = args.interval
    run_monitor(config)


def cmd_login(args):
    """Log in to a retailer and save the session for future auto-cart use."""
    retailer = args.retailer.lower()

    if retailer not in RETAILER_LOGIN_URLS and not retailer.startswith("http"):
        console.print(f"[red]Unknown retailer '{retailer}'.[/red]")
        console.print(f"[yellow]Valid retailers: {', '.join(RETAILER_LOGIN_URLS.keys())}[/yellow]")
        console.print("[yellow]Or provide a full login URL.[/yellow]")
        return

    if retailer.startswith("http"):
        login_url = retailer
        retailer_key = "custom"
    else:
        login_url = RETAILER_LOGIN_URLS[retailer]
        retailer_key = retailer

    console.print(f"[cyan]Opening {retailer_key} login page...[/cyan]")
    console.print("[dim]Log in normally in the browser window that opens.[/dim]")
    console.print("[dim]Your session will be saved and reused for auto-cart.[/dim]\n")

    result = login_to_retailer(retailer_key, login_url)

    if result["success"]:
        console.print(f"[green]{result['message']}[/green]")
    else:
        console.print(f"[red]{result['message']}[/red]")


def cmd_profiles(args):
    """List or manage saved login profiles."""
    import shutil

    if args.clear:
        retailer = args.clear.lower()
        profile = get_profile_dir(retailer)
        if profile.exists() and any(profile.iterdir()):
            shutil.rmtree(profile)
            profile.mkdir(parents=True, exist_ok=True)
            console.print(f"[green]Cleared login profile for '{retailer}'.[/green]")
        else:
            console.print(f"[yellow]No profile found for '{retailer}'.[/yellow]")
        return

    if args.clear_all:
        if PROFILES_DIR.exists():
            shutil.rmtree(PROFILES_DIR)
            PROFILES_DIR.mkdir(parents=True, exist_ok=True)
            console.print("[green]All login profiles cleared.[/green]")
        else:
            console.print("[yellow]No profiles to clear.[/yellow]")
        return

    # List profiles
    if not PROFILES_DIR.exists():
        console.print("[yellow]No login profiles saved yet. Use 'product-monitor login <retailer>' first.[/yellow]")
        return

    table = Table(title="Saved Login Profiles")
    table.add_column("Retailer", style="bold")
    table.add_column("Profile Path")
    table.add_column("Status")

    found_any = False
    for profile_dir in sorted(PROFILES_DIR.iterdir()):
        if profile_dir.is_dir():
            has_data = any(profile_dir.iterdir())
            status = "[green]Active (logged in)[/green]" if has_data else "[dim]Empty[/dim]"
            table.add_row(profile_dir.name, str(profile_dir), status)
            found_any = True

    if found_any:
        console.print(table)
        console.print("\n[dim]To clear a profile: product-monitor profiles --clear amazon[/dim]")
    else:
        console.print("[yellow]No login profiles saved yet. Use 'product-monitor login <retailer>' first.[/yellow]")


def cmd_config(args):
    """View or update configuration."""
    config = load_config()

    if args.interval is not None:
        config.check_interval_seconds = args.interval
    if args.email_to is not None:
        config.notifications.email = True
        config.notifications.email_to = args.email_to
    if args.smtp_host is not None:
        config.notifications.smtp_host = args.smtp_host
    if args.smtp_port is not None:
        config.notifications.smtp_port = args.smtp_port
    if args.smtp_user is not None:
        config.notifications.smtp_user = args.smtp_user
    if args.smtp_password is not None:
        config.notifications.smtp_password = args.smtp_password
    if args.desktop is not None:
        config.notifications.desktop = args.desktop.lower() == "true"
    if args.sound is not None:
        config.notifications.sound = args.sound.lower() == "true"

    save_config(config)
    console.print("[green]Configuration saved.[/green]")

    from dataclasses import asdict
    data = asdict(config)
    if data["notifications"]["smtp_password"]:
        data["notifications"]["smtp_password"] = "***"
    console.print_json(json.dumps(data, indent=2))


def main():
    parser = argparse.ArgumentParser(
        prog="product-monitor",
        description=(
            "Monitor product availability by name across major retailers. "
            "Search by partial or full product name and get notified instantly."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- add ---
    add_p = subparsers.add_parser("add", help="Add a product name to watch")
    add_p.add_argument("query", help="Product name to search for (partial or full)")
    add_p.add_argument(
        "--retailers", "-r", nargs="+",
        help=f"Retailers to search (default: all). Options: {', '.join(VALID_RETAILERS)}. Also accepts URLs.",
    )
    add_p.add_argument("--max-price", "-p", type=float, help="Maximum acceptable price")
    add_p.add_argument(
        "--auto-cart", "-c",
        choices=VALID_CART_MODES, default="off",
        help=(
            "Auto add-to-cart mode when product is found in stock. "
            "'open' = open page in browser, "
            "'prompt' = open page and highlight the button, "
            "'auto' = attempt to click Add to Cart automatically, "
            "'off' = disabled (default)"
        ),
    )

    # --- remove ---
    rm_p = subparsers.add_parser("remove", help="Remove a product from watch list")
    rm_p.add_argument("query", help="Product name to remove")

    # --- list ---
    subparsers.add_parser("list", help="List all watched products")

    # --- check ---
    subparsers.add_parser("check", help="One-time availability check of all watched products")

    # --- watch ---
    watch_p = subparsers.add_parser("watch", help="Start continuous monitoring")
    watch_p.add_argument("--interval", "-i", type=int, help="Check interval in seconds (default: 60)")

    # --- login ---
    login_p = subparsers.add_parser(
        "login",
        help="Log in to a retailer (saves session for auto-cart)",
    )
    login_p.add_argument(
        "retailer",
        help=f"Retailer to log in to ({', '.join(RETAILER_LOGIN_URLS.keys())}) or a login page URL",
    )

    # --- profiles ---
    prof_p = subparsers.add_parser("profiles", help="List or manage saved login profiles")
    prof_p.add_argument("--clear", metavar="RETAILER", help="Clear saved profile for a specific retailer")
    prof_p.add_argument("--clear-all", action="store_true", help="Clear all saved profiles")

    # --- config ---
    cfg_p = subparsers.add_parser("config", help="View or update settings")
    cfg_p.add_argument("--interval", type=int, help="Default check interval (seconds)")
    cfg_p.add_argument("--email-to", help="Email for notifications")
    cfg_p.add_argument("--smtp-host", help="SMTP server host")
    cfg_p.add_argument("--smtp-port", type=int, help="SMTP server port")
    cfg_p.add_argument("--smtp-user", help="SMTP username")
    cfg_p.add_argument("--smtp-password", help="SMTP password")
    cfg_p.add_argument("--desktop", help="Desktop notifications (true/false)")
    cfg_p.add_argument("--sound", help="Sound notifications (true/false)")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    commands = {
        "add": cmd_add,
        "remove": cmd_remove,
        "list": cmd_list,
        "check": cmd_check,
        "watch": cmd_watch,
        "login": cmd_login,
        "profiles": cmd_profiles,
        "config": cmd_config,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
