import re
import unicodedata


URL_PATTERN = re.compile(
    r"(https?://\S+|www\.\S+|\S+\.(com|net|org|gg|tv|io|dev|br|app|me|xyz|live|gg/\S*|com/\S*))",
    re.IGNORECASE,
)

MULTISPACE_PATTERN = re.compile(r"\s+")
REPEATED_PUNCT_PATTERN = re.compile(r"([!?.,:;])\1{1,}")
REPEATED_CHAR_PATTERN = re.compile(r"(.)\1{4,}", re.IGNORECASE)
MENTION_PATTERN = re.compile(r"(?<!\S)@\w+")
COMMAND_PREFIX_PATTERN = re.compile(r"^!\w+\s*", re.IGNORECASE)
NUMBER_SYMBOLS_PATTERN = re.compile(r"[_~^`|\\]+")
WORD_PATTERN = re.compile(r"\S+")
GAMER_NUMBER_PATTERN = re.compile(r"\b(\d+(?:[.,]\d+)?)([kKmMbBtT]+)\b")
ATTACHED_STAT_PATTERN = re.compile(
    r"\b(\d+(?:[.,]\d+)?)(hp|mp|sp|ml|lvl|lv|fps|hz|ms|cd)\b",
    re.IGNORECASE,
)
PLAIN_NUMBER_PATTERN = re.compile(r"\b\d+\b")

EMOJI_LIKE_PATTERN = re.compile(
    r"(:\)|:-\)|:\(|:-\(|:D|xD|XD|<3|:\*|;\)|;-?\)|:P|:-?P)",
    re.IGNORECASE,
)

NON_SPEAKABLE_PATTERN = re.compile(r"[^\w\s!?.,:;+\-/%()'\"\[\]A-Za-z0-9\u00C0-\u00FF]")

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


LAUGH_TOKEN_PATTERN = re.compile(r"\b(?:k{4,}|(?:ha|he|hi|hu|hs|rs){3,})\b", re.IGNORECASE)


def strip_accents_for_compare(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def remove_emojis_and_symbols(text: str) -> str:
    cleaned = []

    for ch in text:
        category = unicodedata.category(ch)

        if ch.isalnum() or ch.isspace() or ch in "!?.,:;+-/%()[]'\"":
            cleaned.append(ch)
            continue

        if category.startswith("L") or category.startswith("N"):
            cleaned.append(ch)
            continue

    return "".join(cleaned)


def replace_multiword_gamer_terms(text: str) -> str:
    result = text

    multi_map = {
        "mini boss": "mini boss",
        "poke x games": "poke x games",
    }

    for source, target in multi_map.items():
        result = re.sub(rf"\b{re.escape(source)}\b", target, result, flags=re.IGNORECASE)

    return result


def normalize_laughs(text: str) -> str:
    return LAUGH_TOKEN_PATTERN.sub(" risos ", text)


def collapse_stretched_words(text: str) -> str:
    return re.sub(r"([A-Za-z\u00C0-\u00FF])\1{2,}", lambda m: m.group(1) * 2, text)


def _replace_word_preserving_punctuation(word: str) -> str:
    match = re.match(r"^([^\w\u00C0-\u00FF]*)([\w\u00C0-\u00FF]+)([^\w\u00C0-\u00FF]*)$", word, flags=re.UNICODE)
    if not match:
        return word

    prefix, core, suffix = match.groups()
    compare_key = strip_accents_for_compare(core.lower())

    replacement = None
    if compare_key in COMMON_REPLACEMENTS:
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


def convert_gamer_numbers(text: str) -> str:
    def repl(match: re.Match) -> str:
        spoken_number = _speak_decimal_number(match.group(1))
        spoken_suffix = " ".join(ch.lower() for ch in match.group(2))
        return f"{spoken_number} {spoken_suffix}"

    return GAMER_NUMBER_PATTERN.sub(repl, text)


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

    text = text.strip()

    text = URL_PATTERN.sub(" ", text)
    text = MENTION_PATTERN.sub(" ", text)
    text = COMMAND_PREFIX_PATTERN.sub("", text)
    text = EMOJI_LIKE_PATTERN.sub(" ", text)

    text = remove_emojis_and_symbols(text)
    text = NON_SPEAKABLE_PATTERN.sub(" ", text)

    text = REPEATED_PUNCT_PATTERN.sub(r"\1", text)
    text = normalize_laughs(text)
    text = REPEATED_CHAR_PATTERN.sub(lambda m: m.group(1) * 2, text)
    text = collapse_stretched_words(text)

    text = MULTISPACE_PATTERN.sub(" ", text).strip()

    text = replace_multiword_gamer_terms(text)
    text = convert_attached_stats(text)
    text = replace_common_terms(text)
    text = convert_gamer_numbers(text)
    text = convert_plain_numbers(text)

    text = MULTISPACE_PATTERN.sub(" ", text).strip()

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


def build_tts_text(display_name: str, message_text: str, platform_name: str | None = None) -> str:
    safe_name = sanitize_username_for_tts(display_name)
    if not safe_name:
        safe_name = "usuario"

    if not message_text:
        return ""

    if platform_name:
        return f"{safe_name} disse no {platform_name}: {message_text}"

    return f"{safe_name} disse: {message_text}"



