from matching import match_products, normalize_title


def test_normalize_title_strips_variants():
    assert normalize_title("Apple iPhone 15 128GB Black (Renewed)") == "iphone 15"


def test_match_products_groups_close_titles():
    groups = match_products(
        [
            {"title": "Apple iPhone 15 128GB Black", "price": 69900, "source_platform": "a", "product_url": "u1", "keyword": "iphone 15"},
            {"title": "iPhone 15 Blue 256 GB", "price": 72900, "source_platform": "b", "product_url": "u2", "keyword": "iphone 15"},
            {"title": "Samsung Galaxy S24 256GB", "price": 62999, "source_platform": "c", "product_url": "u3", "keyword": "s24"},
        ]
    )

    iphone_group = next(group for group in groups if group.normalized_title == "iphone 15")
    assert len(iphone_group.items) == 2
    assert iphone_group.min_price == 69900.0
