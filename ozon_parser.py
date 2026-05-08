import undetected_chromedriver as uc
import json
import re
from datetime import datetime
from pathlib import Path
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

script = """
function extractNumber(text) {
    if (!text) return null;
    const match = text.match(/(\\d+)/);
    return match ? parseInt(match[1]) : null;
}

function getProductData() {
    const data = {};

    // Название товара
    const titleEl = document.querySelector('h1.pdp_j4b');
    data.title = titleEl ? titleEl.textContent.trim() : null;

    // Цвет (из блока pdp_l)
    const colorEl = document.querySelector('.pdp_l span:last-child');
    data.color = colorEl ? colorEl.textContent.trim() : null;

    // Артикул (из характеристик)
    const articleEl = document.querySelector('#section-characteristics .pdp_ja');
    data.article = articleEl ? articleEl.textContent.trim() : null;

    // Цена текущая
    const priceEl = document.querySelector('.pdp_bj.tsHeadline500Medium');
    data.price = priceEl ? priceEl.textContent.trim() : null;

    // Старая цена (зачёркнутая)
    const oldPriceEl = document.querySelector('.pdp_i9b.pdp_bj0');
    data.oldPrice = oldPriceEl ? oldPriceEl.textContent.trim() : null;

    // Цена с банками (Ozon Bank)
    const bankPriceEl = document.querySelector('.pdp_i1b.tsHeadline600Large');
    data.bankPrice = bankPriceEl ? bankPriceEl.textContent.trim() : null;

    // Рейтинг и отзывы
    const ratingBlock = document.querySelector('.ga5_3_16-a3.tsBodyControl500Medium');
    if (ratingBlock) {
        const text = ratingBlock.textContent.trim();
        const parts = text.split('•');
        if (parts[0]) {
            data.rating = parts[0].trim();
        }
        if (parts[1]) {
            const match = parts[1].match(/[\d\s]+/);
            data.reviewsCount = match ? match[0].trim().replace(/\s+/g, ' ') : null;
        }
    }

    // Бренд
    const brandEl = document.querySelector('[data-widget="webProductBrand"] a');
    data.brand = brandEl ? brandEl.textContent.trim() : null;

    // Описание
    const descEl = document.querySelector('.RA-a.RA-c5 .RA-h3');
    data.description = descEl ? descEl.textContent.trim() : null;

    // Количество в наличии
    const stockEl = document.querySelector('[data-widget="webStock"]');
    data.stock = stockEl ? stockEl.textContent.trim() : null;

    // Картинки (только карточки товара)
    const images = [];
    const excludePatterns = ['video-', 'cover', 'logo_ozon', 'pomoch', 'payments-cdn', 'banners', 'cms/', 'qr-code'];
    document.querySelectorAll('img').forEach(img => {
        if (img.src && img.src.includes('multimedia')) {
            const isExcluded = excludePatterns.some(p => img.src.includes(p));
            if (!isExcluded) {
                images.push(img.src);
            }
        }
    });
    data.images = [...new Set(images)];

    // Характеристики
    const props = {};
    document.querySelectorAll('#section-characteristics dl').forEach(dl => {
        const key = dl.querySelector('.pdp_i8a');
        const val = dl.querySelector('.pdp_ia8');
        if (key && val) {
            props[key.textContent.trim()] = val.textContent.trim();
        }
    });
    data.characteristics = Object.keys(props).length ? props : null;

    // Доставка
    const deliverySection = document.querySelector('.pdp_pa4');
    if (deliverySection) {
        const delivery = {};
        const cityEl = deliverySection.querySelector('button .tsCompact400Small');
        delivery.city = cityEl ? cityEl.textContent.trim() : null;
        const methods = [];
        deliverySection.querySelectorAll('.pdp_pa5').forEach(el => {
            const nameEl = el.querySelector('.tsCompact400Small');
            const dateEl = el.querySelector('.tsBody300XSmall');
            const priceEl = el.querySelector('.b5_6_4-a4');
            if (nameEl && nameEl.textContent.trim() !== delivery.city) {
                let price = null;
                if (priceEl) {
                    const priceText = priceEl.textContent.trim();
                    price = priceText === 'Без доплат' ? 0 : extractNumber(priceText);
                }
                let date = dateEl ? dateEl.textContent.trim() : null;
                if (date && date.startsWith('С ')) {
                    date = date.substring(2); // Убираем "С " в начале
                }
                methods.push({
                    name: nameEl.textContent.trim(),
                    date: date,
                    price: price
                });
            }
        });
        delivery.methods = methods;
        data.delivery = delivery;
    }

    // Распродажа / остатки
    const saleSection = document.querySelector('.q4b1_4_3-a[href*="rasprodazhi"]');
    if (saleSection) {
        const sale = {};
        sale.link = saleSection.href;
        const saleTitle = saleSection.querySelector('.tsBodyControl400Small');
        sale.title = saleTitle ? saleTitle.textContent.trim() : null;
        const saleCount = saleSection.querySelector('.wa8_2 .tsCompactControl300XSmall');
        sale.remaining = saleCount ? saleCount.textContent.trim() : null;
        data.sale = sale;
    }

    // Количество вопросов
    const questionsEl = document.querySelector('[data-widget="webQuestionCount"] .tsBodyControl500Medium');
    if (questionsEl) {
        const match = questionsEl.textContent.match(/(\d+)/);
        data.questions_count = match ? parseInt(match[1]) : null;
    }

    // Продавец (seller)
    const sellerEl = document.querySelector('[data-widget="webSeller"] a') ||
                     document.querySelector('.pdp_seller') ||
                     document.querySelector('a[href*="/seller/"]');
    if (sellerEl) {
        data.seller_name = sellerEl.textContent.trim();
        const sellerLink = sellerEl.href;
        const sellerIdMatch = sellerLink.match(/\/seller\/(\d+)/);
        data.seller_id = sellerIdMatch ? sellerIdMatch[1] : null;
    }

    // Хлебные крошки / категории
    const breadcrumbs = [];
    document.querySelectorAll('.pdpBreadcrumbs a, [data-widget="webBreadcrumbs"] a').forEach(a => {
        breadcrumbs.push(a.textContent.trim());
    });
    data.category = breadcrumbs.length ? breadcrumbs : null;

    // SKU варианты (если есть выбор цвета/размера)
    const variants = [];
    document.querySelectorAll('.pdp_variant, [data-widget="webVariantSelector"] button').forEach(btn => {
        variants.push(btn.textContent.trim());
    });
    data.sku_variants = variants.length ? variants : null;

    return data;
}
return getProductData();
"""


