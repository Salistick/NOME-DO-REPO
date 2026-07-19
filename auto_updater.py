import logging
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
INSTALLED_EXE_NAME = "TTSLive.exe"
INSTALL_DIR_NAME = "TTSLive"
UPDATE_DIR_NAME = "TTSLiveUpdater"
SKIP_UPDATE_VERSIONS = {"", "dev", "manual"}
PYINSTALLER_RESET_ENV_NAME = "PYINSTALLER_RESET_ENVIRONMENT"
UPDATE_LOG_RELATIVE_PATH = Path("data") / "logs" / "updater.log"
INSTALLER_WAIT_SECONDS = 15


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

    script = f"""@echo off
setlocal
set "CURRENT_EXE={current_exe}"
set "INSTALLED_EXE={installed_exe}"
set "LOG_FILE={update_log_path}"
set "INSTALLER_LOG={installer_log_path}"
set "LOG_DIR={update_log_path.parent}"
set "{PYINSTALLER_RESET_ENV_NAME}=1"
set "_MEIPASS2="
for /f "delims==" %%V in ('set _PYI_ 2^>NUL') do set "%%V="

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >NUL 2>NUL
call :log "Updater iniciado. PID antigo: {current_pid}. Instalador: {installer_path}"

set "WAIT_COUNT=0"
:wait_for_old_process
tasklist /FI "PID eq {current_pid}" 2>NUL | find "{current_pid}" >NUL
if %ERRORLEVEL%==0 (
    if "%WAIT_COUNT%"=="{INSTALLER_WAIT_SECONDS}" (
        call :log "PID {current_pid} ainda ativo apos {INSTALLER_WAIT_SECONDS}s. Encerrando processo."
        taskkill /PID {current_pid} /F >NUL 2>NUL
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

    script_path.write_text(script, encoding="utf-8")
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
    except Exception as exc:
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

    raw_current_version = (CURRENT_APP_VERSION or "").strip()
    if raw_current_version.lower() in SKIP_UPDATE_VERSIONS:
        return False
    current_version = _normalize_tag(raw_current_version)

    if notify:
        notify("Verificando atualizacoes...")

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
        notify(f"Nova versao encontrada ({latest_tag}). Baixando atualizacao...")

    try:
        installer_path = _download_installer(download_url, latest_tag)
        if notify:
            notify(f"Atualizacao {latest_tag} pronta. Instalando...")
        current_exe = Path(sys.executable).resolve()
        installed_exe = _get_expected_installed_exe_path(current_exe)
        script_path = _write_update_script(installer_path, current_exe, installed_exe, os.getpid())
        logging.info(
            "[UPDATER] Iniciando atualizacao %s | installer=%s | script=%s | log=%s",
            latest_tag,
            installer_path,
            script_path,
            _get_update_log_path(installed_exe),
        )
        _launch_update_script(script_path)
        return True
    except Exception as exc:
        logging.exception("[UPDATER] Falha ao iniciar a atualizacao automatica")
        print(f"[UPDATER] Falha ao iniciar a atualizacao automatica: {exc}")
        return False
