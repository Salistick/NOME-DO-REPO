import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

import requests

from app_version import CURRENT_APP_VERSION


GITHUB_OWNER = "Salistick"
GITHUB_REPO = "NOME-DO-REPO"
LATEST_RELEASE_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
INSTALLER_ASSET_NAME = "TTSLiveInstaller.exe"
UPDATE_DIR_NAME = "TTSLiveUpdater"
SKIP_UPDATE_VERSIONS = {"", "dev", "manual"}


def _is_supported_runtime() -> bool:
    return getattr(sys, "frozen", False)


def _normalize_tag(tag: str) -> str:
    tag = (tag or "").strip()
    if not tag:
        return ""
    if tag.lower().startswith("v"):
        return tag
    return f"v{tag}"


def _parse_version(tag: str) -> tuple[int, ...]:
    normalized = _normalize_tag(tag).lstrip("vV")
    parts = re.findall(r"\d+", normalized)
    if not parts:
        return ()
    return tuple(int(part) for part in parts)


def _find_installer_download_url(release_payload: dict) -> str:
    assets = release_payload.get("assets", []) or []
    for asset in assets:
        name = (asset.get("name") or "").strip()
        if name == INSTALLER_ASSET_NAME:
            return (asset.get("browser_download_url") or "").strip()
    return ""


def _download_installer(download_url: str, tag_name: str) -> Path:
    update_dir = Path(tempfile.gettempdir()) / UPDATE_DIR_NAME
    update_dir.mkdir(parents=True, exist_ok=True)

    installer_path = update_dir / f"TTSLiveInstaller-{tag_name}.exe"

    with requests.get(
        download_url,
        stream=True,
        timeout=(5, 60),
        headers={"User-Agent": "TTSLiveUpdater"},
    ) as response:
        response.raise_for_status()

        with open(installer_path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 128):
                if chunk:
                    handle.write(chunk)

    return installer_path


def _write_update_script(installer_path: Path, current_exe: Path, current_pid: int) -> Path:
    script_path = installer_path.with_suffix(".cmd")

    script = f"""@echo off
setlocal

:wait_for_old_process
tasklist /FI "PID eq {current_pid}" 2>NUL | find "{current_pid}" >NUL
if %ERRORLEVEL%==0 (
    timeout /t 1 /nobreak >NUL
    goto wait_for_old_process
)

start "" /wait "{installer_path}" /SP- /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
set "INSTALL_EXIT=%ERRORLEVEL%"

if "%INSTALL_EXIT%"=="0" (
    del /f /q "{installer_path}" >NUL 2>NUL
    start "" "{current_exe}"
)

start "" cmd /c del /f /q "%~f0" >NUL 2>NUL
endlocal
"""

    script_path.write_text(script, encoding="utf-8")
    return script_path


def _launch_update_script(script_path: Path) -> None:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        ["cmd.exe", "/c", str(script_path)],
        close_fds=True,
        creationflags=creationflags,
    )


def try_start_auto_update(notify: Callable[[str], None] | None = None) -> bool:
    if not _is_supported_runtime():
        return False

    raw_current_version = (CURRENT_APP_VERSION or "").strip()
    if raw_current_version.lower() in SKIP_UPDATE_VERSIONS:
        return False
    current_version = _normalize_tag(raw_current_version)

    try:
        response = requests.get(
            LATEST_RELEASE_API_URL,
            timeout=(3, 10),
            headers={"Accept": "application/vnd.github+json", "User-Agent": "TTSLiveUpdater"},
        )
        response.raise_for_status()
        latest_release = response.json()
    except Exception as exc:
        print(f"[UPDATER] Falha ao consultar release mais recente: {exc}")
        return False

    latest_tag = _normalize_tag(latest_release.get("tag_name", ""))
    if not latest_tag:
        return False

    current_parts = _parse_version(current_version)
    latest_parts = _parse_version(latest_tag)

    if not current_parts or not latest_parts or latest_parts <= current_parts:
        return False

    download_url = _find_installer_download_url(latest_release)
    if not download_url:
        print("[UPDATER] Nenhum instalador encontrado na release mais recente.")
        return False

    if notify:
        notify(
            f"Nova versao encontrada ({latest_tag}). O TTS Live vai baixar e instalar a atualizacao automaticamente."
        )

    try:
        installer_path = _download_installer(download_url, latest_tag)
        current_exe = Path(sys.executable).resolve()
        script_path = _write_update_script(installer_path, current_exe, os.getpid())
        _launch_update_script(script_path)
        return True
    except Exception as exc:
        print(f"[UPDATER] Falha ao iniciar a atualizacao automatica: {exc}")
        return False
