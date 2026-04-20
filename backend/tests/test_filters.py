from scrapers.base import BaseScraper, Item


class FilterScraper(BaseScraper):
    name = "filter_test"
    base_url = "https://example.com"

    def build_search_url(self, keyword: str, page: int = 1) -> str:
        return self.base_url

    def parse(self, html: str, keyword: str) -> list[Item]:
        return []


class NoPriceFilterScraper(FilterScraper):
    apply_price_filter = False


def item(title: str, price: float | None = 50000) -> Item:
    slug = title.lower().replace(" ", "-")
    return Item(
        title=title,
        price=price,
        product_url=f"https://example.com/{slug}",
        source_platform="test",
        keyword="test",
    )


def test_keyword_filter_keeps_matching_items():
    scraper = FilterScraper()
    items = [item("Apple iPhone 15"), item("Samsung Galaxy S24")]

    got = scraper.filter_by_keyword(items, "iphone 15")

    assert [i.title for i in got] == ["Apple iPhone 15"]


def test_keyword_filter_drops_unrelated_accessories():
    scraper = FilterScraper()
    items = [
        item("OnePlus 12 phone", 50000),
        item("Tempered glass case", 500),
        item("USB fast charger", 800),
        item("OnePlus 12 case", 500),
        item("OnePlus 12R phone", 45000),
        item("OnePlus 11 phone", 42000),
        item("OnePlus Nord phone", 30000),
        item("OnePlus 13 phone", 60000),
    ]

    keyword_filtered = scraper.filter_by_keyword(items, "oneplus 12")
    got = scraper.filter_by_price_sanity(keyword_filtered)

    assert "OnePlus 12 phone" in [i.title for i in got]
    assert "OnePlus 12 case" not in [i.title for i in got]
    assert all("charger" not in i.title.lower() for i in got)


def test_keyword_filter_ignores_short_tokens():
    scraper = FilterScraper()
    items = [item("BoAt 15W charger"), item("Apple iPhone 15")]

    got = scraper.filter_by_keyword(items, "iphone 15")

    assert [i.title for i in got] == ["Apple iPhone 15"]


def test_price_filter_drops_outliers_below_30pct_of_median():
    scraper = FilterScraper()
    items = [
        item("Phone 1", 500),
        item("Phone 2", 45000),
        item("Phone 3", 48000),
        item("Phone 4", 49000),
        item("Phone 5", 50000),
        item("Phone 6", 51000),
        item("Phone 7", 52000),
        item("Phone 8", 53000),
        item("Phone 9", 54000),
        item("Phone 10", 55000),
    ]

    got = scraper.filter_by_price_sanity(items)

    assert [i.price for i in got] == [45000, 48000, 49000, 50000, 51000, 52000, 53000, 54000, 55000]


def test_price_filter_skips_when_fewer_than_5_items():
    scraper = FilterScraper()
    items = [item("Phone", 500), item("Phone Pro", 50000), item("Phone Max", 60000)]

    assert scraper.filter_by_price_sanity(items) == items


def test_scraper_with_apply_price_filter_false_skips_sanity_check():
    scraper = NoPriceFilterScraper()
    items = [
        item("Spec Sheet 1", 500),
        item("Spec Sheet 2", 45000),
        item("Spec Sheet 3", 48000),
        item("Spec Sheet 4", 49000),
        item("Spec Sheet 5", 50000),
    ]

    got = items if not scraper.apply_price_filter else scraper.filter_by_price_sanity(items)

    assert got == items
