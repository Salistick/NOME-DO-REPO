import hmac
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


class _IPv6CallbackServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6


class OAuthCallbackServer:
    """Accept exactly one provider response for the current desktop login."""

    def __init__(self, redirect_uri: str, state: str):
        uri_error = "Use um callback OAuth HTTP em localhost, 127.0.0.1 ou [::1]."
        try:
            parsed = urlsplit(redirect_uri)
            port = parsed.port
        except ValueError:
            raise ValueError(uri_error) from None
        host = parsed.hostname
        if (
            parsed.scheme != "http"
            or host not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username is not None
            or parsed.fragment
            or port == 0
        ):
            raise ValueError(uri_error)

        self._host = "127.0.0.1" if host == "localhost" else host
        self._port = port or 80
        self._path = parsed.path or "/"
        self._state = state.encode("utf-8")
        self._complete = threading.Event()
        self._lock = threading.Lock()
        self._result: tuple[str | None, str | None] = (None, None)
        self._server: ThreadingHTTPServer | None = None

    def start(self):
        callback = self

        class Handler(BaseHTTPRequestHandler):
            timeout = 5

            def do_GET(self):
                try:
                    parsed = urlsplit(self.path)
                    params = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=32)
                except ValueError:
                    self._respond(400, b"Resposta OAuth invalida.")
                    return

                if parsed.path != callback._path:
                    self._respond(404, b"Callback inexistente.")
                    return

                status, message = callback._accept_response(params)
                self._respond(status, message)

            def _respond(self, status: int, message: bytes):
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(message)

            def log_message(self, format, *args):
                # The request path contains the OAuth authorization code.
                return

        server_class = _IPv6CallbackServer if self._host == "::1" else ThreadingHTTPServer
        server = server_class((self._host, self._port), Handler)
        try:
            threading.Thread(target=server.serve_forever, daemon=True).start()
        except RuntimeError:
            server.server_close()
            raise
        self._server = server

    def _accept_response(self, params: dict[str, list[str]]) -> tuple[int, bytes]:
        states = params.get("state", [])
        codes = params.get("code", [])
        errors = params.get("error", [])
        valid_state = len(states) == 1 and hmac.compare_digest(states[0].encode("utf-8"), self._state)
        valid_code = len(codes) == 1 and bool(codes[0]) and not errors
        valid_error = len(errors) == 1 and bool(errors[0]) and not codes
        if not valid_state or not (valid_code or valid_error):
            return 400, b"Resposta OAuth invalida. Volte ao fluxo de autorizacao."

        with self._lock:
            if self._complete.is_set():
                return 409, b"Esta resposta OAuth ja foi recebida."
            if valid_code:
                self._result = (codes[0], None)
            else:
                self._result = (None, "autorizacao recusada pelo provedor")
            self._complete.set()

        return 200, b"Resposta OAuth recebida. Volte ao bot para ver o resultado."

    def stop(self):
        server = self._server
        if server is None:
            return
        self._server = None
        try:
            server.shutdown()
        except (OSError, RuntimeError) as exc:
            print(f"[OAUTH] falha ao parar callback: {exc}")
        try:
            server.server_close()
        except OSError as exc:
            print(f"[OAUTH] falha ao fechar callback: {exc}")

    def wait_for_code(
        self, timeout: float = 180, cancel_event: threading.Event | None = None,
    ) -> tuple[str | None, str | None]:
        deadline = time.monotonic() + timeout
        while True:
            if cancel_event is not None and cancel_event.is_set():
                return None, "cancelled"
            if self._complete.is_set():
                return self._result
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None, "timeout"
            self._complete.wait(min(remaining, 0.05))
