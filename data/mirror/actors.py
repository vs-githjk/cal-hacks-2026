"""c1 Apify mirror actors and their small test inputs (demo hero: RTX 5070 Ti)."""

Q = "RTX 5070 Ti"
ACTORS = {
    "newegg": ("kawsar/newegg-product-scraper", {"keywords": [Q], "maxItems": 3, "maxPages": 1}),
    "microcenter": ("sian.agency/microcenter-product-scraper", {"keywords": [Q], "scrapeMode": "overview", "maxResults": 3}),
    "bestbuy": ("benthepythondev/bestbuy-scraper", {"mode": "search", "searchQuery": Q, "maxProducts": 3}),
    "bh": ("shahidirfan/B-H-Photo-Scraper", {"startUrls": [{"url": "https://www.bhphotovideo.com/c/search?q=rtx%205070%20ti"}], "results_wanted": 3, "max_pages": 1}),
    "ebay_sold": ("caffein.dev/ebay-sold-listings", {"keywords": [Q.lower()], "count": 5, "daysToScrape": 30, "ebaySite": "ebay.com"}),
    "ebay_live": ("memo23/ebay-search-scraper-ppe", {"searchQueries": [Q.lower()], "mode": "active", "maxItems": 3, "detailedItems": False, "includeSummary": False}),
    "amazon": ("junglee/Amazon-crawler", {"categoryOrProductUrls": [{"url": "https://www.amazon.com/s?k=rtx+5070+ti"}], "maxItemsPerStartUrl": 3, "maxSearchPagesPerStartUrl": 1}),
    "pcpartpicker": ("lulzasaur/pcpartpicker-scraper", {"category": "video-card", "maxResults": 3, "country": "us"}),
}
