import hashlib
import hmac
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import requests

from app_version import CURRENT_APP_VERSION
from persistence import atomic_write_bytes, atomic_write_json

GITHUB_OWNER = "Salistick"
GITHUB_REPO = "NOME-DO-REPO"
LATEST_RELEASE_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
INSTALLER_ASSET_NAME = "TTSLiveInstaller.exe"
INSTALLED_EXE_NAME = "TTSLive.exe"
INSTALL_DIR_NAME = "TTSLive"
UPDATE_DIR_NAME = "TTSLiveUpdater"
SKIP_UPDATE_VERSIONS = {"", "dev", "manual"}
PYINSTALLER_RESET_ENV_NAME = "PYINSTALLER_RESET_ENVIRONMENT"
UPDATE_LOG_RELATIVE_PATH = Path("data") / "logs" / "updater.log"
INSTALLER_WAIT_SECONDS = 15
MAX_INSTALLER_BYTES = 512 * 1024 * 1024
UPDATE_RETENTION_SECONDS = 7 * 24 * 60 * 60
UPDATE_MARKER_NAME = ".ttslive-update.json"
UPDATE_MARKER_FORMAT = "ttslive-update-v1"
LOGGER = logging.getLogger(__name__)


def _is_supported_runtime() -> bool:
    return sys.platform == "win32" and getattr(sys, "frozen", False)


def _normalize_tag(tag: str) -> str:
    tag = tag.strip() if isinstance(tag, str) else ""
    if not tag:
        return ""
    if tag.lower().startswith("v"):
        return tag
    return f"v{tag}"


def _parse_version(tag: str) -> tuple[int, ...]:
    normalized = _normalize_tag(tag)[1:]
    if not re.fullmatch(r"[0-9]{1,5}(?:\.[0-9]{1,5}){0,3}", normalized):
        return ()
    parts = tuple(int(part) for part in normalized.split("."))
    return parts + (0,) * (4 - len(parts))


def _find_installer_download_url(release_payload: dict) -> str:
    asset = _find_installer_asset(release_payload)
    return asset.get("browser_download_url", "") if asset else ""


def _find_installer_asset(release_payload: dict) -> dict | None:
    if not isinstance(release_payload, dict):
        return None
    assets = release_payload.get("assets", []) or []
    if not isinstance(assets, list):
        return None
    for asset in assets:
        if isinstance(asset, dict) and asset.get("name") == INSTALLER_ASSET_NAME:
            return asset
    return None


def cleanup_old_update_downloads(temp_root: Path | None = None, now: float | None = None) -> int:
    """Remove only expired directories explicitly owned by this updater.

    Unknown files, symbolic links and junctions are preserved. No recursive
    deletion is used, and unmarked directories from old versions are untouched.
    """
    root = Path(temp_root or tempfile.gettempdir()).resolve()
    now = time.time() if now is None else now
    removed = 0
    allowed = {INSTALLER_ASSET_NAME, "TTSLiveInstaller.part", "TTSLiveInstaller.cmd",
               UPDATE_MARKER_NAME}
    try:
        candidates = list(root.glob(f"{UPDATE_DIR_NAME}-*"))
    except OSError:
        return 0
    for directory in candidates:
        try:
            if (directory.is_symlink() or directory.is_junction() or not directory.is_dir()
                    or directory.resolve().parent != root):
                continue
            marker_path = directory / UPDATE_MARKER_NAME
            if marker_path.is_symlink() or not marker_path.is_file():
                continue
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            if (not isinstance(marker, dict) or marker.get("format") != UPDATE_MARKER_FORMAT
                    or type(marker.get("created_at")) not in (int, float)):
                continue
            # A future/NaN timestamp is not evidence that data is expired.
            if not 0 <= marker["created_at"] <= now - UPDATE_RETENTION_SECONDS:
                continue
            files = list(directory.iterdir())
            if any(item.name not in allowed or item.is_symlink() or not item.is_file()
                   for item in files):
                continue
            # Keep the ownership marker until the last operation, so a busy
            # executable or permission failure can be retried on the next run.
            for item in files:
                if item != marker_path:
                    item.unlink()
            marker_path.unlink()
            directory.rmdir()
            removed += 1
        except (OSError, ValueError, TypeError):
            continue
    return removed


