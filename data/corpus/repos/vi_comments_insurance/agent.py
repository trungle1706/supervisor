"""Vòng lặp trợ lý tư vấn bảo hiểm qua ngân hàng (bancassurance)."""
import inspect
import json
import os

from openai import OpenAI

from cong_cu import CONG_CU

# Tên mô hình dùng cho trợ lý
MODEL = "gpt-4.1-mini"

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

# Bảng tra tên công cụ sang hàm tương ứng
TRA_CONG_CU = {ham.__name__: ham for ham in CONG_CU}


def tao_mo_ta_cong_cu() -> list[dict]:
    """Tạo mô tả công cụ theo định dạng của OpenAI từ chữ ký hàm."""
    mo_ta = []
    for ham in CONG_CU:
        tham_so = {
            ten: {"type": "string"} for ten in inspect.signature(ham).parameters
        }
        mo_ta.append(
            {
                "type": "function",
                "function": {
                    "name": ham.__name__,
                    "description": inspect.getdoc(ham),
                    "parameters": {"type": "object", "properties": tham_so},
                },
            }
        )
    return mo_ta


def tu_van(cau_hoi: str) -> str:
    """Trả lời câu hỏi của khách hàng, gọi công cụ khi cần."""
    tin_nhan = [
        {"role": "system", "content": "Bạn là chuyên viên tư vấn bảo hiểm của ngân hàng."},
        {"role": "user", "content": cau_hoi},
    ]
    for _ in range(5):
        # Gọi mô hình với danh sách công cụ
        phan_hoi = client.chat.completions.create(
            model=MODEL, messages=tin_nhan, tools=tao_mo_ta_cong_cu()
        ).choices[0].message
        tin_nhan.append(phan_hoi)
        if not phan_hoi.tool_calls:
            return phan_hoi.content or ""
        for lenh in phan_hoi.tool_calls:
            ket_qua = TRA_CONG_CU[lenh.function.name](**json.loads(lenh.function.arguments))
            tin_nhan.append(
                {"role": "tool", "tool_call_id": lenh.id, "content": json.dumps(ket_qua)}
            )
    return "Xin lỗi, tôi chưa trả lời được câu hỏi này."
