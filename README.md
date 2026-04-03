# Ozon Parser v2

Парсер карточек товаров Ozon с поиском прокси, проверкой и улучшенным антиблоком.

## Возможности

- **Поиск прокси**: автоматический сбор бесплатных прокси из 15+ источников
- **Проверка прокси**: быстрая проверка на работоспособность и скорость
- **Полный пайплайн**: scrape → check → parse одной командой
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

### Прокси

```bash
# Найти бесплатные прокси
python main.py proxy-scrape

# Проверить прокси на работоспособность
python main.py proxy-check --input proxies.txt --output proxies_checked.txt

# Полный пайплайн: найти → проверить → парсить
python main.py pipeline --urls urls.txt
```

### Парсинг

```bash
# Запустить парсинг
python main.py parse --urls urls.txt

# С указанием кол-ва воркеров
python main.py parse --urls urls.txt --workers 3

# Только добавить URL в очередь
python main.py enqueue --urls urls.txt --priority 5
```

### Статистика и экспорт

```bash
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
| `proxy_scraper.py` | Поиск бесплатных прокси |
| `proxy_checker.py` | Проверка прокси |
| `orchestrator.py` | Управление воркерами |
| `main.py` | CLI |

## Команды CLI

| Команда | Описание |
|---|---|
| `proxy-scrape` | Найти бесплатные прокси из публичных источников |
| `proxy-check` | Проверить прокси на работоспособность |
| `pipeline` | Полный пайплайн: scrape → check → parse |
| `parse` | Запустить парсинг товаров |
| `enqueue` | Добавить URL в очередь |
| `stats` | Показать статистику |
| `export` | Экспорт товаров в JSON |
