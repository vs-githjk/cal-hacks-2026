

def test_local_or_ip_source_is_never_spoken():
    from pay.callscript import _speakable_host
    assert not _speakable_host("127.0.0.1") and not _speakable_host("localhost")
    assert _speakable_host("bestbuy.com")
from decimal import Decimal

import pytest

from pay.callscript import ScriptError, amount_words


@pytest.mark.parametrize("amount", ["sNaN", "1e999999", "1e-999999"])
def test_script_amount_rejects_nonfinite_or_extreme_values(amount):
    with pytest.raises(ScriptError):
        amount_words(Decimal(amount))
