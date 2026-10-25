"""Encrypted invitation credentials.

The invitation contains only connection metadata and a capability token. It
must never contain a persona, system prompt, raw chat, or API key.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from pydantic import Field, ValidationError

from person_simulator.errors import InviteError
from person_simulator.models import StrictModel
from person_simulator.storage import utcnow

ENVELOPE_FORMAT = "psim-invite-envelope-1"
KDF_NAME = "pbkdf2-sha256"
KDF_ITERATIONS = 600_000
SALT_BYTES = 16
_MIN_ITERATIONS = 100_000
_MAX_ITERATIONS = 2_000_000
_TOKEN_MIN_LENGTH = 16


class InvitePayload(StrictModel):
    format: Literal["psim-invite-1"] = "psim-invite-1"
    endpoint: str = Field(min_length=1)
    token: str = Field(min_length=_TOKEN_MIN_LENGTH)
    expires_at: datetime
    label: str = ""
    server_fingerprint: str | None = None
    max_sessions: int | None = Field(default=None, ge=1)

    def ensure_valid(self, now: datetime | None = None) -> None:
        current = now or utcnow()
        if self.expires_at.tzinfo is None:
            raise InviteError(
                "邀请过期时间必须包含时区", stage="invite"
            )
        if current.tzinfo is None:
            current = current.replace(tzinfo=self.expires_at.tzinfo)
        if self.expires_at <= current:
            raise InviteError("邀请已过期", stage="invite")

        split = urlsplit(self.endpoint)
        if split.scheme not in {"http", "https"}:
            raise InviteError("邀请 endpoint 必须是 http(s)", stage="invite")
        if split.username or split.password:
            raise InviteError("邀请 endpoint 不得包含用户名或密码", stage="invite")
        if split.query or split.fragment:
            raise InviteError("邀请 endpoint 不得包含查询参数或 fragment", stage="invite")
        if not split.hostname:
            raise InviteError("邀请 endpoint 缺少主机名", stage="invite")


def _derive_key(passphrase: str, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def _require_passphrase(passphrase: str) -> None:
    if not passphrase:
        raise InviteError("邀请口令不能为空", stage="invite")


def encrypt_invite(payload: InvitePayload, passphrase: str) -> bytes:
    _require_passphrase(passphrase)
    payload.ensure_valid()
    plaintext = json.dumps(
        payload.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
    ).encode("utf-8")
    salt = secrets.token_bytes(SALT_BYTES)
    key = _derive_key(passphrase, salt, KDF_ITERATIONS)
    ciphertext = Fernet(key).encrypt(plaintext).decode("ascii")
    envelope = {
        "format": ENVELOPE_FORMAT,
        "kdf": KDF_NAME,
        "iterations": KDF_ITERATIONS,
        "salt": base64.urlsafe_b64encode(salt).decode("ascii"),
        "ciphertext": ciphertext,
    }
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True).encode("utf-8")


def decrypt_invite(blob: bytes, passphrase: str) -> InvitePayload:
    _require_passphrase(passphrase)
    try:
        envelope = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise InviteError("邀请文件不是有效 JSON/UTF-8", stage="invite") from exc
    if not isinstance(envelope, dict):
        raise InviteError("邀请文件顶层不是对象", stage="invite")
    if envelope.get("format") != ENVELOPE_FORMAT:
        raise InviteError("不支持的邀请文件格式", stage="invite")
    if envelope.get("kdf") != KDF_NAME:
        raise InviteError("不支持的邀请 KDF", stage="invite")
    iterations = envelope.get("iterations")
    if (
        not isinstance(iterations, int)
        or isinstance(iterations, bool)
        or not (_MIN_ITERATIONS <= iterations <= _MAX_ITERATIONS)
    ):
        raise InviteError("邀请 KDF 参数不在允许范围", stage="invite")

    try:
        salt = base64.urlsafe_b64decode(str(envelope["salt"]).encode("ascii"))
        ciphertext = str(envelope["ciphertext"]).encode("ascii")
    except (KeyError, ValueError, UnicodeEncodeError) as exc:
        raise InviteError("邀请文件缺少必要字段", stage="invite") from exc

    key = _derive_key(passphrase, salt, iterations)
    try:
        plaintext = Fernet(key).decrypt(ciphertext)
    except InvalidToken as exc:
        raise InviteError("邀请口令错误或文件被篡改", stage="invite") from exc
    try:
        payload = InvitePayload.model_validate_json(plaintext)
    except ValidationError as exc:
        raise InviteError("邀请内容不符合契约", stage="invite") from exc
    return payload


def write_invite(path: str | Path, payload: InvitePayload, passphrase: str) -> None:
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encrypt_invite(payload, passphrase))
        os.chmod(target, 0o600)
    except OSError as exc:
        raise InviteError("无法写入邀请文件", stage="invite", hint=str(target)) from exc


def read_invite(path: str | Path, passphrase: str) -> InvitePayload:
    target = Path(path)
    try:
        blob = target.read_bytes()
    except OSError as exc:
        raise InviteError("无法读取邀请文件", stage="invite", hint=str(target)) from exc
    return decrypt_invite(blob, passphrase)


def generate_passphrase() -> str:
    return secrets.token_urlsafe(24)
