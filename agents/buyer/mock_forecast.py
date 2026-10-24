"""SIMULATED forecast, stock and owner limits. Lane C replaces FORECASTS with the real usage forecast."""
WEEK = "2026-W44"
BUYER_ID = "restaurant-demo-1"


def _f(sku, grade, pack_size, pack_qty, predicted, reason):
    return {"buyer_id": BUYER_ID, "sku_spec": sku, "week": WEEK, "predicted_quantity": predicted,
            "reason": f"SIMULATED: {reason}", "error_last_week": 0.0,
            "grade": grade, "pack_size": pack_size, "pack_qty": pack_qty}


# predicted_quantity and ON_HAND are in lb; pack_qty is lb per pack
FORECASTS = [
    _f("yellow onions", "US No. 1", "50 lb", 50, 180, "steady soup and burger volume"),
    _f("russet potatoes", "US No. 1", "50 lb", 50, 240, "fries are the top side"),
    _f("roma tomatoes", "US No. 1", "25 lb", 25, 90, "salsa special Thursday"),
    _f("chicken thighs", "USDA Grade A", "40 lb case", 40, 150, "weekend catering order"),
    _f("canola oil", "Refined", "35 lb", 35, 70, "fryer change twice a week"),
    _f("all-purpose flour", "Enriched Bleached", "50 lb", 50, 60, "breading and flatbreads"),
]

ON_HAND = {"yellow onions": 30, "russet potatoes": 40, "roma tomatoes": 10,
           "chicken thighs": 20, "canola oil": 35, "all-purpose flour": 25}

OWNER = {"buyer_id": BUYER_ID, "spend_limit": 900.0, "auto_limit": 600.0, "consent": True,
         "delivery_window": "2026-10-27T06:00/2026-10-27T10:00", "auction_window_s": 12}
