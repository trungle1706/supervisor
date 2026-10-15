"""Cac cong cu (tools) cho tac tu khoan vay tieu dung."""
import os

import requests
from langchain_core.tools import StructuredTool, Tool
from pydantic import BaseModel, Field
from sqlalchemy import text

from db import get_session

LENDING_API = "https://lending.nganhang.internal/v1/disbursements"


class DisburseInput(BaseModel):
    so_hop_dong: str = Field(description="So hop dong vay")
    tai_khoan_nhan: str = Field(description="Tai khoan nhan tien giai ngan")
    so_tien: int = Field(description="So tien, don vi dong")


def tra_cuu_hop_dong(so_hop_dong: str) -> dict:
    """Tra cuu khoan vay theo so hop dong."""
    session = get_session()
    try:
        row = session.execute(
            text(
                "SELECT so_hop_dong, ho_ten, so_dien_thoai, du_no, lai_suat "
                "FROM khoan_vay WHERE so_hop_dong = :so"
            ),
            {"so": so_hop_dong},
        ).mappings().first()
    finally:
        session.close()
    return dict(row) if row else {"loi": "khong tim thay hop dong"}


def tinh_ky_tra(chuoi: str) -> str:
    """Tinh tien tra gop moi thang. Dau vao: 'goc,lai_nam_phan_tram,so_thang'."""
    goc, lai, thang = chuoi.split(",")
    r = float(lai) / 100 / 12
    n = int(thang)
    if r == 0:
        return str(round(float(goc) / n))
    tra = float(goc) * r / (1 - (1 + r) ** -n)
    return str(round(tra))


def giai_ngan_khoan_vay(so_hop_dong: str, tai_khoan_nhan: str, so_tien: int) -> dict:
    """Giai ngan khoan vay vao tai khoan nhan."""
    resp = requests.post(
        LENDING_API,
        json={
            "so_hop_dong": so_hop_dong,
            "tai_khoan_nhan": tai_khoan_nhan,
            "so_tien": so_tien,
        },
        headers={"X-Api-Key": os.environ["LENDING_API_KEY"]},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


tra_cuu_tool = StructuredTool.from_function(
    func=tra_cuu_hop_dong,
    name="tra_cuu_khoan_vay",
    description="Tra cuu thong tin khoan vay theo so_hop_dong.",
)

tinh_ky_tra_tool = Tool(
    name="tinh_tien_tra_gop",
    func=tinh_ky_tra,
    description="Tinh tien tra gop hang thang tu goc, lai suat nam, so thang.",
)

giai_ngan_tool = StructuredTool.from_function(
    func=giai_ngan_khoan_vay,
    name="giai_ngan_khoan_vay",
    description="Giai ngan khoan vay den tai_khoan_nhan.",
    args_schema=DisburseInput,
)

ALL_TOOLS = [tra_cuu_tool, tinh_ky_tra_tool, giai_ngan_tool]
