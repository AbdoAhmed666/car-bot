"""Arabic text folding, so different spellings of a part name compare equal."""
import re
import unicodedata

# Arabic-Indic and extended Arabic-Indic digits -> ASCII
_DIGITS = {ord(c): str(i % 10) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩"
                                                     "۰۱۲۳۴۵۶۷۸۹")}

# alef variants -> bare alef, ya/alef-maqsura -> ya, ta marbuta -> ha, hamza forms
_LETTERS = {
    "آ": "ا", "أ": "ا", "إ": "ا", "ٱ": "ا",
    "ى": "ي", "ئ": "ي",
    "ة": "ه",
    "ؤ": "و",
    "ـ": "",  # tatweel
}

_TASHKEEL = re.compile(r"[ً-ْٰۖ-ۭ]")
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")


def normalize(text) -> str:
    """Fold spelling differences: أ/إ/آ -> ا, ى -> ي, ة -> ه, Arabic digits -> 0-9,
    tashkeel and punctuation dropped, Latin lowercased.

    "طلمبة باور أوبترا" and "طلمبه باور اوبترا" give the same string.
    """
    if text is None:
        return ""
    s = unicodedata.normalize("NFKC", str(text))
    s = s.translate(_DIGITS)
    s = _TASHKEEL.sub("", s)
    for src, dst in _LETTERS.items():
        s = s.replace(src, dst)
    s = _NON_WORD.sub(" ", s)
    s = _SPACES.sub(" ", s).strip().lower()
    return s


def tokens(text) -> list:
    """normalize() split into words, with the definite article "ال" dropped."""
    out = []
    for t in normalize(text).split():
        if len(t) > 3 and t.startswith("ال"):
            t = t[2:]
        out.append(t)
    return out
