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
        self._videos_url = "https://www.googleapis.com/youtube/v3/videos"
        self._live_cache = {
            "channel_id": None,
            "video_id": None,
            "title": None,
            "live_url": None,
            "source": None,
            "live_chat_id": None,
        }
        self._api_search_attempted_channels: set[str] = set()
        self._api_search_skip_logged_channels: set[str] = set()

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
            if access_token:
                cached = self._enrich_live_chat_id(cached, access_token)
                self._update_cache(channel_id, cached)
            return cached

        print(f"[YOUTUBE RESOLVER] Procurando live ativa | channel_id={channel_id}")

        if access_token and self._reserve_api_search_attempt(channel_id):
            live_data = self._resolve_from_youtube_api(channel_id, access_token)
            if live_data:
                live_data = self._enrich_live_chat_id(live_data, access_token)
                self._update_cache(channel_id, live_data)
                print(
                    f"[YOUTUBE RESOLVER] Live ativa encontrada via API | "
                    f"video_id={live_data['video_id']}"
                )
                return live_data
        elif access_token:
            if channel_id not in self._api_search_skip_logged_channels:
                self._api_search_skip_logged_channels.add(channel_id)
                print("[YOUTUBE RESOLVER] Busca oficial ja usada nesta sessao; usando polling publico.")

        live_data = self._resolve_from_live_endpoint(channel_id)
        if live_data:
            if access_token:
                live_data = self._enrich_live_chat_id(live_data, access_token)
            self._update_cache(channel_id, live_data)
            print(
                f"[YOUTUBE RESOLVER] Live ativa encontrada via /live | "
                f"video_id={live_data['video_id']}"
            )
            return live_data

        live_data = self._resolve_from_streams(channel_id)
        if live_data:
            if access_token:
                live_data = self._enrich_live_chat_id(live_data, access_token)
            self._update_cache(channel_id, live_data)
            print(
                f"[YOUTUBE RESOLVER] Live ativa encontrada via /streams | "
                f"video_id={live_data['video_id']}"
            )
            return live_data

        self._clear_cache_if_channel(channel_id)
        print("[YOUTUBE RESOLVER] Nenhuma live ativa encontrada.")
        return None

    def resolve_public_active_live(self, channel_identifier: str) -> dict | None:
        channel_identifier = (channel_identifier or "").strip()
        if not channel_identifier:
            raise ValueError("Nome ou URL do canal YouTube e obrigatorio.")

        cache_key = self._normalize_public_channel_identifier(channel_identifier)
        cached = self._resolve_from_cache(cache_key)
        if cached:
            return cached

        print(f"[YOUTUBE RESOLVER] Sem login: procurando live ativa no canal {channel_identifier}.")

        live_data = self._resolve_from_public_live_endpoint(channel_identifier)
        if live_data:
            self._update_cache(cache_key, live_data)
            print(
                f"[YOUTUBE RESOLVER] Live encontrada pela pagina publica /live | "
                f"video_id={live_data['video_id']}"
            )
            return live_data

        live_data = self._resolve_from_public_streams(channel_identifier)
        if live_data:
            self._update_cache(cache_key, live_data)
            print(
                f"[YOUTUBE RESOLVER] Live encontrada pela pagina publica /streams | "
                f"video_id={live_data['video_id']}"
            )
            return live_data

        self._clear_cache_if_channel(cache_key)
        print("[YOUTUBE RESOLVER] Nenhuma live ativa encontrada no canal publico.")
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
        elif cached_source in {"public_live_endpoint", "public_streams"}:
            live_data = self._revalidate_cache_from_public(channel_id, cached_video_id)
        else:
            live_data = None

        if live_data:
            cached_live_chat_id = (self._live_cache.get("live_chat_id") or "").strip()
            if cached_live_chat_id:
                live_data["live_chat_id"] = cached_live_chat_id
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

            live_data = self._build_live_data_from_stream_entry(entry, source="streams")
            if live_data:
                return live_data

            detailed = self._extract_info(self._build_watch_url(video_id))
            live_data = self._build_live_data_if_active(detailed, source="streams")
            if live_data:
                return live_data

        return None

    def _update_cache(self, channel_id: str, live_data: dict) -> None:
        self._live_cache = {
            "channel_id": channel_id,
            "video_id": live_data.get("video_id"),
            "title": live_data.get("title"),
            "live_url": live_data.get("live_url"),
            "source": live_data.get("source"),
            "live_chat_id": live_data.get("live_chat_id"),
        }

    def _clear_cache(self) -> None:
        self._live_cache = {
            "channel_id": None,
            "video_id": None,
            "title": None,
            "live_url": None,
            "source": None,
            "live_chat_id": None,
        }

    def _clear_cache_if_channel(self, channel_id: str) -> None:
        if self._live_cache.get("channel_id") == channel_id:
            self._clear_cache()

    # ==================================
    # Busca inicial
    # ==================================

    def _reserve_api_search_attempt(self, channel_id: str) -> bool:
        if channel_id in self._api_search_attempted_channels:
            return False

        self._api_search_attempted_channels.add(channel_id)
        return True

    def _resolve_from_youtube_api(self, channel_id: str, access_token: str) -> dict | None:
        print("[YOUTUBE RESOLVER] Tentando API do YouTube uma vez nesta sessao")

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

    def _enrich_live_chat_id(self, live_data: dict | None, access_token: str) -> dict | None:
        if not live_data:
            return live_data

        if (live_data.get("live_chat_id") or "").strip():
            return live_data

        video_id = (live_data.get("video_id") or "").strip()
        access_token = (access_token or "").strip()
        if not video_id or not access_token:
            return live_data

        try:
            response = requests.get(
                self._videos_url,
                params={
                    "part": "liveStreamingDetails",
                    "id": video_id,
                },
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=(3, 5),
            )
        except Exception as exc:
            print(f"[YOUTUBE RESOLVER] Falha buscando live_chat_id: {exc}")
            return live_data

        if response.status_code != 200:
            print(
                f"[YOUTUBE RESOLVER] API videos.list retornou status {response.status_code}: "
                f"{response.text[:300]}"
            )
            return live_data

        data = response.json()
        items = data.get("items") or []
        if not items:
            return live_data

        details = (items[0] or {}).get("liveStreamingDetails") or {}
        live_chat_id = (details.get("activeLiveChatId") or "").strip()
        if not live_chat_id:
            return live_data

        enriched = dict(live_data)
        enriched["live_chat_id"] = live_chat_id
        return enriched

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

            live_data = self._build_live_data_from_stream_entry(entry, source="streams")
            if live_data:
                return live_data

            detailed = self._extract_info(self._build_watch_url(video_id))
            live_data = self._build_live_data_if_active(detailed, source="streams")
            if live_data:
                return live_data

        return None

    def _resolve_from_public_live_endpoint(self, channel_identifier: str) -> dict | None:
        print("[YOUTUBE RESOLVER] Tentativa 1: checando o endereco publico /live.")
        live_url, _streams_url = self._build_public_channel_urls(channel_identifier)
        info = self._extract_info(live_url)
        return self._build_live_data_if_active(info, source="public_live_endpoint")

    def _resolve_from_public_streams(self, channel_identifier: str) -> dict | None:
        print("[YOUTUBE RESOLVER] Tentativa 2: checando a aba publica /streams.")
        _live_url, streams_url = self._build_public_channel_urls(channel_identifier)

        playlist_info = self._extract_info(streams_url)
        if not playlist_info:
            return None

        entries = playlist_info.get("entries") or []
        if not entries:
            return None

        for entry in entries[:8]:
            video_id = (entry.get("id") or "").strip()
            if not video_id:
                continue

            live_data = self._build_live_data_from_stream_entry(entry, source="public_streams")
            if live_data:
                return live_data

            detailed = self._extract_info(self._build_watch_url(video_id))
            live_data = self._build_live_data_if_active(detailed, source="public_streams")
            if live_data:
                return live_data

        return None

    def _revalidate_cache_from_public(self, channel_identifier: str, cached_video_id: str) -> dict | None:
        live_data = self._resolve_from_public_live_endpoint(channel_identifier)
        if live_data and (live_data.get("video_id") or "").strip() == cached_video_id:
            return live_data

        live_data = self._resolve_from_public_streams(channel_identifier)
        if live_data and (live_data.get("video_id") or "").strip() == cached_video_id:
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

    def _build_live_data_from_stream_entry(self, entry: dict | None, source: str) -> dict | None:
        if not entry:
            return None

        video_id = (entry.get("id") or "").strip()
        if not video_id:
            return None

        live_status = (entry.get("live_status") or "").strip()
        is_live = bool(entry.get("is_live"))

        if live_status != "is_live" and not is_live:
            return None

        return {
            "video_id": video_id,
            "title": entry.get("title") or "Live ativa",
            "source": source,
            "live_url": self._build_watch_url(video_id),
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

    def _build_watch_url(self, video_id: str) -> str:
        return f"https://www.youtube.com/watch?v={video_id}"

    def _build_public_channel_urls(self, channel_identifier: str) -> tuple[str, str]:
        value = self._normalize_public_channel_identifier(channel_identifier)

        if value.startswith("http://") or value.startswith("https://"):
            base = value.rstrip("/")
            if base.endswith("/live") or base.endswith("/streams"):
                base = base.rsplit("/", 1)[0]
        elif value.startswith("UC"):
            base = f"https://www.youtube.com/channel/{value}"
        elif value.startswith("@"):
            base = f"https://www.youtube.com/{value}"
        else:
            base = f"https://www.youtube.com/@{value.lstrip('@')}"

        return f"{base}/live", f"{base}/streams"

    def _normalize_public_channel_identifier(self, channel_identifier: str) -> str:
        return str(channel_identifier or "").strip().strip("/")
