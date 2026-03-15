import requests
from yt_dlp import YoutubeDL


class _SilentYTDLPLogger:
    def debug(self, msg):
        return

    def warning(self, msg):
        return

    def error(self, msg):
        return


class YouTubeLiveResolver:
    def __init__(self):
        self._ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": False,
            "playlistend": 8,
            "logger": _SilentYTDLPLogger(),
        }
        self._search_url = "https://www.googleapis.com/youtube/v3/search"
        self._live_cache = {
            "channel_id": None,
            "video_id": None,
            "title": None,
            "live_url": None,
            "source": None,
        }

    # ==================================
    # Public API
    # ==================================

    def resolve_active_live(self, channel_id: str, access_token: str = "") -> dict | None:
        channel_id = (channel_id or "").strip()
        access_token = (access_token or "").strip()

        if not channel_id:
            raise ValueError("channel_id e obrigatorio.")

        cached = self._resolve_from_cache(channel_id)
        if cached:
            return cached

        print(f"[YOUTUBE RESOLVER] Procurando live ativa | channel_id={channel_id}")

        if access_token:
            live_data = self._resolve_from_youtube_api(channel_id, access_token)
            if live_data:
                self._update_cache(channel_id, live_data)
                print(
                    f"[YOUTUBE RESOLVER] Live ativa encontrada via API | "
                    f"video_id={live_data['video_id']}"
                )
                return live_data

        live_data = self._resolve_from_live_endpoint(channel_id)
        if live_data:
            self._update_cache(channel_id, live_data)
            print(
                f"[YOUTUBE RESOLVER] Live ativa encontrada via /live | "
                f"video_id={live_data['video_id']}"
            )
            return live_data

        live_data = self._resolve_from_streams(channel_id)
        if live_data:
            self._update_cache(channel_id, live_data)
            print(
                f"[YOUTUBE RESOLVER] Live ativa encontrada via /streams | "
                f"video_id={live_data['video_id']}"
            )
            return live_data

        self._clear_cache_if_channel(channel_id)
        print("[YOUTUBE RESOLVER] Nenhuma live ativa encontrada.")
        return None

    # ==================================
    # Cache
    # ==================================

    def _resolve_from_cache(self, channel_id: str) -> dict | None:
        cached_channel_id = self._live_cache.get("channel_id")
        cached_video_id = self._live_cache.get("video_id")
        cached_source = self._live_cache.get("source")

        if cached_channel_id != channel_id or not cached_video_id or not cached_source:
            return None

        print(
            f"[YOUTUBE RESOLVER] Revalidando cache | "
            f"source={cached_source} | video_id={cached_video_id}"
        )

        if cached_source == "live_endpoint":
            live_data = self._revalidate_cache_from_live_endpoint(channel_id, cached_video_id)
        elif cached_source == "streams":
            live_data = self._revalidate_cache_from_streams(channel_id, cached_video_id)
        elif cached_source == "youtube_api":
            live_data = self._revalidate_cache_from_live_endpoint(channel_id, cached_video_id)
            if not live_data:
                live_data = self._revalidate_cache_from_streams(channel_id, cached_video_id)
        else:
            live_data = None

        if live_data:
            print(f"[YOUTUBE RESOLVER] Cache confirmado | video_id={cached_video_id}")
            return live_data

        print("[YOUTUBE RESOLVER] Cache invalido.")
        self._clear_cache()
        return None

    def _revalidate_cache_from_live_endpoint(self, channel_id: str, cached_video_id: str) -> dict | None:
        info = self._extract_info(f"https://www.youtube.com/channel/{channel_id}/live")
        live_data = self._build_live_data_if_active(info, source="live_endpoint")

        if not live_data:
            return None

        if (live_data.get("video_id") or "").strip() != cached_video_id:
            return None

        return live_data

    def _revalidate_cache_from_streams(self, channel_id: str, cached_video_id: str) -> dict | None:
        playlist_info = self._extract_info(f"https://www.youtube.com/channel/{channel_id}/streams")
        if not playlist_info:
            return None

        entries = playlist_info.get("entries") or []
        if not entries:
            return None

        for entry in entries[:8]:
            video_id = (entry.get("id") or "").strip()
            if not video_id or video_id != cached_video_id:
                continue

            candidate_url = entry.get("url") or f"https://www.youtube.com/watch?v={video_id}"
            detailed = self._extract_info(candidate_url)
            return self._build_live_data_if_active(detailed, source="streams")

        return None

    def _update_cache(self, channel_id: str, live_data: dict) -> None:
        self._live_cache = {
            "channel_id": channel_id,
            "video_id": live_data.get("video_id"),
            "title": live_data.get("title"),
            "live_url": live_data.get("live_url"),
            "source": live_data.get("source"),
        }

    def _clear_cache(self) -> None:
        self._live_cache = {
            "channel_id": None,
            "video_id": None,
            "title": None,
            "live_url": None,
            "source": None,
        }

    def _clear_cache_if_channel(self, channel_id: str) -> None:
        if self._live_cache.get("channel_id") == channel_id:
            self._clear_cache()

    # ==================================
    # Busca inicial
    # ==================================

    def _resolve_from_youtube_api(self, channel_id: str, access_token: str) -> dict | None:
        print("[YOUTUBE RESOLVER] Tentando API do YouTube")

        try:
            response = requests.get(
                self._search_url,
                params={
                    "part": "id,snippet",
                    "channelId": channel_id,
                    "eventType": "live",
                    "maxResults": 1,
                    "order": "date",
                    "type": "video",
                },
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=(3, 5),
            )
        except Exception as exc:
            print(f"[YOUTUBE RESOLVER] Falha chamando API do YouTube: {exc}")
            return None

        if response.status_code != 200:
            print(
                f"[YOUTUBE RESOLVER] API do YouTube retornou status {response.status_code}: "
                f"{response.text}"
            )
            return None

        data = response.json()
        items = data.get("items") or []
        if not items:
            return None

        item = items[0] or {}
        item_id = item.get("id") or {}
        snippet = item.get("snippet") or {}

        video_id = (item_id.get("videoId") or "").strip()
        if not video_id:
            return None

        return {
            "video_id": video_id,
            "title": snippet.get("title") or "Live ativa",
            "source": "youtube_api",
            "live_url": f"https://www.youtube.com/watch?v={video_id}",
        }

    def _resolve_from_live_endpoint(self, channel_id: str) -> dict | None:
        print("[YOUTUBE RESOLVER] Tentando /live")
        info = self._extract_info(f"https://www.youtube.com/channel/{channel_id}/live")
        return self._build_live_data_if_active(info, source="live_endpoint")

    def _resolve_from_streams(self, channel_id: str) -> dict | None:
        print("[YOUTUBE RESOLVER] Tentando /streams")

        playlist_info = self._extract_info(f"https://www.youtube.com/channel/{channel_id}/streams")
        if not playlist_info:
            return None

        entries = playlist_info.get("entries") or []
        if not entries:
            return None

        for entry in entries[:8]:
            video_id = (entry.get("id") or "").strip()
            if not video_id:
                continue

            candidate_url = entry.get("url") or f"https://www.youtube.com/watch?v={video_id}"
            detailed = self._extract_info(candidate_url)
            live_data = self._build_live_data_if_active(detailed, source="streams")
            if live_data:
                return live_data

        return None

    # ==================================
    # Validacao central
    # ==================================

    def _build_live_data_if_active(self, info: dict | None, source: str) -> dict | None:
        if not info:
            return None

        video_id = (info.get("id") or "").strip()
        if not video_id:
            return None

        live_status = (info.get("live_status") or "").strip()
        is_live = bool(info.get("is_live"))

        if live_status != "is_live" and not is_live:
            return None

        return {
            "video_id": video_id,
            "title": info.get("title") or "Live ativa",
            "source": source,
            "live_url": info.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}",
        }

    # ==================================
    # Utils
    # ==================================

    def _extract_info(self, url: str) -> dict | None:
        try:
            with YoutubeDL(self._ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)
        except Exception:
            return None
