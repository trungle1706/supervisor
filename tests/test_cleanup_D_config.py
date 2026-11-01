"""Clean-up audit X1 / G1: every ``Settings`` field is declared once in the class body (a second
declaration silently wins and hides the first comment)."""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "src" / "supervisor" / "config.py"


def test_every_settings_field_is_declared_once() -> None:
    tree = ast.parse(CONFIG.read_text(encoding="utf-8"))
    (cls,) = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Settings"]
    names = [
        n.target.id
        for n in cls.body
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
    ]
    assert len(names) > 300  # the scan really saw the class
    dup = sorted(k for k, v in Counter(names).items() if v > 1)
    assert dup == [], f"fields declared twice: {dup}"


def test_console_my_agents_is_a_bool_flag_off_by_default() -> None:
    from supervisor.config import Settings

    f = Settings.model_fields["console_my_agents"]
    assert f.default is False and f.annotation is bool
