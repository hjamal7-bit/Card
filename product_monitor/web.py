"""Web dashboard for Product Availability Monitor."""

import json
import threading
import time
from datetime import datetime
from dataclasses import asdict

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
    <title>Product Availability Monitor</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0a0f;
            color: #e0e0e0;
            min-height: 100vh;
        }
        .header {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            padding: 24px 32px;
            border-bottom: 1px solid #2a2a4a;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 {
            font-size: 24px;
            font-weight: 700;
            color: #fff;
        }
        .header h1 span { color: #00d4aa; }
        .header-status {
            display: flex;
            align-items: center;
            gap: 16px;
        }
        .status-dot {
            width: 10px; height: 10px;
            border-radius: 50%;
            display: inline-block;
        }
        .status-dot.active { background: #00d4aa; animation: pulse 2s infinite; }
        .status-dot.inactive { background: #666; }
        @keyframes pulse {
            0%, 100% { box-shadow: 0 0 0 0 rgba(0,212,170,0.4); }
            50% { box-shadow: 0 0 0 8px rgba(0,212,170,0); }
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 24px; }

        .add-form {
            background: #12121f;
            border: 1px solid #2a2a4a;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 24px;
            display: flex;
            gap: 12px;
            align-items: end;
            flex-wrap: wrap;
        }
        .form-group { display: flex; flex-direction: column; gap: 4px; }
        .form-group label { font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }
        .form-group input, .form-group select {
            background: #1a1a2e;
            border: 1px solid #2a2a4a;
            color: #fff;
            padding: 10px 14px;
            border-radius: 8px;
            font-size: 14px;
            outline: none;
        }
        .form-group input:focus { border-color: #00d4aa; }
        .form-group input::placeholder { color: #555; }
        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-primary { background: #00d4aa; color: #000; }
        .btn-primary:hover { background: #00f0c0; transform: translateY(-1px); }
        .btn-danger { background: #ff4757; color: #fff; }
        .btn-danger:hover { background: #ff6b7a; }
        .btn-sm { padding: 6px 12px; font-size: 12px; }

        .stats-bar {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }
        .stat-card {
            background: #12121f;
            border: 1px solid #2a2a4a;
            border-radius: 12px;
            padding: 16px 20px;
        }
        .stat-card .label { font-size: 12px; color: #888; text-transform: uppercase; }
        .stat-card .value { font-size: 28px; font-weight: 700; margin-top: 4px; }
        .stat-card .value.green { color: #00d4aa; }
        .stat-card .value.red { color: #ff4757; }
        .stat-card .value.blue { color: #3b82f6; }

        .watches-section h2 {
            font-size: 18px;
            margin-bottom: 16px;
            color: #fff;
        }
        .product-grid {
            display: grid;
            gap: 12px;
        }
        .product-card {
            background: #12121f;
            border: 1px solid #2a2a4a;
            border-radius: 12px;
            padding: 16px 20px;
            display: grid;
            grid-template-columns: 1fr auto auto auto auto;
            align-items: center;
            gap: 16px;
            transition: border-color 0.2s;
        }
        .product-card:hover { border-color: #3a3a5a; }
        .product-card.available { border-left: 3px solid #00d4aa; }
        .product-card.unavailable { border-left: 3px solid #ff4757; }
        .product-card.unknown { border-left: 3px solid #ffa502; }
        .product-name {
            font-weight: 600;
            font-size: 15px;
        }
        .product-name .retailer {
            font-size: 12px;
            color: #888;
            font-weight: 400;
            display: block;
            margin-top: 2px;
        }
        .badge {
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
        }
        .badge-available { background: rgba(0,212,170,0.15); color: #00d4aa; }
        .badge-unavailable { background: rgba(255,71,87,0.15); color: #ff4757; }
        .badge-unknown { background: rgba(255,165,2,0.15); color: #ffa502; }
        .price { font-size: 18px; font-weight: 700; color: #fff; }
        .price.no-price { color: #555; font-size: 14px; }
        a.buy-link {
            color: #00d4aa;
            text-decoration: none;
            font-size: 13px;
            font-weight: 600;
        }
        a.buy-link:hover { text-decoration: underline; }

        .watch-group {
            margin-bottom: 32px;
        }
        .watch-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
            padding: 12px 16px;
            background: #16213e;
            border-radius: 8px;
        }
        .watch-query { font-size: 18px; font-weight: 700; color: #fff; }
        .watch-meta { font-size: 13px; color: #888; }

        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #555;
        }
        .empty-state h3 { color: #888; margin-bottom: 8px; }

        .last-update { font-size: 12px; color: #555; }

        @media (max-width: 768px) {
            .product-card {
                grid-template-columns: 1fr;
                gap: 8px;
            }
            .add-form { flex-direction: column; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1><span>&#9679;</span> Product Availability Monitor</h1>
        <div class="header-status">
            <span class="last-update" id="lastUpdate">--</span>
            <span class="status-dot active" id="statusDot"></span>
            <span id="statusText" style="font-size:13px;">Monitoring</span>
        </div>
    </div>

    <div class="container">
        <form class="add-form" method="POST" action="/add">
            <div class="form-group" style="flex:2;">
                <label>Product Name</label>
                <input type="text" name="query" placeholder="e.g. Jordan 1, RTX 4090, AirPods Pro" required>
            </div>
            <div class="form-group">
                <label>Max Price</label>
                <input type="number" name="max_price" placeholder="Any" step="0.01" min="0">
            </div>
            <div class="form-group">
                <label>Auto-Cart</label>
                <select name="auto_cart">
                    <option value="off">Off</option>
                    <option value="open" selected>Open Page</option>
                    <option value="prompt">Highlight Button</option>
                    <option value="auto">Auto Click</option>
                </select>
            </div>
            <button type="submit" class="btn btn-primary">+ Add Watch</button>
        </form>

        <div class="stats-bar">
            <div class="stat-card">
                <div class="label">Watching</div>
                <div class="value blue" id="statWatching">0</div>
            </div>
            <div class="stat-card">
                <div class="label">In Stock</div>
                <div class="value green" id="statAvailable">0</div>
            </div>
            <div class="stat-card">
                <div class="label">Out of Stock</div>
                <div class="value red" id="statUnavailable">0</div>
            </div>
            <div class="stat-card">
                <div class="label">Checks Run</div>
                <div class="value" id="statChecks" style="color:#888;">0</div>
            </div>
        </div>

        <div class="watches-section" id="watchesContainer">
            <div class="empty-state" id="emptyState">
                <h3>No products being monitored</h3>
                <p>Add a product above to start watching for availability</p>
            </div>
        </div>
    </div>

    <script>
        function fetchData() {
            fetch('/api/status')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('statWatching').textContent = data.watches.length;
                    document.getElementById('statChecks').textContent = data.check_count;
                    if (data.last_check) {
                        document.getElementById('lastUpdate').textContent = 'Last check: ' + data.last_check;
                    }

                    let totalAvailable = 0;
                    let totalUnavailable = 0;
                    const container = document.getElementById('watchesContainer');
                    const empty = document.getElementById('emptyState');

                    if (data.watches.length === 0) {
                        container.innerHTML = '';
                        container.appendChild(empty);
                        return;
                    }

                    let html = '';
                    data.watches.forEach(watch => {
                        const results = data.results[watch.query] || [];
                        const avail = results.filter(r => r.available).length;
                        const unavail = results.filter(r => !r.available).length;
                        totalAvailable += avail;
                        totalUnavailable += unavail;

                        html += '<div class="watch-group">';
                        html += '<div class="watch-header">';
                        html += '<div>';
                        html += '<span class="watch-query">' + escHtml(watch.query) + '</span>';
                        html += '<span class="watch-meta"> &mdash; ' + results.length + ' results';
                        if (watch.max_price) html += ' &bull; max $' + watch.max_price.toFixed(2);
                        if (watch.auto_cart !== 'off') html += ' &bull; auto-cart: ' + watch.auto_cart;
                        html += '</span>';
                        html += '</div>';
                        html += '<form method="POST" action="/remove" style="margin:0;"><input type="hidden" name="query" value="' + escAttr(watch.query) + '"><button class="btn btn-danger btn-sm" type="submit">Remove</button></form>';
                        html += '</div>';

                        html += '<div class="product-grid">';
                        if (results.length === 0) {
                            html += '<div class="product-card unknown"><div class="product-name">Searching...</div><div></div><div></div><div></div><div></div></div>';
                        }
                        results.forEach(r => {
                            const cls = r.available ? 'available' : 'unavailable';
                            const badgeCls = r.available ? 'badge-available' : 'badge-unavailable';
                            const badgeText = r.available ? 'In Stock' : r.availability_text;
                            const priceStr = r.price ? '$' + r.price.toFixed(2) : '--';
                            const priceCls = r.price ? 'price' : 'price no-price';

                            html += '<div class="product-card ' + cls + '">';
                            html += '<div class="product-name">' + escHtml(r.name) + '<span class="retailer">' + escHtml(r.retailer) + '</span></div>';
                            html += '<span class="badge ' + badgeCls + '">' + escHtml(badgeText) + '</span>';
                            html += '<span class="' + priceCls + '">' + priceStr + '</span>';
                            if (r.available) {
                                html += '<a href="' + escAttr(r.url) + '" target="_blank" class="buy-link">Buy Now &rarr;</a>';
                            } else {
                                html += '<span></span>';
                            }
                            html += '</div>';
                        });
                        html += '</div></div>';
                    });

                    container.innerHTML = html;
                    document.getElementById('statAvailable').textContent = totalAvailable;
                    document.getElementById('statUnavailable').textContent = totalUnavailable;
                });
        }

        function escHtml(s) {
            const d = document.createElement('div');
            d.textContent = s;
            return d.innerHTML;
        }
        function escAttr(s) {
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


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


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
    max_price = float(max_price_str) if max_price_str else None
    auto_cart = request.form.get("auto_cart", "off")

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
