"""
Ozon Parser v2 — CLI Entrypoint
Использование:
  python main.py parse --urls urls.txt
  python main.py parse --urls urls.txt --workers 3
  python main.py proxy-scrape
  python main.py proxy-check --input proxies.txt
  python main.py pipeline --urls urls.txt
  python main.py enqueue --urls urls.txt
  python main.py stats
  python main.py export --output products.json
"""

import argparse
import logging
import sys
from pathlib import Path

from config import config
from orchestrator import ParserOrchestrator

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("parser.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")


def load_urls(path: str) -> list:
    """Загрузить URL из файла."""
    urls = []
    file_path = Path(path)
    if not file_path.exists():
        logger.error("❌ Файл не найден: %s", path)
        return urls

    with open(file_path, encoding="utf-8") as f:
        for line in f:
            url = line.strip()
            if url and url.startswith("http"):
                urls.append(url)

    logger.info("📂 Загружено %d URL из %s", len(urls), path)
    return urls


def cmd_parse(args):
    """Команда parse."""
    urls = load_urls(args.urls)
    if not urls:
        logger.warning("⚠️ Нет URL для парсинга")
        return

    orchestrator = ParserOrchestrator()
    orchestrator.run(urls=urls, enqueue_only=args.enqueue_only)


def cmd_enqueue(args):
    """Команда enqueue."""
    from database import DatabaseManager

    urls = load_urls(args.urls)
    if not urls:
        return

    db = DatabaseManager(db_path=config.db_path)
    added = db.enqueue_urls(urls, priority=args.priority)
    logger.info("✅ Добавлено %d URL в очередь", added)


def cmd_stats(args):
    """Команда stats."""
    from database import DatabaseManager

    db = DatabaseManager(db_path=config.db_path)
    queue = db.get_queue_stats()
    products = db.get_product_stats()

    print("\n" + "=" * 40)
    print("📊 СТАТИСТИКА ОЧЕРЕДИ")
    print("=" * 40)
    for k, v in queue.items():
        print(f"  {k:15s}: {v}")

    print("\n" + "=" * 40)
    print("📦 СТАТИСТИКА ТОВАРОВ")
    print("=" * 40)
    for k, v in products.items():
        if v is not None:
            val = round(float(v), 3) if "." in str(v) else v
            print(f"  {k:15s}: {val}")

    total_done = queue.get("done", 0) + queue.get("not_found", 0)
    remaining = queue.get("pending", 0) + queue.get("retry", 0)
    print(f"\n  ✅ Готово: {total_done} | ⏳ Осталось: {remaining}")
    print("=" * 40)


def cmd_export(args):
    """Команда export."""
    from database import DatabaseManager

    db = DatabaseManager(db_path=config.db_path)
    count = db.export_to_json(args.output)
    logger.info("📦 Экспортировано %d товаров в %s", count, args.output)


def cmd_proxy_scrape(args):
    """Команда proxy-scrape — поиск бесплатных прокси."""
    import asyncio
    from proxy_scraper import ProxyScraper

    async def _run():
        async with ProxyScraper() as scraper:
            return await scraper.scrape_and_save(args.output)

    count = asyncio.run(_run())
    print(f"\n✅ Найдено {count} прокси → {args.output}")


def cmd_proxy_check(args):
    """Команда proxy-check — проверка прокси."""
    from proxy_checker import ProxyChecker

    checker = ProxyChecker()
    alive = checker.check_and_save(args.input, args.output, args.workers)
    print(f"\n✅ Рабочих прокси: {len(alive)} → {args.output}")


