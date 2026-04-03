"""
Конфигурация Ozon Parser v2
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Настройки парсера."""

    # База данных
    db_path: str = os.getenv("DB_PATH", "ozon_data.db")

    # Парсинг
    max_workers: int = int(os.getenv("MAX_WORKERS", "5"))
    request_delay_min: float = float(os.getenv("REQUEST_DELAY_MIN", "1.0"))
    request_delay_max: float = float(os.getenv("REQUEST_DELAY_MAX", "4.0"))
    request_timeout: int = int(os.getenv("REQUEST_TIMEOUT", "30"))
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))

    # Антиблок
    use_proxy_rotation: bool = os.getenv("USE_PROXY_ROTATION", "true").lower() == "true"
    proxy_file: str = os.getenv("PROXY_FILE", "proxies.txt")
    rotate_user_agent: bool = True
    randomize_fingerprint: bool = os.getenv("RANDOMIZE_FINGERPRINT", "true").lower() == "true"
    enable_jitter: bool = True

    # Ozon API
    ozon_api_enabled: bool = os.getenv("OZON_API_ENABLED", "false").lower() == "true"
    ozon_api_key: Optional[str] = os.getenv("OZON_API_KEY")
    ozon_client_id: Optional[str] = os.getenv("OZON_CLIENT_ID")

    # Браузер (fallback)
    use_browser_fallback: bool = os.getenv("USE_BROWSER", "false").lower() == "true"

    # Файлы
    urls_file: str = os.getenv("URLS_FILE", "urls.txt")
    export_dir: str = os.getenv("EXPORT_DIR", "exports")

    @classmethod
    def from_env(cls) -> "Config":
        return cls()


config = Config.from_env()
