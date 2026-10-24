"""SIMULATED reference data for Tech Bazaar. Real price history, seller records and the CPSC feed replace these."""
SOURCE = "simulated"
PRICE_URL = "https://example.com/price-history/simulated"
RECORD_URL = "https://example.com/seller-record/simulated"
CPSC_URL = "https://www.cpsc.gov/Recalls"

# sku_spec -> simulated price-history baseline (per unit, USD)
BASELINE = {sku: {"unit_price": p, "source_url": PRICE_URL, "source": SOURCE} for sku, p in {
    "rtx 4070 super 12gb": 600.0,
    "rx 7800 xt 16gb": 500.0,
    "psu 750w": 95.0,
    "psu 850w": 120.0,
    "case": 85.0,
}.items()}

# seller_id -> record ("good" | "caution")
RECORDS = {sid: {"record": r, "source_url": RECORD_URL, "source": SOURCE} for sid, r in {
    "seller_1": "good",
    "seller_2": "good",
    "seller_3": "caution",
}.items()}

# CPSC-style recall list: lowercase substrings matched against sku_spec. One unrelated item.
RECALLS = [{"match": "space heater model sh-100", "source_url": CPSC_URL}]
