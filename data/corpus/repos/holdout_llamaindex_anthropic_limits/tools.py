"""Cong cu dieu chinh han muc the tin dung."""
import asyncio
import os

import psycopg2
from llama_index.core.tools import FunctionTool
from opentelemetry import trace

tracer = trace.get_tracer("han_muc_the")

DSN = os.environ.get("CARDS_DSN", "host=pg.example.vn dbname=the user=svc_the")
CAN_BO_QUEUE: asyncio.Queue = asyncio.Queue()


async def await_officer_approval(customer_id: str, han_muc_moi: int) -> bool:
    """Cho can bo tin dung duyet. Tra ve True neu duoc duyet."""
    await CAN_BO_QUEUE.put({"customer_id": customer_id, "han_muc_moi": han_muc_moi})
    phan_hoi = await asyncio.wait_for(CAN_BO_QUEUE.get(), timeout=3600)
    return bool(phan_hoi.get("duyet"))


def doc_su_dung_the(customer_id: str) -> dict:
    """Doc muc su dung the 3 thang gan nhat."""
    with tracer.start_as_current_span("doc_su_dung_the"):
        conn = psycopg2.connect(DSN)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT card_number, han_muc, du_no, thu_nhap "
                "FROM the_tin_dung WHERE customer_id = %s",
                (customer_id,),
            )
            row = cur.fetchone()
        finally:
            conn.close()
    if row is None:
        return {"loi": "khong co the"}
    return {"card_number": row[0], "han_muc": row[1], "du_no": row[2], "thu_nhap": row[3]}


def de_xuat_han_muc(han_muc_hien_tai: int, du_no_trung_binh: int) -> int:
    """De xuat han muc moi, lam tron den 1 trieu dong."""
    if du_no_trung_binh * 10 >= han_muc_hien_tai * 8:
        moi = int(han_muc_hien_tai * 1.2)
    else:
        moi = han_muc_hien_tai
    return (moi // 1_000_000) * 1_000_000


async def ap_dung_han_muc(customer_id: str, han_muc_moi: int) -> str:
    """Ap dung han muc moi sau khi can bo duyet."""
    duoc_duyet = await await_officer_approval(customer_id, han_muc_moi)
    if not duoc_duyet:
        return "Can bo tu choi, khong thay doi han muc."
    with tracer.start_as_current_span("ap_dung_han_muc"):
        conn = psycopg2.connect(DSN)
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE the_tin_dung SET han_muc = %s WHERE customer_id = %s",
                (han_muc_moi, customer_id),
            )
            conn.commit()
        finally:
            conn.close()
    return "Da cap nhat han muc."


doc_tool = FunctionTool.from_defaults(fn=doc_su_dung_the, name="doc_su_dung_the")
de_xuat_tool = FunctionTool.from_defaults(fn=de_xuat_han_muc, name="de_xuat_han_muc")
ap_dung_tool = FunctionTool.from_defaults(async_fn=ap_dung_han_muc, name="ap_dung_han_muc")

TOOLS = [doc_tool, de_xuat_tool, ap_dung_tool]