def extract_number(text):
    if text:
        return int(''.join(filter(str.isdigit, text.split('₽')[0].split(' ')[-1])))
    return None


def normalize_data(data, url):
    # Нормализация цен в числа
    if data.get('price'):
        data['price'] = extract_number(data['price'])
    if data.get('oldPrice'):
        data['oldPrice'] = extract_number(data['oldPrice'])
    if data.get('bankPrice'):
        data['bankPrice'] = extract_number(data['bankPrice'])

    # Артикул в число
    if data.get('article'):
        data['article'] = int(data['article']) if data['article'].isdigit() else data['article']

    # Количество отзывов в число (без пробелов)
    if data.get('reviewsCount'):
        data['reviewsCount'] = int(data['reviewsCount'].replace(' ', '').replace('\u00a0', ''))

    # Количество вопросов в число
    if data.get('questions_count'):
        data['questions_count'] = int(data['questions_count'])

    # Остатки в распродаже в число
    if data.get('sale') and data['sale'].get('remaining'):
        data['sale']['remaining'] = int(data['sale']['remaining'].replace(' ', ''))

    # Рейтинг в число
    if data.get('rating'):
        try:
            data['rating'] = float(data['rating'].replace(',', '.'))
        except:
            pass

    # Скидка в процентах
    if data.get('price') and data.get('oldPrice') and data['oldPrice'] > 0:
        data['discount_percent'] = round((1 - data['price'] / data['oldPrice']) * 100)

    # Валюта
    data['currency'] = 'RUB'

    # URL
    data['url'] = url

    # Главная картинка
    if data.get('images') and len(data['images']) > 0:
        data['main_image'] = data['images'][0]

    # Время парсинга
    data['parsed_at'] = datetime.now().isoformat()

    # delivery_days — вычисляем из даты первой доставки
    if data.get('delivery') and data['delivery'].get('methods'):
        first_method = data['delivery']['methods'][0]
        date_text = first_method.get('date', '')

        # Парсим дату "С 30 мая", "Завтра, 9 мая", etc.
        months = {'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4, 'мая': 5, 'июня': 6,
                  'июля': 7, 'августа': 8, 'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12}
        today = datetime.now()

        if 'Завтра' in date_text:
            data['delivery_days'] = 1
        elif 'С' in date_text:
            # "С 30 мая"
            match = re.search(r'(\d+)\s+(\w+)', date_text)
            if match:
                day, month_name = int(match.group(1)), months.get(match.group(2).lower(), today.month)
                year = today.year if month_name >= today.month else today.year + 1
                target_date = datetime(year, month_name, day)
                data['delivery_days'] = max(1, (target_date - today).days)
        else:
            match = re.search(r'(\d+)', date_text)
            if match:
                data['delivery_days'] = int(match.group(1))

    # Убираем article и color из characteristics (уже есть на верхнем уровне)
    if data.get('characteristics'):
        for key in ['Артикул', 'Цвет']:
            if key in data['characteristics']:
                del data['characteristics'][key]
        if not data['characteristics']:
            data['characteristics'] = None

    # Оставляем только лучшее качество картинок (300 > 250 > 100)
    if data.get('images'):
        best_images = {}
        for img in data['images']:
            if '/wc300/' in img:
                key = img.split('/wc300/')[0].split('/')[-1]
                if key not in best_images or '/wc250/' in best_images.get(key, '') or '/wc100/' in best_images.get(key, ''):
                    best_images[key] = img
            elif '/wc250/' in img:
                key = img.split('/wc250/')[0].split('/')[-1]
                if key not in best_images:
                    best_images[key] = img
            elif '/wc100/' in img:
                key = img.split('/wc100/')[0].split('/')[-1]
                if key not in best_images:
                    best_images[key] = img
        data['images'] = list(best_images.values())

    # Порядок полей
    ordered_fields = ['url', 'title', 'price', 'oldPrice', 'discount_percent', 'bankPrice', 'currency',
                     'article', 'brand', 'seller_name', 'seller_id', 'color', 'category', 'rating',
                     'reviewsCount', 'questions_count', 'stock', 'sku_variants', 'description',
                     'characteristics', 'main_image', 'images', 'delivery', 'delivery_days', 'sale', 'parsed_at']
    ordered_data = {}
    for key in ordered_fields:
        if key in data:
            ordered_data[key] = data[key]
    return ordered_data


# Запуск
options = uc.ChromeOptions()
options.add_argument("--disable-gpu")
driver = uc.Chrome(options=options)

urls_file = Path(__file__).parent / 'urls.txt'
urls = [line.strip() for line in urls_file.read_text(encoding='utf-8').splitlines() if line.strip()]

results = []

for i, url in enumerate(urls, 1):
    print(f"\n[{i}/{len(urls)}] Парсинг: {url[:80]}...")
    driver.get(url)

    # Ждём загрузки основного контента (цена или название)
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '.pdp_bj.tsHeadline500Medium, h1.pdp_j4b'))
        )
        print("  ✅ Страница загружена")
    except:
        print("  ⚠️ Не дождался, пробуем парсить...")

    import time
    time.sleep(2)  # Дополнительная пауза для JS

    raw_data = driver.execute_script(script)
    data = normalize_data(raw_data, url)
    results.append(data)

    print(f"  ✅ Собрано полей: {len(data)}")

