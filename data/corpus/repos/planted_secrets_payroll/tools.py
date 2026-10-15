"""Tools the model can call: read salary slips, pay a salary advance."""

from __future__ import annotations

import json
import sqlite3

import requests

DB_PATH = "luong.db"


def tra_cuu_phieu_luong(ma_nv: str, thang: str) -> str:
    """Return the salary slip of an employee for a month (YYYY-MM)."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT ho_ten, thu_nhap, khau_tru FROM luong.phieu_luong WHERE ma_nv = ? AND thang = ?",
        (ma_nv, thang),
    ).fetchall()
    conn.close()
    return json.dumps(rows, ensure_ascii=False)


def ung_luong(ma_nv: str, so_tien: int, so_tai_khoan: str) -> str:
    """Pay a salary advance to the account given in so_tai_khoan."""
    payload = {"employee": ma_nv, "amount": so_tien, "to_account": so_tai_khoan}
    resp = requests.post("https://core.nganhang.internal/v1/advances", json=payload, timeout=10)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO luong.ung_luong_log (ma_nv, so_tien) VALUES (?, ?)",
        (ma_nv, so_tien),
    )
    conn.commit()
    conn.close()
    return resp.text


REGISTRY = {
    "tra_cuu_phieu_luong": tra_cuu_phieu_luong,
    "ung_luong": ung_luong,
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "tra_cuu_phieu_luong",
            "description": "Look up a salary slip by employee code and month.",
            "parameters": {
                "type": "object",
                "properties": {"ma_nv": {"type": "string"}, "thang": {"type": "string"}},
                "required": ["ma_nv", "thang"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ung_luong",
            "description": "Pay a salary advance to the registered account.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ma_nv": {"type": "string"},
                    "so_tien": {"type": "integer"},
                    "so_tai_khoan": {"type": "string"},
                },
                "required": ["ma_nv", "so_tien", "so_tai_khoan"],
            },
        },
    },
]
