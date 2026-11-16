import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from platforms.kick.kick_auth import KickAuth
from platforms.oauth_callback import OAuthCallbackServer
from platforms.twitch.twitch_auth import TwitchAuth
from platforms.twitch.twitch_sender import TwitchChatSender
from platforms.youtube.youtube_auth import YouTubeAuth


class OAuthCallbackTests(unittest.TestCase):
    def test_localhost_listener_binds_to_the_loopback_address(self):
        callback = OAuthCallbackServer("http://localhost:8790/signin", "expected")
        with patch("platforms.oauth_callback.ThreadingHTTPServer") as server, patch(
            "platforms.oauth_callback.threading.Thread"
        ):
            try:
                callback.start()
                self.assertEqual(server.call_args.args[0], ("127.0.0.1", 8790))
            finally:
                callback.stop()

    def test_rejects_nonlocal_or_invalid_callback_urls(self):
        for uri in (
            "http://example.invalid:8790/callback",
            "http://0.0.0.0:8790/callback",
            "http://localhost:0/callback",
            "http://user@localhost:8790/callback",
            "https://localhost:8790/callback",
        ):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                OAuthCallbackServer(uri, "expected")

    def test_invalid_response_does_not_complete_login_and_valid_response_is_recorded_once(self):
        callback = OAuthCallbackServer("http://127.0.0.1:8790/callback", "expected")

        status, _ = callback._accept_response({"state": ["unexpected"], "code": ["other"]})
        self.assertEqual(status, 400)
        self.assertEqual(callback.wait_for_code(timeout=0), (None, "timeout"))

        status, _ = callback._accept_response({"state": ["expected"], "code": ["first"]})
        self.assertEqual(status, 200)
        status, _ = callback._accept_response({"state": ["expected"], "code": ["second"]})
        self.assertEqual(status, 409)
        self.assertEqual(callback.wait_for_code(timeout=0), ("first", None))

    def test_cancelled_login_returns_without_a_code(self):
        callback = OAuthCallbackServer("http://localhost:8790/callback", "expected")
        cancelled = threading.Event()
        cancelled.set()

        self.assertEqual(callback.wait_for_code(cancel_event=cancelled), (None, "cancelled"))


class OAuthTokenRequestTests(unittest.TestCase):
    def test_token_requests_reject_redirects_without_including_provider_body(self):
        twitch = TwitchAuth(Mock())
        twitch_sender = TwitchChatSender()
        youtube = YouTubeAuth(Path("unused.json"), Mock())
        kick = KickAuth(Path("unused.json"))
        operations = (
            (twitch.exchange_code_for_token, ("code",)),
            (twitch.refresh_token, ("refresh",)),
            (twitch_sender._refresh_token, ("refresh",)),
            (youtube.exchange_code_for_token, ("code",)),
            (youtube.refresh_token, ("refresh",)),
            (kick.exchange_code_for_token, ("code", "verifier")),
            (kick.refresh_token, ("refresh",)),
        )
        response = Mock(status_code=307, text="provider-response-body")

        for operation, arguments in operations:
            with self.subTest(operation=operation.__qualname__), patch(
                "requests.post", return_value=response
            ) as post:
                with self.assertRaisesRegex(RuntimeError, "HTTP 307") as error:
                    operation(*arguments)
                self.assertNotIn(response.text, str(error.exception))
                self.assertIs(post.call_args.kwargs["allow_redirects"], False)


if __name__ == "__main__":
    unittest.main()
