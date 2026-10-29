import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from platforms.kick.kick_auth import KickAuth
from platforms.kick.kick_bot import KickBot
from platforms.kick.kick_chat_sender import KickChatSender
from platforms.kick.kick_pusher_client import KickPusherClient
from platforms.kick.kick_pusher_event_mapper import map_kick_pusher_chat_message_event


class KickRoleRegressionTests(unittest.TestCase):
    def event(self, **sender):
        return map_kick_pusher_chat_message_event(
            {"content": "hello", "sender": {"username": "viewer", **sender}}, channel_slug="channel"
        )

    def test_substrings_do_not_grant_admin_or_subscriber_privileges(self):
        for label in ("non-subscriber", "model", "unsubscribed"):
            with self.subTest(label=label):
                event = self.event(badges=[{"type": label}])
                self.assertFalse(event.is_mod)
                self.assertFalse(event.is_sub)
                self.assertEqual(event.role, "viewer")

    def test_inactive_membership_metadata_does_not_grant_subscriber_privilege(self):
        for value in ({"active": False}, {"status": "expired"}, {"id": 123}, [{"is_active": False}]):
            with self.subTest(value=value):
                self.assertFalse(self.event(membership=value).is_sub)

    def test_explicit_roles_and_active_memberships_remain_supported(self):
        self.assertTrue(self.event(badges=[{"type": "moderator"}]).is_mod)
        self.assertTrue(self.event(identity={"badges": [{"type": "subscriber", "count": 6}]}).is_sub)
        self.assertTrue(self.event(membership={"active": True}).is_sub)
        self.assertTrue(self.event(roles="moderator,subscriber").is_mod)


class KickLifecycleRegressionTests(unittest.TestCase):
    def test_non_object_websocket_json_is_ignored(self):
        client = KickPusherClient(None)
        for raw in ("[]", "null", "42", '"text"', "{invalid"):
            client._handle_frame(raw)
        self.assertFalse(client._connected_event.is_set())

    def test_wait_until_connected_returns_immediately_after_stop(self):
        client = KickPusherClient(None)
        client._stop_event.set()
        with patch.object(client._connected_event, "wait") as wait:
            self.assertFalse(client.wait_until_connected(timeout=10))
        wait.assert_not_called()

    def test_stop_retains_live_worker_so_restart_cannot_revive_it(self):
        client = KickPusherClient(None)
        thread = Mock()
        thread.is_alive.return_value = True
        client._thread = thread
        client.stop()
        with patch.object(client, "resolve_channel", return_value={"chatroom_id": "123"}):
            client.start("channel")
        self.assertIs(client._thread, thread)
        self.assertTrue(client._stop_event.is_set())
        self.assertEqual(client.get_status(), "desconectando")

    def test_cancellation_during_channel_resolution_prevents_new_worker(self):
        client = KickPusherClient(None)
        cancelled = threading.Event()

        def resolve(_slug):
            cancelled.set()
            return {"chatroom_id": "123"}

        with patch.object(client, "resolve_channel", side_effect=resolve):
            client.start("channel", cancel_event=cancelled)
        self.assertIsNone(client._thread)

    def test_socket_finishing_connect_after_stop_is_closed(self):
        client = KickPusherClient(None)
        client._stop_event.set()
        ws = Mock()
        with patch("platforms.kick.kick_pusher_client.websocket.create_connection", return_value=ws):
            client._connect_once()
        ws.close.assert_called_once()
        ws.recv.assert_not_called()
        self.assertIsNone(client._ws)

    def test_kick_bot_retains_its_pending_worker(self):
        bot = KickBot(None)
        bot.pusher_client = Mock()
        thread = Mock()
        thread.is_alive.return_value = True
        bot._thread = thread
        bot.stop()
        bot.start(force_auth=False, channel_slug="new")
        self.assertIs(bot._thread, thread)
        self.assertTrue(bot._cancel_event.is_set())
        self.assertTrue(bot.is_running())
        self.assertEqual(bot.get_status(), "desconectando")


class KickAuthRegressionTests(unittest.TestCase):
    def test_failed_cache_write_preserves_previous_token(self):
        with tempfile.TemporaryDirectory() as folder:
            auth = KickAuth(Path(folder) / "token.json")
            auth.save_token_cache({"access_token": "previous"})
            with self.assertRaises(TypeError):
                auth.save_token_cache({"bad": object()})
            self.assertEqual(auth.load_token_cache(), {"access_token": "previous"})
            self.assertEqual(len(list(Path(folder).iterdir())), 1)

    def test_invalid_expiry_in_cache_can_still_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            auth = KickAuth(Path(folder) / "token.json")
            auth.save_token_cache({"access_token": "old", "refresh_token": "refresh", "expires_at": "invalid"})
            with patch.object(auth, "refresh_token", return_value={"access_token": "new"}), patch.object(
                auth, "_attach_profile", side_effect=lambda token: token
            ):
                self.assertEqual(auth.get_valid_cached_token()["access_token"], "new")

    def test_non_object_profile_response_does_not_crash_login(self):
        with tempfile.TemporaryDirectory() as folder:
            auth = KickAuth(Path(folder) / "token.json")
            token = {"access_token": "token"}
            response = Mock(status_code=200)
            response.json.return_value = []
            with patch("platforms.kick.kick_auth.requests.get", return_value=response):
                self.assertEqual(auth._attach_profile(token), token)


class KickSenderRegressionTests(unittest.TestCase):
    def test_network_failure_returns_false_instead_of_killing_message_callback(self):
        sender = KickChatSender(lambda: {"access_token": "token"}, lambda: "123")
        with patch("platforms.kick.kick_chat_sender.requests.post", side_effect=requests.Timeout("timeout")):
            self.assertFalse(sender.send_message("hello"))

    def test_invalid_broadcaster_id_does_not_send_request(self):
        sender = KickChatSender(lambda: {"access_token": "token"}, lambda: "invalid")
        with patch("platforms.kick.kick_chat_sender.requests.post") as post:
            self.assertFalse(sender.send_message("hello"))
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
