"""Local HTTP simulation server with a separate loopback admin listener."""

from __future__ import annotations

import hmac
import json
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlsplit

from person_simulator.config import Settings
from person_simulator.errors import (
    AccessDeniedError,
    ConfigError,
    ForbiddenError,
    InputTooLongError,
    InviteError,
    OutputBlockedError,
    PersonSimError,
)
from person_simulator.providers import build_client
from person_simulator.providers.base import ModelClient
from person_simulator.runtime.guard import OutputGuard
from person_simulator.runtime.models import RuntimePersona
from person_simulator.runtime.service import ChatService
from person_simulator.runtime.session import SessionManager
from person_simulator.server.registry import InviteRecord, InviteRegistry

_STATIC_DIR = Path(__file__).with_name("static")
_STATIC_FILES = {"app.js", "style.css"}
_COOKIE_NAME = "psim_session"
_MAX_BODY_BYTES = 64 * 1024
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


@dataclass
class ServerContext:
    persona: RuntimePersona
    settings: Settings
    registry: InviteRegistry
    manager: SessionManager
    chat_service: ChatService
    admin_token: str
    allowed_hosts: frozenset[str]
    secure_cookies: bool
    shutdown_event: threading.Event = field(default_factory=threading.Event)
    verbose: bool = False


def _status_for(exc: PersonSimError) -> int:
    mapping = {
        "E_INVITE": 401,
        "E_UNAUTHORIZED": 401,
        "E_FORBIDDEN": 403,
        "E_SESSION_NOT_FOUND": 404,
        "E_SESSION_ENDED": 410,
        "E_SESSION_EXPIRED": 410,
        "E_SESSION_LIMIT": 429,
        "E_SESSION_RATE_LIMIT": 429,
        "E_TURN_LIMIT": 429,
        "E_INPUT_TOO_LONG": 413,
        "E_INPUT": 400,
        "E_CONTEXT_LIMIT": 400,
        "E_OUTPUT_BLOCKED": 422,
        "E_RUN_NOT_FOUND": 404,
        "E_RUN_INCOMPLETE": 409,
        "E_RUN_VERSION": 409,
        "E_RUN_HASH": 409,
        "E_RUN_MODE": 409,
        "E_AUTH": 502,
        "E_RATE_LIMIT": 503,
        "E_PROVIDER_UNAVAILABLE": 503,
        "E_TRANSPORT": 504,
        "E_TIMEOUT": 504,
        "E_RESPONSE_FORMAT": 502,
        "E_OUTPUT_TRUNCATED": 502,
        "E_API": 502,
    }
    return mapping.get(exc.error_code, 500)


def _public_message(exc: PersonSimError) -> str:
    if exc.error_code.startswith("E_AUTH") or exc.error_code in {
        "E_TRANSPORT",
        "E_TIMEOUT",
        "E_API",
        "E_RESPONSE_FORMAT",
        "E_OUTPUT_TRUNCATED",
        "E_PROVIDER_UNAVAILABLE",
        "E_RATE_LIMIT",
    }:
        return "模型服务暂时不可用"
    return exc.message


class _HttpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, context: ServerContext) -> None:
        super().__init__(address, handler)
        self.context = context


