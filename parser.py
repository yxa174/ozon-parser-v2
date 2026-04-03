"""
Ozon Parser v2 — Улучшенный парсер с антиблоком и API
"""
import asyncio
import hashlib
import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import httpx

from config import config
from models import ProductCard

logger = logging.getLogger(__name__)


# ─── Ротация User-Agent ─────────────────────────────────────────────────────

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]

PLATFORMS = [
    "Win32", "Win64", "MacIntel", "Linux x86_64"
]

ACCEPT_LANGUAGES = [
    "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "ru-RU,ru;q=0.8,en-US;q=0.6,en;q=0.5",
    "ru,en-US;q=0.9,en;q=0.8",
]


# ─── Утилиты антиблока ──────────────────────────────────────────────────────

def generate_fingerprint() -> dict:
    """Генерирует случайный фингерпринт браузера."""
    ua = random.choice(USER_AGENTS)

    if "Chrome" in ua and "Edg" not in ua:
        version_match = re.search(r"Chrome/(\d+)", ua)
        version = int(version_match.group(1)) if version_match else 120
        brand_version = str(version)
        brand_major = str(version - 1)
        sec_ch_ua = f'"Chromium";v="{brand_version}", "Google Chrome";v="{brand_version}", "Not-A.Brand";v="{brand_major}"'
    elif "Edg" in ua:
        version_match = re.search(r"Edg/(\d+)", ua)
        version = int(version_match.group(1)) if version_match else 124
        sec_ch_ua = f'"Chromium";v="{version}", "Microsoft Edge";v="{version}", "Not-A.Brand";v="{version - 1}"'
    elif "Firefox" in ua:
        sec_ch_ua = None
    else:
        sec_ch_ua = None

    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": random.choice(ACCEPT_LANGUAGES),
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Sec-Ch-Ua": sec_ch_ua,
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": f'"{random.choice(PLATFORMS)}"',
        "Cache-Control": "max-age=0",
        "DNT": "1",
    }

    if sec_ch_ua is None:
        headers.pop("Sec-Ch-Ua")
        headers.pop("Sec-Ch-Ua-Mobile")
        headers.pop("Sec-Ch-Ua-Platform")

    return headers


def smart_delay(success_count: int = 0, fail_count: int = 0) -> float:
    """Умная задержка: увеличивается при ошибках, уменьшается при успехе."""
    base_min = config.request_delay_min
    base_max = config.request_delay_max

    if fail_count > 0:
        delay = base_max * (1 + fail_count * 0.5)
        delay = min(delay, 30)
    elif success_count > 10:
        delay = base_min * 0.7
    else:
        delay = random.uniform(base_min, base_max)

    if config.enable_jitter:
        delay *= random.uniform(0.8, 1.2)

    return max(0.5, delay)


def load_proxies(proxy_file: str) -> List[str]:
    """Загрузить прокси из файла."""
    path = Path(proxy_file)
    if not path.exists():
        return []

    proxies = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            proxy = line.strip()
            if proxy and not proxy.startswith("#"):
                proxies.append(proxy)

    logger.info("🔄 Загружено %d прокси из %s", len(proxies), proxy_file)
    return proxies


class ProxyRotator:
    """Ротатор прокси с учётом ошибок."""

    def __init__(self, proxies: List[str]):
        self.proxies = proxies
        self.failures: Dict[str, int] = {p: 0 for p in proxies}
        self.idx = 0
        self.max_failures = 3

    def get(self) -> Optional[str]:
        if not self.proxies:
            return None

        available = [p for p in self.proxies if self.failures[p] < self.max_failures]
        if not available:
            self.failures = {p: 0 for p in self.proxies}
            available = self.proxies

        proxy = available[self.idx % len(available)]
        self.idx += 1
        return proxy

    def report_failure(self, proxy: str):
        if proxy in self.failures:
            self.failures[proxy] += 1
            logger.warning("⚠️ Прокси ошибка #%d: %s", self.failures[proxy], proxy[:50])

    def report_success(self, proxy: str):
        if proxy in self.failures:
            self.failures[proxy] = max(0, self.failures[proxy] - 1)


