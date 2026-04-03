"""
Orchestrator v2 — Управление воркерами парсинга
Упрощённый: без async, с SQLite и threading.
"""
import asyncio
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Optional

from config import config
from database import DatabaseManager
from models import ParseStats, ProductCard
from parser import OzonParser, ProxyRotator, load_proxies

logger = logging.getLogger(__name__)


class ParserOrchestrator:
    """Оркестратор парсинга с пулом воркеров."""

    def __init__(self, proxies: Optional[List[str]] = None):
        self.db = DatabaseManager(db_path=config.db_path)
        self.proxies = proxies or []
        self.proxy_rotator = ProxyRotator(self.proxies) if self.proxies else None
        self.stats = ParseStats()
        self._running = False

    def update_proxies(self, proxies: List[str]):
        """Обновить пул прокси на лету."""
        self.proxies = proxies
        self.proxy_rotator = ProxyRotator(proxies)
        logger.info("🔄 Пул прокси обновлён: %d штук", len(proxies))

    def run(self, urls: Optional[List[str]] = None, enqueue_only: bool = False):
        """Запустить парсинг."""
        self._running = True
        self.stats.started_at = datetime.now().isoformat()

        # Загрузка URL
        if urls:
            self.db.enqueue_urls(urls)

        if enqueue_only:
            queue_stats = self.db.get_queue_stats()
            logger.info("📋 URL добавлены в очередь. Ожидание: %d", queue_stats.get("pending", 0))
            return

        logger.info("🚀 Запуск парсера: %d воркеров, %d прокси", config.max_workers, len(self.proxies))

        # Основной цикл
        with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
            while self._running:
                urls_batch = self.db.fetch_pending_urls(batch_size=config.max_workers)

                if not urls_batch:
                    queue_stats = self.db.get_queue_stats()
                    pending = queue_stats.get("pending", 0)
                    retry = queue_stats.get("retry", 0)

                    if pending == 0 and retry == 0:
                        logger.info("✅ Очередь пуста. Завершение.")
                        break

                    logger.info("⏳ Нет доступных URL, ждём... (pending: %d, retry: %d)", pending, retry)
                    time.sleep(10)
                    continue

                # Запуск парсинга
                futures = {}
                for url in urls_batch:
                    proxy = self.proxy_rotator.get() if self.proxy_rotator else None
                    future = executor.submit(self._parse_single, url, proxy)
                    futures[future] = url

                for future in as_completed(futures):
                    url = futures[future]
                    try:
                        card = future.result()
                        self._handle_result(card, url)
                    except Exception as e:
                        logger.error("❌ Ошибка воркера для %s: %s", url[:60], e)
                        self.stats.errors += 1
                        self.db.mark_url_retry(url, delay_seconds=300)

                # Лог статистики
                self._log_progress()

        self.stats.finished_at = datetime.now().isoformat()
        self._print_final_stats()

    def _parse_single(self, url: str, proxy: Optional[str]) -> "ProductCard":
        """Парсинг одного URL."""
        import asyncio

        async def _run():
            p = OzonParser(proxy=proxy)
            return await p.parse_url(url)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(_run())
        finally:
            loop.close()

    def _handle_result(self, card, url: str):
        """Обработка результата парсинга."""
        self.stats.total_urls += 1

        if card.parse_status == "success":
            self.stats.success += 1
            self.db.save_product(card)
            self.db.mark_url_done(url, status="done")

            if self.proxy_rotator and self.proxy_rotator.proxies:
                current_proxy = self.proxy_rotator.get()
                if current_proxy:
                    self.proxy_rotator.report_success(current_proxy)

        elif card.parse_status == "blocked":
            self.stats.blocked += 1
            self.db.save_product(card)
            self.db.mark_url_retry(url, delay_seconds=random.randint(300, 1800))

            if self.proxy_rotator and self.proxy_rotator.proxies:
                current_proxy = self.proxy_rotator.get()
                if current_proxy:
                    self.proxy_rotator.report_failure(current_proxy)

        elif card.parse_status == "not_found":
            self.stats.not_found += 1
            self.db.save_product(card)
            self.db.mark_url_done(url, status="not_found")

        elif card.parse_status == "partial":
            self.stats.success += 1
            self.db.save_product(card)
            self.db.mark_url_done(url, status="done")
            logger.warning("⚠️ Частичный парсинг: %s", card.title or url[:50])

        else:
            self.stats.errors += 1
            self.db.save_product(card)
            self.db.mark_url_retry(url, delay_seconds=random.randint(120, 600))

        # Задержка между запросами
        delay = random.uniform(config.request_delay_min, config.request_delay_max)
        time.sleep(delay)

    def _log_progress(self):
        """Лог прогресса."""
        queue = self.db.get_queue_stats()
        products = self.db.get_product_stats()

        logger.info(
            "📊 Прогресс | "
            "Успешно: %d | Ошибки: %d | Заблокировано: %d | "
            "В очереди: %d | Всего товаров: %d",
            self.stats.success,
            self.stats.errors,
            self.stats.blocked,
            queue.get("pending", 0) + queue.get("retry", 0),
            products.get("total", 0),
        )

    def _print_final_stats(self):
        """Финальная статистика."""
        products = self.db.get_product_stats()

        print("\n" + "=" * 50)
        print("📊 ФИНАЛЬНАЯ СТАТИСТИКА")
        print("=" * 50)
        print(f"  Всего обработано: {self.stats.total_urls}")
        print(f"  ✅ Успешно: {self.stats.success}")
        print(f"  ❌ Ошибки: {self.stats.errors}")
        print(f"  🚫 Заблокировано: {self.stats.blocked}")
        print(f"  🔍 Не найдено: {self.stats.not_found}")
        print(f"  📦 Всего в базе: {products.get('total', 0)}")

        avg_time = products.get("avg_parse_time")
        if avg_time:
            print(f"  ⏱ Среднее время: {avg_time:.2f}с")

        print(f"  🕐 Начато: {self.stats.started_at}")
        print(f"  🕐 Завершено: {self.stats.finished_at}")
        print("=" * 50)

    def stop(self):
        """Остановить парсинг."""
        self._running = False
        logger.info("🛑 Остановка парсера...")