class _BaseHandler(BaseHTTPRequestHandler):
    server_version = "person-sim"
    protocol_version = "HTTP/1.1"

    @property
    def context(self) -> ServerContext:
        return self.server.context  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args) -> None:
        if not self.context.verbose:
            return
        # Never log query strings, cookies, bodies, or tokens.
        print(f"{self.command} {urlsplit(self.path).path} {args[1] if len(args) > 1 else ''}")

    def _send_bytes(
        self,
        status: int,
        body: bytes,
        content_type: str,
        *,
        headers: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, status: int, payload: object, **kwargs) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(
            status, body, "application/json; charset=utf-8", **kwargs
        )

    def _html(self, status: int, text: str) -> None:
        self._send_bytes(
            status, text.encode("utf-8"), "text/html; charset=utf-8"
        )

    def _error(self, exc: PersonSimError) -> None:
        payload: dict[str, object] = {
            "error_code": exc.error_code,
            "message": _public_message(exc),
        }
        if exc.hint and _status_for(exc) < 500:
            payload["hint"] = exc.hint
        self._json(_status_for(exc), payload)

    def _host_ok(self) -> bool:
        raw = self.headers.get("Host", "")
        hostname = urlsplit("//" + raw).hostname
        return bool(hostname) and hostname.lower() in self.context.allowed_hosts

    def _origin_ok(self) -> bool:
        raw = self.headers.get("Origin")
        if not raw:
            return True
        hostname = urlsplit(raw).hostname
        return bool(hostname) and hostname.lower() in self.context.allowed_hosts

    def _guard_request(self) -> bool:
        if not self._host_ok() or not self._origin_ok():
            self._error(ForbiddenError("请求来源不被允许", stage="server"))
            return False
        return True

    def _read_json(self) -> dict[str, object]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise InputTooLongError("请求长度无效", stage="server") from exc
        if length <= 0 or length > _MAX_BODY_BYTES:
            raise InputTooLongError("请求体为空或过大", stage="server")
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise InputTooLongError("请求体不是有效 JSON", stage="server") from exc
        if not isinstance(value, dict):
            raise InputTooLongError("请求体必须是 JSON 对象", stage="server")
        return value

    def _cookie_session_id(self) -> str | None:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            return None
        morsel = cookie.get(_COOKIE_NAME)
        return morsel.value if morsel else None

    def _bearer(self) -> str | None:
        raw = self.headers.get("Authorization", "")
        if raw.startswith("Bearer "):
            return raw[7:].strip() or None
        return None

    def _session_id(self) -> str | None:
        return self.headers.get("X-PSIM-Session") or self._cookie_session_id()

    def _session(self):
        session_id = self._session_id()
        if not session_id:
            raise AccessDeniedError("缺少会话凭证", stage="server")
        session = self.context.manager.get(session_id)
        bearer = self._bearer()
        if bearer:
            invite = self.context.registry.validate(bearer)
            if invite.id != session.invite_id:
                raise ForbiddenError("会话与邀请不匹配", stage="server")
        return session

    def _set_session_cookie(self, session_id: str) -> None:
        suffix = "; Secure" if self.context.secure_cookies else ""
        self.send_header(
            "Set-Cookie",
            f"{_COOKIE_NAME}={session_id}; Path=/; HttpOnly; SameSite=Strict{suffix}",
        )

    def _clear_session_cookie(self) -> None:
        self.send_header(
            "Set-Cookie",
            f"{_COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict",
        )

    def _session_payload(self, session) -> dict[str, object]:
        return {
            "id": session.id,
            "invite_id": session.invite_id,
            "state": session.state.value,
            "turns": session.turns,
            "created_at": session.created_at.isoformat(),
            "last_active": session.last_active.isoformat(),
        }

    def _admin_ok(self) -> bool:
        provided = self.headers.get("X-PSIM-Admin", "")
        return bool(provided) and hmac.compare_digest(
            provided, self.context.admin_token
        )

    def do_DELETE(self) -> None:  # noqa: N802
        self._json(404, {"error_code": "E_NOT_FOUND", "message": "not found"})


