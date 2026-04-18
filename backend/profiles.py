import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup

def clean_price_generic(text: str):
    if not text:
        return None
    # tries INR-like numbers, otherwise just big number groups
    m = re.search(r"(₹|rs\.?)\s*([\d,]+)", text.lower())
    raw = m.group(2) if m else None
    if not raw:
        m2 = re.search(r"(\d[\d,]{3,})", text)
        raw = m2.group(1) if m2 else None
    if not raw:
        return None
    try:
        val = int(raw.replace(",", ""))
    except:
        return None
    if val < 500 or val > 500000:
        return None
    return val

def parse_gsmarena_list(html: str, base_url: str):
    """
    Parses GSMArena phone listing pages like:
    https://www.gsmarena.com/samsung-phones-9.php
    https://www.gsmarena.com/makers.php3 (brands list)
    """
    soup = BeautifulSoup(html, "html.parser")
    items = []

    # GSMArena phone list page usually has: div.makers > ul > li > a
    cards = soup.select("div.makers ul li a")
    if not cards:
        # some pages use: div.section-body ul li a (fallback)
        cards = soup.select("div.section-body ul li a")

    for a in cards:
        href = a.get("href")
        if not href:
            continue
        product_url = urljoin(base_url, href)

        title = a.get_text(" ", strip=True)
        if not title:
            # sometimes title is in <strong>
            strong = a.select_one("strong")
            title = strong.get_text(" ", strip=True) if strong else None
        if not title:
            continue

        items.append({
            "product_url": product_url,
            "title": title[:250],
            "price": None,  # GSMArena list pages usually don't show price
        })

    return items

PROFILES = {
    "gsmarena": {
        "parser": parse_gsmarena_list,
        "platform": "gsmarena"
    }
}