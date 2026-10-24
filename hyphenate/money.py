"""Money is integer cents everywhere. Dollars come in as int, float or str and are rounded half-up once, at the edge."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any


def cents(v: Any) -> int:
    if isinstance(v, bool) or v is None:
        raise ValueError(f"not an amount: {v!r}")
    try:
        d = Decimal(str(v))
    except Exception as e:  # InvalidOperation
        raise ValueError(f"not an amount: {v!r}") from e
    if not d.is_finite():
        raise ValueError(f"not an amount: {v!r}")
    return int((d * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def usd(c: int) -> str:
    sign = "-" if c < 0 else ""
    c = abs(int(c))
    return f"{sign}${c // 100:,}.{c % 100:02d}"
