"""Find the item someone means from how they typed it.

"فاضل كام من طلمبة باور أوبترا؟" -> the item "طلمبه باور اوبترا".
Spelling is folded first (normalize), the question words are dropped, then
item names are compared word by word, so a missing or misspelt word still
matches. When several items fit equally, the caller asks which one.
"""
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from .normalize import tokens

# words that are part of the question, not of the item name (already normalized)
STOPWORDS = {
    "فاضل", "فاضله", "باقي", "لسه", "كام", "كم", "بكام", "عدد", "رصيد", "كميه", "سعر",
    "عندنا", "عندك", "عندي", "عندكم", "موجود", "موجوده", "متاح", "في", "من", "علي",
    "ايه", "اي", "هو", "هي", "ده", "دي", "دا", "يا", "لو", "سمحت", "عايز", "عاوز",
    "شوف", "قولي", "قطعه", "قطع", "حته", "حاجه",
    "حساب", "عليه", "عليها", "مديونيه", "عميل", "زبون", "اشتري", "بيشتري",
}

# words that say the question is about a customer, not an item
CUSTOMER_HINTS = {"حساب", "عليه", "عليها", "مديونيه", "عميل", "زبون", "اشتري", "بيشتري"}

# common spellings of the same word
SPELLING = {"طرمبه": "طلمبه", "طرومبه": "طلمبه", "رولمان": "بلي"}

BEST = 85        # a single item at least this good, clearly ahead of the rest, is the answer
AHEAD = 8        # ... by at least this many points
MAYBE = 60       # below this nothing is suggested


@dataclass
class Result:
    item: object = None          # the one item meant, when it is clear
    choices: list = None         # otherwise the likely ones, best first
    query: str = ""              # what was searched for, after cleaning
    score: float = 0.0           # how well the best one matched (0-100)
    hinted: bool = False         # the question has a customer word in it (حساب، عليه، ...)


def clean(text) -> str:
    words = [SPELLING.get(t, t) for t in tokens(text)]
    return " ".join(w for w in words if w not in STOPWORDS)


def search(text, items, popularity=None, limit=6) -> Result:
    """Match free text to one of `items` (objects with .id, .name, .code).

    popularity: {item id: number} used to order equally good choices
    (e.g. quantity sold lately), so the usual item comes first.
    """
    query = clean(text)
    hinted = bool(CUSTOMER_HINTS & set(tokens(text)))
    if not query:
        return Result(choices=[], query=query, hinted=hinted)
    popularity = popularity or {}

    names = {i.id: " ".join(SPELLING.get(t, t) for t in tokens(i.name)) for i in items}
    by_id = {i.id: i for i in items}

    for i in items:     # the item's code, or its exact name
        if (i.code and query == i.code.lower()) or query == names[i.id]:
            return Result(item=i, query=query, score=100.0, hinted=hinted)

    found = process.extract(query, names, scorer=_score, limit=30, score_cutoff=MAYBE)
    if not found:
        return Result(choices=[], query=query, hinted=hinted)
    found.sort(key=lambda f: -f[1])
    top = found[0][1]
    second = found[1][1] if len(found) > 1 else 0
    if top >= BEST and top - second >= AHEAD:
        return Result(item=by_id[found[0][2]], query=query, score=top, hinted=hinted)
    # equally good ones (within 5 points) in order of popularity
    close = [f for f in found if f[1] >= top - 15]
    close.sort(key=lambda f: (-round(f[1] / 5), -popularity.get(f[2], 0)))
    return Result(choices=[by_id[f[2]] for f in close[:limit]], query=query, score=top, hinted=hinted)


def _word(qword, name_words) -> float:
    """How well one query word appears in the name: 100 if it is there, even
    inside a longer word ("كروز" in "كروزبالثرموستات"), else the closest spelling."""
    best = 0.0
    for w in name_words:
        if qword == w or (len(qword) >= 3 and qword in w):
            return 100.0
        best = max(best, fuzz.ratio(qword, w))
    return best


def _score(query, name, **_) -> float:
    qwords, nwords = query.split(), name.split()
    coverage = sum(_word(q, nwords) for q in qwords) / len(qwords)
    # coverage: every word asked for is in the name; the other two prefer the
    # name that has little else besides those words
    return 0.6 * coverage + 0.25 * fuzz.token_set_ratio(query, name) + 0.15 * fuzz.ratio(query, name)
