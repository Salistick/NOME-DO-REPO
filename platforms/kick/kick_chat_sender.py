import requests

from config import KICK_CLIENT_ID


KICK_CHAT_URL = "https://api.kick.com/public/v1/chat"


class KickChatSender:
    def __init__(self, token_provider, broadcaster_user_id_provider):
        self.token_provider = token_provider
        self.broadcaster_user_id_provider = broadcaster_user_id_provider

    def send_message(self, text: str) -> bool:
        text = " ".join((text or "").split()).strip()
        if not text:
            return False

        token_data = {}
        if callable(self.token_provider):
            token_data = self.token_provider() or {}

        access_token = (token_data.get("access_token") or "").strip()
        if not access_token:
            print("[KICK SENDER] Conta Kick nao autenticada. Mensagem nao enviada.")
            return False

        broadcaster_user_id = ""
        if callable(self.broadcaster_user_id_provider):
            broadcaster_user_id = str(self.broadcaster_user_id_provider() or "").strip()

        if not broadcaster_user_id:
            print("[KICK SENDER] broadcaster_user_id indisponivel. Mensagem nao enviada.")
            return False

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if KICK_CLIENT_ID:
            headers["Client-ID"] = KICK_CLIENT_ID
            headers["Client-Id"] = KICK_CLIENT_ID

        response = requests.post(
            KICK_CHAT_URL,
            headers=headers,
            json={
                "content": text[:500],
                "type": "user",
                "broadcaster_user_id": int(broadcaster_user_id),
            },
            timeout=(5, 15),
        )

        if response.status_code not in {200, 201, 202, 204}:
            print(
                f"[KICK SENDER] Falha ao enviar mensagem. "
                f"Status={response.status_code} Body={response.text[:300]}"
            )
            return False

        return True
