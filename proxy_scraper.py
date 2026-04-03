"""
Proxy Scraper — поиск бесплатных прокси из публичных источников
"""
import asyncio
import logging
import re
import time
from typing import List, Set

import httpx

logger = logging.getLogger(__name__)


PROXY_SOURCES = [
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=https&timeout=10000&country=all&ssl=all&anonymity=all",
    "https://raw.githubusercontent.com/TheSpeedX/SOCKS-Proxy-List/master/http.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/https.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-http.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-https.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTP_RAW.txt",
    "https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/http.txt",
    "https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/https.txt",
    "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
    "https://raw.githubusercontent.com/opsxcq/proxy-list/master/list.txt",
    "https://raw.githubusercontent.com/saschazesiger/Free-Proxies/master/proxies/http.txt",
    "https://raw.githubusercontent.com/saschazesiger/Free-Proxies/master/proxies/https.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies_anonymous/http.txt",
]


class ProxyScraper:
    """Скрапер бесплатных прокси."""

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
        )
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    def _parse_proxies(self, text: str) -> Set[str]:
        """Извлечь прокси из текста."""
        pattern = r"\b(?:\d{1,3}\.){3}\d{1,3}:\d{2,5}\b"
        return set(re.findall(pattern, text))

    async def _fetch_source(self, url: str) -> Set[str]:
        """Загрузить прокси из одного источника."""
        if not self._client:
            return set()

        try:
            response = await self._client.get(url)
            if response.status_code == 200:
                proxies = self._parse_proxies(response.text)
                logger.info("  ✅ %s → %d прокси", url.split("/")[-1][:40], len(proxies))
                return proxies
            else:
                logger.warning("  ❌ %s → статус %d", url.split("/")[-1][:40], response.status_code)
        except httpx.TimeoutException:
            logger.warning("  ⏱ Таймаут: %s", url.split("/")[-1][:40])
        except Exception as e:
            logger.warning("  ❌ Ошибка %s: %s", url.split("/")[-1][:40], e)

        return set()

    async def scrape(self) -> List[str]:
        """Собрать прокси из всех источников."""
        start = time.time()
        all_proxies: Set[str] = set()

        logger.info("🔍 Сканирование %d источников прокси...", len(PROXY_SOURCES))

        tasks = [self._fetch_source(url) for url in PROXY_SOURCES]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, set):
                all_proxies.update(result)

        elapsed = time.time() - start
        logger.info(
            "📊 Найдено %d уникальных прокси за %.1fс",
            len(all_proxies),
            elapsed,
        )

        return sorted(all_proxies)

    async def scrape_and_save(self, filepath: str = "proxies.txt") -> int:
        """Собрать и сохранить прокси в файл."""
        proxies = await self.scrape()

        if proxies:
            with open(filepath, "w", encoding="utf-8") as f:
                for proxy in proxies:
                    f.write(proxy + "\n")
            logger.info("💾 Сохранено %d прокси в %s", len(proxies), filepath)
        else:
            logger.warning("⚠️ Прокси не найдены")

        return len(proxies)


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    async with ProxyScraper() as scraper:
        count = await scraper.scrape_and_save("proxies.txt")
        print(f"\n✅ Готово: {count} прокси сохранено в proxies.txt")


if __name__ == "__main__":
    asyncio.run(main())
