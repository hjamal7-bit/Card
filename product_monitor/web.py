"""Web dashboard for Product Availability Monitor."""

import math
import threading
import time
from datetime import datetime

from flask import Flask, render_template_string, jsonify, request, redirect, url_for

from .config import (
    RETAILER_LOGIN_URLS,
    WatchEntry,
    load_config,
    load_watches,
    save_watches,
)
from .scrapers import ProductResult, filter_results, search_product

app = Flask(__name__)

# Keep in sync with cli.py's VALID_CART_MODES. "auto" clicks the real
# add-to-cart button on the retailer's site, so an unrecognized/tampered
# form value must never be allowed to fall through to that behavior.
VALID_CART_MODES = ("off", "open", "prompt", "auto")

# In-memory state for the dashboard
monitor_state = {
    "running": False,
    "results": {},       # query -> list of ProductResult dicts
    "last_check": None,
    "errors": [],
    "check_count": 0,
}

# Demo results for sandbox/preview environments where network is unavailable
DEMO_RESULTS = {
    "Jordan 1": [
        {"name": "Air Jordan 1 Retro High OG 'Chicago'", "retailer": "Nike", "price": 180.00,
         "url": "https://www.nike.com/t/air-jordan-1-retro-high-og", "available": False,
         "availability_text": "sold out"},
        {"name": "Air Jordan 1 Mid SE Men's Shoes", "retailer": "Amazon", "price": 134.99,
         "url": "https://www.amazon.com/dp/B09V3KXJPB", "available": True,
         "availability_text": "in stock"},
        {"name": "Jordan 1 Retro High OG 'Royal Reimagined'", "retailer": "Foot Locker", "price": 180.00,
         "url": "https://www.footlocker.com/product/jordan-1-retro", "available": True,
         "availability_text": "add to cart"},
        {"name": "Air Jordan 1 Low G Golf Shoe", "retailer": "Walmart", "price": 89.97,
         "url": "https://www.walmart.com/ip/air-jordan-1-low", "available": True,
         "availability_text": "in stock"},
        {"name": "Air Jordan 1 Mid 'Bred Toe'", "retailer": "Best Buy", "price": None,
         "url": "https://www.bestbuy.com", "available": False,
         "availability_text": "out of stock"},
        {"name": "Jordan 1 Retro High OG 'Black/White'", "retailer": "Target", "price": 170.00,
         "url": "https://www.target.com/p/jordan-1", "available": False,
         "availability_text": "notify me"},
    ],
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Product Monitor</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
            background: #f0f2f5;
            color: #1a1a2e;
            min-height: 100vh;
        }

        /* ── Header ── */
        .header {
            background: #fff;
            padding: 16px 28px;
            border-bottom: 1px solid #e2e5ea;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header-left { display: flex; align-items: center; gap: 24px; }
        .logo {
            font-size: 22px;
            font-weight: 800;
            color: #1a1a2e;
            letter-spacing: -0.5px;
        }
        .logo span { color: #4f6ef7; }
        .search-bar {
            background: #f5f6f8;
            border: 1px solid #e2e5ea;
            border-radius: 8px;
            padding: 9px 16px;
            font-size: 14px;
            color: #555;
            width: 320px;
            outline: none;
            transition: border-color 0.2s;
        }
        .search-bar:focus { border-color: #4f6ef7; background: #fff; }
        .search-bar::placeholder { color: #aab0b8; }
        .header-right { display: flex; align-items: center; gap: 12px; }
        .header-nav {
            display: flex;
            gap: 4px;
        }
        .nav-tab {
            padding: 8px 16px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 500;
            color: #666;
            text-decoration: none;
            cursor: pointer;
            border: none;
            background: none;
            transition: all 0.15s;
        }
        .nav-tab:hover { background: #f0f2f5; color: #333; }
        .nav-tab.active { background: #eef0ff; color: #4f6ef7; font-weight: 600; }
        .btn-add-new {
            background: #4f6ef7;
            color: #fff;
            border: none;
            border-radius: 8px;
            padding: 9px 18px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s;
        }
        .btn-add-new:hover { background: #3b5bdb; }
        .status-indicator {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 12px;
            color: #888;
        }
        .status-dot {
            width: 8px; height: 8px;
            border-radius: 50%;
            background: #34d399;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { box-shadow: 0 0 0 0 rgba(52,211,153,0.4); }
            50% { box-shadow: 0 0 0 6px rgba(52,211,153,0); }
        }

        /* ── Board ── */
        .board {
            display: flex;
            gap: 16px;
            padding: 20px 28px;
            overflow-x: auto;
            min-height: calc(100vh - 65px);
            align-items: flex-start;
        }

        /* ── Columns ── */
        .column {
            min-width: 300px;
            max-width: 340px;
            flex-shrink: 0;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .col-header {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px 4px;
        }
        .col-count {
            background: #e8eaed;
            color: #555;
            font-size: 13px;
            font-weight: 700;
            width: 28px; height: 28px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .col-title {
            font-size: 15px;
            font-weight: 600;
            color: #333;
        }
        .col-menu {
            margin-left: auto;
            color: #bbb;
            cursor: pointer;
            font-size: 18px;
        }

        /* ── Cards ── */
        .card {
            background: #fff;
            border: 1px solid #e2e5ea;
            border-radius: 10px;
            padding: 14px 16px;
            cursor: default;
            transition: box-shadow 0.15s, border-color 0.15s;
            position: relative;
        }
        .card:hover {
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            border-color: #d0d3d8;
        }
        .card.highlight-green {
            background: #f0fdf4;
            border-color: #bbf7d0;
        }
        .card.highlight-yellow {
            background: #fefce8;
            border-color: #fde68a;
        }
        .card.highlight-red {
            background: #fef2f2;
            border-color: #fecaca;
        }
        .card-top {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            margin-bottom: 8px;
        }
        .card-name {
            font-size: 14px;
            font-weight: 600;
            color: #1a1a2e;
            line-height: 1.3;
        }
        .card-tags {
            display: flex;
            gap: 5px;
            flex-shrink: 0;
            margin-left: 8px;
        }
        .tag {
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.3px;
        }
        .tag-retailer { background: #e8eaed; color: #555; }
        .tag-available { background: #dcfce7; color: #166534; }
        .tag-unavailable { background: #fee2e2; color: #991b1b; }
        .tag-auto { background: #e0e7ff; color: #3730a3; }
        .card-url {
            font-size: 12px;
            color: #4f6ef7;
            text-decoration: none;
            display: block;
            margin-bottom: 12px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .card-url:hover { text-decoration: underline; }

        .card-fields {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 2px;
            border-top: 1px solid #f0f2f5;
            padding-top: 10px;
        }
        .field-label {
            font-size: 10px;
            font-weight: 600;
            color: #aab0b8;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .field-value {
            font-size: 14px;
            font-weight: 600;
            color: #333;
            margin-top: 2px;
        }
        .field-value.muted { color: #ccc; }

        .card-actions {
            display: flex;
            gap: 6px;
            position: absolute;
            top: 12px;
            right: 12px;
            opacity: 0;
            transition: opacity 0.15s;
        }
        .card:hover .card-actions { opacity: 1; }
        .card-action-btn {
            width: 28px; height: 28px;
            border-radius: 6px;
            border: 1px solid #e2e5ea;
            background: #fff;
            color: #888;
            font-size: 14px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.15s;
        }
        .card-action-btn:hover { background: #f5f6f8; color: #333; }

        .card-event {
            margin-top: 10px;
            padding: 8px 10px;
            background: #fefce8;
            border-radius: 6px;
            font-size: 12px;
            color: #854d0e;
            font-weight: 500;
        }
        .card-event.success {
            background: #f0fdf4;
            color: #166534;
        }

        /* ── Add form modal ── */
        .modal-overlay {
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.3);
            z-index: 100;
            align-items: center;
            justify-content: center;
        }
        .modal-overlay.show { display: flex; }
        .modal {
            background: #fff;
            border-radius: 12px;
            padding: 28px;
            width: 460px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.15);
        }
        .modal h2 {
            font-size: 18px;
            font-weight: 700;
            margin-bottom: 20px;
            color: #1a1a2e;
        }
        .modal .form-group {
            margin-bottom: 14px;
        }
        .modal label {
            display: block;
            font-size: 12px;
            font-weight: 600;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 4px;
        }
        .modal input, .modal select {
            width: 100%;
            padding: 10px 12px;
            border: 1px solid #e2e5ea;
            border-radius: 8px;
            font-size: 14px;
            color: #333;
            outline: none;
            background: #f9fafb;
            transition: border-color 0.15s;
        }
        .modal input:focus, .modal select:focus {
            border-color: #4f6ef7;
            background: #fff;
        }
        .modal-buttons {
            display: flex;
            gap: 10px;
            justify-content: flex-end;
            margin-top: 20px;
        }
        .btn-cancel {
            padding: 9px 18px;
            border-radius: 8px;
            border: 1px solid #e2e5ea;
            background: #fff;
            color: #666;
            font-size: 13px;
            font-weight: 500;
            cursor: pointer;
        }
        .btn-cancel:hover { background: #f5f6f8; }

        /* ── Empty state ── */
        .empty-col {
            padding: 32px 16px;
            text-align: center;
            color: #bbb;
            font-size: 13px;
        }

        /* ── Form error banner ── */
        .form-error {
            background: #fdecea;
            border-bottom: 1px solid #f5c2bd;
            color: #8c1d13;
            font-size: 14px;
            padding: 12px 28px;
        }

        /* ── Responsive ── */
        @media (max-width: 900px) {
            .board { padding: 12px; }
            .column { min-width: 260px; }
            .search-bar { width: 200px; }
        }
    </style>
</head>
<body>
    {% if error_message %}
    <div class="form-error">{{ error_message }}</div>
    {% endif %}
    <div class="header">
        <div class="header-left">
            <div class="logo"><span>&#9670;</span> StockPulse</div>
            <input type="text" class="search-bar" placeholder="Search products by name or retailer..." id="searchInput">
        </div>
        <div class="header-right">
            <div class="header-nav">
                <button class="nav-tab active">Board</button>
                <button class="nav-tab" id="navWatches">Watches</button>
            </div>
            <button class="btn-add-new" onclick="openModal()">+ New Watch</button>
            <div class="status-indicator">
                <span class="status-dot"></span>
                <span id="lastUpdate">Monitoring</span>
            </div>
        </div>
    </div>

    <div class="board" id="board">
        <!-- Columns rendered by JS -->
    </div>

    <!-- Add Watch Modal -->
    <div class="modal-overlay" id="modalOverlay">
        <div class="modal">
            <h2>Add New Watch</h2>
            <form method="POST" action="/add">
                <div class="form-group">
                    <label>Product Name</label>
                    <input type="text" name="query" placeholder="e.g. Jordan 1, RTX 4090, AirPods Pro" required>
                </div>
                <div class="form-group">
                    <label>Max Price</label>
                    <input type="number" name="max_price" placeholder="Any price" step="0.01" min="0">
                </div>
                <div class="form-group">
                    <label>Auto-Cart Mode</label>
                    <select name="auto_cart">
                        <option value="off">Off</option>
                        <option value="open" selected>Open Page</option>
                        <option value="prompt">Highlight Button</option>
                        <option value="auto">Auto Click</option>
                    </select>
                </div>
                <div class="modal-buttons">
                    <button type="button" class="btn-cancel" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn-add-new">Add Watch</button>
                </div>
            </form>
        </div>
    </div>

    <script>
        function openModal() { document.getElementById('modalOverlay').classList.add('show'); }
        function closeModal() { document.getElementById('modalOverlay').classList.remove('show'); }
        document.getElementById('modalOverlay').addEventListener('click', function(e) {
            if (e.target === this) closeModal();
        });

        let searchFilter = '';
        document.getElementById('searchInput').addEventListener('input', function(e) {
            searchFilter = e.target.value.toLowerCase();
            renderBoard(lastData);
        });

        let lastData = null;

        function fetchData() {
            fetch('/api/status')
                .then(r => r.json())
                .then(data => {
                    lastData = data;
                    if (data.last_check) {
                        document.getElementById('lastUpdate').textContent = 'Updated ' + data.last_check;
                    }
                    renderBoard(data);
                });
        }

        function renderBoard(data) {
            if (!data) return;
            const board = document.getElementById('board');

            // Collect all results across all watches
            let allResults = [];
            data.watches.forEach(watch => {
                const results = data.results[watch.query] || [];
                results.forEach(r => {
                    r._query = watch.query;
                    r._auto_cart = watch.auto_cart;
                    r._max_price = watch.max_price;
                    allResults.push(r);
                });
            });

            // Filter by search
            if (searchFilter) {
                allResults = allResults.filter(r =>
                    r.name.toLowerCase().includes(searchFilter) ||
                    r.retailer.toLowerCase().includes(searchFilter) ||
                    r._query.toLowerCase().includes(searchFilter)
                );
            }

            // Bucket into columns
            const watching = data.watches;
            const inStock = allResults.filter(r => r.available);
            const outOfStock = allResults.filter(r => !r.available && r.availability_text !== 'notify me');
            const waitlist = allResults.filter(r => !r.available && r.availability_text === 'notify me');

            let html = '';

            // ── Watchlist Column ──
            html += buildColumn('Watchlist', watching.length, watching.map(w => {
                const results = data.results[w.query] || [];
                const avail = results.filter(r => r.available).length;
                const total = results.length;
                return cardWatch(w, avail, total);
            }), '#4f6ef7');

            // ── In Stock Column ──
            html += buildColumn('In Stock', inStock.length, inStock.map(r => cardProduct(r, 'green')), '#22c55e');

            // ── Out of Stock Column ──
            html += buildColumn('Out of Stock', outOfStock.length, outOfStock.map(r => cardProduct(r, 'red')), '#ef4444');

            // ── Waitlist Column ──
            html += buildColumn('Waitlist', waitlist.length, waitlist.map(r => cardProduct(r, 'yellow')), '#f59e0b');

            board.innerHTML = html;
        }

        function buildColumn(title, count, cards, color) {
            let html = '<div class="column">';
            html += '<div class="col-header">';
            html += '<div class="col-count" style="background:' + color + '15; color:' + color + ';">' + count + '</div>';
            html += '<div class="col-title">' + title + '</div>';
            html += '<div class="col-menu">&#8943;</div>';
            html += '</div>';
            if (cards.length === 0) {
                html += '<div class="empty-col">No items</div>';
            } else {
                html += cards.join('');
            }
            html += '</div>';
            return html;
        }

        function cardWatch(watch, avail, total) {
            let cls = avail > 0 ? 'highlight-green' : '';
            let html = '<div class="card ' + cls + '">';

            html += '<div class="card-actions">';
            html += '<form method="POST" action="/remove" style="margin:0;display:inline;">';
            html += '<input type="hidden" name="query" value="' + escAttr(watch.query) + '">';
            html += '<button type="submit" class="card-action-btn" title="Remove">&#128465;</button>';
            html += '</form>';
            html += '</div>';

            html += '<div class="card-top">';
            html += '<div class="card-name">' + escHtml(watch.query) + '</div>';
            html += '<div class="card-tags">';
            if (watch.auto_cart !== 'off') html += '<span class="tag tag-auto">' + escHtml(watch.auto_cart) + '</span>';
            html += '</div>';
            html += '</div>';

            html += '<div class="card-fields">';
            html += '<div><div class="field-label">Retailers</div><div class="field-value">' + watch.retailers.length + '</div></div>';
            html += '<div><div class="field-label">Found</div><div class="field-value">' + total + '</div></div>';
            html += '<div><div class="field-label">Max Price</div><div class="field-value ' + (watch.max_price ? '' : 'muted') + '">' + (watch.max_price ? '$' + watch.max_price.toFixed(0) : '&mdash;') + '</div></div>';
            html += '</div>';

            if (avail > 0) {
                html += '<div class="card-event success">' + avail + ' item' + (avail > 1 ? 's' : '') + ' available now</div>';
            }

            html += '</div>';
            return html;
        }

        function cardProduct(r, highlight) {
            let cls = 'highlight-' + highlight;
            let html = '<div class="card ' + cls + '">';

            html += '<div class="card-actions">';
            if (r.available && r.url) {
                html += '<a href="' + escAttr(r.url) + '" target="_blank" class="card-action-btn" title="Open">&#8599;</a>';
            }
            html += '</div>';

            html += '<div class="card-top">';
            html += '<div class="card-name">' + escHtml(r.name) + '</div>';
            html += '<div class="card-tags">';
            html += '<span class="tag tag-retailer">' + escHtml(r.retailer) + '</span>';
            html += '</div>';
            html += '</div>';

            html += '<a class="card-url" href="' + escAttr(r.url) + '" target="_blank">' + escHtml(r.url) + '</a>';

            html += '<div class="card-fields">';
            html += '<div><div class="field-label">Price</div><div class="field-value ' + (r.price ? '' : 'muted') + '">' + (r.price ? '$' + r.price.toFixed(2) : '&mdash;') + '</div></div>';
            html += '<div><div class="field-label">Status</div><div class="field-value">' + escHtml(r.availability_text) + '</div></div>';
            html += '<div><div class="field-label">Query</div><div class="field-value">' + escHtml(r._query) + '</div></div>';
            html += '</div>';

            if (r.available && r._auto_cart && r._auto_cart !== 'off') {
                html += '<div class="card-event success">Auto-cart: ' + escHtml(r._auto_cart) + '</div>';
            }

            html += '</div>';
            return html;
        }

        function escHtml(s) {
            if (!s) return '';
            const d = document.createElement('div');
            d.textContent = s;
            return d.innerHTML;
        }
        function escAttr(s) {
            if (!s) return '';
            return s.replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/</g,'&lt;');
        }

        fetchData();
        setInterval(fetchData, 3000);
    </script>
</body>
</html>
"""


def _run_background_checker():
    """Background thread that periodically checks all watches."""
    config = load_config()
    while monitor_state["running"]:
        watches = load_watches()
        for watch in watches:
            if not watch.enabled or not monitor_state["running"]:
                continue
            try:
                raw = search_product(watch.query, watch.retailers, config)
                filtered = filter_results(raw, watch.query, watch.max_price)
                monitor_state["results"][watch.query] = [r.to_dict() for r in filtered]
            except Exception as e:
                monitor_state["errors"].append(str(e))
                monitor_state["errors"] = monitor_state["errors"][-50:]
                # If network fails, use demo data as fallback
                if watch.query not in monitor_state["results"]:
                    demo = DEMO_RESULTS.get(watch.query, [])
                    if demo:
                        monitor_state["results"][watch.query] = demo

        monitor_state["last_check"] = datetime.now().strftime("%H:%M:%S")
        monitor_state["check_count"] += 1

        for _ in range(config.check_interval_seconds * 2):
            if not monitor_state["running"]:
                break
            time.sleep(0.5)


# Fixed server-side text per error code. The redirect only ever carries the
# code, so nothing a caller supplies is echoed back into the page.
FORM_ERRORS = {
    "bad_price": "Max price must be a number, for example 1200 or 1200.50. The watch was not added.",
}


@app.route("/")
def index():
    return render_template_string(
        HTML_TEMPLATE,
        error_message=FORM_ERRORS.get(request.args.get("error", "")),
    )


@app.route("/api/status")
def api_status():
    watches = load_watches()
    # Seed demo data for watches that have no results yet
    for w in watches:
        if w.query not in monitor_state["results"]:
            demo = DEMO_RESULTS.get(w.query, [])
            if demo:
                monitor_state["results"][w.query] = demo
    return jsonify({
        "running": monitor_state["running"],
        "watches": [w.to_dict() for w in watches],
        "results": monitor_state["results"],
        "last_check": monitor_state["last_check"],
        "check_count": monitor_state["check_count"],
    })


@app.route("/add", methods=["POST"])
def add_watch():
    query = request.form.get("query", "").strip()
    if not query:
        return redirect(url_for("index"))

    max_price_str = request.form.get("max_price", "").strip()
    try:
        max_price = float(max_price_str) if max_price_str else None
    except ValueError:
        # Falling back to None would mean "no price cap at all", which is the
        # opposite of what someone typing a price wants, and with auto_cart set
        # to "auto" it would let the monitor act on an item at any price.
        # Refuse the add and say why instead.
        return redirect(url_for("index", error="bad_price"))
    # float() also accepts "nan" and "inf". A NaN cap silently matches nothing,
    # and both serialize into watches.json as tokens no strict JSON reader takes.
    if max_price is not None and not math.isfinite(max_price):
        return redirect(url_for("index", error="bad_price"))
    auto_cart = request.form.get("auto_cart", "off")
    if auto_cart not in VALID_CART_MODES:
        # Unlike the CLI (argparse choices=VALID_CART_MODES), this form field
        # isn't validated by the framework, so reject anything unrecognized
        # rather than persisting it — "auto" auto-clicks Add to Cart for real.
        auto_cart = "off"

    watches = load_watches()
    for w in watches:
        if w.query.lower() == query.lower():
            return redirect(url_for("index"))

    watch = WatchEntry(
        query=query,
        max_price=max_price,
        auto_cart=auto_cart,
    )
    watches.append(watch)
    save_watches(watches)

    # Seed demo data if available
    demo = DEMO_RESULTS.get(query, [])
    if demo:
        monitor_state["results"][query] = demo

    return redirect(url_for("index"))


@app.route("/remove", methods=["POST"])
def remove_watch():
    query = request.form.get("query", "").strip()
    watches = load_watches()
    watches = [w for w in watches if w.query.lower() != query.lower()]
    save_watches(watches)
    monitor_state["results"].pop(query, None)
    return redirect(url_for("index"))


def run_web(host="0.0.0.0", port=5000):
    """Start the web dashboard."""
    monitor_state["running"] = True
    checker = threading.Thread(target=_run_background_checker, daemon=True)
    checker.start()
    app.run(host=host, port=port, debug=False)
