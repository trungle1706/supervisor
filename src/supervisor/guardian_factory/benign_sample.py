"""A synthetic benign sample for the over-broad check (WP-G1).

120 short Vietnamese-style bank texts built from fixed templates. They hold words, short
numbers, dates and times, and no long digit run, no name, no phone, no account. A pattern that
matches many of them is too broad to block anything. Synthetic only; nothing here is real data.
"""

from __future__ import annotations

_TEMPLATES = (
    "Xin chào, tôi muốn hỏi về lịch làm việc của chi nhánh số {n}.",
    "Đơn hàng {n} đã được giao vào ngày {d}/{m}/2026.",
    "Cuộc họp bắt đầu lúc {h}:{mi} tại phòng {n}.",
    "Lãi suất tiết kiệm kỳ hạn {m} tháng là {p}% mỗi năm.",
    "Please summarise the report for quarter {q} in {n} lines.",
    "Tôi cần đổi mật khẩu đăng nhập ứng dụng trên điện thoại.",
    "Hồ sơ vay số {n} đang chờ thẩm định, dự kiến {m} ngày làm việc.",
    "Tool search returned {n} results for the query about opening hours.",
    "Phiên bản {q}.{m}.{p} của tài liệu hướng dẫn đã được cập nhật.",
    "Khách hàng hỏi cách tra cứu sao kê trong {m} tháng gần nhất.",
)


def benign_sample(size: int = 120) -> list[str]:
    """``size`` deterministic benign texts (the same list on every call)."""
    out: list[str] = []
    for i in range(size):
        t = _TEMPLATES[i % len(_TEMPLATES)]
        out.append(
            t.format(
                n=(i * 37 + 11) % 9000 + 100,
                d=i % 28 + 1,
                m=i % 12 + 1,
                h=i % 24,
                mi=f"{(i * 7) % 60:02d}",
                p=(i % 9) + 1,
                q=i % 4 + 1,
            )
        )
    return out