def _download_installer(
    download_url: str, tag_name: str, expected_digest: str, expected_size: int,
) -> Path:
    if not _parse_version(tag_name):
        raise ValueError("Versao de atualizacao invalida.")
    expected_url = (
        f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/"
        f"{tag_name}/{INSTALLER_ASSET_NAME}"
    )
    if download_url != expected_url:
        raise ValueError("URL do instalador fora da release esperada.")
    if not isinstance(expected_digest, str) or not re.fullmatch(
        r"sha256:[0-9a-fA-F]{64}", expected_digest,
    ):
        raise ValueError("Release sem SHA-256 valido; atualizacao ignorada.")
    if type(expected_size) is not int or not 0 < expected_size <= MAX_INSTALLER_BYTES:
        raise ValueError("Tamanho do instalador invalido.")

    # Each attempt owns its directory; parallel launches cannot overwrite a download.
    update_dir = Path(tempfile.mkdtemp(prefix=f"{UPDATE_DIR_NAME}-"))
    installer_path = update_dir / INSTALLER_ASSET_NAME
    partial_path = installer_path.with_suffix(".part")
    try:
        atomic_write_json(update_dir / UPDATE_MARKER_NAME, {
            "format": UPDATE_MARKER_FORMAT, "created_at": time.time(),
        })
        digest = hashlib.sha256()
        downloaded = 0
        with requests.get(
            download_url, stream=True, timeout=(5, 60),
            headers={"User-Agent": "TTSLiveUpdater"},
        ) as response:
            response.raise_for_status()
            with open(partial_path, "wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 128):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if downloaded > expected_size:
                        raise ValueError("Instalador excede o tamanho publicado.")
                    digest.update(chunk)
                    handle.write(chunk)
        if downloaded != expected_size or not hmac.compare_digest(
            digest.hexdigest(), expected_digest.split(":", 1)[1].lower(),
        ):
            raise ValueError("Instalador incompleto ou SHA-256 diferente da release.")
        partial_path.replace(installer_path)
        return installer_path
    except BaseException:
        partial_path.unlink(missing_ok=True)
        installer_path.unlink(missing_ok=True)
        (update_dir / UPDATE_MARKER_NAME).unlink(missing_ok=True)
        update_dir.rmdir()
        raise


def _get_expected_installed_exe_path(current_exe: Path) -> Path:
    local_app_data = (os.getenv("LOCALAPPDATA") or "").strip()
    if local_app_data:
        return Path(local_app_data) / INSTALL_DIR_NAME / INSTALLED_EXE_NAME
    return current_exe


def _get_update_log_path(installed_exe: Path) -> Path:
    return installed_exe.resolve().parent / UPDATE_LOG_RELATIVE_PATH


def _write_update_script(
    installer_path: Path,
    current_exe: Path,
    installed_exe: Path,
    current_pid: int,
) -> Path:
    script_path = installer_path.with_suffix(".cmd")
    update_log_path = _get_update_log_path(installed_exe)
    installer_log_path = update_log_path.with_name("installer.log")

    # Percent expansion and CALL reparsing can turn a valid Windows path into
    # commands. Refuse those rare paths instead of executing a corrupted script.
    for path in (installer_path, current_exe, installed_exe, update_log_path):
        if any(character in str(path) for character in ('%', '"', '\r', '\n')):
            raise ValueError("Caminho incompativel com o atualizador Windows.")

    script = f"""@echo off
chcp 65001 >NUL
setlocal DisableDelayedExpansion
set "CURRENT_EXE={current_exe}"
set "INSTALLED_EXE={installed_exe}"
set "LOG_FILE={update_log_path}"
set "INSTALLER_LOG={installer_log_path}"
set "LOG_DIR={update_log_path.parent}"
set "{PYINSTALLER_RESET_ENV_NAME}=1"
set "_MEIPASS2="
for /f "delims==" %%V in ('set _PYI_ 2^>NUL') do set "%%V="

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >NUL 2>NUL
call :log "Updater iniciado. PID antigo: {current_pid}."

set "WAIT_COUNT=0"
:wait_for_old_process
tasklist /FI "PID eq {current_pid}" 2>NUL | find "{current_pid}" >NUL
if %ERRORLEVEL%==0 (
    if "%WAIT_COUNT%"=="{INSTALLER_WAIT_SECONDS}" (
        call :log "PID {current_pid} ainda ativo apos {INSTALLER_WAIT_SECONDS}s. Encerrando processo."
        taskkill /PID {current_pid} /F >NUL 2>NUL
        if errorlevel 1 (
            call :log "Falha ao encerrar processo. Atualizacao cancelada."
            exit /b 1
        )
        timeout /t 1 /nobreak >NUL
        goto wait_for_old_process
    )
    timeout /t 1 /nobreak >NUL
    set /a WAIT_COUNT+=1
    goto wait_for_old_process
)

tasklist /FI "IMAGENAME eq {INSTALLED_EXE_NAME}" 2>NUL | find /I "{INSTALLED_EXE_NAME}" >NUL
if %ERRORLEVEL%==0 (
    call :log "Instancias antigas de {INSTALLED_EXE_NAME} encontradas. Encerrando antes da instalacao."
    taskkill /IM "{INSTALLED_EXE_NAME}" /F >NUL 2>NUL
    timeout /t 1 /nobreak >NUL
)

call :log "Executando instalador silencioso."
"{installer_path}" /SP- /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NORESTARTAPPLICATIONS /CLOSEAPPLICATIONS /FORCECLOSEAPPLICATIONS /LOG="%INSTALLER_LOG%"
set "INSTALL_EXIT=%ERRORLEVEL%"
call :log "Instalador finalizado com codigo %INSTALL_EXIT%."

if "%INSTALL_EXIT%"=="0" (
    del /f /q "{installer_path}" >NUL 2>NUL
    timeout /t 2 /nobreak >NUL

    if exist "%INSTALLED_EXE%" (
        call :log "Atualizacao concluida. Abrindo executavel instalado."
        start "" "%INSTALLED_EXE%"
    ) else if exist "%CURRENT_EXE%" (
        call :log "Atualizacao concluida, mas executavel instalado nao foi encontrado. Abrindo executavel atual."
        start "" "%CURRENT_EXE%"
    )
) else (
    call :log "Falha na instalacao. Instalador preservado para diagnostico."
    if exist "%CURRENT_EXE%" (
        call :log "Reabrindo executavel atual apos falha."
        start "" "%CURRENT_EXE%"
    )
)

set "SCRIPT_EXIT=%INSTALL_EXIT%"
call :log "Updater encerrado."
del /f /q "%~f0" >NUL 2>NUL
endlocal & exit /b %SCRIPT_EXIT%

:log
echo [%DATE% %TIME%] %~1>>"%LOG_FILE%"
exit /b 0
"""

    atomic_write_bytes(script_path, script.encode("utf-8"))
    return script_path


def _sanitize_pyinstaller_environment() -> dict:
    env = os.environ.copy()

    for key in list(env):
        normalized_key = key.upper()
        if normalized_key == "_MEIPASS2" or normalized_key.startswith("_PYI_"):
            env.pop(key, None)

    env[PYINSTALLER_RESET_ENV_NAME] = "1"
    return env


def _reset_windows_dll_directory() -> None:
    if sys.platform != "win32":
        return

    try:
        import ctypes

        ctypes.windll.kernel32.SetDllDirectoryW(None)
    except (AttributeError, OSError) as exc:
        print(f"[UPDATER] Nao foi possivel limpar o diretorio de DLL herdado: {exc}")


def _launch_update_script(script_path: Path) -> None:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

    _reset_windows_dll_directory()
    subprocess.Popen(
        ["cmd.exe", "/d", "/c", str(script_path)],
        close_fds=True,
        creationflags=creationflags,
        env=_sanitize_pyinstaller_environment(),
        startupinfo=startupinfo,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def try_start_auto_update(notify: Callable[[str], None] | None = None) -> bool:
    if not _is_supported_runtime():
        return False

    cleanup_old_update_downloads()

    raw_current_version = (CURRENT_APP_VERSION or "").strip()
    if raw_current_version.lower() in SKIP_UPDATE_VERSIONS:
        return False
    current_version = _normalize_tag(raw_current_version)

    if notify:
        notify("Verificando atualizacoes...")

    try:
        with requests.get(
            LATEST_RELEASE_API_URL,
            timeout=(3, 10),
            headers={"Accept": "application/vnd.github+json", "User-Agent": "TTSLiveUpdater"},
        ) as response:
            response.raise_for_status()
            latest_release = response.json()
    except (OSError, requests.RequestException, TypeError, ValueError) as exc:
        print(f"[UPDATER] Falha ao consultar release mais recente: {exc}")
        return False

    if not isinstance(latest_release, dict):
        return False
    raw_latest_tag = latest_release.get("tag_name", "")
    latest_tag = _normalize_tag(raw_latest_tag)
    if not latest_tag or latest_release.get("draft") or latest_release.get("prerelease"):
        return False

    current_parts = _parse_version(current_version)
    latest_parts = _parse_version(latest_tag)

    if not current_parts or not latest_parts or latest_parts <= current_parts:
        return False

    asset = _find_installer_asset(latest_release)
    if not asset:
        print("[UPDATER] Nenhum instalador encontrado na release mais recente.")
        return False

    if notify:
        notify(f"Nova versao encontrada ({latest_tag}). Baixando atualizacao...")

    try:
        installer_path = _download_installer(
            asset.get("browser_download_url", ""), raw_latest_tag,
            asset.get("digest", ""), asset.get("size", 0),
        )
        if notify:
            notify(f"Atualizacao {latest_tag} pronta. Instalando...")
        current_exe = Path(sys.executable).resolve()
        installed_exe = _get_expected_installed_exe_path(current_exe)
        script_path = _write_update_script(installer_path, current_exe, installed_exe, os.getpid())
        LOGGER.info(
            "[UPDATER] Iniciando atualizacao %s | installer=%s | script=%s | log=%s",
            latest_tag,
            installer_path,
            script_path,
            _get_update_log_path(installed_exe),
        )
        _launch_update_script(script_path)
        return True
    except (OSError, requests.RequestException, subprocess.SubprocessError, TypeError, ValueError) as exc:
        LOGGER.exception("[UPDATER] Falha ao iniciar a atualizacao automatica")
        print(f"[UPDATER] Falha ao iniciar a atualizacao automatica: {exc}")
        return False
