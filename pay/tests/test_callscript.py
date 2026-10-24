

def test_local_or_ip_source_is_never_spoken():
    from pay.callscript import _speakable_host
    assert not _speakable_host("127.0.0.1") and not _speakable_host("localhost")
    assert _speakable_host("bestbuy.com")
