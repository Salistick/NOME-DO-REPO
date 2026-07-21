import html
import os
import re
import unicodedata

from services.tts.pronunciation_rules import load_pronunciation_rules


URL_PATTERN = re.compile(
    r"(https?://\S+|www\.\S+|\S+\.(com|net|org|gg|tv|io|dev|br|app|me|xyz|live|gg/\S*|com/\S*))",
    re.IGNORECASE,
)

MULTISPACE_PATTERN = re.compile(r"\s+")
REPEATED_PUNCT_PATTERN = re.compile(r"([!?,:;])\1{1,}")
REPEATED_CHAR_PATTERN = re.compile(r"(.)\1{4,}", re.IGNORECASE)
MENTION_PATTERN = re.compile(r"(?<!\S)@\w+")
COMMAND_PREFIX_PATTERN = re.compile(r"^!\w+\s*", re.IGNORECASE)
NUMBER_SYMBOLS_PATTERN = re.compile(r"[_~^`|\\]+")
WORD_PATTERN = re.compile(r"\S+")
COMPACT_MAGNITUDE_PATTERN = re.compile(r"\b(\d+(?:[.,]\d+)?)(k{1,3}|b|t)\b", re.IGNORECASE)
ATTACHED_STAT_PATTERN = re.compile(
    r"\b(\d+(?:[.,]\d+)?)(hp|mp|sp|ml|lvl|lv|fps|hz|ms|cd)\b",
    re.IGNORECASE,
)
ORDINAL_NUMBER_PATTERN = re.compile(r"\b(\d+)(?:°|º)(?=\s|$)")
PLAIN_NUMBER_PATTERN = re.compile(r"\b\d+\b")
ELLIPSIS_CHAR = "\u2026"
ELLIPSIS_PATTERN = re.compile(r"\.{3,}|\u2026")
TIME_DURATION_PATTERN = re.compile(r"\b(\d+(?:[.,]\d+)?)([sSmMhH])\b")
MONEY_PATTERN = re.compile(r"(?<!\w)(?:R\$|rs\$?)\s*(\d+(?:[.,]\d{1,2})?)", re.IGNORECASE)
PERCENT_PATTERN = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*%")
SCORE_PATTERN = re.compile(r"\b(\d+)\s*x\s*(\d+)\b", re.IGNORECASE)
FRACTION_PATTERN = re.compile(r"\b(\d+)\s*/\s*(\d+)\b")
MULTIPLIER_PATTERN = re.compile(r"\b(\d+(?:[.,]\d+)?)x\b", re.IGNORECASE)
CAPS_WORD_PATTERN = re.compile(r"\b[A-ZÁÉÍÓÚÀÂÊÔÃÕÇ]{4,}\b")
SSML_BREAK_TIMES_BY_PUNCTUATION = {
    ",": 180,
    ";": 280,
    ":": 260,
    ".": 450,
    "!": 520,
    "?": 520,
    ELLIPSIS_CHAR: 700,
}
SSML_SILENT_PUNCTUATION = set("()[]{}\"'`´“”‘’+-/$\\|_~^")
SPEAKABLE_SYMBOLS = set("!?.,:;+-/%$()[]'\"") | {ELLIPSIS_CHAR}

EMOJI_LIKE_PATTERN = re.compile(
    r"(:\)|:-\)|:\(|:-\(|:D|xD|XD|<3|:\*|;\)|;-?\)|:P|:-?P)",
    re.IGNORECASE,
)
INTENT_EMOJI_REPLACEMENTS = {
    "😂": "risos",
    "🤣": "risos",
    "😆": "risos",
    "😅": "risos",
    "😭": "chorando",
    "😢": "chorando",
    "❤️": "coracao",
    "❤": "coracao",
    "💜": "coracao",
    "💙": "coracao",
    "💚": "coracao",
    "💛": "coracao",
    "🧡": "coracao",
    "👏": "palmas",
    "🔥": "fogo",
    "👍": "positivo",
    "👎": "negativo",
}
VARIATION_SELECTOR = "\ufe0f"

NON_SPEAKABLE_PATTERN = re.compile(r"[^\w\s!?.,:;\u2026+\-/%$()'\"\[\]A-Za-z0-9\u00C0-\u00FF]")

