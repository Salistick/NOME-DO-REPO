import ctypes
import json
import os
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from config import (
    AWS_POLLY_CONFIG_FILE,
    AWS_POLLY_SECRET_FILE,
    POLLY_ENGINE,
    POLLY_OUTPUT_FORMAT,
    POLLY_SAMPLE_RATE,
    POLLY_VOICE_ID,
)

POLLY_SOURCE_ACCESS_KEY = "access_key"
POLLY_SOURCE_SSO = "sso"
POLLY_SOURCE_PROFILE = "profile"
SUPPORTED_POLLY_SOURCES = {POLLY_SOURCE_ACCESS_KEY, POLLY_SOURCE_SSO, POLLY_SOURCE_PROFILE}

SSO_ACCOUNT_SCOPE = "sso:account:access"
SSO_DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
SSO_REFRESH_GRANT = "refresh_token"
BOTO_CLIENT_CONFIG = Config(
    connect_timeout=5,
    read_timeout=20,
    retries={"max_attempts": 3, "mode": "standard"},
)
POLLY_CREDENTIAL_RECOVERABLE_ERRORS = (
    RuntimeError,
    OSError,
    ValueError,
    TypeError,
    KeyError,
    BotoCoreError,
    ClientError,
)


class PollyCredentialsError(RuntimeError):
    pass


@dataclass
class PollyCredentialConfig:
    source: str
    region: str
    access_key_id: str = ""
    sso_start_url: str = ""
    sso_region: str = ""
    sso_account_id: str = ""
    sso_account_name: str = ""
    sso_role_name: str = ""
    profile_name: str = ""
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "region": self.region,
            "access_key_id": self.access_key_id,
            "sso_start_url": self.sso_start_url,
            "sso_region": self.sso_region,
            "sso_account_id": self.sso_account_id,
            "sso_account_name": self.sso_account_name,
            "sso_role_name": self.sso_role_name,
            "profile_name": self.profile_name,
            "updated_at": self.updated_at or int(time.time()),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PollyCredentialConfig | None":
        if not isinstance(data, dict):
            return None

        source = str(data.get("source") or "").strip().lower()
        region = str(data.get("region") or "").strip()

        if source not in SUPPORTED_POLLY_SOURCES or not region:
            return None

        return cls(
            source=source,
            region=region,
            access_key_id=str(data.get("access_key_id") or "").strip(),
            sso_start_url=str(data.get("sso_start_url") or "").strip(),
            sso_region=str(data.get("sso_region") or "").strip(),
            sso_account_id=str(data.get("sso_account_id") or "").strip(),
            sso_account_name=str(data.get("sso_account_name") or "").strip(),
            sso_role_name=str(data.get("sso_role_name") or "").strip(),
            profile_name=str(data.get("profile_name") or "").strip(),
            updated_at=int(data.get("updated_at") or 0),
        )