# ─── Извлечение product_id из URL ───────────────────────────────────────────

def extract_product_id(url: str) -> Optional[str]:
    """Извлечь ID товара из URL Ozon."""
    patterns = [
        r"/product/[^/]+-(\d+)/",
        r"/product/(\d+)/",
        r"[?&]sku=(\d+)",
        r"/(\d{7,12})(?:/|\?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


# ─── HTTP Parser с улучшенным антиблоком ────────────────────────────────────

class OzonHTTPParser:
    """
    HTTP-парсер с улучшенным антиблоком:
    - Ротация User-Agent + фингерпринтов
    - Ротация прокси
    - Умные задержки
    - Обход базовых проверок
    """

    def __init__(self, proxy: Optional[str] = None):
        self.proxy = proxy
        self._client: Optional[httpx.AsyncClient] = None
        self.success_count = 0
        self.fail_count = 0

    async def __aenter__(self):
        await self._create_client()
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    async def _create_client(self):
        """Создать HTTP клиент с настройками антиблока."""
        proxy_config = None
        if self.proxy:
            proxy_config = self.proxy

        self._client = httpx.AsyncClient(
            timeout=config.request_timeout,
            follow_redirects=True,
            http2=True,
            verify=True,
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20,
            ),
        )

        if proxy_config:
            self._client = httpx.AsyncClient(
                proxy=proxy_config,
                timeout=config.request_timeout,
                follow_redirects=True,
                http2=True,
                verify=True,
                limits=httpx.Limits(
                    max_connections=100,
                    max_keepalive_connections=20,
                ),
            )

    def _get_headers(self) -> dict:
        """Сгенерировать случайные заголовки."""
        return generate_fingerprint()

    async def fetch_page(self, url: str) -> tuple[str, int]:
        """Загрузить HTML страницы с повторными попытками."""
        for attempt in range(config.max_retries):
            try:
                headers = self._get_headers()
                headers["Referer"] = "https://www.ozon.ru/"

                response = await self._client.get(url, headers=headers)

                if response.status_code == 403:
                    self.fail_count += 1
                    if attempt < config.max_retries - 1:
                        wait = smart_delay(self.success_count, self.fail_count) * 2
                        logger.warning("🚫 403 Forbidden, ждём %.1fс (попытка %d)", wait, attempt + 1)
                        await asyncio.sleep(wait)
                        continue
                    return "", 403

                if response.status_code == 404:
                    return "", 404

                response.raise_for_status()
                self.success_count += 1
                self.fail_count = 0
                return response.text, response.status_code

            except httpx.TimeoutException:
                self.fail_count += 1
                logger.warning("⏱ Таймаут (попытка %d)", attempt + 1)
                await asyncio.sleep(smart_delay(0, self.fail_count + 1))

            except httpx.ConnectError:
                self.fail_count += 1
                logger.warning("🔌 Ошибка соединения (попытка %d)", attempt + 1)
                await asyncio.sleep(smart_delay(0, self.fail_count + 1))

            except Exception as e:
                self.fail_count += 1
                logger.warning("❌ Ошибка: %s (попытка %d)", e, attempt + 1)
                if attempt < config.max_retries - 1:
                    await asyncio.sleep(smart_delay(0, self.fail_count + 1))

        return "", 0

    def _extract_data_from_html(self, html: str, url: str) -> ProductCard:
        """Извлечь данные товара из HTML с улучшенными паттернами."""
        card = ProductCard(url=url, parse_method="http")
        card.product_id = extract_product_id(url)

        # 1. JSON-LD (structured data)
        card = self._extract_json_ld(html, card)

        # 2. Встроенные JSON-данные Ozon
        card = self._extract_embedded_json(html, card)

        # 3. Fallback: regex-паттерны
        card = self._extract_regex_fallback(html, card)

        # 4. Рассчитать скидку если есть цены
        if card.price and card.price_original and card.price_original > card.price:
            card.discount_percent = int((1 - card.price / card.price_original) * 100)

        card.parse_status = "success" if card.title else "partial"
        return card

    def _extract_json_ld(self, html: str, card: ProductCard) -> ProductCard:
        """Извлечь JSON-LD данные."""
        pattern = r'<script type="application/ld\+json">(.*?)</script>'
        match = re.search(pattern, html, re.DOTALL)
        if not match:
            return card

        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return card

        card.title = card.title or data.get("name")
        card.description = card.description or data.get("description")
        card.short_description = card.description[:200] + "..." if card.description and len(card.description) > 200 else card.description

        brand = data.get("brand")
        if isinstance(brand, dict):
            card.brand = card.brand or brand.get("name")
        elif isinstance(brand, str):
            card.brand = card.brand or brand

        offers = data.get("offers", {})
        if offers:
            try:
                price_str = str(offers.get("price", "")).replace(",", ".").replace(" ", "")
                if price_str:
                    card.price = card.price or float(price_str)
            except (ValueError, TypeError):
                pass

            card.in_stock = offers.get("availability", "").lower() in [
                "https://schema.org/instock", "instock", "in_stock"
            ]

        rating = data.get("aggregateRating", {})
        if rating:
            try:
                card.rating = card.rating or float(rating.get("ratingValue", 0))
                card.reviews_count = card.reviews_count or int(rating.get("reviewCount", 0))
            except (ValueError, TypeError):
                pass

        images = data.get("image", [])
        if isinstance(images, str):
            card.images = [images] if not card.images else card.images
        elif isinstance(images, list):
            card.images = card.images or images

        card.raw_json = data
        return card

    def _extract_embedded_json(self, html: str, card: ProductCard) -> ProductCard:
        """Извлечь данные из встроенных JSON-объектов Ozon."""
        # Пытаем найти __NUXT_DATA__ или window.__INITIAL_STATE__
        patterns = [
            (r'window\.__INITIAL_STATE__\s*=\s*({.*?});\s*</script>', "initial_state"),
            (r'window\.__NUXT__\s*=\s*({.*?});\s*</script>', "nuxt"),
            (r'"state":\s*({.*?})\s*}\s*</script>', "state"),
        ]

        for pattern, name in patterns:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    card = self._parse_state_json(data, card)
                    break
                except (json.JSONDecodeError, TypeError):
                    continue

        # Ищем специфичные поля Ozon
        if not card.price:
            price_patterns = [
                r'"finalPrice":\s*(\d+(?:\.\d+)?)',
                r'"price":\s*"?(\d+(?:\.\d+)?)"?',
                r'"mainState":\[{.*?"price":\s*"?(\d+(?:\.\d+)?)',
                r'"priceWithDiscount":\s*"?(\d+(?:\.\d+)?)',
            ]
            for pp in price_patterns:
                m = re.search(pp, html)
                if m:
                    try:
                        card.price = float(m.group(1))
                        break
                    except ValueError:
                        pass

        if not card.price_original:
            m = re.search(r'"originalPrice":\s*"?(\d+(?:\.\d+)?)', html)
            if m:
                try:
                    card.price_original = float(m.group(1))
                except ValueError:
                    pass

        if not card.seller_name:
            m = re.search(r'"sellerName":\s*"([^"]+)"', html)
            if m:
                card.seller_name = m.group(1)

        if not card.seller_id:
            m = re.search(r'"sellerId":\s*"?(\d+)"?', html)
            if m:
                card.seller_id = m.group(1)

        # SKU
        if not card.sku_id:
            m = re.search(r'"skuId":\s*"?(\d+)"?', html)
            if m:
                card.sku_id = m.group(1)

        # Наличие
        if "нет в наличии" in html.lower() or "out of stock" in html.lower():
            card.in_stock = False

        # Рейтинг из атрибутов
        if not card.rating:
            m = re.search(r'"rating":\s*"?(\d+(?:\.\d+)?)', html)
            if m:
                try:
                    card.rating = float(m.group(1))
                except ValueError:
                    pass

        if not card.reviews_count:
            m = re.search(r'"reviewsCount":\s*"?(\d+)"?', html)
            if m:
                try:
                    card.reviews_count = int(m.group(1))
                except ValueError:
                    pass

        return card

    def _parse_state_json(self, data: dict, card: ProductCard) -> ProductCard:
        """Парсинг JSON состояния Ozon."""
        def deep_search(obj: Any, keys: List[str], max_depth: int = 5) -> dict:
            """Рекурсивный поиск ключей в JSON."""
            results = {}
            if max_depth <= 0 or not isinstance(obj, (dict, list)):
                return results

            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key in keys and value:
                        results[key] = value
                    if isinstance(value, (dict, list)):
                        results.update(deep_search(value, keys, max_depth - 1))
            elif isinstance(obj, list):
                for item in obj:
                    results.update(deep_search(item, keys, max_depth - 1))

            return results

        search_keys = [
            "title", "name", "brand", "price", "originalPrice",
            "rating", "reviewsCount", "sellerName", "sellerId",
            "description", "category", "images", "skuId",
        ]

        found = deep_search(data, search_keys)

        card.title = card.title or found.get("title") or found.get("name")
        card.brand = card.brand or found.get("brand")
        card.seller_name = card.seller_name or found.get("sellerName")
        card.seller_id = card.seller_id or str(found.get("sellerId", ""))
        card.sku_id = card.sku_id or str(found.get("skuId", ""))
        card.description = card.description or found.get("description")
        card.category = card.category or found.get("category")

        if "price" in found:
            try:
                card.price = card.price or float(str(found["price"]).replace(",", "."))
            except (ValueError, TypeError):
                pass

        if "originalPrice" in found:
            try:
                card.price_original = card.price_original or float(str(found["originalPrice"]).replace(",", "."))
            except (ValueError, TypeError):
                pass

        if "rating" in found:
            try:
                card.rating = card.rating or float(found["rating"])
            except (ValueError, TypeError):
                pass

        if "reviewsCount" in found:
            try:
                card.reviews_count = card.reviews_count or int(found["reviewsCount"])
            except (ValueError, TypeError):
                pass

        if "images" in found:
            imgs = found["images"]
            if isinstance(imgs, list):
                card.images = card.images or imgs
            elif isinstance(imgs, str):
                card.images = card.images or [imgs]

        return card

    def _extract_regex_fallback(self, html: str, card: ProductCard) -> ProductCard:
        """Извлечение данных через regex как fallback."""
        if not card.title:
            m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL)
            if m:
                card.title = re.sub(r'<[^>]+>', "", m.group(1)).strip()

        if not card.brand:
            m = re.search(r'data-brand="([^"]+)"', html)
            if m:
                card.brand = m.group(1)

        if not card.category:
            m = re.search(r'data-category="([^"]+)"', html)
            if m:
                card.category = m.group(1)

        if not card.images:
            img_matches = re.findall(r'data-src="([^"]*ozon\.ru/[^"]*\.(?:jpg|jpeg|png|webp)[^"]*)"', html)
            if img_matches:
                card.images = list(dict.fromkeys(img_matches))[:10]

        return card

    async def parse_url(self, url: str) -> ProductCard:
        """Парсинг одного URL товара."""
        start_time = time.time()

        try:
            html, status = await self.fetch_page(url)

            if status == 404:
                return ProductCard(
                    url=url,
                    parse_status="not_found",
                    error_message="Товар не найден (404)",
                    parse_time=time.time() - start_time,
                    parse_method="http",
                )

            if status == 403:
                return ProductCard(
                    url=url,
                    parse_status="blocked",
                    error_message="Доступ заблокирован (403) — возможно CAPTCHA",
                    parse_time=time.time() - start_time,
                    parse_method="http",
                )

            if not html:
                return ProductCard(
                    url=url,
                    parse_status="error",
                    error_message=f"Пустой ответ (статус: {status})",
                    parse_time=time.time() - start_time,
                    parse_method="http",
                )

            card = self._extract_data_from_html(html, url)
            card.parse_time = time.time() - start_time
            return card

        except Exception as e:
            logger.exception("❌ Ошибка парсинга %s: %s", url, e)
            return ProductCard(
                url=url,
                parse_status="error",
                error_message=str(e),
                parse_time=time.time() - start_time,
                parse_method="http",
            )


