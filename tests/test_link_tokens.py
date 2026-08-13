from archive.utils import link_tokens


def test_sign_and_verify_round_trip(monkeypatch):
    monkeypatch.setenv("ALERT_UNSUBSCRIBE_SECRET", "test-secret")
    token = link_tokens.sign_saved_item_id(42)
    assert link_tokens.verify_saved_item_token(token) == 42


def test_tampered_id_is_rejected(monkeypatch):
    monkeypatch.setenv("ALERT_UNSUBSCRIBE_SECRET", "test-secret")
    token = link_tokens.sign_saved_item_id(42)
    _id, _, signature = token.partition(".")
    tampered = f"43.{signature}"  # same signature, different claimed id
    assert link_tokens.verify_saved_item_token(tampered) is None


def test_tampered_signature_is_rejected(monkeypatch):
    monkeypatch.setenv("ALERT_UNSUBSCRIBE_SECRET", "test-secret")
    token = link_tokens.sign_saved_item_id(42)
    raw_id, _, signature = token.partition(".")
    flipped = ("0" if signature[0] != "0" else "1") + signature[1:]
    assert link_tokens.verify_saved_item_token(f"{raw_id}.{flipped}") is None


def test_wrong_secret_is_rejected(monkeypatch):
    monkeypatch.setenv("ALERT_UNSUBSCRIBE_SECRET", "secret-a")
    token = link_tokens.sign_saved_item_id(42)
    monkeypatch.setenv("ALERT_UNSUBSCRIBE_SECRET", "secret-b")
    assert link_tokens.verify_saved_item_token(token) is None


def test_malformed_tokens_return_none(monkeypatch):
    monkeypatch.setenv("ALERT_UNSUBSCRIBE_SECRET", "test-secret")
    assert link_tokens.verify_saved_item_token("") is None
    assert link_tokens.verify_saved_item_token("no-dot-here") is None
    assert link_tokens.verify_saved_item_token("not-an-int.somesig") is None


def test_missing_secret_fails_closed(monkeypatch):
    monkeypatch.delenv("ALERT_UNSUBSCRIBE_SECRET", raising=False)
    token = link_tokens.sign_saved_item_id(42)
    assert link_tokens.verify_saved_item_token(token) is None
