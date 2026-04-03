"""
Proxy Checker — проверка прокси на работоспособность
"""
import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class ProxyResult:
    """Результат проверки прокси."""

    proxy: str
    is_alive: bool = False
    response_time: float = 0.0
    country: str = ""
    ip: str = ""
    error: str = ""


CHECK_URLS = [
    "https://api.ipify.org?format=json",
    "https://httpbin.org/ip",
    "https://api.myip.com",
]


class ProxyChecker:
    """Проверка списка прокси."""

    def __init__(
        self,
        timeout: int = 10,
        max_workers: int = 20,
        check_url: Optional[str] = None,
    ):
        self.timeout = timeout
        self.max_workers = max_workers
        self.check_url = check_url or CHECK_URLS[0]

    def _check_single(self, proxy: str) -> ProxyResult:
        """Проверить один прокси синхронно."""
        result = ProxyResult(proxy=proxy)
        start = time.time()

        try:
            with httpx.Client(
                proxy=f"http://{proxy}",
                timeout=self.timeout,
                follow_redirects=True,
            ) as client:
                response = client.get(self.check_url)
                response.raise_for_status()

                data = response.json()
                result.ip = data.get("ip", "") or data.get("origin", "") or data.get("ip", "")

                # Пробуем определить страну
                if "country" in data:
                    result.country = data["country"]
                elif "country" in str(data):
                    result.country = data.get("country", data.get("country_name", ""))

                result.response_time = time.time() - start
                result.is_alive = True

        except httpx.TimeoutException:
            result.error = "timeout"
        except httpx.ProxyError as e:
            result.error = f"proxy_error: {e}"
        except Exception as e:
            result.error = str(e)[:100]

        return result

    def check(self, proxies: List[str], show_progress: bool = True) -> List[ProxyResult]:
        """Проверить список прокси."""
        if not proxies:
            logger.warning("⚠️ Список прокси пуст")
            return []

        logger.info("🔍 Проверка %d прокси (%d воркеров)...", len(proxies), self.max_workers)
        start = time.time()

        results: List[ProxyResult] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self._check_single, p): p for p in proxies}

            for i, future in enumerate(as_completed(futures), 1):
                result = future.result()
                results.append(result)

                if show_progress and i % 10 == 0:
                    alive = sum(1 for r in results if r.is_alive)
                    logger.info("  ⏳ Проверено %d/%d → живых: %d", i, len(proxies), alive)

        elapsed = time.time() - start
        alive = [r for r in results if r.is_alive]

        logger.info(
            "✅ Готово: %d/%d живых за %.1fс",
            len(alive),
            len(proxies),
            elapsed,
        )

        return results

    def check_and_save(
        self,
        input_file: str = "proxies.txt",
        output_file: str = "proxies_checked.txt",
        max_workers: int = 20,
    ) -> List[str]:
        """Загрузить, проверить и сохранить рабочие прокси."""
        self.max_workers = max_workers

        # Загрузка
        with open(input_file, encoding="utf-8") as f:
            proxies = [line.strip() for line in f if line.strip() and not line.startswith("#")]

        logger.info("📂 Загружено %d прокси из %s", len(proxies), input_file)

        if not proxies:
            return []

        # Проверка
        results = self.check(proxies)

        # Сохранение рабочих
        alive = [r for r in results if r.is_alive]
        alive.sort(key=lambda r: r.response_time)

        with open(output_file, "w", encoding="utf-8") as f:
            for r in alive:
                f.write(r.proxy + "\n")

        logger.info("💾 Сохранено %d рабочих прокси в %s", len(alive), output_file)

        # Статистика
        if alive:
            times = [r.response_time for r in alive]
            logger.info(
                "📊 Среднее время: %.2fс | Мин: %.2fс | Макс: %.2fс",
                sum(times) / len(times),
                min(times),
                max(times),
            )

        return [r.proxy for r in alive]


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    import argparse

    parser = argparse.ArgumentParser(description="Проверка прокси")
    parser.add_argument("--input", default="proxies.txt", help="Файл с прокси")
    parser.add_argument("--output", default="proxies_checked.txt", help="Файл для рабочих прокси")
    parser.add_argument("--workers", type=int, default=20, help="Кол-во воркеров")
    args = parser.parse_args()

    checker = ProxyChecker()
    alive = checker.check_and_save(args.input, args.output, args.workers)

    print(f"\n✅ Рабочих прокси: {len(alive)}")
    if alive:
        print(f"📁 Сохранено в: {args.output}")


if __name__ == "__main__":
    main()
