from buyer.chat_diagnostics import ChatDiagnostics


def test_ack_must_match_message_and_expected_recipient_without_logging_raw_ids():
    lines = []
    current = [10.0]
    clock = lambda: current[0]
    diag = ChatDiagnostics(lines.append, clock=clock, now=lambda: '2026-10-24T09:00:00Z')
    diag.send_started('msg-1', 'private-owner-address', 'session-private', 'round-private')

    assert not diag.acknowledged('msg-1', 'foreign-sender')
    current[0] = 10.1
    assert diag.acknowledged('msg-1', 'private-owner-address')
    assert 'private-owner-address' not in '\n'.join(lines)
    assert 'session-private' not in '\n'.join(lines)
    assert 'round-private' not in '\n'.join(lines)
    assert all('body' not in line.lower() and 'code' not in line.lower() for line in lines)


def test_out_of_order_acks_are_correlated_and_expired_entries_are_unacknowledged():
    lines = []
    current = [0.0]
    diag = ChatDiagnostics(lines.append, clock=lambda: current[0], now=lambda: '2026-10-24T09:00:00Z', ttl_s=5)
    diag.send_started('msg-a', 'owner-a', 'session-a', 'round-a')
    diag.send_started('msg-b', 'owner-a', 'session-b', 'round-a')
    assert diag.acknowledged('msg-b', 'owner-a')
    assert diag.acknowledged('msg-a', 'owner-a')

    diag.send_started('msg-c', 'owner-a', 'session-c', 'round-a')
    current[0] = 6.0
    assert not diag.acknowledged('msg-c', 'owner-a')
    assert 'event=unacknowledged' in '\n'.join(lines)


def test_idle_expiration_emits_unacknowledged_without_another_message():
    lines = []
    current = [1.0]
    diag = ChatDiagnostics(lines.append, clock=lambda: current[0], now=lambda: '2026-10-24T09:00:00Z', ttl_s=5)
    diag.send_started('msg-1', 'owner-private', 'session-private', 'round-private')
    current[0] = 7.0
    diag.expire()
    assert 'event=unacknowledged' in '\n'.join(lines)
    assert 'owner-private' not in '\n'.join(lines)
    assert 'session-private' not in '\n'.join(lines)


def test_send_result_logs_only_closed_status_and_exception_type():
    lines = []
    diag = ChatDiagnostics(lines.append, clock=lambda: 1.0, now=lambda: '2026-10-24T09:00:00Z')
    diag.send_started('msg-1', 'owner', 'session', 'round')
    diag.send_result('msg-1', 'delivered')
    diag.send_started('msg-2', 'owner', 'session', 'round')
    diag.send_exception('msg-2', ValueError('contains private message body'))
    text = '\n'.join(lines)
    assert 'status=delivered' in text and 'status=failed' in text
    assert 'ValueError' in text and 'contains private message body' not in text
    assert 'status=contains' not in text


def test_ack_send_logs_correlation_and_closed_transport_status_only():
    lines = []
    diag = ChatDiagnostics(lines.append, clock=lambda: 1.0, now=lambda: '2026-10-24T09:00:00Z')
    diag.ack_send_result('ack-id', 'private-inbound-id', 'private-owner', 'private-session',
                         result=type('Status', (), {'status': 'delivered', 'detail': 'private detail'})())
    text = '\n'.join(lines)
    assert 'event=ack_send_result' in text and 'status=delivered' in text
    assert 'private-inbound-id' not in text and 'private-owner' not in text
    assert 'private-session' not in text and 'private detail' not in text
