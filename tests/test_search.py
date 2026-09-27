import pytest

from src.search import search
from src.shop import Item

NAMES = [
    "طلمبه باور اوبترا", "طلمبه باور لانوس", "طلمبه باور نيو اوبترا", "طلمبه باور فيرنا",
    "طلمبه بنزين كامله اوبترا", "موبينه سيراتو", "موبينه كرولا 1300", "موبينه نيسان N17",
    "بلي عجل امامي لانوس HSC", "بلي عجل امامي فيرنا", "ماستر فرامل عمومى لانوس",
    "كوعه كاملة كروزبالثرموستات", "كولر كامل كروز", "زيت فتيس 4 سرعات", "زيت فتيس 6 سرعات",
    "فلتر تكييف نيوالينترا", "حساس ايدل لانوس", "حساس ايدل لانوس GM كورى", "اويل سيل صباب لانسر",
]
ITEMS = [Item(n, name, f"0{1000 + n}", 5, 100, 70) for n, name in enumerate(NAMES, 1)]


def best(text):
    r = search(text, ITEMS)
    return r.item.name if r.item else None


@pytest.mark.parametrize("text, name", [
    ("فاضل كام من طلمبة باور أوبترا؟", "طلمبه باور اوبترا"),      # question words, ة, أ
    ("طرمبة باور لانوس", "طلمبه باور لانوس"),                       # other spelling of طلمبه
    ("طلنبه باور لانوس", "طلمبه باور لانوس"),                       # typo
    ("عندنا موبينة سيراتو؟", "موبينه سيراتو"),
    ("بلي عجل لانوس", "بلي عجل امامي لانوس HSC"),                   # a word left out
    ("ماستر فرامل لانوس", "ماستر فرامل عمومى لانوس"),
    ("زيت فتيس ٤ سرعات", "زيت فتيس 4 سرعات"),                        # Arabic digit
    ("زيت فتيس 4", "زيت فتيس 4 سرعات"),
    ("فلتر تكيف النيو النترا", "فلتر تكييف نيوالينترا"),             # words glued in the name
    ("رصيد اويل سيل لانسر", "اويل سيل صباب لانسر"),
    ("01003", "طلمبه باور نيو اوبترا"),                              # the item code
])
def test_finds_the_item(text, name):
    assert best(text) == name


def test_several_items_fit_most_sold_first():
    r = search("طلمبه باور", ITEMS, popularity={2: 50, 4: 10})
    assert r.item is None
    names = [i.name for i in r.choices]
    assert names[:2] == ["طلمبه باور لانوس", "طلمبه باور فيرنا"]
    assert set(names) >= {"طلمبه باور اوبترا", "طلمبه باور نيو اوبترا"}


def test_glued_word_is_offered():
    r = search("كوعة كروز", ITEMS)
    assert (r.item or r.choices[0]).name == "كوعه كاملة كروزبالثرموستات"


def test_nothing_like_it():
    r = search("بطارية", ITEMS)
    assert r.item is None and r.choices == []


def test_only_question_words():
    r = search("فاضل كام؟", ITEMS)
    assert r.item is None and r.choices == [] and r.query == ""
