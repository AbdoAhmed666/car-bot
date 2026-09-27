"""Rules every query on the shop's SQL Server (src/export.py) must follow:
read-only, never block the shop program, and run on SQL Server 2008."""
import ast
import re
from pathlib import Path

import pytest

from src import export, shop

SOURCE = Path(export.__file__).read_text(encoding="utf-8")
SQL = [n.value for n in ast.walk(ast.parse(SOURCE))
       if isinstance(n, ast.Constant) and isinstance(n.value, str) and "SELECT" in n.value]

# T-SQL added after SQL Server 2008 (compatibility level 100 still accepts some of them)
NEWER_THAN_2008 = ["IIF(", "CONCAT(", "FORMAT(", "TRY_CAST", "TRY_CONVERT", "TRY_PARSE", "STRING_AGG",
                   "STRING_SPLIT", "OFFSET ", "FETCH NEXT", "EOMONTH", "DATEFROMPARTS", "CHOOSE(",
                   "LAG(", "LEAD(", "FIRST_VALUE", "LAST_VALUE", "THROW", "JSON_", "TRIM("]


def test_found_the_queries():
    assert len(SQL) >= 9


def test_every_shop_table_is_read_with_nolock():
    refs = re.findall(r"(?:FROM|JOIN)\s+dbo\.\w+(?:\s+(?!WITH\b)\w+)?\s*(WITH \(NOLOCK\))?", SOURCE)
    assert refs, "no table references found"
    assert all(refs), "a dbo table is read without WITH (NOLOCK)"


@pytest.mark.parametrize("word", NEWER_THAN_2008)
def test_sql_server_2008_only(word):
    assert not [q for q in SQL if word in q.upper()]


def test_only_selects():
    with pytest.raises(ValueError):
        shop.Shop(cfg=None)._rows("DELETE FROM items")
    assert all(sql.lstrip().upper().startswith("SELECT") for sql, _ in export.TABLES.values())
