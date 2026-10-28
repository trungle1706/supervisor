# ruff: noqa: E501
"""Labels of the Source panel (WP-O1), English and Vietnamese, prefix ``ik_``. Merged into
``i18n._T`` by one line in ``i18n.py``. Synthetic UI text only."""

from __future__ import annotations

IK: dict[str, tuple[str, str]] = {
    "ik_title": ("Source", "Mã nguồn"),
    "ik_hint": (
        "The code of this candidate, taken in as numbered attempts. Every file is scrubbed for secrets before it is stored. Zip up to {mb} MB; Python and config text files only.",
        "Mã nguồn của ứng viên này, nhận vào theo từng lần đánh số. Mọi tệp được xóa bí mật trước khi lưu. Zip tối đa {mb} MB; chỉ tệp văn bản Python và cấu hình.",
    ),
    "ik_files_hint": (
        "Allowed: .py .yaml .yml .toml .json .md .txt .cfg .ini .env.example .sql .ipynb (notebooks keep code cells only). A path with .., an absolute path, a link or a binary file refuses the whole zip. A new upload is a new attempt; old attempts stay.",
        "Cho phép: .py .yaml .yml .toml .json .md .txt .cfg .ini .env.example .sql .ipynb (notebook chỉ giữ ô mã). Đường dẫn có .., đường dẫn tuyệt đối, liên kết hoặc tệp nhị phân sẽ làm cả tệp zip bị từ chối. Tải lên mới là lần mới; các lần cũ được giữ.",
    ),
    "ik_none": ("No source taken in yet.", "Chưa nhận mã nguồn nào."),
    "ik_upload": ("Upload source", "Tải mã nguồn lên"),
    "ik_reupload": ("Re-upload", "Tải lại"),
    "ik_file": ("Zip file", "Tệp zip"),
    "ik_git": ("or git URL", "hoặc URL git"),
    "ik_send": ("Take in", "Nhận vào"),
    "ik_view_only": (
        "Your role may look at the attempts but not add one.",
        "Vai trò của bạn chỉ xem được các lần nhận, không thêm được.",
    ),
    "ik_c_n": ("Attempt", "Lần"),
    "ik_c_source": ("Source", "Nguồn"),
    "ik_c_files": ("Files", "Tệp"),
    "ik_c_sha": ("SHA-256", "SHA-256"),
    "ik_c_by": ("By", "Bởi"),
    "ik_c_note": ("Note", "Ghi chú"),
    "ik_kind_upload": ("zip", "zip"),
    "ik_kind_git": ("git", "git"),
    "ik_kind_workspace": ("workspace", "workspace"),
    "ik_st_scrubbed": ("scrubbed", "đã xóa bí mật"),
    "ik_st_stored": ("stored", "đã lưu"),
    "ik_st_failed": ("failed", "lỗi"),
    "ik_open_page": ("Open the Source page", "Mở trang Mã nguồn"),
}
