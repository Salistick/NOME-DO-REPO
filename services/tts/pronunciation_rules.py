import json
import sys
from pathlib import Path
from typing import Any

from config import TTS_PRONUNCIATION_FILE


DEFAULT_PRONUNCIATION_RULES = {
    "single_words": {
        "vc": "voce",
        "vcs": "voces",
        "pq": "porque",
        "q": "que",
        "so": "soh",
        "nao": "nao",
        "tb": "tambem",
        "tbm": "tambem",
        "blz": "beleza",
        "msg": "mensagem",
        "obg": "obrigado",
        "vlw": "valeu",
        "tmj": "tamo junto",
        "pfv": "por favor",
        "mds": "meu deus",
        "plmds": "pelo amor de deus",
        "kk": "risos",
        "kkk": "risos",
        "kkkk": "risos",
        "kkkkk": "risos",
        "ksks": "risos",
        "rsrs": "risos",
        "rs": "risos",
        "pxg": "p x g",
        "pokexgames": "poke x games",
        "tibia": "tibia",
        "lvl": "level",
        "lv": "level",
        "xp": "experiencia",
        "exp": "experiencia",
        "hp": "vida",
        "mp": "mana",
        "sp": "stamina",
        "dps": "d p s",
        "rpg": "r p g",
        "mmorpg": "m m o r p g",
        "npc": "n p c",
        "pvp": "p v p",
        "pve": "p v e",
        "aoe": "area",
        "cd": "cooldown",
        "crit": "critico",
        "build": "biudi",
        "buff": "baf",
        "debuff": "dibaf",
        "nerf": "nerf",
        "farm": "farm",
        "farming": "farm",
        "loot": "lut",
        "boss": "boss",
        "gg": "g g",
        "wp": "u p",
        "afk": "a f k",
        "brb": "b r b",
        "dc": "desconectou",
        "pk": "p k",
        "ms": "m s",
        "ml": "m l",
        "rl": "r l",
        "fs": "f s",
        "ss": "s s",
        "ds": "d s",
        "ot": "o t",
        "ts": "t s",
        "tc": "t c",
        "sd": "s d",
        "ue": "u e",
        "uh": "u h",
        "bp": "b p",
        "pb": "p b",
        "ks": "k s",
        "fps": "f p s",
        "atk": "ataque",
        "def": "defesa",
        "matk": "m ataque",
        "mdef": "m defesa",
        "hz": "hertz",
        "ek": "e k",
        "rp": "r p",
        "ed": "e d",
        "lol": "risos",
    },
    "phrases": {
        "mini boss": "mini boss",
        "poke x games": "poke x games",
    },
}

_RULES_CACHE: dict[str, Any] | None = None


def _candidate_default_paths() -> list[Path]:
    paths: list[Path] = []

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        paths.append(Path(meipass) / "assets" / "tts_pronunciations.default.json")

    paths.append(Path(__file__).resolve().parents[2] / "assets" / "tts_pronunciations.default.json")
    return paths


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
                if isinstance(data, dict):
                    return data
    except Exception:
        return {}
    return {}


def _load_default_rules() -> dict[str, Any]:
    for path in _candidate_default_paths():
        data = _read_json_file(path)
        if data:
            return data

    return DEFAULT_PRONUNCIATION_RULES


def _clean_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}

    cleaned: dict[str, str] = {}
    for key, replacement in value.items():
        clean_key = str(key or "").strip()
        clean_value = str(replacement or "").strip()
        if clean_key and clean_value:
            cleaned[clean_key] = clean_value
    return cleaned


def _write_default_file(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(
                json.dumps(_load_default_rules(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    except Exception:
        pass


def load_pronunciation_rules(force_reload: bool = False) -> dict[str, dict[str, str]]:
    global _RULES_CACHE

    if _RULES_CACHE is not None and not force_reload:
        return _RULES_CACHE

    path = Path(TTS_PRONUNCIATION_FILE)
    _write_default_file(path)

    defaults = _load_default_rules()
    loaded = _read_json_file(path)

    single_words = {
        **_clean_mapping(defaults.get("single_words")),
        **_clean_mapping(loaded.get("single_words")),
    }
    phrases = {
        **_clean_mapping(defaults.get("phrases")),
        **_clean_mapping(loaded.get("phrases")),
    }

    _RULES_CACHE = {
        "single_words": single_words,
        "phrases": phrases,
    }
    return _RULES_CACHE
