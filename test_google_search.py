from price_comparison import PriceComparator

def test_clean_google_link():
    comp = PriceComparator()
    url = "https://www.google.com/url?q=https://example.com/product&sa=U&ved=2ah"
    cleaned = comp._clean_google_link(url)
    assert cleaned == "https://example.com/product"
