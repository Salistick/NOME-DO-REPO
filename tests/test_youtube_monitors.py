import signal
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from platforms.youtube.youtube_api_chat_monitor import (
    YOUTUBE_LIVE_CHAT_LIST_URL,
    YouTubeApiChatMonitor,
)
from platforms.youtube.youtube_bot import YouTubeBot
from platforms.youtube.youtube_chat_monitor import YouTubeChatMonitor


class YouTubeMonitorTests(unittest.TestCase):
    def test_public_monitor_uses_native_background_option_without_changing_signal(self):
        monitor = YouTubeChatMonitor("abcdefghijk", Mock())
        original = signal.signal
        with patch("platforms.youtube.youtube_chat_monitor.pytchat.create") as create:
            create.side_effect = lambda **kwargs: self.assertIs(signal.signal, original)
            monitor._create_chat_safe()
        create.assert_called_once_with(video_id="abcdefghijk", interruptable=False)

    def test_default_monitor_uses_documented_list_and_official_interval(self):
        monitor = YouTubeApiChatMonitor("chat", lambda: "token", Mock())
        monitor._running = True
        response = Mock(status_code=200)
        response.json.return_value = {"items": [], "pollingIntervalMillis": 7500}
        with (
            patch("platforms.youtube.youtube_api_chat_monitor.requests.get", return_value=response) as get,
            patch.object(monitor, "_sleep_interruptible", side_effect=lambda _seconds: setattr(monitor, "_running", False)) as sleep,
        ):
            monitor._run()
        self.assertEqual(get.call_args.args[0], YOUTUBE_LIVE_CHAT_LIST_URL)
        self.assertNotIn("stream", get.call_args.kwargs)
        sleep.assert_called_once_with(7.5)
        response.close.assert_called_once()

    def test_poll_response_is_closed_when_parsing_callback_fails(self):
        monitor = YouTubeApiChatMonitor("chat", lambda: "token", Mock())
        monitor._running = True
        response = Mock(status_code=200)
        response.json.return_value = {"items": [{"id": "a", "snippet": {"displayMessage": "hi"}}]}
        with (
            patch("platforms.youtube.youtube_api_chat_monitor.requests.get", return_value=response),
            patch.object(monitor, "on_message", side_effect=ValueError("callback")),
            self.assertRaises(ValueError),
        ):
            monitor._poll_once()
        response.close.assert_called_once()

    def test_poll_response_is_closed_when_json_is_invalid(self):
        monitor = YouTubeApiChatMonitor("chat", lambda: "token", Mock())
        response = Mock(status_code=200)
        response.json.side_effect = ValueError("invalid JSON")
        with (
            patch("platforms.youtube.youtube_api_chat_monitor.requests.get", return_value=response),
            self.assertRaises(ValueError),
        ):
            monitor._poll_once()
        response.close.assert_called_once()

    def test_stop_keeps_worker_reference_until_it_exits(self):
        for monitor in (
            YouTubeApiChatMonitor("chat", lambda: "token", Mock()),
            YouTubeChatMonitor("abcdefghijk", Mock()),
        ):
            with self.subTest(monitor=type(monitor).__name__):
                worker = Mock()
                worker.is_alive.return_value = True
                monitor._thread = worker
                monitor.stop()
                self.assertIs(monitor._thread, worker)
                with patch("threading.Thread") as new_thread:
                    monitor.start()
                new_thread.assert_not_called()

    def test_stop_from_callback_does_not_join_current_thread(self):
        monitor = YouTubeApiChatMonitor("chat", lambda: "token", Mock())
        monitor._thread = threading.current_thread()
        with patch.object(monitor._thread, "join") as join:
            monitor.stop()
        join.assert_not_called()

    def test_cancelled_payload_does_not_deliver_more_messages(self):
        callback = Mock()
        monitor = YouTubeApiChatMonitor("chat", lambda: "token", callback)
        monitor._running = True
        def cancel(_message):
            monitor._running = False
        callback.side_effect = cancel
        item = {"id": "a", "snippet": {"displayMessage": "hello"}}
        monitor._handle_payload({"items": [item, item]})
        self.assertEqual(callback.call_count, 1)


class YouTubeDiscoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name)
        self.bot = YouTubeBot(Mock(), path / "tokens.json", path / "config.json", path / "messages.json")
        self.bot._active_channel = {"channel_id": "channel"}
        self.bot._active_live = {"video_id": "previous"}
        self.bot._public_mode = True
        self.bot._should_reconnect = True
        self.bot.live_resolver = Mock()

    def test_missing_live_is_discovered_once_per_reconciliation(self):
        self.bot.live_resolver.resolve_public_active_live.return_value = None
        self.bot._reconcile_live_state()
        self.bot.live_resolver.resolve_public_active_live.assert_called_once_with("channel")

    def test_stop_during_discovery_does_not_start_new_monitor(self):
        def stop_during_discovery(_channel):
            self.bot._manual_stop = True
            return {"video_id": "new"}
        self.bot.live_resolver.resolve_public_active_live.side_effect = stop_during_discovery
        with patch.object(self.bot, "_create_chat_monitor_for_live") as create:
            self.bot._reconcile_live_state()
        create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
