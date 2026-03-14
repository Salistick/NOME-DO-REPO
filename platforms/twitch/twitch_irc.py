import re
import socket
import ssl
from typing import Callable, Optional


def parse_irc_tags(raw_tags: str) -> dict[str, str]:
    tags = {}
    if not raw_tags:
        return tags

    for item in raw_tags.split(";"):
        if "=" in item:
            key, value = item.split("=", 1)
            tags[key] = value
        else:
            tags[item] = ""
    return tags


def parse_badges(badges_str: str) -> dict[str, str]:
    badges = {}
    if not badges_str:
        return badges

    for badge in badges_str.split(","):
        if "/" in badge:
            name, version = badge.split("/", 1)
            badges[name] = version
    return badges


def detect_user_role(tags: dict[str, str]) -> str:
    badges = parse_badges(tags.get("badges", ""))

    if "broadcaster" in badges:
        return "broadcaster"
    if tags.get("mod") == "1" or "moderator" in badges:
        return "moderator"
    if "vip" in badges:
        return "vip"
    if tags.get("subscriber") == "1" or "subscriber" in badges:
        return "subscriber"
    return "viewer"


class TwitchIRCClient:
    def __init__(
        self,
        oauth_token: str,
        login_name: str,
        channel_name: str,
        host: str = "irc.chat.twitch.tv",
        port: int = 6697,
    ):
        self.oauth_token = oauth_token
        self.login_name = login_name.lower()
        self.channel_name = channel_name.lower().lstrip("#")
        self.host = host
        self.port = port
        self.sock: Optional[ssl.SSLSocket] = None
        self.buffer = ""
        self._running = False

    def connect(self) -> None:
        raw_sock = socket.create_connection((self.host, self.port), timeout=30)
        context = ssl.create_default_context()
        self.sock = context.wrap_socket(raw_sock, server_hostname=self.host)
        self.sock.settimeout(1.0)

        self._running = True

        self.send_line("CAP REQ :twitch.tv/tags")
        self.send_line("CAP REQ :twitch.tv/commands")
        self.send_line(f"PASS oauth:{self.oauth_token}")
        self.send_line(f"NICK {self.login_name}")
        self.send_line(f"JOIN #{self.channel_name}")

    def stop(self) -> None:
        self._running = False

        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass

            try:
                self.sock.close()
            except Exception:
                pass

            self.sock = None

    def send_line(self, line: str) -> None:
        if not self.sock:
            raise RuntimeError("Socket não conectado.")
        self.sock.sendall((line + "\r\n").encode("utf-8"))

    def send_chat_message(self, text: str) -> None:
        clean = " ".join(text.strip().split())
        if not clean:
            return
        self.send_line(f"PRIVMSG #{self.channel_name} :{clean}")

    def recv_lines(self) -> list[str]:
        if not self.sock:
            raise ConnectionError("Socket não conectado.")

        try:
            data = self.sock.recv(4096)
        except socket.timeout:
            return []
        except OSError as exc:
            raise ConnectionError(str(exc)) from exc

        if not data:
            raise ConnectionError("Conexão IRC encerrada.")

        decoded = data.decode("utf-8", errors="ignore")
        self.buffer += decoded

        lines = []
        while "\r\n" in self.buffer:
            line, self.buffer = self.buffer.split("\r\n", 1)
            lines.append(line)

        return lines

    def listen_forever(self, on_message: Callable[[dict], None]) -> None:

        while self._running:
            try:
                for line in self.recv_lines():
                    if line.startswith("PING "):
                        try:
                            self.send_line(line.replace("PING", "PONG", 1))
                        except Exception:
                            self._running = False
                            break
                        continue

                    parsed = self.parse_privmsg(line)
                    if parsed:
                        on_message(parsed)

            except ConnectionError:
                if self._running:
                    print("Conexão IRC encerrada.")
                break
            except OSError:
                if self._running:
                    print("Socket IRC finalizado.")
                break
            except Exception as exc:
                if self._running:
                    print(f"Erro no loop IRC: {exc}")
                break

        self._running = False

    def parse_privmsg(self, line: str) -> Optional[dict]:
        pattern = r"^(?:@(?P<tags>[^ ]+) )?:(?P<prefix>[^ ]+) (?P<command>[A-Z]+) (?P<channel>#[^ ]+) :(?P<message>.*)$"
        match = re.match(pattern, line)
        if not match:
            return None

        command = match.group("command")
        if command != "PRIVMSG":
            return None

        tags = parse_irc_tags(match.group("tags") or "")
        prefix = match.group("prefix")
        message = match.group("message")
        channel = match.group("channel").lstrip("#")

        username = prefix.split("!", 1)[0].lower()
        display_name = tags.get("display-name", username)
        role = detect_user_role(tags)

        return {
            "channel": channel,
            "username": username,
            "display_name": display_name,
            "message": message,
            "role": role,
            "tags": tags,
        }