"""Explicit recovery commands that work before application configuration loads."""

import argparse
import os
import sys
from pathlib import Path

from single_instance import SingleInstanceLock


def run_maintenance(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Recuperacao de credenciais TTS Live")
    commands = parser.add_mutually_exclusive_group(required=True)
    commands.add_argument("--recover-env", action="store_true")
    commands.add_argument("--recover-token", choices=("twitch", "youtube", "kick"))
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--maintenance-output", type=Path)
    args = parser.parse_args(argv)
    base = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parent)
    data_dir = Path(args.data_dir or os.environ.get("TTSLIVE_DATA_DIR") or base / "data").resolve()
    result = {"ok": False, "operation": "recover-env" if args.recover_env else "recover-token"}
    try:
        with SingleInstanceLock(data_dir):
            if args.recover_env:
                from secret_config import recover_environment_secrets

                recover_environment_secrets(
                    data_dir / "platform_secrets.bin", data_dir / "env_original.bin",
                )
            else:
                from secure_storage import recover_secure_json

                recover_secure_json(data_dir / f"{args.recover_token}_token.json")
        result["ok"] = True
    except Exception as exc:
        result["error_type"] = type(exc).__name__
    if args.maintenance_output:
        from persistence import atomic_write_json

        atomic_write_json(args.maintenance_output, result)
    elif getattr(sys, "frozen", False):
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        try:
            if result["ok"]:
                messagebox.showinfo("TTS Live", "Backup protegido recuperado.", parent=root)
            else:
                messagebox.showerror(
                    "TTS Live", "Nao foi possivel recuperar o backup. Feche o aplicativo e "
                    "use o mesmo usuario Windows que salvou as credenciais.", parent=root,
                )
        finally:
            root.destroy()
    else:
        print("Backup protegido recuperado." if result["ok"] else
              "Recuperacao nao concluida; confira o backup, o perfil Windows e feche o aplicativo.")
    return 0 if result["ok"] else 1