COMMON_REPLACEMENTS = {
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
    "kkk": "risos",
    "kkkk": "risos",
    "kkkkk": "risos",
    "ksks": "risos",
    "rsrs": "risos",
    "rs": "risos",
}

GAMER_REPLACEMENTS = {
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
}

UNITS_PT = {
    0: "zero",
    1: "um",
    2: "dois",
    3: "tres",
    4: "quatro",
    5: "cinco",
    6: "seis",
    7: "sete",
    8: "oito",
    9: "nove",
    10: "dez",
    11: "onze",
    12: "doze",
    13: "treze",
    14: "quatorze",
    15: "quinze",
    16: "dezesseis",
    17: "dezessete",
    18: "dezoito",
    19: "dezenove",
}

TENS_PT = {
    20: "vinte",
    30: "trinta",
    40: "quarenta",
    50: "cinquenta",
    60: "sessenta",
    70: "setenta",
    80: "oitenta",
    90: "noventa",
}

HUNDREDS_PT = {
    100: "cem",
    200: "duzentos",
    300: "trezentos",
    400: "quatrocentos",
    500: "quinhentos",
    600: "seiscentos",
    700: "setecentos",
    800: "oitocentos",
    900: "novecentos",
}

ORDINAL_UNITS_PT = {
    1: "primeiro",
    2: "segundo",
    3: "terceiro",
    4: "quarto",
    5: "quinto",
    6: "sexto",
    7: "setimo",
    8: "oitavo",
    9: "nono",
}

ORDINAL_TENS_PT = {
    10: "decimo",
    20: "vigesimo",
    30: "trigesimo",
    40: "quadragesimo",
    50: "quinquagesimo",
    60: "sexagesimo",
    70: "septuagesimo",
    80: "octogesimo",
    90: "nonagesimo",
}

ORDINAL_HUNDREDS_PT = {
    100: "centesimo",
    200: "ducentesimo",
    300: "trecentesimo",
    400: "quadringentesimo",
    500: "quingentesimo",
    600: "sexcentesimo",
    700: "septingentesimo",
    800: "octingentesimo",
    900: "nongentesimo",
}


LAUGH_TOKEN_PATTERN = re.compile(r"\b(?:k{4,}|(?:ha|he|hi|hu|hs|rs){3,})\b", re.IGNORECASE)