# ─── Ozon Seller API Parser ─────────────────────────────────────────────────

class OzonAPIParser:
    """
    Парсер через официальный Ozon Seller API.
    Требует API-ключ и Client-ID.
    """

    BASE_URL = "https://api-seller.ozon.ru"

    def __init__(self):
        self.api_key = config.ozon_api_key
        self.client_id = config.ozon_client_id
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.client_id)

    def _headers(self) -> dict:
        return {
            "Client-Id": self.client_id or "",
            "Api-Key": self.api_key or "",
            "Content-Type": "application/json",
        }

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=30,
            headers=self._headers(),
        )
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    async def get_product_info(self, product_id: str) -> Optional[dict]:
        """Получить информацию о товаре через API."""
        if not self.is_configured or not self._client:
            return None

        try:
            response = await self._client.post(
                "/v3/product/info",
                json={"product_id": int(product_id)},
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning("⚠️ Ozon API ошибка: %s", e)
            return None

    async def get_product_by_sku(self, sku: str) -> Optional[dict]:
        """Получить информацию о товаре по SKU."""
        if not self.is_configured or not self._client:
            return None

        try:
            response = await self._client.post(
                "/v2/product/info",
                json={"sku": int(sku)},
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning("⚠️ Ozon API ошибка: %s", e)
            return None

    async def get_stock_info(self, product_id: str) -> Optional[dict]:
        """Получить информацию об остатках."""
        if not self.is_configured or not self._client:
            return None

        try:
            response = await self._client.post(
                "/v2/product/info/stocks",
                json={"product_id": [int(product_id)]},
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning("⚠️ Ozon API ошибка: %s", e)
            return None

    def api_to_card(self, api_data: dict, url: str) -> ProductCard:
        """Конвертировать данные API в ProductCard."""
        result = api_data.get("result", {})

        card = ProductCard(
            url=url,
            product_id=str(result.get("id", "")),
            sku_id=str(result.get("sku", "")),
            title=result.get("name"),
            brand=result.get("brand"),
            parse_method="api",
        )

        # Цена
        price_info = result.get("price", {})
        try:
            card.price = float(price_info.get("price", 0))
        except (ValueError, TypeError):
            pass

        try:
            card.price_original = float(price_info.get("old_price", 0))
        except (ValueError, TypeError):
            pass

        # Скидка
        try:
            card.discount_percent = int(result.get("discount", {}).get("percent", 0))
        except (ValueError, TypeError):
            pass

        # Рейтинг и отзывы
        try:
            card.rating = float(result.get("rating", 0))
        except (ValueError, TypeError):
            pass

        card.reviews_count = result.get("reviews_count", 0)

        # Продавец
        seller = result.get("seller", {})
        card.seller_name = seller.get("name")
        card.seller_id = str(seller.get("seller_id", ""))

        # Категория
        card.category = result.get("category_name")

        # Изображения
        images = result.get("images", [])
        card.images = [f"https://cdn1.ozone.ru/s3/multimedia-{img}" for img in images] if images else []

        # Наличие
        card.in_stock = result.get("is_available", False)

        # Остатки
        stocks = result.get("stocks", [])
        card.stock_quantity = sum(s.get("amount", 0) for s in stocks) if stocks else None

        # Описание
        card.description = result.get("description")

        # Атрибуты
        attributes = result.get("attributes", [])
        card.attributes = {a.get("name"): a.get("value") for a in attributes if a.get("name")}

        card.parse_status = "success" if card.title else "partial"
        card.raw_json = api_data

        return card


# ─── Комбинированный парсер ─────────────────────────────────────────────────

class OzonParser:
    """
    Комбинированный парсер: API -> HTTP -> Browser fallback.
    """

    def __init__(self, proxy: Optional[str] = None):
        self.proxy = proxy

    async def parse_url(self, url: str) -> ProductCard:
        """Парсинг URL с каскадным fallback."""
        product_id = extract_product_id(url)

        # 1. Пробуем Ozon API
        if config.ozon_api_enabled:
            async with OzonAPIParser() as api:
                if api.is_configured and product_id:
                    api_data = await api.get_product_info(product_id)
                    if api_data:
                        card = api.api_to_card(api_data, url)
                        logger.info("✅ API парсинг: %s", card.title or "без названия")
                        return card

        # 2. HTTP парсер
        async with OzonHTTPParser(proxy=self.proxy) as http_parser:
            card = await http_parser.parse_url(url)

            if card.parse_status == "success":
                logger.info("✅ HTTP парсинг: %s", card.title or "без названия")
                return card

            # 3. Browser fallback
            if card.parse_status in ("blocked", "partial") and config.use_browser_fallback:
                logger.info("🔄 Fallback на браузер для %s", url[:60])
                card = await self._browser_parse(url)

        return card

    async def _browser_parse(self, url: str) -> ProductCard:
        """Браузерный парсинг через Playwright."""
        start_time = time.time()

        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                launch_args = {
                    "headless": True,
                    "args": [
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-infobars",
                        "--window-size=1366,768",
                    ],
                }

                if self.proxy:
                    launch_args["proxy"] = {"server": self.proxy}

                browser = await p.chromium.launch(**launch_args)
                context = await browser.new_context(
                    user_agent=random.choice(USER_AGENTS),
                    viewport={"width": 1366, "height": 768},
                    locale="ru-RU",
                    timezone_id="Europe/Moscow",
                )

                page = await context.new_page()

                # Блокировка лишних ресурсов для скорости
                await page.route("**/*.{png,jpg,jpeg,gif,svg,mp4,webp,woff,woff2}", lambda r: r.abort())
                await page.route("**/analytics/**", lambda r: r.abort())
                await page.route("**/metrika/**", lambda r: r.abort())
                await page.route("**/ads/**", lambda r: r.abort())

                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(random.randint(1500, 3000))

                # JSON-LD
                ld_json = await page.evaluate("""
                    () => {
                        const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                        for (const s of scripts) {
                            try { return JSON.parse(s.textContent); } catch(e) {}
                        }
                        return null;
                    }
                """)

                card = ProductCard(url=url, parse_method="browser")
                card.product_id = extract_product_id(url)

                if ld_json:
                    card.title = ld_json.get("name")
                    card.description = ld_json.get("description")
                    brand = ld_json.get("brand")
                    card.brand = brand.get("name") if isinstance(brand, dict) else brand

                    offers = ld_json.get("offers", {})
                    if offers:
                        try:
                            card.price = float(str(offers.get("price", 0)).replace(",", "."))
                        except (ValueError, TypeError):
                            pass

                    rating = ld_json.get("aggregateRating", {})
                    if rating:
                        try:
                            card.rating = float(rating.get("ratingValue", 0))
                            card.reviews_count = int(rating.get("reviewCount", 0))
                        except (ValueError, TypeError):
                            pass

                if not card.title:
                    try:
                        card.title = await page.text_content("h1", timeout=2000)
                    except Exception:
                        pass

                card.parse_status = "success" if card.title else "partial"
                card.parse_time = time.time() - start_time

                await browser.close()
                return card

        except Exception as e:
            logger.error("❌ Browser ошибка для %s: %s", url[:60], e)
            return ProductCard(
                url=url,
                parse_status="error",
                error_message=f"Browser: {e}",
                parse_time=time.time() - start_time,
                parse_method="browser",
            )
