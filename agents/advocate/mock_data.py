"""SIMULATED reference data. Lanes C (USDA baseline) and D (CRS signals, recalls) replace these.
Keys match the supplier catalog in supplier/suppliers.json."""
SOURCE = "simulated"
USDA_URL = "https://www.ams.usda.gov/market-news"
CRS_URL = "https://example.com/crs/simulated"

# sku_spec -> USDA-style price per pack
BASELINE = {sku: {"unit_price": p, "source_url": USDA_URL, "source": SOURCE} for sku, p in {
    "yellow onions": 22.0,
    "russet potatoes": 24.5,
    "roma tomatoes": 28.0,
    "chicken thighs": 90.0,
    "canola oil": 42.0,
    "all-purpose flour": 20.0,
}.items()}

# supplier_id -> SupplierSignal (+ source_url)
SIGNALS = {sid: {"supplier_id": sid, "stability": st, "checked_at": "2026-10-23T00:00:00Z",
                 "source": SOURCE, "source_url": CRS_URL} for sid, st in {
    "sup-honest-hal": "verified_stable",
    "sup-shady-sam": "caution",
    "sup-valley-produce": "verified_stable",
    "sup-bay-broadline": "verified_stable",
    "sup-golden-mill": "not_verified",
}.items()}

RECALLS: list[str] = []
