import unittest
from unittest.mock import MagicMock, patch

import requests

from platforms.youtube.youtube_live_resolver import YouTubeLiveResolver


def response_for(payload):
    response = MagicMock()
    response.__enter__.return_value = response
    response.json.return_value = payload
    return response


class YouTubeOfficialDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.resolver = YouTubeLiveResolver()
        self.channel = "UC-channel"

    def test_owned_broadcast_uses_official_api_without_public_extraction(self):
        response = response_for({"items": [{
            "id": "live", "snippet": {"channelId": self.channel, "liveChatId": "chat", "title": "Title"},
        }]})
        with (
            patch("platforms.youtube.youtube_live_resolver.requests.get", return_value=response) as get,
            patch.object(self.resolver, "_extract_info", side_effect=AssertionError("unexpected scraping")),
        ):
            live = self.resolver.resolve_active_live(self.channel, "token")
        self.assertEqual(live["live_chat_id"], "chat")
        self.assertEqual(live["source"], "youtube_official")
        self.assertEqual(get.call_args.kwargs["params"]["broadcastStatus"], "active")
        self.assertNotIn("mine", get.call_args.kwargs["params"])
        response.__exit__.assert_called_once()

    def test_cached_live_is_revalidated_without_scraping(self):
        self.resolver._update_cache(self.channel, {"video_id": "live", "source": "streams"})
        response = response_for({"items": [{
            "id": "live", "snippet": {"channelId": self.channel, "title": "Title"},
            "liveStreamingDetails": {"activeLiveChatId": "chat"},
        }]})
        with (
            patch("platforms.youtube.youtube_live_resolver.requests.get", return_value=response) as get,
            patch.object(self.resolver, "_extract_info", side_effect=AssertionError("unexpected scraping")),
        ):
            live = self.resolver.resolve_active_live(self.channel, "token")
        self.assertEqual(live["video_id"], "live")
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.args[0], self.resolver._videos_url)

    def test_owned_broadcast_does_not_select_another_channel(self):
        response = response_for({"items": [{
            "id": "other", "snippet": {"channelId": "different", "liveChatId": "other-chat"},
        }]})
        with patch("platforms.youtube.youtube_live_resolver.requests.get", return_value=response):
            self.assertIsNone(self.resolver._resolve_owned_broadcast(self.channel, "token"))

    def test_official_discovery_follows_pages_and_rejects_repeated_token(self):
        response = response_for({"items": [], "nextPageToken": "same"})
        with patch("platforms.youtube.youtube_live_resolver.requests.get", return_value=response) as get:
            self.assertIsNone(self.resolver._resolve_owned_broadcast(self.channel, "token"))
        self.assertEqual(get.call_count, 2)

    def test_official_failure_preserves_public_discovery(self):
        self.resolver._api_search_attempted_channels.add(self.channel)
        with (
            patch("platforms.youtube.youtube_live_resolver.requests.get", side_effect=requests.ConnectionError("offline")),
            patch.object(self.resolver, "_resolve_from_live_endpoint", return_value={"video_id": "public", "live_chat_id": "chat"}) as public,
        ):
            live = self.resolver.resolve_active_live(self.channel, "token")
        public.assert_called_once_with(self.channel)
        self.assertEqual(live["video_id"], "public")

    def test_ended_cached_video_is_not_confirmed_as_active(self):
        self.resolver._update_cache(self.channel, {"video_id": "live", "source": "youtube_official"})
        response = response_for({"items": [{
            "snippet": {"channelId": self.channel},
            "liveStreamingDetails": {"activeLiveChatId": "chat", "actualEndTime": "2026-10-29T00:00:00Z"},
        }]})
        with patch("platforms.youtube.youtube_live_resolver.requests.get", return_value=response):
            self.assertIsNone(self.resolver._resolve_official_cached_live(self.channel, "token"))


if __name__ == "__main__":
    unittest.main()
