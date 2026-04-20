from scrapers.base import BaseScraper
from scrapers.sites.amazon_in import AmazonInScraper
from scrapers.sites.croma import CromaScraper
from scrapers.sites.flipkart import FlipkartScraper
from scrapers.sites.gsmarena import GSMArenaScraper
from scrapers.sites.reliance_digital import RelianceDigitalScraper
from scrapers.sites.vijaysales import VijaySalesScraper


SCRAPERS: dict[str, type[BaseScraper]] = {
    "vijaysales": VijaySalesScraper,
    "flipkart": FlipkartScraper,
    "amazon_in": AmazonInScraper,
    "croma": CromaScraper,
    "reliance_digital": RelianceDigitalScraper,
    "gsmarena": GSMArenaScraper,
}


ALIASES = {
    "amazon": "amazon_in",
    "amazon.in": "amazon_in",
    "reliance": "reliance_digital",
}


def get_scraper(name: str) -> BaseScraper:
    key = ALIASES.get(name.strip().lower(), name.strip().lower())
    if key not in SCRAPERS:
        supported = ", ".join(sorted(SCRAPERS))
        raise ValueError(f"Unsupported scraper '{name}'. Supported: {supported}")
    return SCRAPERS[key]()


def all_scrapers() -> list[BaseScraper]:
    return [scraper_cls() for scraper_cls in SCRAPERS.values()]