class PollyCredentialStore:
    def __init__(
        self,
        config_file: Path = AWS_POLLY_CONFIG_FILE,
        secret_file: Path = AWS_POLLY_SECRET_FILE,
    ):
        self.config_file = Path(config_file)
        self.secret_file = Path(secret_file)
        self.config_file.parent.mkdir(parents=True, exist_ok=True)

    def load_config(self) -> PollyCredentialConfig | None:
        try:
            if not self.config_file.exists():
                return None
            raw = json.loads(self.config_file.read_text(encoding="utf-8"))
            return PollyCredentialConfig.from_dict(raw)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None

    def has_saved_configuration(self) -> bool:
        config = self.load_config()
        if not config:
            return False
        if config.source == POLLY_SOURCE_ACCESS_KEY:
            return bool(config.access_key_id and self.secret_file.exists())
        if config.source == POLLY_SOURCE_SSO:
            return bool(
                config.sso_start_url
                and config.sso_region
                and config.sso_account_id
                and config.sso_role_name
                and self.secret_file.exists()
            )
        if config.source == POLLY_SOURCE_PROFILE:
            return bool(config.profile_name)
        return False

    def save_access_key(
        self,
        region: str,
        access_key_id: str,
        secret_access_key: str,
        session_token: str = "",
    ) -> None:
        region = self._require_text(region, "Regiao AWS")
        access_key_id = self._require_text(access_key_id, "Access key ID")
        secret_access_key = self._require_text(secret_access_key, "Secret access key")

        secret_data = {
            "secret_access_key": secret_access_key,
            "session_token": str(session_token or "").strip(),
        }
        self._write_protected_secret(secret_data)

        config = PollyCredentialConfig(
            source=POLLY_SOURCE_ACCESS_KEY,
            region=region,
            access_key_id=access_key_id,
            updated_at=int(time.time()),
        )
        self._write_config(config)

    def save_sso(
        self,
        region: str,
        start_url: str,
        sso_region: str,
        account_id: str,
        account_name: str,
        role_name: str,
    ) -> None:
        region = self._require_text(region, "Regiao do Polly")
        start_url = self._require_text(start_url, "URL do portal AWS")
        sso_region = self._require_text(sso_region, "Regiao do IAM Identity Center")
        account_id = self._require_text(account_id, "Conta AWS")
        role_name = self._require_text(role_name, "Role AWS")

        config = PollyCredentialConfig(
            source=POLLY_SOURCE_SSO,
            region=region,
            sso_start_url=start_url,
            sso_region=sso_region,
            sso_account_id=account_id,
            sso_account_name=str(account_name or "").strip(),
            sso_role_name=role_name,
            updated_at=int(time.time()),
        )
        self._write_config(config)

    def save_profile(self, region: str, profile_name: str) -> None:
        region = self._require_text(region, "Regiao AWS")
        profile_name = self._require_text(profile_name, "Nome do perfil AWS")

        config = PollyCredentialConfig(
            source=POLLY_SOURCE_PROFILE,
            region=region,
            profile_name=profile_name,
            updated_at=int(time.time()),
        )
        self._write_config(config)

        try:
            self.secret_file.unlink(missing_ok=True)
        except OSError as exc:
            print(f"[POLLY] nao foi possivel remover segredo antigo: {exc}")

    def clear(self) -> None:
        for path in (self.config_file, self.secret_file):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                print(f"[POLLY] nao foi possivel limpar {path}: {exc}")

    def create_client(self):
        config = self.load_config()
        if not config:
            raise PollyCredentialsError("Amazon Polly ainda nao foi configurado.")

        if config.source == POLLY_SOURCE_ACCESS_KEY:
            secret_data = self._read_protected_secret()
            secret_access_key = str(secret_data.get("secret_access_key") or "").strip()
            session_token = str(secret_data.get("session_token") or "").strip()

            if not secret_access_key:
                raise PollyCredentialsError("Secret access key do Amazon Polly nao encontrada.")

            kwargs = {
                "region_name": config.region,
                "aws_access_key_id": config.access_key_id,
                "aws_secret_access_key": secret_access_key,
            }
            if session_token:
                kwargs["aws_session_token"] = session_token

            return boto3.client("polly", config=BOTO_CLIENT_CONFIG, **kwargs)

        if config.source == POLLY_SOURCE_SSO:
            return self.create_sso_polly_client(config)

        if config.source == POLLY_SOURCE_PROFILE:
            session = boto3.Session(profile_name=config.profile_name, region_name=config.region)
            return session.client("polly")

        raise PollyCredentialsError("Origem de credenciais Polly invalida.")

    def validate_access_key(
        self,
        region: str,
        access_key_id: str,
        secret_access_key: str,
        session_token: str = "",
    ) -> None:
        region = self._require_text(region, "Regiao AWS")
        access_key_id = self._require_text(access_key_id, "Access key ID")
        secret_access_key = self._require_text(secret_access_key, "Secret access key")

        kwargs = {
            "region_name": region,
            "aws_access_key_id": access_key_id,
            "aws_secret_access_key": secret_access_key,
        }
        session_token = str(session_token or "").strip()
        if session_token:
            kwargs["aws_session_token"] = session_token

        client = boto3.client("polly", config=BOTO_CLIENT_CONFIG, **kwargs)
        validate_polly_client(client)

    def validate_profile(self, region: str, profile_name: str) -> None:
        region = self._require_text(region, "Regiao AWS")
        profile_name = self._require_text(profile_name, "Nome do perfil AWS")

        session = boto3.Session(profile_name=profile_name, region_name=region)
        validate_polly_client(session.client("polly", config=BOTO_CLIENT_CONFIG))

    def start_sso_browser_login(
        self,
        start_url: str,
        sso_region: str,
        status_callback=None,
    ) -> str:
        start_url = self._require_text(start_url, "URL do portal AWS")
        sso_region = self._require_text(sso_region, "Regiao do IAM Identity Center")

        oidc = boto3.client("sso-oidc", region_name=sso_region, config=BOTO_CLIENT_CONFIG)
        registration = oidc.register_client(
            clientName="TTSLive",
            clientType="public",
            scopes=[SSO_ACCOUNT_SCOPE],
        )
        authorization = oidc.start_device_authorization(
            clientId=registration["clientId"],
            clientSecret=registration["clientSecret"],
            startUrl=start_url,
        )

        login_url = authorization.get("verificationUriComplete") or authorization.get("verificationUri")
        if not login_url:
            raise PollyCredentialsError("AWS nao retornou URL de login.")

        if status_callback:
            status_callback("Abrindo navegador para login AWS...")

        webbrowser.open(login_url)

        access_data = self._poll_sso_device_authorization(
            oidc=oidc,
            registration=registration,
            authorization=authorization,
            status_callback=status_callback,
        )
        self._write_protected_secret(access_data)
        return access_data["sso_access_token"]

    def list_sso_accounts(self, sso_region: str, access_token: str) -> list[dict[str, str]]:
        sso = boto3.client("sso", region_name=sso_region, config=BOTO_CLIENT_CONFIG)
        accounts: list[dict[str, str]] = []
        next_token = None

        while True:
            kwargs = {"accessToken": access_token, "maxResults": 100}
            if next_token:
                kwargs["nextToken"] = next_token
            response = sso.list_accounts(**kwargs)
            accounts.extend(response.get("accountList") or [])
            next_token = response.get("nextToken")
            if not next_token:
                return accounts

    def list_sso_roles(
        self,
        sso_region: str,
        access_token: str,
        account_id: str,
    ) -> list[dict[str, str]]:
        account_id = self._require_text(account_id, "Conta AWS")
        sso = boto3.client("sso", region_name=sso_region, config=BOTO_CLIENT_CONFIG)
        roles: list[dict[str, str]] = []
        next_token = None

        while True:
            kwargs = {
                "accessToken": access_token,
                "accountId": account_id,
                "maxResults": 100,
            }
            if next_token:
                kwargs["nextToken"] = next_token
            response = sso.list_account_roles(**kwargs)
            roles.extend(response.get("roleList") or [])
            next_token = response.get("nextToken")
            if not next_token:
                return roles

    def validate_sso_role(
        self,
        region: str,
        sso_region: str,
        access_token: str,
        account_id: str,
        role_name: str,
    ) -> None:
        client = self.create_sso_polly_client_from_token(
            region=region,
            sso_region=sso_region,
            access_token=access_token,
            account_id=account_id,
            role_name=role_name,
        )
        validate_polly_client(client)

    def create_sso_polly_client(self, config: PollyCredentialConfig):
        access_token = self._get_sso_access_token(config)
        return self.create_sso_polly_client_from_token(
            region=config.region,
            sso_region=config.sso_region,
            access_token=access_token,
            account_id=config.sso_account_id,
            role_name=config.sso_role_name,
        )

    def create_sso_polly_client_from_token(
        self,
        region: str,
        sso_region: str,
        access_token: str,
        account_id: str,
        role_name: str,
    ):
        region = self._require_text(region, "Regiao do Polly")
        sso_region = self._require_text(sso_region, "Regiao do IAM Identity Center")
        access_token = self._require_text(access_token, "Token do IAM Identity Center")
        account_id = self._require_text(account_id, "Conta AWS")
        role_name = self._require_text(role_name, "Role AWS")

        sso = boto3.client("sso", region_name=sso_region, config=BOTO_CLIENT_CONFIG)
        response = sso.get_role_credentials(
            roleName=role_name,
            accountId=account_id,
            accessToken=access_token,
        )
        credentials = response.get("roleCredentials") or {}
        if not (
            credentials.get("accessKeyId")
            and credentials.get("secretAccessKey")
            and credentials.get("sessionToken")
        ):
            raise PollyCredentialsError("A role AWS selecionada nao retornou credenciais temporarias.")

        return boto3.client(
            "polly",
            region_name=region,
            aws_access_key_id=credentials.get("accessKeyId"),
            aws_secret_access_key=credentials.get("secretAccessKey"),
            aws_session_token=credentials.get("sessionToken"),
            config=BOTO_CLIENT_CONFIG,
        )

    def describe_configuration(self) -> str:
        config = self.load_config()
        if not config:
            return "Amazon Polly nao configurado"
        if config.source == POLLY_SOURCE_ACCESS_KEY:
            return f"Amazon Polly via chave IAM ({config.access_key_id}) em {config.region}"
        if config.source == POLLY_SOURCE_SSO:
            account_label = config.sso_account_name or config.sso_account_id
            return f"Amazon Polly via login AWS ({account_label}/{config.sso_role_name}) em {config.region}"
        if config.source == POLLY_SOURCE_PROFILE:
            return f"Amazon Polly via perfil AWS ({config.profile_name}) em {config.region}"
        return "Amazon Polly configurado"

    def _poll_sso_device_authorization(
        self,
        oidc,
        registration: dict[str, Any],
        authorization: dict[str, Any],
        status_callback=None,
    ) -> dict[str, Any]:
        expires_at = time.time() + int(authorization.get("expiresIn") or 600)
        interval = max(1, int(authorization.get("interval") or 5))
        device_code = authorization.get("deviceCode")

        if not device_code:
            raise PollyCredentialsError("AWS nao retornou codigo de dispositivo.")

        while time.time() < expires_at:
            try:
                if status_callback:
                    status_callback("Aguardando login no navegador...")

                response = oidc.create_token(
                    clientId=registration["clientId"],
                    clientSecret=registration["clientSecret"],
                    grantType=SSO_DEVICE_GRANT,
                    deviceCode=device_code,
                )
                return self._build_sso_secret_data(registration, response)

            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code in {"AuthorizationPendingException", "authorization_pending"}:
                    time.sleep(interval)
                    continue
                if code in {"SlowDownException", "slow_down"}:
                    interval += 5
                    time.sleep(interval)
                    continue
                if code in {"ExpiredTokenException", "expired_token"}:
                    raise PollyCredentialsError("O login AWS expirou. Tente novamente.") from exc
                raise

        raise PollyCredentialsError("Tempo de login AWS expirado.")

    def _get_sso_access_token(self, config: PollyCredentialConfig) -> str:
        secret_data = self._read_protected_secret()
        access_token = str(secret_data.get("sso_access_token") or "").strip()
        expires_at = int(secret_data.get("sso_token_expires_at") or 0)

        if access_token and expires_at > int(time.time()) + 60:
            return access_token

        refreshed = self._refresh_sso_access_token(config, secret_data)
        return str(refreshed.get("sso_access_token") or "").strip()

    def _refresh_sso_access_token(
        self,
        config: PollyCredentialConfig,
        secret_data: dict[str, Any],
    ) -> dict[str, Any]:
        refresh_token = str(secret_data.get("sso_refresh_token") or "").strip()
        client_id = str(secret_data.get("sso_client_id") or "").strip()
        client_secret = str(secret_data.get("sso_client_secret") or "").strip()

        if not (refresh_token and client_id and client_secret):
            raise PollyCredentialsError(
                "Sessao AWS expirada. Clique em Configurar Amazon Polly e faça login novamente."
            )

        oidc = boto3.client("sso-oidc", region_name=config.sso_region, config=BOTO_CLIENT_CONFIG)

        try:
            response = oidc.create_token(
                clientId=client_id,
                clientSecret=client_secret,
                grantType=SSO_REFRESH_GRANT,
                refreshToken=refresh_token,
            )
        except ClientError as exc:
            raise PollyCredentialsError(
                "Sessao AWS expirada. Clique em Configurar Amazon Polly e faça login novamente."
            ) from exc

        updated = self._build_sso_secret_data(
            {
                "clientId": client_id,
                "clientSecret": client_secret,
                "clientSecretExpiresAt": secret_data.get("sso_client_secret_expires_at") or 0,
            },
            response,
            fallback_refresh_token=refresh_token,
        )
        self._write_protected_secret(updated)
        return updated

    @staticmethod
    def _build_sso_secret_data(
        registration: dict[str, Any],
        token_response: dict[str, Any],
        fallback_refresh_token: str = "",
    ) -> dict[str, Any]:
        now = int(time.time())
        return {
            "sso_access_token": token_response.get("accessToken", ""),
            "sso_token_expires_at": now + int(token_response.get("expiresIn") or 0),
            "sso_refresh_token": token_response.get("refreshToken") or fallback_refresh_token,
            "sso_client_id": registration.get("clientId", ""),
            "sso_client_secret": registration.get("clientSecret", ""),
            "sso_client_secret_expires_at": int(registration.get("clientSecretExpiresAt") or 0),
        }

    def _write_config(self, config: PollyCredentialConfig) -> None:
        self.config_file.write_text(
            json.dumps(config.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _write_protected_secret(self, data: dict[str, Any]) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        protected = protect_secret_bytes(payload)
        self.secret_file.write_bytes(protected)

    def _read_protected_secret(self) -> dict[str, Any]:
        if not self.secret_file.exists():
            raise PollyCredentialsError("Arquivo protegido de credenciais Polly nao encontrado.")

        payload = unprotect_secret_bytes(self.secret_file.read_bytes())
        data = json.loads(payload.decode("utf-8"))
        if not isinstance(data, dict):
            raise PollyCredentialsError("Credenciais Polly protegidas estao invalidas.")
        return data

    @staticmethod
    def _require_text(value: str, label: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise PollyCredentialsError(f"{label} nao informado.")
        return text


def validate_polly_client(client) -> None:
    response = client.synthesize_speech(
        Text="ok",
        TextType="text",
        VoiceId=POLLY_VOICE_ID,
        Engine=POLLY_ENGINE,
        OutputFormat=POLLY_OUTPUT_FORMAT,
        SampleRate=POLLY_SAMPLE_RATE,
    )
    stream = response.get("AudioStream")
    if stream:
        try:
            stream.read(1)
        finally:
            try:
                stream.close()
            except POLLY_CREDENTIAL_RECOVERABLE_ERRORS as exc:
                print(f"[POLLY] falha ao fechar stream de validacao: {exc}")


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_ulong),
        ("pbData", ctypes.c_void_p),
    ]


def protect_secret_bytes(data: bytes) -> bytes:
    if os.name != "nt":
        raise PollyCredentialsError("Protecao local de credenciais requer Windows.")
    return _crypt_protect(data)


def unprotect_secret_bytes(data: bytes) -> bytes:
    if os.name != "nt":
        raise PollyCredentialsError("Leitura de credenciais protegidas requer Windows.")
    return _crypt_unprotect(data)


def _crypt_protect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    in_buffer = ctypes.create_string_buffer(data)
    in_blob = _DATA_BLOB(len(data), ctypes.cast(in_buffer, ctypes.c_void_p))
    out_blob = _DATA_BLOB()

    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "TTSLive Amazon Polly",
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise PollyCredentialsError("Falha ao proteger credenciais Polly no Windows.")

    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _crypt_unprotect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    in_buffer = ctypes.create_string_buffer(data)
    in_blob = _DATA_BLOB(len(data), ctypes.cast(in_buffer, ctypes.c_void_p))
    out_blob = _DATA_BLOB()

    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise PollyCredentialsError("Falha ao abrir credenciais Polly protegidas.")

    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)
