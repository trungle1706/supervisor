"""Tac tu nap tien tiet kiem dung Anthropic SDK truc tiep."""
import configparser
import json

import anthropic

from tools import nap_tiet_kiem, tinh_lai_tiet_kiem, tra_cuu_so_du

cfg = configparser.ConfigParser()
cfg.read("settings.ini")

client = anthropic.Anthropic()

TOOL_SCHEMAS = [
    {
        "name": "tra_cuu_so_du",
        "description": "Xem so du tai khoan thanh toan.",
        "input_schema": {
            "type": "object",
            "properties": {"so_tai_khoan": {"type": "string"}},
            "required": ["so_tai_khoan"],
        },
    },
    {
        "name": "tinh_lai_tiet_kiem",
        "description": "Tinh tien lai du kien cua mot khoan tiet kiem.",
        "input_schema": {
            "type": "object",
            "properties": {
                "so_tien": {"type": "integer"},
                "so_thang": {"type": "integer"},
                "lai_suat_nam": {"type": "number"},
            },
            "required": ["so_tien", "so_thang", "lai_suat_nam"],
        },
    },
    {
        "name": "nap_tiet_kiem",
        "description": "Nap tien vao so tiet kiem cua nguoi thu huong.",
        "input_schema": {
            "type": "object",
            "properties": {
                "so_tai_khoan": {"type": "string"},
                "so_tai_khoan_thu_huong": {"type": "string"},
                "so_tien": {"type": "integer"},
            },
            "required": ["so_tai_khoan", "so_tai_khoan_thu_huong", "so_tien"],
        },
    },
]

DISPATCH = {
    "tra_cuu_so_du": tra_cuu_so_du,
    "tinh_lai_tiet_kiem": tinh_lai_tiet_kiem,
    "nap_tiet_kiem": nap_tiet_kiem,
}


def chay(yeu_cau: str) -> str:
    messages = [{"role": "user", "content": yeu_cau}]
    for _ in range(6):
        rep = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system="Ban ho tro khach nap tien tiet kiem. Tra loi bang tieng Viet.",
            tools=TOOL_SCHEMAS,
            messages=messages,
        )
        if rep.stop_reason != "tool_use":
            return "".join(b.text for b in rep.content if b.type == "text")
        messages.append({"role": "assistant", "content": rep.content})
        ket_qua = []
        for b in rep.content:
            if b.type == "tool_use":
                out = DISPATCH[b.name](**b.input)
                ket_qua.append(
                    {"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(out)}
                )
        messages.append({"role": "user", "content": ket_qua})
    return ""


if __name__ == "__main__":
    print(chay("Nap 2000000 dong tu tai khoan 0123456789 vao so tiet kiem 0987654321"))
