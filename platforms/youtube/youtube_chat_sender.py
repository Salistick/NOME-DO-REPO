import requests


YOUTUBE_LIVE_CHAT_MESSAGES_URL = "https://www.googleapis.com/youtube/v3/liveChat/messages"


class YouTubeChatSender:
    def __init__(self, access_token_provider):
        self.access_token_provider = access_token_provider

    def send_message(self, live_chat_id: str, text: str) -> bool:
        live_chat_id = (live_chat_id or "").strip()
        text = " ".join((text or "").split()).strip()

        if not live_chat_id or not text:
            return False

        token = ""
        if callable(self.access_token_provider):
            token = (self.access_token_provider() or "").strip()

        if not token:
            print("[YOUTUBE SENDER] Token OAuth indisponivel. Mensagem nao enviada.")
            return False

        response = requests.post(
            YOUTUBE_LIVE_CHAT_MESSAGES_URL,
            params={"part": "snippet"},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={
                "snippet": {
                    "liveChatId": live_chat_id,
                    "type": "textMessageEvent",
                    "textMessageDetails": {
                        "messageText": text[:200],
                    },
                }
            },
            timeout=(5, 15),
        )

        if response.status_code not in {200, 201}:
            print(
                f"[YOUTUBE SENDER] Falha ao enviar mensagem. "
                f"Status={response.status_code} Body={response.text[:300]}"
            )
            return False

        return True
