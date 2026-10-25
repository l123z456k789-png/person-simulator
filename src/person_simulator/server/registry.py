"""In-memory invite registry; only token hashes are retained."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from person_simulator.errors import InviteError
from person_simulator.storage import utcnow


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class InviteRecord:
    id: str
    token_hash: str
    label: str
    created_at: datetime
    expires_at: datetime
    max_sessions: int | None = None
    revoked: bool = False

    def metadata(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "max_sessions": self.max_sessions,
            "revoked": self.revoked,
        }


@dataclass
class InviteRegistry:
    clock: Callable[[], datetime] = utcnow
    _by_id: dict[str, InviteRecord] = field(default_factory=dict)
    _by_hash: dict[str, InviteRecord] = field(default_factory=dict)

    def create(
        self,
        label: str,
        expires_in: timedelta,
        max_sessions: int | None = None,
    ) -> tuple[InviteRecord, str]:
        if expires_in <= timedelta(0):
            raise InviteError("邀请有效期必须大于 0", stage="invite")
        if max_sessions is not None and max_sessions < 1:
            raise InviteError("邀请会话上限必须大于 0", stage="invite")
        now = self.clock()
        token = secrets.token_urlsafe(32)
        record = InviteRecord(
            id=secrets.token_urlsafe(12),
            token_hash=_hash_token(token),
            label=label.strip(),
            created_at=now,
            expires_at=now + expires_in,
            max_sessions=max_sessions,
        )
        self._by_id[record.id] = record
        self._by_hash[record.token_hash] = record
        return record, token

    def validate(self, token: str) -> InviteRecord:
        if not token:
            raise InviteError("缺少访问令牌", stage="invite")
        record = self._by_hash.get(_hash_token(token))
        if record is None:
            raise InviteError("邀请无效", stage="invite")
        if record.revoked:
            raise InviteError("邀请已撤销", stage="invite")
        if record.expires_at <= self.clock():
            raise InviteError("邀请已过期", stage="invite")
        return record

    def revoke(self, invite_id: str) -> None:
        record = self._by_id.get(invite_id)
        if record is None:
            raise InviteError("邀请不存在", stage="invite")
        record.revoked = True

    def list_metadata(self) -> list[dict[str, object]]:
        return [
            record.metadata()
            for record in sorted(self._by_id.values(), key=lambda item: item.created_at)
        ]
