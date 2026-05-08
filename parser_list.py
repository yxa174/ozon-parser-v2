import undetected_chromedriver as uc
import json
import time
from pathlib import Path

MAX_LINKS = 10


def extract_links_from_page(driver):
    """Извлечь ссылки на товары со страницы категории/поиска."""
    script = """
function getProductLinks() {
    const links = [];
    const seen = new Set();

    document.querySelectorAll('[data-index]').forEach(card => {
        const anchors = card.querySelectorAll('a[href*="/product/"]');
        anchors.forEach(a => {
            let href = a.getAttribute('href') || '';
            if (href && href.includes('/product/')) {
                const parts = href.split('?')[0];
                if (parts && parts !== '/' && !seen.has(parts)) {
                    const fullUrl = parts.startsWith('http') ? parts : 'https://www.ozon.ru' + parts;
                    seen.add(parts);
                    links.push(fullUrl);
                }
            }
        });
    });

    if (links.length === 0) {
        document.querySelectorAll('a[href*="/product/"]').forEach(a => {
            let href = a.getAttribute('href') || '';
            if (href && href.includes('/product/')) {
                const parts = href.split('?')[0];
                if (parts && parts !== '/' && !seen.has(parts)) {
                    const fullUrl = parts.startsWith('http') ? parts : 'https://www.ozon.ru' + parts;
                    seen.add(parts);
                    links.push(fullUrl);
                }
            }
        });
    }

    return { links: links, debug: Array.from(document.querySelectorAll('[href*="/product/"]')).slice(0, 3).map(el => el.getAttribute('href')) };
}
return getProductLinks();
"""

    try:
        result = driver.execute_script(script)
        print(f"    📊 Карточек: {len(result['links'])}, примеры href: {result['debug'][:3]}")
        return result['links']
    except Exception as e:
        print(f"    ❌ Ошибка JS: {e}")
        return []

    try:
        return driver.execute_script(script)
    except Exception as e:
        print(f"    ❌ Ошибка JS: {e}")
        return []


def main():
    input_file = Path(__file__).parent / "urls_catalogs.txt"
    if not input_file.exists():
        print(f"❌ Файл не найден: {input_file}")
        return

    catalog_urls = [line.strip() for line in input_file.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not catalog_urls:
        print("❌ Файл пустой")
        return

    print(f"📂 Найдено {len(catalog_urls)} категорий для обработки")

    options = uc.ChromeOptions()
    options.add_argument("--disable-gpu")
    driver = None

    all_links = []

    for i, catalog_url in enumerate(catalog_urls, 1):
        print(f"\n[{i}/{len(catalog_urls)}] 🔗 {catalog_url[:60]}...")

        if driver:
            try:
                driver.quit()
            except:
                pass

        try:
            driver = uc.Chrome(options=options)
        except Exception as e:
            print(f"  ❌ Не удалось запустить браузер: {e}")
            continue

        try:
            print("  🌐 Открываю страницу...")
            driver.get(catalog_url)
            print("  ⏳ Ждём загрузку...")
            time.sleep(5)

            print("  📜 Прокручиваем...")
            for _ in range(3):
                try:
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(2)  # Больше времени
                except:
                    break

            print("  🔍 Ищем ссылки...")
            links = extract_links_from_page(driver)
            print(f"  ✅ Найдено {len(links)} ссылок")
            all_links.extend(links)

        except Exception as e:
            print(f"  ❌ Ошибка: {e}")

        if driver:
            try:
                driver.quit()
            except:
                pass
            driver = None

        if len(all_links) >= MAX_LINKS:
            break

    print(f"\n✅ Итого собрано {len(all_links)} ссылок")

    output_file = Path(__file__).parent / "urls.txt"
    with open(output_file, 'w', encoding='utf-8') as f:
        for link in all_links[:MAX_LINKS]:
            f.write(link + '\n')

    print(f"💾 Сохранено в {output_file}")

    for j, link in enumerate(all_links[:MAX_LINKS], 1):
        print(f"  [{j}] {link[:80]}...")

    print("\n🏁 Готово!")


if __name__ == "__main__":
    main()