def strip_accents_for_compare(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def remove_emojis_and_symbols(text: str) -> str:
    cleaned = []

    for ch in text:
        category = unicodedata.category(ch)

        if ch.isalnum() or ch.isspace() or ch in SPEAKABLE_SYMBOLS:
            cleaned.append(ch)
            continue

        if category.startswith("L") or category.startswith("N"):
            cleaned.append(ch)
            continue

    return "".join(cleaned)


def replace_intent_emojis(text: str) -> str:
    if not text:
        return text

    result: list[str] = []
    last_replacement = ""
    repeated_count = 0

    for ch in text:
        if ch == VARIATION_SELECTOR:
            continue

        replacement = INTENT_EMOJI_REPLACEMENTS.get(ch)
        if not replacement:
            result.append(ch)
            last_replacement = ""
            repeated_count = 0
            continue

        if replacement == last_replacement:
            repeated_count += 1
        else:
            last_replacement = replacement
            repeated_count = 1

        if repeated_count <= 2:
            result.append(f" {replacement} ")

    return "".join(result)


def collapse_intent_words(text: str) -> str:
    intent_words = set(INTENT_EMOJI_REPLACEMENTS.values()) | {"risos"}
    for word in sorted(intent_words):
        text = re.sub(rf"\b{re.escape(word)}(?:\s+{re.escape(word)})+\b", word, text, flags=re.IGNORECASE)
    return text


def replace_multiword_gamer_terms(text: str) -> str:
    result = text

    multi_map = load_pronunciation_rules().get("phrases", {})

    for source, target in multi_map.items():
        result = re.sub(rf"\b{re.escape(source)}\b", target, result, flags=re.IGNORECASE)

    return result


def normalize_laughs(text: str) -> str:
    return LAUGH_TOKEN_PATTERN.sub(" risos ", text)


def collapse_stretched_words(text: str) -> str:
    return re.sub(r"([A-Za-z\u00C0-\u00FF])\1{2,}", lambda m: m.group(1) * 2, text)


def normalize_caps_lock(text: str) -> str:
    def repl(match: re.Match) -> str:
        word = match.group(0)
        if len(word) <= 4:
            return word
        return f"{word.lower()}!"

    return CAPS_WORD_PATTERN.sub(repl, text)


def spell_uppercase_token(token: str) -> str:
    if not token or not token.isupper() or len(token) > 4:
        return token
    return " ".join(token.lower())


def _replace_word_preserving_punctuation(word: str) -> str:
    match = re.match(r"^([^\w\u00C0-\u00FF]*)([\w\u00C0-\u00FF]+)([^\w\u00C0-\u00FF]*)$", word, flags=re.UNICODE)
    if not match:
        return word

    prefix, core, suffix = match.groups()
    compare_key = strip_accents_for_compare(core.lower())
    word_rules = load_pronunciation_rules().get("single_words", {})

    replacement = None
    if compare_key in word_rules:
        replacement = word_rules[compare_key]
    elif compare_key in COMMON_REPLACEMENTS:
        replacement = COMMON_REPLACEMENTS[compare_key]
    elif compare_key in GAMER_REPLACEMENTS:
        replacement = GAMER_REPLACEMENTS[compare_key]

    if replacement is None:
        return word

    return f"{prefix}{replacement}{suffix}"


def replace_common_terms(text: str) -> str:
    words = text.split()
    replaced = [_replace_word_preserving_punctuation(word) for word in words]
    return " ".join(replaced)


def sanitize_username_for_tts(name: str) -> str:
    text = name.strip()

    text = text.replace("_", " ")
    text = text.replace("-", " ")
    text = text.replace(".", " ")
    text = NUMBER_SYMBOLS_PATTERN.sub(" ", text)

    text = re.sub(r"([a-zA-Z\u00C0-\u00FF])(\d)", r"\1 \2", text)
    text = re.sub(r"(\d)([a-zA-Z\u00C0-\u00FF])", r"\1 \2", text)
    text = convert_plain_numbers(text)
    text = " ".join(spell_uppercase_token(token) for token in text.split())

    text = MULTISPACE_PATTERN.sub(" ", text).strip()

    if not text:
        return "usuario"

    return text


def number_to_pt_br(n: int) -> str:
    if n < 0:
        return "menos " + number_to_pt_br(abs(n))

    if n < 20:
        return UNITS_PT[n]

    if n < 100:
        tens = (n // 10) * 10
        rest = n % 10
        if rest == 0:
            return TENS_PT[tens]
        return f"{TENS_PT[tens]} e {number_to_pt_br(rest)}"

    if n < 1000:
        if n == 100:
            return "cem"

        hundreds = (n // 100) * 100
        rest = n % 100

        if hundreds == 100:
            prefix = "cento"
        else:
            prefix = HUNDREDS_PT[hundreds]

        if rest == 0:
            return prefix

        return f"{prefix} e {number_to_pt_br(rest)}"

    if n < 1_000_000:
        thousands = n // 1000
        rest = n % 1000

        if thousands == 1:
            prefix = "mil"
        else:
            prefix = f"{number_to_pt_br(thousands)} mil"

        if rest == 0:
            return prefix

        if rest < 100:
            return f"{prefix} e {number_to_pt_br(rest)}"

        return f"{prefix} {number_to_pt_br(rest)}"

    if n < 1_000_000_000:
        millions = n // 1_000_000
        rest = n % 1_000_000

        if millions == 1:
            prefix = "um milhao"
        else:
            prefix = f"{number_to_pt_br(millions)} milhoes"

        if rest == 0:
            return prefix

        if rest < 100:
            return f"{prefix} e {number_to_pt_br(rest)}"

        return f"{prefix} {number_to_pt_br(rest)}"

    return " ".join(number_to_pt_br(int(d)) for d in str(n))


def _speak_decimal_number(number_part: str) -> str:
    normalized = number_part.replace(",", ".")
    if "." in normalized:
        left, right = normalized.split(".", 1)
        left_spoken = number_to_pt_br(int(left)) if left.isdigit() else left
        right_spoken = " ".join(number_to_pt_br(int(ch)) for ch in right if ch.isdigit())
        return f"{left_spoken} ponto {right_spoken}".strip()

    return number_to_pt_br(int(normalized))


def _is_singular_number(number_part: str) -> bool:
    try:
        return float(number_part.replace(",", ".")) == 1.0
    except (TypeError, ValueError):
        return False


def _speak_time_number(number_part: str, unit: str) -> str:
    spoken = _speak_decimal_number(number_part)
    if unit.lower() != "h":
        return spoken

    # "hora" pede feminino: uma hora, duas horas, vinte e uma horas.
    spoken = re.sub(r"\bum$", "uma", spoken)
    spoken = re.sub(r"\bdois$", "duas", spoken)
    return spoken


def ordinal_to_pt_br(n: int) -> str:
    if n <= 0:
        return number_to_pt_br(n)

    if n < 10:
        return ORDINAL_UNITS_PT[n]

    if n < 100:
        tens = (n // 10) * 10
        rest = n % 10
        prefix = ORDINAL_TENS_PT.get(tens)
        if prefix is None:
            return number_to_pt_br(n)
        if rest == 0:
            return prefix
        return f"{prefix} {ordinal_to_pt_br(rest)}"

    if n < 1000:
        hundreds = (n // 100) * 100
        rest = n % 100
        prefix = ORDINAL_HUNDREDS_PT.get(hundreds)
        if prefix is None:
            return number_to_pt_br(n)
        if rest == 0:
            return prefix
        return f"{prefix} {ordinal_to_pt_br(rest)}"

    if n == 1000:
        return "milesimo"

    if n < 2000:
        return f"milesimo {ordinal_to_pt_br(n - 1000)}"

    return number_to_pt_br(n)


def convert_compact_magnitudes(text: str) -> str:
    suffix_map = {
        "k": ("mil", "mil"),
        "kk": ("milhao", "milhoes"),
        "kkk": ("bilhao", "bilhoes"),
        "b": ("bilhao", "bilhoes"),
        "t": ("trilhao", "trilhoes"),
    }

    def repl(match: re.Match) -> str:
        number_part = match.group(1)
        suffix = match.group(2).lower()
        if suffix == "k" and _is_singular_number(number_part):
            return "mil"

        spoken_number = _speak_decimal_number(match.group(1))
        singular, plural = suffix_map.get(suffix, ("", ""))
        spoken_suffix = singular if _is_singular_number(number_part) else plural
        return f"{spoken_number} {spoken_suffix}".strip()

    return COMPACT_MAGNITUDE_PATTERN.sub(repl, text)


def convert_money_amounts(text: str) -> str:
    def repl(match: re.Match) -> str:
        raw_value = match.group(1).replace(",", ".")
        try:
            amount = round(float(raw_value), 2)
        except ValueError:
            return match.group(0)

        reais = int(amount)
        centavos = int(round((amount - reais) * 100))
        parts: list[str] = []

        if reais:
            parts.append(f"{number_to_pt_br(reais)} {'real' if reais == 1 else 'reais'}")
        if centavos:
            parts.append(f"{number_to_pt_br(centavos)} {'centavo' if centavos == 1 else 'centavos'}")

        if not parts:
            return "zero reais"
        return " e ".join(parts)

    return MONEY_PATTERN.sub(repl, text)


def convert_percentages(text: str) -> str:
    def repl(match: re.Match) -> str:
        return f"{_speak_decimal_number(match.group(1))} por cento"

    return PERCENT_PATTERN.sub(repl, text)


def convert_scores(text: str) -> str:
    def repl(match: re.Match) -> str:
        left = number_to_pt_br(int(match.group(1)))
        right = number_to_pt_br(int(match.group(2)))
        return f"{left} a {right}"

    return SCORE_PATTERN.sub(repl, text)


def convert_fractions(text: str) -> str:
    common_denominators = {
        2: ("meio", "meios"),
        3: ("terco", "tercos"),
        4: ("quarto", "quartos"),
    }

    def repl(match: re.Match) -> str:
        numerator = int(match.group(1))
        denominator = int(match.group(2))
        if denominator == 0:
            return match.group(0)

        if numerator == 1 and denominator == 2:
            return "meio"

        denominator_words = common_denominators.get(denominator)
        if denominator_words:
            singular, plural = denominator_words
            return f"{number_to_pt_br(numerator)} {singular if numerator == 1 else plural}"

        return f"{number_to_pt_br(numerator)} sobre {number_to_pt_br(denominator)}"

    return FRACTION_PATTERN.sub(repl, text)


def convert_multipliers(text: str) -> str:
    def repl(match: re.Match) -> str:
        return f"{_speak_decimal_number(match.group(1))} vezes"

    return MULTIPLIER_PATTERN.sub(repl, text)


def convert_attached_stats(text: str) -> str:
    suffix_map = {
        "hp": "vida",
        "mp": "mana",
        "sp": "stamina",
        "ml": "m l",
        "lvl": "level",
        "lv": "level",
        "fps": "f p s",
        "hz": "hertz",
        "ms": "m s",
        "cd": "cooldown",
    }

    def repl(match: re.Match) -> str:
        spoken_number = _speak_decimal_number(match.group(1))
        suffix = strip_accents_for_compare(match.group(2).lower())
        spoken_suffix = suffix_map.get(suffix, " ".join(ch for ch in suffix))
        return f"{spoken_number} {spoken_suffix}"

    return ATTACHED_STAT_PATTERN.sub(repl, text)


def convert_time_durations(text: str) -> str:
    unit_map = {
        "s": ("segundo", "segundos"),
        "m": ("minuto", "minutos"),
        "h": ("hora", "horas"),
    }

    def repl(match: re.Match) -> str:
        number_part = match.group(1)
        unit = match.group(2).lower()
        singular, plural = unit_map[unit]
        spoken_number = _speak_time_number(number_part, unit)
        spoken_unit = singular if _is_singular_number(number_part) else plural
        return f"{spoken_number} {spoken_unit}"

    return TIME_DURATION_PATTERN.sub(repl, text)


def convert_ordinal_numbers(text: str) -> str:
    def repl(match: re.Match) -> str:
        value = int(match.group(1))
        return ordinal_to_pt_br(value)

    return ORDINAL_NUMBER_PATTERN.sub(repl, text)


def convert_plain_numbers(text: str) -> str:
    def repl(match: re.Match) -> str:
        value = int(match.group(0))
        return number_to_pt_br(value)

    return PLAIN_NUMBER_PATTERN.sub(repl, text)


def apply_word_limit(text: str, max_words: int) -> tuple[str, bool]:
    words = WORD_PATTERN.findall(text)

    if max_words <= 0:
        return "blablabla fala demais", True

    if len(words) <= max_words:
        return text, False

    kept = words[:max_words]
    return " ".join(kept) + " blablabla fala demais", True


def looks_like_spam(text: str) -> bool:
    compact = re.sub(r"\s+", "", text.lower())
    words = text.lower().split()

    if len(compact) < 4:
        return False

    longest_run = 1
    current_run = 1
    for i in range(1, len(compact)):
        if compact[i] == compact[i - 1]:
            current_run += 1
            longest_run = max(longest_run, current_run)
        else:
            current_run = 1

    if longest_run >= 10:
        return True

    letters = [c for c in compact if c.isalpha()]
    digits = [c for c in compact if c.isdigit()]

    if len(compact) >= 8 and len(digits) / len(compact) > 0.75:
        return True

    if len(compact) >= 10 and len(letters) <= 2:
        return True

    if 3 <= len(words) <= 6:
        unique_words = set(words)
        if len(unique_words) <= 2:
            return True

    laugh_like = compact.replace("h", "").replace("a", "").replace("k", "").replace("s", "").replace("r", "")
    if len(compact) >= 12 and len(laugh_like) == 0:
        return True

    return False


def _tts_debug_enabled() -> bool:
    return os.getenv("TTS_DEBUG_SANITIZER", "").strip().lower() in {"1", "true", "yes", "sim", "on"}


def _debug_tts_preview(label: str, value: str) -> None:
    if _tts_debug_enabled():
        print(f"[TTS SANITIZER] {label}: {value}")


def clean_chat_noise(text: str) -> str:
    text = str(text or "").strip()
    if not text:
        return ""

    text = URL_PATTERN.sub(" ", text)
    text = MENTION_PATTERN.sub(" ", text)
    text = COMMAND_PREFIX_PATTERN.sub("", text)
    text = replace_intent_emojis(text)
    text = EMOJI_LIKE_PATTERN.sub(" risos ", text)

    text = remove_emojis_and_symbols(text)
    text = NON_SPEAKABLE_PATTERN.sub(" ", text)

    text = ELLIPSIS_PATTERN.sub(ELLIPSIS_CHAR, text)
    text = REPEATED_PUNCT_PATTERN.sub(r"\1", text)
    text = normalize_caps_lock(text)
    text = normalize_laughs(text)
    text = REPEATED_CHAR_PATTERN.sub(lambda m: m.group(1) * 2, text)
    text = collapse_stretched_words(text)
    text = collapse_intent_words(text)

    return MULTISPACE_PATTERN.sub(" ", text).strip()


def normalize_for_speech(text: str) -> str:
    text = str(text or "").strip()
    if not text:
        return ""

    text = convert_ordinal_numbers(text)
    text = replace_multiword_gamer_terms(text)
    text = convert_time_durations(text)
    text = convert_money_amounts(text)
    text = convert_percentages(text)
    text = convert_scores(text)
    text = convert_fractions(text)
    text = convert_multipliers(text)
    text = convert_attached_stats(text)
    text = replace_common_terms(text)
    text = convert_compact_magnitudes(text)
    text = convert_plain_numbers(text)
    text = collapse_intent_words(text)

    return MULTISPACE_PATTERN.sub(" ", text).strip()


def sanitize_chat_text(
    text: str,
    max_length: int = 220,
    max_words: int = 20,
) -> tuple[str, bool]:
    """
    Retorna:
      - texto sanitizado
      - bool indicando se houve truncamento por limite de palavras

    Se for detectado spam pesado, retorna texto vazio.
    """
    if not text:
        return "", False

    original_text = str(text)
    text = clean_chat_noise(original_text)
    _debug_tts_preview("original", original_text)
    _debug_tts_preview("limpo", text)

    text = normalize_for_speech(text)
    _debug_tts_preview("normalizado", text)

    if not text:
        return "", False

    if looks_like_spam(text):
        return "", False

    text, truncated = apply_word_limit(text, max_words)

    if len(text) > max_length:
        text = text[:max_length].rstrip()

    if not re.search(r"[A-Za-z\u00C0-\u00FF0-9]", text):
        return "", False

    return text, truncated


def _append_ssml_break(parts: list[str], milliseconds: int) -> None:
    if not parts:
        return

    break_tag = f'<break time="{milliseconds}ms"/>'
    last = parts[-1]
    if not last.startswith("<break"):
        parts.append(break_tag)
        return

    match = re.search(r'time="(\d+)ms"', last)
    previous_milliseconds = int(match.group(1)) if match else 0
    if milliseconds > previous_milliseconds:
        parts[-1] = break_tag


def build_polly_ssml(text: str) -> str:
    text = str(text or "").strip()
    if not text:
        return ""

    parts: list[str] = []
    buffer: list[str] = []
    pending_break_ms = 0

    def flush_buffer() -> None:
        segment = MULTISPACE_PATTERN.sub(" ", "".join(buffer)).strip()
        buffer.clear()
        if segment:
            parts.append(html.escape(segment, quote=False))

    for ch in text:
        break_time = SSML_BREAK_TIMES_BY_PUNCTUATION.get(ch)
        if break_time is not None:
            if buffer:
                while buffer and buffer[-1].isspace():
                    buffer.pop()
                buffer.append(ch)
            pending_break_ms = max(pending_break_ms, break_time)
            continue

        if pending_break_ms:
            flush_buffer()
            _append_ssml_break(parts, pending_break_ms)
            pending_break_ms = 0

        if ch in SSML_SILENT_PUNCTUATION or unicodedata.category(ch).startswith("P"):
            buffer.append(" ")
            continue

        buffer.append(ch)

    if pending_break_ms:
        flush_buffer()
        _append_ssml_break(parts, pending_break_ms)

    flush_buffer()

    while parts and parts[-1].startswith("<break"):
        parts.pop()

    if not parts:
        return ""

    ssml = f"<speak>{' '.join(parts)}</speak>"
    _debug_tts_preview("ssml", ssml)
    return ssml


def build_tts_text(display_name: str, message_text: str, platform_name: str | None = None) -> str:
    safe_name = sanitize_username_for_tts(display_name)
    if not safe_name:
        safe_name = "usuario"

    if not message_text:
        return ""

    if platform_name:
        return f"{safe_name} disse no {platform_name}: {message_text}"

    return f"{safe_name} disse: {message_text}"
