# Product Availability Monitor

Search for any product by name (partial or full) across major retailers and get **instant notifications** when it's in stock.

## How It Works

You give it a product name like `"RTX 4090"` or `"PlayStation 5"`. It searches Amazon, Best Buy, Walmart, Target, and Newegg (or any custom URL you provide), checks if the product is available for purchase, and alerts you via desktop notification, sound, and/or email the moment it finds stock.

## Quick Start

```bash
# Install
pip install -e .

# Add a product to watch (partial name is fine)
product-monitor add "RTX 4090"

# Add with a price cap and specific retailers
product-monitor add "PlayStation 5" --max-price 499.99 --retailers amazon bestbuy walmart

# See what you're watching
product-monitor list

# One-time check
product-monitor check

# Start continuous monitoring (checks every 60s by default)
product-monitor watch

# Check more frequently
product-monitor watch --interval 30
```

## Commands

| Command | Description |
|---------|-------------|
| `add <name>` | Add a product name to watch |
| `remove <name>` | Remove a product from watch list |
| `list` | Show all watched products |
| `check` | One-time availability check |
| `watch` | Start continuous monitoring loop |
| `config` | View or update settings |

## Adding Products

```bash
# Simple - searches all retailers
product-monitor add "AirPods Pro"

# With price limit
product-monitor add "Nintendo Switch" --max-price 299.99

# Specific retailers only
product-monitor add "Ryzen 9800X3D" --retailers amazon newegg

# Watch a specific website
product-monitor add "Limited Edition Sneakers" --retailers "https://example.com/drops"
```

## Supported Retailers

- **Amazon** (`amazon`)
- **Best Buy** (`bestbuy`)
- **Walmart** (`walmart`)
- **Target** (`target`)
- **Newegg** (`newegg`)
- **Any URL** - pass a full URL as a retailer to monitor any website

## Notifications

By default, you get **desktop notifications** and **sound alerts**. To add email:

```bash
product-monitor config --email-to you@email.com --smtp-user you@gmail.com --smtp-password "your-app-password"
```

Toggle notifications:

```bash
product-monitor config --desktop true --sound false
```

## Configuration

Config is stored in `~/.product-monitor/config.json`. View current settings:

```bash
product-monitor config
```

## Development

```bash
pip install -e ".[dev]"
pytest
```
