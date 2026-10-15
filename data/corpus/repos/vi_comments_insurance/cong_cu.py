"""Các công cụ của trợ lý bảo hiểm: tra cứu hợp đồng, tính phí, gửi email tư vấn."""
import sqlite3
from datetime import date

import requests

# Đường dẫn tới tệp cơ sở dữ liệu hợp đồng
DUONG_DAN_DB = "hop_dong.db"


def tra_cuu_hop_dong(so_cccd: str) -> list[dict]:
    """Lấy thông tin hợp đồng bảo hiểm của khách hàng theo số căn cước."""
    ket_noi = sqlite3.connect(DUONG_DAN_DB)
    cur = ket_noi.cursor()
    # Chỉ lấy các hợp đồng còn hiệu lực
    cur.execute(
        "SELECT so_hop_dong, ho_ten, san_pham, phi_nam FROM hop_dong "
        "WHERE so_cccd = ? AND trang_thai = 'con_hieu_luc'",
        (so_cccd,),
    )
    ket_qua = [
        {"so_hop_dong": h[0], "ho_ten": h[1], "san_pham": h[2], "phi_nam": h[3]}
        for h in cur.fetchall()
    ]
    ket_noi.close()
    return ket_qua


def tinh_phi_bao_hiem(ngay_sinh: str, thu_nhap: int, so_tien_bao_hiem: int) -> dict:
    """Tính phí bảo hiểm hằng năm dựa trên tuổi và thu nhập của khách hàng."""
    nam_sinh = int(ngay_sinh[:4])
    tuoi = date.today().year - nam_sinh
    # Phí cơ bản tăng dần theo độ tuổi
    ty_le = 0.012 + 0.0004 * max(tuoi - 25, 0)
    phi = int(so_tien_bao_hiem * ty_le)
    # Không để phí vượt quá 20% thu nhập năm
    tran = int(thu_nhap * 12 * 0.2)
    return {"phi_nam": min(phi, tran), "tuoi": tuoi}


def gui_email_tu_van(email: str, ho_ten: str, noi_dung: str) -> dict:
    """Gửi email tư vấn sản phẩm bảo hiểm tới khách hàng."""
    phan_hoi = requests.post(
        "https://mail.example.vn/api/send",
        json={"to": email, "ten": ho_ten, "body": noi_dung},
        timeout=15,
    )
    return {"da_gui": phan_hoi.ok}


# Danh sách công cụ mà mô hình được phép gọi
CONG_CU = [tra_cuu_hop_dong, tinh_phi_bao_hiem, gui_email_tu_van]
