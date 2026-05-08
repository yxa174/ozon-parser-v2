# Ozon Parser v2

Product parser for Ozon.ru with automatic link collection from categories.

## Structure

- `main.py` — parse products (price, rating, specs, delivery, etc.)
- `parser_list.py` — collect product links from Ozon categories
- `urls.txt` — list of product links
- `urls_catalogs.txt` — list of categories to parse links from

## Installation

```bash
pip install undetected-chromedriver selenium
```

## Usage

### 1. Collect product links from categories

Edit `urls_catalogs.txt` — add Ozon category URLs (one per line).

```bash
python parser_list.py
```

Results saved to `urls.txt`.

### 2. Parse products

```bash
python main.py
```

Script opens ozon.ru, waits for load, then navigates links from `urls.txt` and saves data to JSON file `ozon_products_YYYYMMDD_HHMMSS.json`.

## Product Data

- Title, price, old price, discount
- Brand, seller, article, color
- Rating, reviews count, questions count
- Categories (breadcrumbs)
- Images (main + gallery)
- Characteristics
- Variants (color/size)
- Delivery (dates, methods, prices)
- Sale (remaining stock)
- Parse timestamp

## Requirements

- Python 3.8+
- Chrome / Chromium
- undetected-chromedriver