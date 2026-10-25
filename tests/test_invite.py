from __future__ import annotations

import json
from datetime import timedelta

import pytest

from person_simulator.errors import InviteError
from person_simulator.runtime.invite import (
    InvitePayload,
    decrypt_invite,
    encrypt_invite,
    generate_passphrase,
    read_invite,
    write_invite,
)
from person_simulator.storage import utcnow


def make_invite(**overrides) -> InvitePayload:
    values = {
        "endpoint": "https://sim.example.test",
        "token": "token-0123456789abcdef",
        "expires_at": utcnow() + timedelta(hours=1),
        "label": "给同学的邀请",
    }
    values.update(overrides)
    return InvitePayload(**values)


def test_invite_roundtrip_and_no_persona_payload():
    payload = make_invite()
    blob = encrypt_invite(payload, "correct horse battery staple")

    assert b"persona" not in blob.lower()
    assert decrypt_invite(blob, "correct horse battery staple") == payload


def test_invite_file_roundtrip(tmp_path):
    payload = make_invite()
    path = tmp_path / "invite.psim"
    write_invite(path, payload, "passphrase-1")

    assert path.is_file()
    assert read_invite(path, "passphrase-1") == payload


def test_wrong_passphrase_and_tamper_rejected():
    blob = encrypt_invite(make_invite(), "passphrase-1")

    with pytest.raises(InviteError):
        decrypt_invite(blob, "passphrase-2")
    with pytest.raises(InviteError):
        decrypt_invite(blob[:-2] + b"xx", "passphrase-1")


def test_unknown_envelope_format_rejected():
    blob = encrypt_invite(make_invite(), "passphrase-1")
    envelope = json.loads(blob.decode("utf-8"))
    envelope["format"] = "future-envelope"
    with pytest.raises(InviteError):
        decrypt_invite(json.dumps(envelope).encode("utf-8"), "passphrase-1")


def test_expired_invite_rejected():
    payload = make_invite(expires_at=utcnow() - timedelta(seconds=1))
    with pytest.raises(InviteError):
        payload.ensure_valid()


def test_invalid_endpoint_rejected():
    for endpoint in (
        "ftp://example.test",
        "https://user:pass@example.test",
        "https://example.test/path?q=1",
        "https://example.test/path#fragment",
        "https:///missing-host",
    ):
        with pytest.raises(InviteError):
            make_invite(endpoint=endpoint).ensure_valid()


def test_public_http_endpoint_rejected():
    with pytest.raises(InviteError):
        make_invite(endpoint="http://example.test").ensure_valid()


def test_loopback_http_endpoint_allowed():
    make_invite(endpoint="http://127.0.0.1:8765").ensure_valid()


def test_empty_passphrase_rejected():
    with pytest.raises(InviteError):
        encrypt_invite(make_invite(), "")


def test_generated_passphrase_is_long_enough():
    passphrase = generate_passphrase()
    assert len(passphrase) >= 24
    assert generate_passphrase() != passphrase
