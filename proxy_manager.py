"""
Proxy Manager — поиск, проверка и живой пул прокси
Находит прокси → проверяет → как только 10 живых → запускает парсинг
В фоне продолжает проверять остальные и обновлять пул
"""
import asyncio
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, List, Optional, Set

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

CHECK_URL = "https://api.ipify.org?format=json"


class ProxyManager:
    """
    Управляет пулом прокси:
    1. Сканирует источники
    2. Проверяет прокси
    3. Как только min_alive собрано — вызывает callback
    4. В фоне продолжает проверять остальные
    """

    def __init__(
        self,
        min_alive: int = 10,
        check_workers: int = 20,
        check_timeout: int = 10,
        proxy_file: str = "proxies.txt",
        checked_file: str = "proxies_checked.txt",
    ):
        self.min_alive = min_alive
        self.check_workers = check_workers
        self.check_timeout = check_timeout
        self.proxy_file = proxy_file
        self.checked_file = checked_file

        self._all_proxies: Set[str] = set()
        self._alive_proxies: List[str] = []
        self._checked: Set[str] = set()
        self._lock = threading.Lock()
        self._ready_event = threading.Event()
        self._scrape_done = threading.Event()

    @property
    def alive_count(self) -> int:
        return len(self._alive_proxies)

    @property
    def ready(self) -> bool:
        return self._ready_event.is_set()

    def get_alive_proxies(self) -> List[str]:
        """Получить текущие живые прокси."""
        with self._lock:
            return list(self._alive_proxies)

    def wait_ready(self, timeout: float = 300) -> bool:
        """Ждать пока наберётся min_alive прокси."""
        return self._ready_event.wait(timeout=timeout)

    def _parse_proxies(self, text: str) -> Set[str]:
        pattern = r"\b(?:\d{1,3}\.){3}\d{1,3}:\d{2,5}\b"
        return set(re.findall(pattern, text))

    async def _fetch_source(self, url: str, client: httpx.AsyncClient) -> Set[str]:
        try:
            response = await client.get(url, timeout=self.check_timeout)
            if response.status_code == 200:
                proxies = self._parse_proxies(response.text)
                logger.info("  ✅ %s → %d прокси", url.split("/")[-1][:40], len(proxies))
                return proxies
        except Exception as e:
            logger.warning("  ❌ %s: %s", url.split("/")[-1][:40], e)
        return set()

    async def scrape_all(self) -> List[str]:
        """Собрать все прокси из источников."""
        async with httpx.AsyncClient(
            timeout=self.check_timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        ) as client:
            tasks = [self._fetch_source(url, client) for url in PROXY_SOURCES]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        all_proxies: Set[str] = set()
        for r in results:
            if isinstance(r, set):
                all_proxies.update(r)

        self._all_proxies = all_proxies
        logger.info("📊 Найдено %d уникальных прокси", len(all_proxies))
        return sorted(all_proxies)

    def _check_single(self, proxy: str) -> Optional[str]:
        """Проверить один прокси. Возвращает proxy если живой."""
        try:
            with httpx.Client(
                proxy=f"http://{proxy}",
                timeout=self.check_timeout,
                follow_redirects=True,
            ) as client:
                resp = client.get(CHECK_URL)
                if resp.status_code == 200:
                    return proxy
        except Exception:
            pass
        return None

    def _add_alive(self, proxy: str):
        """Добавить живой прокси в пул."""
        with self._lock:
            if proxy not in self._checked:
                self._checked.add(proxy)
                self._alive_proxies.append(proxy)

                count = len(self._alive_proxies)
                logger.info("  ✅ Живой прокси #%d: %s", count, proxy)

                if count >= self.min_alive and not self._ready_event.is_set():
                    self._ready_event.set()
                    logger.info("🎉 Набрано %d живых прокси — можно запускать парсинг!", count)

    def _check_batch(self, proxies: List[str]):
        """Проверить пакет прокси."""
        with ThreadPoolExecutor(max_workers=self.check_workers) as executor:
            futures = {executor.submit(self._check_single, p): p for p in proxies}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    self._add_alive(result)

    def _save_checked(self):
        """Сохранить проверенные прокси."""
        with open(self.checked_file, "w", encoding="utf-8") as f:
            for p in self._alive_proxies:
                f.write(p + "\n")

    def run(self, on_ready: Optional[Callable] = None):
        """
        Основной цикл:
        1. Сканирует источники
        2. Проверяет прокси пачками
        3. Как только min_alive — вызывает on_ready
        4. Продолжает проверять остальные
        """
        start = time.time()

        # Шаг 1: Сканирование
        logger.info("🔍 Сканирование %d источников...", len(PROXY_SOURCES))
        proxies = asyncio.run(self.scrape_all())

        if not proxies:
            logger.warning("⚠️ Прокси не найдены")
            return []

        # Загрузка уже проверенных (если есть)
        if Path(self.checked_file).exists():
            with open(self.checked_file, encoding="utf-8") as f:
                existing = [line.strip() for line in f if line.strip()]
            self._alive_proxies = existing
            self._checked = set(existing)
            logger.info("📂 Загружено %d ранее проверенных прокси", len(existing))

            if len(self._alive_proxies) >= self.min_alive:
                logger.info("✅ Достаточно проверенных прокси из файла")
                self._ready_event.set()
                if on_ready:
                    on_ready(self._alive_proxies)
                return self._alive_proxies

        # Шаг 2: Проверка пачками
        logger.info("🔍 Проверка прокси (нужно %d живых)...", self.min_alive)

        batch_size = max(self.check_workers * 2, 40)
        unchecked = [p for p in proxies if p not in self._checked]

        for i in range(0, len(unchecked), batch_size):
            batch = unchecked[i:i + batch_size]
            self._check_batch(batch)

            if self.ready and on_ready:
                on_ready(self.get_alive_proxies())
                on_ready = None

        self._scrape_done.set()
        self._save_checked()

        elapsed = time.time() - start
        logger.info(
            "✅ Проверка завершена: %d/%d живых за %.1fс",
            self.alive_count,
            len(proxies),
            elapsed,
        )

        return self.get_alive_proxies()

    def run_and_get(self) -> List[str]:
        """Просто запустить и вернуть живые прокси."""
        return self.run()