def cmd_pipeline(args):
    """Полный пайплайн: scrape → check → как только 10 живых → parse → в фоне допроверка."""
    import threading
    from proxy_manager import ProxyManager

    print("\n" + "=" * 50)
    print("🔄 ПАЙПЛАЙН: scrape → check → parse (от 10 живых)")
    print("=" * 50)

    urls = load_urls(args.urls)
    if not urls:
        logger.warning("⚠️ Нет URL для парсинга")
        return

    if args.workers:
        config.max_workers = args.workers

    orchestrator = ParserOrchestrator()
    parse_thread = None
    parse_started = threading.Event()

    def on_proxies_ready(alive_proxies):
        """Callback: когда набралось min_alive прокси."""
        nonlocal parse_thread
        print(f"\n🚀 Набрано {len(alive_proxies)} живых прокси — запускаю парсинг!")
        orchestrator.update_proxies(alive_proxies)
        config.use_proxy_rotation = True

        parse_thread = threading.Thread(
            target=orchestrator.run,
            kwargs={"urls": urls},
            daemon=True,
        )
        parse_thread.start()
        parse_started.set()

    # Запуск ProxyManager
    manager = ProxyManager(
        min_alive=args.min_alive,
        check_workers=args.proxy_workers,
        proxy_file=args.proxy_file,
        checked_file=args.proxy_checked,
    )

    # Run в отдельном потоке чтобы не блокировать main
    def _run_manager():
        manager.run(on_ready=on_proxies_ready)
        if parse_started.is_set():
            print("\n✅ Все прокси проверены, парсинг продолжается...")

    manager_thread = threading.Thread(target=_run_manager, daemon=True)
    manager_thread.start()

    # Ждём пока парсинг завершится
    manager_thread.join()
    if parse_thread:
        parse_thread.join()


def main():
    parser = argparse.ArgumentParser(
        description="Ozon Parser v2 — Парсер карточек товаров",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    # parse
    p_parse = subparsers.add_parser("parse", help="Запустить парсинг")
    p_parse.add_argument("--urls", required=True, help="Файл с URL")
    p_parse.add_argument("--workers", type=int, help="Кол-во воркеров")
    p_parse.add_argument("--enqueue-only", action="store_true", help="Только добавить в очередь")

    # enqueue
    p_enqueue = subparsers.add_parser("enqueue", help="Добавить URL в очередь")
    p_enqueue.add_argument("--urls", required=True, help="Файл с URL")
    p_enqueue.add_argument("--priority", type=int, default=5, help="Приоритет 1-10")

    # stats
    subparsers.add_parser("stats", help="Статистика")

    # export
    p_export = subparsers.add_parser("export", help="Экспорт в JSON")
    p_export.add_argument("--output", default="products.json", help="Файл вывода")

    # proxy-scrape
    p_scrape = subparsers.add_parser("proxy-scrape", help="Найти бесплатные прокси")
    p_scrape.add_argument("--output", default="proxies.txt", help="Файл для сохранения")

    # proxy-check
    p_check = subparsers.add_parser("proxy-check", help="Проверить прокси")
    p_check.add_argument("--input", default="proxies.txt", help="Файл с прокси")
    p_check.add_argument("--output", default="proxies_checked.txt", help="Файл рабочих прокси")
    p_check.add_argument("--workers", type=int, default=20, help="Кол-во воркеров")

    # pipeline (scrape → check → parse)
    p_pipeline = subparsers.add_parser("pipeline", help="Scrape → Check → Parse (от 10 живых)")
    p_pipeline.add_argument("--urls", required=True, help="Файл с URL товаров")
    p_pipeline.add_argument("--proxy-file", default="proxies.txt", help="Файл для сырых прокси")
    p_pipeline.add_argument("--proxy-checked", default="proxies_checked.txt", help="Файл рабочих прокси")
    p_pipeline.add_argument("--proxy-workers", type=int, default=20, help="Воркеров для проверки прокси")
    p_pipeline.add_argument("--workers", type=int, help="Воркеров для парсинга")
    p_pipeline.add_argument("--min-alive", type=int, default=10, help="Мин. живых прокси для старта")

    args = parser.parse_args()

    if args.command == "parse":
        if args.workers:
            config.max_workers = args.workers
        cmd_parse(args)
    elif args.command == "enqueue":
        cmd_enqueue(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "export":
        cmd_export(args)
    elif args.command == "proxy-scrape":
        cmd_proxy_scrape(args)
    elif args.command == "proxy-check":
        cmd_proxy_check(args)
    elif args.command == "pipeline":
        cmd_pipeline(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
