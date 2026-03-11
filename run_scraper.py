import sys

from scraper_common import run_scrape
from scrape_vijaysales import run as run_vijaysales
from scrape_webscraper_ecom import run as run_webscraper


def cli_run(site: str, keywords: list[str], pages: int):
    if site == "gsmarena":
        # default URL for CLI mode
        url = "https://www.gsmarena.com/samsung-phones-9.php"
        run_scrape(site, url, keywords, json_out="scraped.json")

    elif site == "vijaysales":
        run_vijaysales(keywords, pages=pages, json_out="vijaysales_mobiles.json")

    elif site == "webscraper":
        run_webscraper(keywords, pages_per_cat=pages)

    else:
        print("Unsupported site.")
        raise SystemExit(1)


if __name__ == "__main__":
    # CLI mode from Next.js API
    if len(sys.argv) >= 3:
        site = sys.argv[1].strip().lower()
        keywords = [k.strip() for k in sys.argv[2].split(",") if k.strip()]
        pages = int(sys.argv[3]) if len(sys.argv) > 3 else 2
        cli_run(site, keywords, pages)
        raise SystemExit(0)

    # Manual mode
    print("Supported sites: gsmarena, vijaysales, webscraper")
    site = input("Site: ").strip().lower()
    keywords_in = input("Keywords (comma separated): ").strip()

    keywords = [k.strip() for k in keywords_in.split(",") if k.strip()]
    if not keywords:
        print("No keywords provided. Exiting.")
        raise SystemExit(0)

    if site == "gsmarena":
        url = input("URL: ").strip()
        if not url:
            print("No URL provided. Exiting.")
            raise SystemExit(0)
        run_scrape(site, url, keywords, json_out="scraped.json")

    elif site == "vijaysales":
        pages_in = input("How many pages to try? (default 3): ").strip()
        pages = int(pages_in) if pages_in.isdigit() and int(pages_in) > 0 else 3
        run_vijaysales(keywords, pages=pages, json_out="vijaysales_mobiles.json")

    elif site == "webscraper":
        pages_in = input("How many pages per category? (default 5): ").strip()
        pages = int(pages_in) if pages_in.isdigit() and int(pages_in) > 0 else 5
        run_webscraper(keywords, pages_per_cat=pages)

    else:
        print("Unsupported site.")