# Обработка всех результатов
for result in results:
    # Рейтинг в число
    if result.get('rating') and result['rating'] is not None:
        try:
            result['rating'] = float(str(result['rating']).replace(',', '.'))
        except:
            result['rating'] = None
    else:
        result['rating'] = None

    # delivery_days — вычисляем из даты первой доставки
    if result.get('delivery') and result['delivery'].get('methods') and len(result['delivery']['methods']) > 0:
        first_method = result['delivery']['methods'][0]
        date_text = first_method.get('date', '') or ''

        months = {'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4, 'мая': 5, 'июня': 6,
                  'июля': 7, 'августа': 8, 'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12}
        today = datetime.now()

        result['delivery_days'] = None
        if 'Завтра' in date_text:
            result['delivery_days'] = 1
        elif 'С' in date_text or any(m in date_text for m in months):
            match = re.search(r'(\d+)\s*([а-яё]+)', date_text, re.IGNORECASE)
            if match:
                try:
                    day, month_name = int(match.group(1)), months.get(match.group(2).lower(), None)
                    if month_name:
                        year = today.year if month_name >= today.month else today.year + 1
                        target_date = datetime(year, month_name, day)
                        result['delivery_days'] = max(1, (target_date - today).days)
                except:
                    pass
        elif re.search(r'\d+', date_text):
            match = re.search(r'(\d+)', date_text)
            if match:
                result['delivery_days'] = int(match.group(1))
    else:
        result['delivery_days'] = None

# Сохранение всех результатов
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
filename = f"ozon_products_{timestamp}.json"

with open(filename, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"\n{'='*60}")
print(f"✅ Сохранено {len(results)} товаров в {filename}")
print(f"{'='*60}")

for j, data in enumerate(results, 1):
    print(f"\n[{j}] {data.get('title', 'N/A')[:50]}...")
    print(f"    Цена: {data.get('price')} ₽ | Скидка: {data.get('discount_percent', 0)}%")

driver.quit()
print("\n🏁 Парсинг завершён!")