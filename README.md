# Ozon Parser v2

Парсер карточек товаров Ozon с улучшенным антиблоком и поддержкой официального API.

## Возможности

- **Улучшенный антиблок**: ротация User-Agent, фингерпринтов, прокси, умные задержки
- **Ozon Seller API**: поддержка официального API для получения данных о товарах
- **Каскадный парсинг**: API → HTTP → Browser (Playwright) fallback
- **SQLite**: простая база данных без Docker и PostgreSQL
- **Экспорт в JSON**: выгрузка всех распарсенных товаров

## Установка

```bash
pip install -r requirements.txt
```

Для браузерного fallback:
```bash
playwright install chromium
```

## Настройка

```bash
cp .env.example .env
# Отредактируйте .env под свои нужды
```

## Использование

```bash
# Запустить парсинг
python main.py parse --urls urls.txt

# С указанием кол-ва воркеров
python main.py parse --urls urls.txt --workers 3

# Только добавить URL в очередь
python main.py enqueue --urls urls.txt --priority 5

# Статистика
python main.py stats

# Экспорт в JSON
python main.py export --output products.json
```

## Структура

| Файл | Описание |
|---|---|
| `config.py` | Настройки из .env |
| `models.py` | Модели данных (ProductCard, ParseStats) |
| `database.py` | SQLite менеджер |
| `parser.py` | Парсеры (HTTP, API, Browser) |
| `orchestrator.py` | Управление воркерами |
| `main.py` | CLI |
