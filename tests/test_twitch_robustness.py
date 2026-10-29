import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from platforms.twitch.twitch_auth import TwitchAuth
from platforms.twitch.twitch_bot import TwitchBot
from platforms.twitch.twitch_cache import TokenCache
from platforms.twitch.twitch_irc import TwitchIRCClient
from platforms.twitch.twitch_sender import TwitchChatSender


class TwitchIRCRegressionTests(unittest.TestCase):
    def test_tls_handshake_failure_closes_raw_socket(self):
        client = TwitchIRCClient("token", "bot", "channel")
        raw_sock = Mock()
        context = Mock()
        context.wrap_socket.side_effect = OSError("handshake failed")
        with patch("platforms.twitch.twitch_irc.socket.create_connection", return_value=raw_sock), patch(
            "platforms.twitch.twitch_irc.ssl.create_default_context", return_value=context
        ):
            with self.assertRaises(OSError):
                client.connect()
        raw_sock.close.assert_called_once()

    def test_multibyte_character_split_across_tcp_packets_is_preserved(self):
        client = TwitchIRCClient("token", "bot", "channel")
        raw = ":user!user@host PRIVMSG #channel :ação\r\n".encode()
        split = raw.index("ç".encode()) + 1
        client.sock = Mock()
        client.sock.recv.side_effect = [raw[:split], raw[split:]]

        self.assertEqual(client.recv_lines(), [])
        lines = client.recv_lines()
        self.assertEqual(client.parse_privmsg(lines[0])["message"], "ação")

    def test_irc_command_cannot_inject_a_second_line(self):
        client = TwitchIRCClient("token", "bot", "channel")
        client.sock = Mock()
        with self.assertRaises(ValueError):
            client.send_line("JOIN #channel\r\nPRIVMSG #other :bad")
        client.sock.sendall.assert_not_called()

    def test_persistent_sender_answers_server_ping(self):
        sock = Mock()
        sock.recv.side_effect = [b"PING :tmi.twitch.tv\r\n", b""]

        def connect(client):
            client.sock = sock
            client._running = True

        sender = TwitchChatSender()
        sender._get_valid_token_unlocked = lambda: {"login": "bot", "access_token": "token"}
        with patch.object(TwitchIRCClient, "connect", connect), patch(
            "platforms.twitch.twitch_sender.time.sleep"
        ):
            sender._ensure_connected_unlocked("channel")
            reader = sender._reader_thread
            reader.join(timeout=1)
            self.assertFalse(reader.is_alive())
            sock.sendall.assert_any_call(b"PONG :tmi.twitch.tv\r\n")
            sender.disconnect()


class TwitchCacheRegressionTests(unittest.TestCase):
    def test_refresh_keeps_existing_refresh_token_when_not_rotated(self):
        response = Mock(status_code=200)
        response.json.return_value = {"access_token": "new", "expires_in": 3600}
        auth = TwitchAuth(Mock())
        with patch("platforms.twitch.twitch_auth.requests.post", return_value=response):
            self.assertEqual(auth.refresh_token("existing")["refresh_token"], "existing")

    def test_json_non_object_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "token.json"
            path.write_text("[]", encoding="utf-8")
            self.assertIsNone(TokenCache(path).load())

    def test_failed_save_preserves_previous_token_and_removes_temp_file(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = TokenCache(Path(folder) / "token.json")
            cache.save({"access_token": "previous"})
            with self.assertRaises(TypeError):
                cache.save({"unserializable": object()})
            self.assertEqual(cache.load(), {"access_token": "previous"})
            self.assertEqual(len(list(Path(folder).iterdir())), 1)

    def test_delayed_validation_cannot_restore_forgotten_login(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = TokenCache(Path(folder) / "token.json")
            cache.save({"access_token": "old"})
            cache.clear()
            self.assertFalse(cache.save_if_current("old", {"access_token": "old", "login": "user"}))
            self.assertFalse(cache.exists())


class TwitchBotRegressionTests(unittest.TestCase):
    def test_vip_subscriber_keeps_subscriber_flag(self):
        tts = Mock()
        bot = TwitchBot(tts)
        bot._on_message({"role": "vip", "tags": {"badges": "vip/1,subscriber/6", "subscriber": "1"}})
        payload = tts.handle_message.call_args.args[0]
        self.assertTrue(payload["is_sub"])
        self.assertEqual(payload["role"], "vip")

    def test_start_does_not_replace_worker_still_unwinding_after_stop(self):
        bot = TwitchBot(None)
        thread = Mock()
        thread.is_alive.return_value = True
        bot._thread = thread
        bot.stop()
        bot.start({"login": "new", "access_token": "token"})
        self.assertIs(bot._thread, thread)
        self.assertTrue(bot._stop_event.is_set())
        self.assertTrue(bot.is_running())
        self.assertEqual(bot.get_status(), "desconectando")

    def test_cancelled_connection_is_closed_before_listening(self):
        bot = TwitchBot(None)
        bot._token_data = {"login": "anonymous"}
        bot._public_mode = True
        bot._public_channel = "channel"
        client = Mock()
        client.connect.side_effect = bot._stop_event.set
        with patch("platforms.twitch.twitch_bot.TwitchIRCClient", return_value=client):
            bot._run_once()
        client.stop.assert_called_once()
        client.listen_forever.assert_not_called()

    def test_send_reports_sender_failure(self):
        bot = TwitchBot(None)
        bot._public_channel = "channel"
        bot.sender.send_message = Mock(return_value=False)
        with patch("platforms.twitch.twitch_bot.has_twitch_bot_sender_config", return_value=True):
            self.assertFalse(bot.send_chat_message("hello"))


if __name__ == "__main__":
    unittest.main()
