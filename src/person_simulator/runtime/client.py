"""HTTP clients for the owner-hosted simulation service."""

from __future__ import annotations

from typing import Any

import httpx

from person_simulator.errors import ClientError


def _raise_for_response(response: httpx.Response) -> dict[str, Any] | list[Any]:
    if 200 <= response.status_code < 300:
        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise ClientError("服务返回了非 JSON 响应", stage="client") from exc
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    message = payload.get("message") if isinstance(payload, dict) else None
    hint = payload.get("error_code") if isinstance(payload, dict) else None
    raise ClientError(
        str(message or f"服务返回 HTTP {response.status_code}"),
        stage="client",
        hint=str(hint) if hint else None,
    )


class _BaseClient:
    def __init__(
        self,
        base_url: str,
        *,
        headers: dict[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            headers=headers or {},
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any] | list[Any]:
        try:
            response = self._client.request(method, path.lstrip("/"), **kwargs)
        except httpx.HTTPError as exc:
            raise ClientError(
                "无法连接模拟服务", stage="client", hint="检查地址、网络和隧道状态"
            ) from exc
        return _raise_for_response(response)


class AdminClient(_BaseClient):
    def __init__(
        self,
        server_url: str,
        admin_token: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(
            server_url,
            headers={"X-PSIM-Admin": admin_token},
            transport=transport,
        )

    def create_invite(
        self,
        *,
        label: str,
        expires_in_seconds: int,
        max_sessions: int | None,
    ) -> dict[str, Any]:
        result = self._request(
            "POST",
            "/admin/invites",
            json={
                "label": label,
                "expires_in_seconds": expires_in_seconds,
                "max_sessions": max_sessions,
            },
        )
        if not isinstance(result, dict):
            raise ClientError("管理员响应格式错误", stage="client")
        return result

    def list_sessions(self) -> list[dict[str, Any]]:
        result = self._request("GET", "/admin/sessions")
        if not isinstance(result, list):
            raise ClientError("管理员响应格式错误", stage="client")
        return [item for item in result if isinstance(item, dict)]

    def delete_session(self, session_id: str) -> None:
        self._request("DELETE", f"/admin/sessions/{session_id}")

    def revoke_invite(self, invite_id: str) -> None:
        self._request("DELETE", f"/admin/invites/{invite_id}")

    def shutdown(self) -> None:
        self._request("POST", "/admin/shutdown")


class SimulationClient(_BaseClient):
    def __init__(
        self,
        endpoint: str,
        token: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(
            endpoint,
            headers={"Authorization": f"Bearer {token}"},
            transport=transport,
        )
        self.session_id: str | None = None

    def create_session(self) -> dict[str, Any]:
        result = self._request("POST", "/api/session", json={})
        if not isinstance(result, dict) or not isinstance(result.get("id"), str):
            raise ClientError("服务没有返回会话 ID", stage="client")
        self.session_id = str(result["id"])
        self._client.headers["X-PSIM-Session"] = self.session_id
        return result

    def chat(self, message: str) -> dict[str, Any]:
        if self.session_id is None:
            raise ClientError("请先创建会话", stage="client")
        result = self._request("POST", "/api/chat", json={"message": message})
        if not isinstance(result, dict) or not isinstance(result.get("reply"), str):
            raise ClientError("服务没有返回模拟回复", stage="client")
        return result

    def end_session(self) -> None:
        self._request("POST", "/api/session/end", json={})
        self.session_id = None
