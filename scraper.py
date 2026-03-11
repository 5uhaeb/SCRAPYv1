import re
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus

from playwright.sync_api import sync_playwright
from supabase_db import upsert_products

HEADLESS = False
MAX_PAGES = 2
DELAY_SEC = (1.0, 2.5)

def clean_price(text: str):
    if not text:
        return None
    nums = re.findall(r"\d+", text.replace(",", ""))
    if not nums:
        return None
    return int("".join(nums))

def clean_float(text: str):
    try:
        return float(text)
    except:
        return None

def _rand_delay():
    import random
    return random.uniform(DELAY_SEC[0], DELAY_SEC[1])
def safe_text(locator, timeout=1200):
    try:
        if locator.count() == 0:
            return None
        return locator.first.text_content(timeout=timeout)
    except:
        return None

def safe_attr(locator, name: str):
    try:
        if locator.count() == 0:
            return None
        return locator.first.get_attribute(name)
    except:
        return None

def scrape_amazon(page, keyword: str, max_pages: int):
    products = []
    for p in range(1, max_pages + 1):
        url = f"https://www.amazon.in/s?k={quote_plus(keyword)}&page={p}"
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        page.mouse.wheel(0, 1600)
        page.wait_for_timeout(1500)
        page.mouse.wheel(0, 1600)
        page.wait_for_timeout(1500)

        cards = page.locator("div.s-result-item[data-component-type='s-search-result']")
        if cards.count() == 0:
            print("Amazon: No result cards found (captcha or blocked or layout changed).")
            continue
        count = cards.count()

        for i in range(min(count, 25)):
            card = cards.nth(i)

            title_el = card.locator("h2 a span").first
            title = (title_el.text_content(timeout=2000) or "").strip() if title_el.count() else ""
            link_el = card.locator("h2 a").first
            href = link_el.get_attribute("href") if link_el.count() else None
            product_url = f"https://www.amazon.in{href}" if href else None

            price_whole = safe_text(card.locator("span.a-price-whole"))
            price = clean_price(price_whole)

            reviews_count = clean_price(reviews_text) if reviews_text else None
            rating_text = safe_text(card.locator("span.a-icon-alt")) or ""
            rating = clean_float(rating_text.split(" ")[0]) if rating_text else None

            reviews_text = safe_text(card.locator("span.a-size-base.s-underline-text"))
            reviews_count = clean_price(reviews_text) if reviews_text else None

            if product_url and title:
                products.append({
                    "product_url": product_url,
                    "platform": "amazon",
                    "keyword": keyword,
                    "title": title,
                    "price": price,
                    "rating": rating,
                    "reviews_count": reviews_count,
                    "scraped_at": datetime.now(timezone.utc),
                })

        time.sleep(_rand_delay())
    return products

def scrape_flipkart(page, keyword: str, max_pages: int):
    products = []
    base = f"https://www.flipkart.com/search?q={quote_plus(keyword)}"

    # open once and close popup if present
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    page.mouse.wheel(0, 1800)
    page.wait_for_timeout(1200)
    try:
        close_btn = page.locator("button._2KpZ6l._2doB4z")
        if close_btn.count() > 0:
            close_btn.first.click()
    except:
        pass

    for p in range(1, max_pages + 1):
        url = base + (f"&page={p}" if p > 1 else "")
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        cards = page.locator("div._1AtVbE")
        if cards.count()==0:
            print("Flipkart: No cards found (blocked or layout changed).")
        count = cards.count()

        for i in range(min(count, 35)):
            card = cards.nth(i)

            title = card.locator("div._4rR01T").first.text_content()
            if not title:
                title = card.locator("a.s1Q9rs").first.text_content()
            title = (title or "").strip()

            href = card.locator("a").first.get_attribute("href")
            product_url = f"https://www.flipkart.com{href}" if href and href.startswith("/") else None

            price_text = card.locator("div._30jeq3").first.text_content()
            price = clean_price(price_text)

            rating_text = card.locator("div._3LWZlK").first.text_content()
            rating = clean_float(rating_text) if rating_text else None

            reviews_text = card.locator("span._2_R_DZ").first.text_content()
            reviews_count = None
            if reviews_text:
                m = re.search(r"([\d,]+)\s+Ratings", reviews_text)
                if m:
                    reviews_count = clean_price(m.group(1))

            if product_url and title:
                products.append({
                    "product_url": product_url,
                    "platform": "flipkart",
                    "keyword": keyword,
                    "title": title,
                    "price": price,
                    "rating": rating,
                    "reviews_count": reviews_count,
                    "scraped_at": datetime.now(timezone.utc),
                })

        time.sleep(_rand_delay())
    return products

def run(keywords: list[str], max_pages: int = MAX_PAGES):
    all_items = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        context = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"),
            viewport={"width": 1366, "height": 768},
            locale="en-IN"
        )
        page = context.new_page()

        for kw in keywords:
            print(f"\n--- Scraping for keyword: {kw} ---")

            try:
                amazon_items = scrape_amazon(page, kw, max_pages)
                print("Amazon items:", len(amazon_items))
                all_items.extend(amazon_items)
            except Exception as e:
                print("Amazon scrape error:", e)

            try:
                flipkart_items = scrape_flipkart(page, kw, max_pages)
                print("Flipkart items:", len(flipkart_items))
                all_items.extend(flipkart_items)
            except Exception as e:
                print("Flipkart scrape error:", e)

        browser.close()

    saved = upsert_products(all_items)
    print(f"\nTotal scraped: {len(all_items)} | Saved/Upserted: {saved}")

    saved = upsert_products(all_items)
    print(f"\nTotal scraped: {len(all_items)} | Saved/Upserted: {saved}")

if __name__ == "__main__":
    keywords = ["iphone 15", "samsung s24", "laptop i5"]
    run(keywords, max_pages=2)