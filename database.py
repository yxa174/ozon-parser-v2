"""
SQLite Database Manager для Ozon Parser v2
Простая, быстрая, без зависимостей.
"""
import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional, Tuple

from models import ProductCard

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Управление SQLite базой данных."""

    def __init__(self, db_path: str = "ozon_data.db"):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        """Создать таблицы если не существуют."""
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    product_id TEXT,
                    sku_id TEXT,
                    title TEXT,
                    brand TEXT,
                    price REAL,
                    price_original REAL,
                    discount_percent INTEGER,
                    rating REAL,
                    reviews_count INTEGER,
                    seller_name TEXT,
                    seller_id TEXT,
                    category TEXT,
                    category_path TEXT,
                    images TEXT,
                    in_stock BOOLEAN DEFAULT 1,
                    stock_quantity INTEGER,
                    attributes TEXT,
                    description TEXT,
                    short_description TEXT,
                    variants TEXT,
                    delivery_info TEXT,
                    parse_status TEXT NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    parse_time REAL,
                    parse_method TEXT,
                    raw_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_products_status
                    ON products (parse_status);

                CREATE INDEX IF NOT EXISTS idx_products_price
                    ON products (price) WHERE price IS NOT NULL;

                CREATE INDEX IF NOT EXISTS idx_products_seller
                    ON products (seller_id) WHERE seller_id IS NOT NULL;

                CREATE TABLE IF NOT EXISTS parse_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 5,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    next_retry TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_queue_status
                    ON parse_queue (status, priority DESC, next_retry)
                    WHERE status IN ('pending', 'retry');

                CREATE TABLE IF NOT EXISTS parse_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    finished_at TIMESTAMP,
                    total_urls INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    error_count INTEGER DEFAULT 0,
                    blocked_count INTEGER DEFAULT 0,
                    avg_parse_time REAL
                );
            """)
        logger.info("✅ База данных SQLite готова: %s", self.db_path)

    def enqueue_urls(self, urls: List[str], priority: int = 5) -> int:
        """Добавить URL в очередь парсинга. Возвращает количество добавленных."""
        added = 0
        with self._connect() as conn:
            for url in urls:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO parse_queue (url, priority) VALUES (?, ?)",
                        (url, priority),
                    )
                    if conn.total_changes > 0:
                        added += 1
                except Exception:
                    pass
        logger.info("📋 Добавлено %d новых URL в очередь", added)
        return added

    def fetch_pending_urls(self, batch_size: int = 10) -> List[str]:
        """Получить пакет URL для парсинга."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT url FROM parse_queue
                WHERE status IN ('pending', 'retry')
                  AND next_retry <= CURRENT_TIMESTAMP
                ORDER BY priority DESC, id ASC
                LIMIT ?
                """,
                (batch_size,),
            ).fetchall()

            if rows:
                urls = [r["url"] for r in rows]
                placeholders = ",".join("?" for _ in urls)
                conn.execute(
                    f"UPDATE parse_queue SET status = 'processing', attempts = attempts + 1, updated_at = CURRENT_TIMESTAMP WHERE url IN ({placeholders})",
                    urls,
                )
                return urls
        return []

    def mark_url_done(self, url: str, status: str = "done"):
        """Отметить URL как обработанный."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE parse_queue SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE url = ?",
                (status, url),
            )

    def mark_url_retry(self, url: str, delay_seconds: int = 300):
        """Отметить URL для повторной попытки."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE parse_queue
                SET status = 'retry',
                    next_retry = datetime('now', '+' || ? || ' seconds'),
                    updated_at = CURRENT_TIMESTAMP
                WHERE url = ?
                """,
                (str(delay_seconds), url),
            )

    def save_product(self, card: ProductCard):
        """Сохранить карточку товара (upsert)."""
        d = card.to_dict()
        columns = ", ".join(d.keys())
        placeholders = ", ".join("?" for _ in d)
        updates = ", ".join(f"{k} = EXCLUDED.{k}" for k in d.keys() if k != "url")

        sql = f"""
            INSERT INTO products ({columns}) VALUES ({placeholders})
            ON CONFLICT(url) DO UPDATE SET
                {updates},
                updated_at = CURRENT_TIMESTAMP
        """
        with self._connect() as conn:
            conn.execute(sql, list(d.values()))

    def get_queue_stats(self) -> dict:
        """Статистика очереди."""
        with self._connect() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'pending') as pending,
                    COUNT(*) FILTER (WHERE status = 'processing') as processing,
                    COUNT(*) FILTER (WHERE status = 'retry') as retry,
                    COUNT(*) FILTER (WHERE status = 'done') as done,
                    COUNT(*) FILTER (WHERE status = 'failed') as failed,
                    COUNT(*) as total
                FROM parse_queue
            """).fetchone()
            return dict(row) if row else {}

    def get_product_stats(self) -> dict:
        """Статистика товаров."""
        with self._connect() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE parse_status = 'success') as success,
                    COUNT(*) FILTER (WHERE parse_status = 'partial') as partial,
                    COUNT(*) FILTER (WHERE parse_status = 'error') as error,
                    COUNT(*) FILTER (WHERE parse_status = 'blocked') as blocked,
                    AVG(parse_time) as avg_parse_time
                FROM products
            """).fetchone()
            return dict(row) if row else {}

    def export_to_json(self, filepath: str = "products.json"):
        """Экспорт всех товаров в JSON."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM products WHERE parse_status = 'success'"
            ).fetchall()

            products = []
            for row in rows:
                product = dict(row)
                for field in ["category_path", "images", "attributes", "variants", "raw_json"]:
                    if product.get(field):
                        try:
                            product[field] = json.loads(product[field])
                        except (json.JSONDecodeError, TypeError):
                            pass
                products.append(product)

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(products, f, ensure_ascii=False, indent=2)

            logger.info("📦 Экспортировано %d товаров в %s", len(products), filepath)
            return len(products)