class PublicHandler(_BaseHandler):
    def do_GET(self) -> None:  # noqa: N802
        if not self._guard_request():
            return
        parsed = urlsplit(self.path)
        path = parsed.path
        try:
            if path == "/healthz":
                self._json(200, {"status": "ok"})
                return
            if path == "/":
                token = parse_qs(parsed.query).get("token", [None])[0]
                if token:
                    record = self.context.registry.validate(token)
                    session = self.context.manager.create(
                        record.id,
                        max_sessions_for_invite=record.max_sessions,
                    )
                    self.send_response(303)
                    self.send_header("Location", "/")
                    self._set_session_cookie(session.id)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self._serve_static("index.html")
                return
            if path.startswith("/static/"):
                self._serve_static(path.removeprefix("/static/"))
                return
            if path == "/api/session":
                session = self._session()
                self._json(200, self._session_payload(session))
                return
            if path.startswith("/admin/"):
                self._json(404, {"error_code": "E_NOT_FOUND", "message": "not found"})
                return
            self._json(404, {"error_code": "E_NOT_FOUND", "message": "not found"})
        except PersonSimError as exc:
            self._error(exc)
        except Exception:
            self._json(500, {"error_code": "E_INTERNAL", "message": "internal error"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._guard_request():
            return
        path = urlsplit(self.path).path
        try:
            if path.startswith("/admin/"):
                self._json(404, {"error_code": "E_NOT_FOUND", "message": "not found"})
                return
            if path == "/api/session":
                token = self._bearer()
                if not token:
                    raise AccessDeniedError("缺少访问令牌", stage="server")
                record = self.context.registry.validate(token)
                session = self.context.manager.create(
                    record.id, max_sessions_for_invite=record.max_sessions
                )
                body = json.dumps(
                    self._session_payload(session), ensure_ascii=False
                ).encode("utf-8")
                self.send_response(201)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self._set_session_cookie(session.id)
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/chat":
                session = self._session()
                payload = self._read_json()
                message = payload.get("message")
                if not isinstance(message, str):
                    raise InputTooLongError("message 必须是字符串", stage="server")
                reply = self.context.chat_service.chat(session.id, message)
                self._json(
                    200,
                    {
                        "reply": reply.text,
                        "turn": reply.turn,
                        "redactions": reply.redactions,
                        "notices": list(reply.notices),
                    },
                )
                return
            if path == "/api/session/end":
                session = self._session()
                self.context.manager.end(session.id)
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._json(404, {"error_code": "E_NOT_FOUND", "message": "not found"})
        except PersonSimError as exc:
            self._error(exc)
        except Exception:
            self._json(500, {"error_code": "E_INTERNAL", "message": "internal error"})

    def _serve_static(self, name: str) -> None:
        if name == "index.html":
            pass
        elif name not in _STATIC_FILES:
            self._json(404, {"error_code": "E_NOT_FOUND", "message": "not found"})
            return
        path = _STATIC_DIR / name
        try:
            data = path.read_bytes()
        except OSError:
            self._json(500, {"error_code": "E_INTERNAL", "message": "internal error"})
            return
        content_type = {
            "index.html": "text/html; charset=utf-8",
            "app.js": "text/javascript; charset=utf-8",
            "style.css": "text/css; charset=utf-8",
        }[name]
        self._send_bytes(200, data, content_type)


class AdminHandler(_BaseHandler):
    def _require_admin(self) -> None:
        if not self._host_ok() or not self._origin_ok():
            raise ForbiddenError("请求来源不被允许", stage="server")
        if not self._admin_ok():
            raise AccessDeniedError("管理员令牌无效", stage="server")

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        try:
            self._require_admin()
            if path == "/admin/sessions":
                self._json(200, self.context.manager.list_metadata())
                return
            if path == "/admin/invites":
                self._json(200, self.context.registry.list_metadata())
                return
            self._json(404, {"error_code": "E_NOT_FOUND", "message": "not found"})
        except PersonSimError as exc:
            self._error(exc)

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        try:
            self._require_admin()
            if path == "/admin/invites":
                payload = self._read_json()
                label = str(payload.get("label", ""))
                try:
                    expires_in = int(payload.get("expires_in_seconds", 3600))
                    max_sessions = payload.get("max_sessions")
                    max_sessions = (
                        int(max_sessions) if max_sessions is not None else None
                    )
                except (TypeError, ValueError) as exc:
                    raise InviteError("邀请参数无效", stage="invite") from exc
                record, token = self.context.registry.create(
                    label, timedelta(seconds=expires_in), max_sessions
                )
                self._json(
                    201,
                    {
                        "invite_id": record.id,
                        "token": token,
                        "expires_at": record.expires_at.isoformat(),
                        "label": record.label,
                    },
                )
                return
            if path == "/admin/shutdown":
                self.context.shutdown_event.set()
                self._json(202, {"status": "shutting_down"})
                return
            self._json(404, {"error_code": "E_NOT_FOUND", "message": "not found"})
        except PersonSimError as exc:
            self._error(exc)

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        try:
            self._require_admin()
            if path.startswith("/admin/invites/"):
                self.context.registry.revoke(path.removeprefix("/admin/invites/"))
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path.startswith("/admin/sessions/"):
                self.context.manager.delete(path.removeprefix("/admin/sessions/"))
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._json(404, {"error_code": "E_NOT_FOUND", "message": "not found"})
        except PersonSimError as exc:
            self._error(exc)


class SimulationServer:
    def __init__(
        self,
        context: ServerContext,
        public_server: _HttpServer,
        admin_server: _HttpServer,
    ) -> None:
        self.context = context
        self.public_server = public_server
        self.admin_server = admin_server
        self._threads: list[threading.Thread] = []
        self._closed = False
        self._lock = threading.Lock()

    @property
    def public_url(self) -> str:
        host, port = self.public_server.server_address[:2]
        display = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        return f"http://{display}:{port}"

    @property
    def admin_url(self) -> str:
        host, port = self.admin_server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def admin_token(self) -> str:
        return self.context.admin_token

    @property
    def registry(self) -> InviteRegistry:
        return self.context.registry

    @property
    def manager(self) -> SessionManager:
        return self.context.manager

    def start(self) -> None:
        with self._lock:
            if self._threads:
                return
            for server in (self.public_server, self.admin_server):
                thread = threading.Thread(
                    target=server.serve_forever, daemon=True
                )
                thread.start()
                self._threads.append(thread)

    def serve_forever(self) -> None:
        self.start()
        try:
            self.context.shutdown_event.wait()
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        for server in (self.public_server, self.admin_server):
            if self._threads:
                server.shutdown()
            server.server_close()
        for thread in self._threads:
            thread.join(timeout=5)
        self.context.chat_service.close()


def create_server(
    *,
    persona: RuntimePersona,
    settings: Settings,
    host: str,
    port: int,
    registry: InviteRegistry,
    admin_token: str,
    client: ModelClient | None = None,
    replay_messages: Iterable[str] = (),
) -> SimulationServer:
    if not admin_token:
        raise ConfigError("管理员令牌不能为空", stage="server")
    if host not in _LOOPBACK_HOSTS and not settings.simulation.allow_lan:
        raise ConfigError(
            "非 loopback 监听需要显式 allow_lan",
            stage="server",
            hint="设置 simulation.allow_lan=true 或使用 127.0.0.1",
        )
    allowed_hosts = frozenset(
        {item.lower() for item in settings.simulation.allowed_hosts}
        | _LOOPBACK_HOSTS
        | {host.lower()}
    )
    manager = SessionManager(
        max_sessions=settings.simulation.max_sessions,
        ttl=timedelta(minutes=settings.simulation.ttl_minutes),
        idle=timedelta(minutes=settings.simulation.idle_minutes),
        max_turns=settings.simulation.max_turns,
        max_input_chars=settings.simulation.max_input_chars,
        requests_per_minute=settings.simulation.requests_per_minute,
    )
    guard = OutputGuard(
        persona.system_prompt,
        blocked_terms=settings.simulation.blocked_terms,
        replay_messages=replay_messages,
    )
    chat_service = ChatService(
        persona=persona,
        settings=settings,
        client=client or build_client(settings),
        manager=manager,
        guard=guard,
    )
    context = ServerContext(
        persona=persona,
        settings=settings,
        registry=registry,
        manager=manager,
        chat_service=chat_service,
        admin_token=admin_token,
        allowed_hosts=allowed_hosts,
        secure_cookies=settings.simulation.secure_cookies,
    )
    public_server = _HttpServer((host, port), PublicHandler, context)
    admin_server = _HttpServer(("127.0.0.1", 0), AdminHandler, context)
    return SimulationServer(context, public_server, admin_server)
