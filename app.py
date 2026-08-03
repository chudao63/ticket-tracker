# -*- coding: utf-8 -*-
"""
Ticket Tracker — VOMS × CCTS (backend FastAPI + SQLite)

Chạy:  pip install -r requirements.txt
       python app.py
Mở:    http://localhost:8000   (người khác trong LAN: http://<ip-máy-này>:8000)

- Import file tổng (.xlsx) -> phân tỉnh -> ASP (SE/EC/ITS/ES) + CSE phụ trách.
- Lấy trạng thái VOMS qua API (dán Authorization + X-Tenant-Id).
- CCTS: dán TSV từ script chạy trong tab (không dính 511), hoặc thử token+cookie.
- Note chung theo từng ticket (lưu DB, giữ lịch sử, mọi người cùng thấy).
- Token/cookie lưu ở file creds.local.json cạnh app (để tắt/mở server không phải
  dán lại) — file này KHÔNG mã hoá, chỉ nên dùng trên máy/server nội bộ tin cậy,
  và đã thêm vào .gitignore để không lỡ commit lên git.
"""
import base64
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests
import uvicorn

# Khi chạy qua Task Scheduler / redirect ra file (>> server.log), Windows dùng
# codepage cp1252 cho stdout thay vì UTF-8 -> print() có dấu tiếng Việt sẽ crash
# ngay lúc khởi động. Ép UTF-8 để chạy được cả trong terminal lẫn chạy nền.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
# TICKET_DATA_DIR: nơi lưu DB + creds — mặc định cạnh app.py (chạy local/LAN như cũ).
# Deploy lên Railway/Render (ổ đĩa app bị xoá mỗi lần deploy lại) thì PHẢI trỏ biến
# này ra thư mục Volume/Persistent Disk, nếu không mất sạch dữ liệu sau mỗi lần deploy.
DATA_DIR = Path(os.environ.get("TICKET_DATA_DIR", str(BASE_DIR)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "ticket_tracker.db"
CREDS_FILE = DATA_DIR / "creds.local.json"

# =========================================================
#  DỮ LIỆU TỈNH -> CSE  +  TỈNH -> ASP (SE/EC/ITS/ES)
# =========================================================
PROVINCE_DATA = {
    # chuongpham (Miền Tây + Tây Ninh + Long An)
    "STR": ("Tỉnh Sóc Trăng", ["chuongpham"]),
    "CTH": ("TP Cần Thơ", ["chuongpham"]),
    "HUG": ("Tỉnh Hậu Giang", ["chuongpham"]),
    "AGI": ("Tỉnh An Giang", ["chuongpham"]),
    "KGI": ("Tỉnh Kiên Giang", ["chuongpham"]),
    "BLI": ("Tỉnh Bạc Liêu", ["chuongpham"]),
    "CMA": ("Tỉnh Cà Mau", ["chuongpham"]),
    "TGI": ("Tỉnh Tiền Giang", ["chuongpham"]),
    "DTH": ("Tỉnh Đồng Tháp", ["chuongpham"]),
    "BTR": ("Tỉnh Bến Tre", ["chuongpham"]),
    "TVI": ("Tỉnh Trà Vinh", ["chuongpham"]),
    "VLO": ("Tỉnh Vĩnh Long", ["chuongpham"]),
    "TNI": ("Tỉnh Tây Ninh", ["chuongpham"]),
    "LAN": ("Tỉnh Long An", ["chuongpham"]),
    # daochu (Tây Bắc)
    "PTH": ("Tỉnh Phú Thọ", ["daochu"]),
    "DBI": ("Tỉnh Điện Biên", ["daochu"]),
    "LCH": ("Tỉnh Lai Châu", ["daochu"]),
    "LCA": ("Tỉnh Lào Cai", ["daochu"]),
    "YBI": ("Tỉnh Yên Bái", ["daochu"]),
    "SLA": ("Tỉnh Sơn La", ["daochu"]),
    "HAG": ("Tỉnh Hà Giang", ["daochu"]),
    "HBI": ("Tỉnh Hoà Bình", ["daochu"]),
    "TQU": ("Tỉnh Tuyên Quang", ["daochu"]),
    "VPH": ("Tỉnh Vĩnh Phúc", ["daochu"]),
    # dinhnguyen (Đông Bắc)
    "HPH": ("TP Hải Phòng", ["dinhnguyen"]),
    "HDU": ("Tỉnh Hải Dương", ["dinhnguyen"]),
    "TNG": ("Tỉnh Thái Nguyên", ["dinhnguyen"]),
    "CBA": ("Tỉnh Cao Bằng", ["dinhnguyen"]),
    "BKA": ("Tỉnh Bắc Kạn", ["dinhnguyen"]),
    "LSO": ("Tỉnh Lạng Sơn", ["dinhnguyen"]),
    "QNI": ("Tỉnh Quảng Ninh", ["dinhnguyen"]),
    # qtuan (Bắc Trung Bộ + 1 phần Tây Nguyên)
    "QBI": ("Tỉnh Quảng Bình", ["qtuan"]),
    "DNA": ("TP Đà Nẵng", ["qtuan"]),
    "QNA": ("Tỉnh Quảng Nam", ["qtuan"]),
    "TTH": ("Tỉnh Thừa Thiên Huế", ["qtuan"]),
    "QTR": ("Tỉnh Quảng Trị", ["qtuan"]),
    "KTU": ("Tỉnh Kon Tum", ["qtuan"]),
    "QNG": ("Tỉnh Quảng Ngãi", ["qtuan"]),
    # khiemnguyen (Đồng bằng sông Hồng)
    "BNI": ("Tỉnh Bắc Ninh", ["khiemnguyen"]),
    "BGI": ("Tỉnh Bắc Giang", ["khiemnguyen"]),
    "HYE": ("Tỉnh Hưng Yên", ["khiemnguyen"]),
    "TBI": ("Tỉnh Thái Bình", ["khiemnguyen"]),
    "NDI": ("Tỉnh Nam Định", ["khiemnguyen"]),
    "HNA": ("Tỉnh Hà Nam", ["khiemnguyen"]),
    "NBI": ("Tỉnh Ninh Bình", ["khiemnguyen"]),
    # thailong (Tây Nguyên + Nam Trung Bộ)
    "DLA": ("Tỉnh Đắk Lắk", ["thailong"]),
    "PYE": ("Tỉnh Phú Yên", ["thailong"]),
    "GLA": ("Tỉnh Gia Lai", ["thailong"]),
    "BDI": ("Tỉnh Bình Định", ["thailong"]),
    "NTH": ("Tỉnh Ninh Thuận", ["thailong"]),
    "KHO": ("Tỉnh Khánh Hòa", ["thailong"]),
    # tienkieu
    "HTI": ("Tỉnh Hà Tĩnh", ["tienkieu"]),
    "NAN": ("Tỉnh Nghệ An", ["tienkieu"]),
    "THO": ("Tỉnh Thanh Hóa", ["tienkieu"]),
    # NHIỀU NGƯỜI QUẢN LÝ
    "HNO": ("TP Hà Nội", ["hungvu", "vinhpham", "thainguyen", "phongbui"]),
    "HCM": ("TP Hồ Chí Minh",
            ["thuanlu", "duynguyen", "luanlu", "lehieu", "lamdam", "khaitran"]),
    "BDU": ("Tỉnh Bình Dương", ["thuanlu", "duynguyen"]),
    "VTU": ("Tỉnh Bà Rịa - Vũng Tàu", ["thuanlu", "duynguyen"]),
    "BPH": ("Tỉnh Bình Phước", ["thuanlu", "duynguyen"]),
    "DNI": ("Tỉnh Đồng Nai", ["thuanlu", "duynguyen"]),
    "BTH": ("Tỉnh Bình Thuận", ["thuanlu", "duynguyen"]),
    "DNO": ("Tỉnh Đắk Nông", ["thuanlu", "duynguyen"]),
    "LDO": ("Tỉnh Lâm Đồng", ["thuanlu", "duynguyen"]),
}

ASP_BY_CODE = {}
for _asp, _codes in {
    "SE": "HNO",
    "EC": "HPH BNI DBI HDU HYE LCH LCA NDI SLA TNG THO YBI BDU TGI BGI BKA HNA NBI TBI DTH",
    "ITS": "PTH CBA HAG HTI HBI LSO NAN QBI QNI TQU VPH DNA QNA TTH QTR TNI LAN",
    "ES": ("HCM VTU BPH DNI STR CTH AGI BLI BTR CMA HUG KGI TVI VLO NTH BTH "
           "DLA DNO GLA KTU KHO LDO PYE QNG BDI"),
}.items():
    for _c in _codes.split():
        ASP_BY_CODE[_c] = _asp

ALL_CSES = sorted({c for _, (_, cs) in PROVINCE_DATA.items() for c in cs})
ASPS = ["SE", "EC", "ITS", "ES"]

# =========================================================
#  TIỆN ÍCH CHUNG (giữ nguyên logic bản Streamlit)
# =========================================================

def remove_accents(text):
    text = unicodedata.normalize("NFD", str(text))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.replace("đ", "d").replace("Đ", "D")


def normalize_text(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    v = re.sub(r"\s+", " ", str(v).strip()).lower()
    return remove_accents(v)


def norm_key(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return re.sub(r"\s+", "", str(v)).upper()


def clean_rc(v):
    """Xoá ký tự '#' — VOMS/CCTS tìm theo mã không có '#'."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).replace("#", "").strip()


def _norm_header(s):
    s = str(s).replace("\xa0", " ")
    return remove_accents(re.sub(r"\s+", " ", s).strip().lower())


ID_COL_CANDIDATES = ["ID Yêu cầu", "Mã yêu cầu", "Mã RC", "External Ticket ID (full)",
                     "External Ticket ID", "Third Ticket ID", "Mã ticket", "Ticket ID", "RC"]
PROVINCE_COL_CANDIDATES = ["Tỉnh/Thành phố", "Tỉnh thành", "Tỉnh", "Province"]
STATION_COL_CANDIDATES = ["Mã trạm", "Station", "Mã trụ"]


def find_col_fuzzy(cols, candidates):
    norm_map = {}
    for c in cols:
        norm_map.setdefault(_norm_header(c), c)
    for cand in candidates:
        k = _norm_header(cand)
        if k in norm_map:
            return norm_map[k]
    for cand in candidates:
        k = _norm_header(cand)
        for c in cols:
            if k and k in _norm_header(c):
                return c
    return None


# ---- tỉnh (tên hoặc mã trạm) -> mã tỉnh ----
def _norm_province(name):
    s = normalize_text(name)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\b(thanh pho trung uong|thanh pho|tp|tinh)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


PROVINCE_NAME_TO_CODE = {_norm_province(nm): code for code, (nm, _) in PROVINCE_DATA.items()}
_STATION_RE = re.compile(r"^[A-Z]\.([A-Z]{3})", re.I)


def province_code_of(province_name, station_code=""):
    key = _norm_province(province_name)
    if key in PROVINCE_NAME_TO_CODE:
        return PROVINCE_NAME_TO_CODE[key]
    m = _STATION_RE.match(str(station_code or "").strip())
    if m and m.group(1).upper() in PROVINCE_DATA:
        return m.group(1).upper()
    return ""


# =========================================================
#  CẤU HÌNH ADMIN + TỰ ĐỘNG CẬP NHẬT
# =========================================================
# Khoá trang quản trị (/admin) — đặt biến môi trường TICKET_ADMIN_KEY.
# Không hardcode mật khẩu thật trong code (code này có thể lên GitHub).
# Để trống (không đặt env var) = /admin không hỏi mật khẩu.
ADMIN_KEY = os.environ.get("TICKET_ADMIN_KEY", "")

# Khoá TOÀN BỘ app (kể cả trang chính/API) bằng HTTP Basic Auth — dùng khi deploy
# ra internet công khai, không chỉ LAN nội bộ. Username: gì cũng được, chỉ check
# password. Để trống (không đặt env var) = không khoá gì cả (như khi chạy LAN cũ).
SITE_PASSWORD = os.environ.get("TICKET_SITE_PASSWORD", "")

AUTO = {"enabled": False, "interval_min": 20, "last_run": "", "last_result": ""}
CREDS = {"voms": {"token": "", "tenant": "", "saved_at": ""},
         "ccts": {"token": "", "cookie": "", "saved_at": ""}}
HEALTH = {"voms": {"status": "chưa có token", "checked_at": ""},
          "ccts": {"status": "chưa có token", "checked_at": ""}}


def _persist_creds():
    """Ghi token xuống creds.local.json để tắt/mở server không phải dán lại.
    File không mã hoá — chấp nhận đánh đổi để tiện, chỉ dùng trên máy tin cậy."""
    try:
        CREDS_FILE.write_text(json.dumps(CREDS, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(CREDS_FILE, 0o600)
        except Exception:
            pass  # Windows không có POSIX mode bits, bỏ qua nếu chmod không áp dụng được
    except Exception as e:
        print("Không ghi được creds.local.json:", e)


def _load_creds_file():
    if not CREDS_FILE.exists():
        return
    try:
        data = json.loads(CREDS_FILE.read_text(encoding="utf-8"))
        for kind in ("voms", "ccts"):
            if isinstance(data.get(kind), dict):
                CREDS[kind].update(data[kind])
    except Exception as e:
        print("Không đọc được creds.local.json:", e)


# =========================================================
#  NHÓM TRẠNG THÁI + BỘ LUẬT CẢNH BÁO (VOMS × CCTS)
# =========================================================
_VOMS_GROUP = {"cho xu ly": "pending", "da phan cong": "assigned", "ktv da nhan": "accepted",
               "dang xu ly": "processing", "hoan cong": "completed", "mo lai": "reopened",
               "dong": "closed", "da huy": "cancelled"}
_CCTS_GROUP = {"open": "open", "appointment": "appointment",
               "pending for spare parts": "spare", "pending for others": "others",
               "pending for local team close": "localclose",
               "pending for voms confirm": "vomsconfirm",
               "pending closure": "closure", "closed": "closed"}


def _vgroup(s):
    t = str(s or "").strip()
    if not t or t.startswith("LỖI"):
        return ""                      # chưa có dữ liệu -> chưa kết luận
    if t == "Không có dữ liệu":
        return "missing"
    return _VOMS_GROUP.get(normalize_text(t), "other")


def _cgroup(s):
    t = str(s or "").strip()
    if not t or t.startswith("LỖI"):
        return ""
    if t in ("Không có dữ liệu", "Không khớp mã"):
        return "missing"
    return _CCTS_GROUP.get(normalize_text(t), "other")


def make_flag(voms_status, ccts_status):
    """
    Trả (text, level). level: action | warn | danger | info | "".
    action = làm được ngay (vd đóng CCTS) · danger = lệch/mất dấu · warn = cần check · info = theo dõi.
    Trạng thái về theo đợt: trống/LỖI = CHƯA lấy -> không kết luận;
    "Không có dữ liệu"/"Không khớp mã" = ĐÃ quét mà không thấy -> báo.
    """
    v, c = _vgroup(voms_status), _cgroup(ccts_status)
    v_s, c_s = str(voms_status or "").strip(), str(ccts_status or "").strip()

    # ---- thiếu 1 bên (đã quét) ----
    if v == "missing" and c == "missing":
        return ("Không thấy ở cả VOMS lẫn CCTS, kiểm tra lại mã", "danger")
    if v == "missing":
        return ("Không thấy bên VOMS: kiểm tra lại mã, ticket có thể đã bị xoá", "danger")
    if c == "missing":
        return ("Không thấy bên CCTS: có thể chưa được tạo sang CCTS", "danger")

    # ---- mới có 1 bên ----
    if v and not c:
        return ("", "")
    if c and not v:
        if c == "localclose":
            return ("CCTS chờ đóng (local team): lấy VOMS để đối chiếu trước khi đóng", "warn")
        return ("", "")
    if not v and not c:
        return ("", "")

    # ---- đủ 2 bên: ma trận ----
    if v == "closed":
        if c in ("closed", "closure"):
            return ("", "")
        if c == "localclose":
            return ("VOMS và CCTS đều xong, đóng được CCTS", "action")
        if c == "vomsconfirm":
            return ("VOMS đã đóng, CCTS đang chờ xác nhận: vào CCTS xác nhận và đóng", "action")
        return (f"VOMS đã đóng nhưng CCTS còn '{c_s}': kiểm tra CCTS, cập nhật rồi mới đóng được", "warn")

    if v == "cancelled":
        if c in ("closed", "closure"):
            return ("", "")
        return (f"VOMS đã huỷ: kiểm tra huỷ/đóng CCTS tương ứng (đang '{c_s}')", "warn")

    if c in ("closed", "closure"):
        return (f"CCTS đã đóng mà VOMS còn '{v_s}': đẩy VOMS về Đóng, kiểm tra đồng bộ", "danger")

    if v == "completed":
        if c in ("localclose", "vomsconfirm"):
            return ("KTV hoàn công, 2 bên chờ đóng: xác nhận rồi đóng VOMS trước, sau đó đóng CCTS", "action")
        if c in ("open", "appointment"):
            return ("VOMS đã hoàn công nhưng CCTS chưa ghi nhận: cập nhật trạng thái CCTS", "warn")

    if v in ("accepted", "assigned", "processing"):
        if c in ("localclose", "vomsconfirm"):
            return ("CCTS báo xong mà VOMS chưa đóng: kiểm tra lại CCTS xem có lỗi gì không", "warn")
        if c in ("open", "appointment"):
            return ("KTV chưa xử lý", "info")

    if v == "reopened":
        if c in ("open", "appointment"):
            return ("Mở lại, chưa gán KTV: nhắc L0 gán KTV", "warn")
        if c == "spare":
            return ("Xử lý bị mở lại, chờ spare parts: hỏi KTV cần vật tư gì để chuẩn bị", "warn")
        if c in ("localclose", "vomsconfirm"):
            return ("VOMS mở lại nhưng CCTS báo xong: đối chiếu lại 2 bên", "warn")
        return ("Mở lại, theo dõi xử lý lại", "warn")

    if c == "spare":
        return ("Chờ spare parts: CSE xác nhận cần vật tư gì để chuẩn bị", "info")
    if c == "others":
        return ("CCTS Pending for others: xem lý do đang chờ", "info")
    if v == "pending":
        return ("VOMS chưa phân công, theo dõi gán KTV", "info")
    return ("", "")


# =========================================================
#  DB
# =========================================================

def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


# Khoá ghi DB dùng chung để 2 job (VOMS + CCTS) chạy song song vẫn ghi an toàn.
DB_WRITE_LOCK = threading.Lock()


def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS tickets(
            rc_key TEXT PRIMARY KEY,
            rc TEXT, province TEXT, pcode TEXT, asp TEXT, cses TEXT, station TEXT,
            voms_status TEXT DEFAULT '', voms_raw TEXT DEFAULT '',
            voms_station TEXT DEFAULT '', voms_time TEXT DEFAULT '',
            ccts_status TEXT DEFAULT '', ccts_create TEXT DEFAULT '', ccts_time TEXT DEFAULT '',
            active INTEGER DEFAULT 1, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS notes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rc_key TEXT, author TEXT, text TEXT, created_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_notes_rc ON notes(rc_key);
        """)


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# =========================================================
#  VOMS API
# =========================================================
VOMS_API = "https://voms-api.vgreen.net/api/v1/repair-cases"
VOMS_EXPORT_API = "https://voms-api.vgreen.net/api/v1/repair-cases/export"
VOMS_EXPORT_HISTORY_API = "https://voms-api.vgreen.net/api/v1/export-history"
# Tự phát hiện ticket mới bằng export VOMS (thay vì chờ ai đó tải Excel tay).
# 4 ngày là tạm thời — sau này sẽ tăng lên theo tháng (~50k ticket/lần), lúc đó
# cần tính lại việc merge theo lô để không khoá DB quá lâu 1 lượt.
DISCOVER_DAYS_BACK = 4
DISCOVER_INTERVAL_MIN = 30  # thưa hơn nhịp refresh status vì export là thao tác nặng hơn phía VOMS
DISCOVER_STATE = {"last_run": "", "last_result": ""}
VOMS_STATUS_VI = {
    "pending": "Chờ xử lý", "assigned": "Đã phân công", "accepted": "KTV đã nhận",
    "in_progress": "Đang xử lý", "processing": "Đang xử lý", "completed": "Hoàn công",
    "reopened": "Mở lại", "closed": "Đóng", "cancelled": "Đã huỷ", "canceled": "Đã huỷ",
}


def voms_headers(token, tenant):
    t = (token or "").strip()
    if t and not re.match(r"(?i)^bearer\s", t) and t.count(".") == 2:
        t = "Bearer " + t
    return {"Accept": "application/json, text/plain, */*",
            "Authorization": t, "X-Tenant-Id": (tenant or "").strip()}


def voms_get_one(session, rc, headers):
    last = None
    for attempt in range(3):
        try:
            r = session.get(VOMS_API, params={"page": 1, "limit": 10, "search": rc},
                            headers=headers, timeout=20)
            if r.status_code == 429 or r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                time.sleep(1.2 * (attempt + 1))
                continue
            return r, None
        except requests.exceptions.RequestException as e:
            last = str(e)[:200]
            time.sleep(1.2 * (attempt + 1))
    return None, (last or "lỗi mạng")


def voms_trigger_export(headers, days_back):
    """Kêu VOMS tạo file export (bất đồng bộ, trả 202 ngay). Trả lại mốc thời
    gian (UTC) lúc gọi để _voms_wait_export_link biết job nào là job vừa tạo."""
    since = datetime.now(timezone.utc).replace(tzinfo=None)
    end = since + timedelta(days=1)          # dư 1 ngày phòng lệch giờ/timezone
    start = since - timedelta(days=days_back)
    params = {"startDate": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
              "endDate": end.strftime("%Y-%m-%dT%H:%M:%S.999Z")}
    r = requests.get(VOMS_EXPORT_API, params=params, headers=headers, timeout=20)
    r.raise_for_status()
    return since


def voms_wait_export_link(headers, since, timeout_s=90, poll_every=3):
    """Chờ job export tạo lúc `since` chuyển sang completed, trả về downloadLink.
    export-history trả về mới nhất trước -> gặp job cũ hơn since (trừ hao 10s vì
    createdAt của VOMS có thể lệch mili-giây so với lúc mình gọi) thì dừng tìm sớm."""
    cutoff = since - timedelta(seconds=10)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = requests.get(VOMS_EXPORT_HISTORY_API, headers=headers, timeout=20)
            if r.ok:
                for it in (r.json() or {}).get("data") or []:
                    try:
                        created = datetime.strptime((it.get("createdAt") or "")[:19], "%Y-%m-%dT%H:%M:%S")
                    except Exception:
                        continue
                    if created < cutoff:
                        break
                    if it.get("status") == "completed" and it.get("downloadLink"):
                        return it["downloadLink"]
        except requests.exceptions.RequestException:
            pass
        time.sleep(poll_every)
    return None


# =========================================================
#  CCTS API
# =========================================================
CCTS_API = "https://cloud.cnpowercore.com:8091/ccts/cctsTicket/findCCTSTicket"
CCTS_ORIGIN = "https://console.cnpowercore.com"
CCTS_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
CCTS_TSV_HEADERS = ["External Ticket ID (query)", "Matched Ext ID", "Ticket Status",
                    "Create Time", "Rows Found", "Matched?", "Note"]


def ccts_headers(cookie):
    h = {"Accept": "application/json, text/plain, */*",
         "Content-Type": "application/json;charset=utf-8",
         "Accept-Language": "en-US", "Origin": CCTS_ORIGIN,
         "Referer": CCTS_ORIGIN + "/", "User-Agent": CCTS_UA}
    if cookie and cookie.strip():
        h["Cookie"] = cookie.strip()
    return h


def parse_ccts_tsv(text):
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    rows = [ln.split("\t") for ln in text.split("\n") if ln.strip()]
    if not rows:
        return []
    exp = [normalize_text(h) for h in CCTS_TSV_HEADERS]

    def is_header(r):
        rn = [normalize_text(c) for c in r]
        return sum(1 for a, b in zip(rn, exp) if a == b) >= 3

    start = 1 if is_header(rows[0]) else 0
    out = []
    for r in rows[start:]:
        if is_header(r):
            continue
        r = (r + [""] * len(CCTS_TSV_HEADERS))[:len(CCTS_TSV_HEADERS)]
        out.append({"query": r[0].strip(), "status": r[2].strip(), "create_time": r[3].strip()})
    return out


# =========================================================
#  JOB nền (ĐA LUỒNG) + tự động cập nhật
#  Luồng con chỉ gọi mạng; ghi DB ở luồng chính (an toàn SQLite).
#  Hỏng giữa chừng -> giữ kết quả đã ghi, dừng, báo lỗi. only_missing=True
#  chỉ lấy các mã chưa có / đang LỖI (để "lấy tiếp phần còn thiếu").
#
#  Nhiều người có thể bấm cùng lúc: mỗi lượt bấm là 1 job riêng (job_id),
#  tiến độ theo dõi độc lập. Cái thật sự cần giới hạn không phải "số job"
#  mà là tổng số request đồng thời bắn sang VOMS/CCTS (dùng chung 1 token
#  cho cả hệ thống) — API_SEM chặn ở đó, bất kể bao nhiêu job đang chạy.
# =========================================================
JOBS = {"voms": {}, "ccts": {}}          # kind -> {job_id: trạng thái}
JOB_LOCK = threading.Lock()
_JOB_SEQ = 0
_tls = threading.local()

API_CONCURRENCY = {"voms": 10, "ccts": 10}
API_SEM = {"voms": threading.Semaphore(API_CONCURRENCY["voms"]),
           "ccts": threading.Semaphore(API_CONCURRENCY["ccts"])}


def _sess():
    s = getattr(_tls, "s", None)
    if s is None:
        s = requests.Session()
        _tls.s = s
    return s


def _any_running(kind):
    return any(st.get("running") for st in JOBS[kind].values())


def _init_job(kind, by="", scope=""):
    """Luôn tạo job mới (không còn từ chối vì 'đang có job chạy'). Dọn các
    job đã xong quá 60s để JOBS không phình to theo thời gian."""
    global _JOB_SEQ
    with JOB_LOCK:
        cutoff = time.time() - 60
        for jid in [j for j, st in JOBS[kind].items()
                    if st.get("finished") and st.get("_fin_ts", 0) < cutoff]:
            del JOBS[kind][jid]
        _JOB_SEQ += 1
        job_id = str(_JOB_SEQ)
        JOBS[kind][job_id] = {"id": job_id, "running": True, "done": 0, "total": 0, "current": "",
                              "ok": 0, "error": "", "finished": False, "started_at": now_str(),
                              "workers": 0, "only_missing": False, "by": by, "scope": scope}
    return job_id


def start_job(kind, target, by="", scope=""):
    """target nhận 1 tham số job_id. Trả về job_id (luôn thành công)."""
    job_id = _init_job(kind, by, scope)
    threading.Thread(target=lambda: target(job_id), daemon=True).start()
    return job_id


def _rcs_to_fetch(side, only_missing, cse=None, skip_voms_closed=False):
    """skip_voms_closed=True: b\u1ecf qua ticket m\u00e0 VOMS \u0111\u00e3 "\u0110\u00f3ng"/"\u0110\u00e3 hu\u1ef7" \u2014 tr\u1ea1ng th\u00e1i
    \u0111\u00f3 kh\u00f4ng \u0111\u1ed5i n\u1eefa, ch\u1ec9 c\u00f2n CCTS \u0111\u00e1ng theo d\u00f5i ti\u1ebfp. D\u00f9ng cho v\u00f2ng t\u1ef1 \u0111\u1ed9ng l\u1eb7p
    \u0111\u1ecbnh k\u1ef3 \u0111\u1ec3 \u0111\u1ee1 ph\u1ea3i g\u1ecdi l\u1ea1i to\u00e0n b\u1ed9 ticket m\u1ed7i l\u1ea7n (ticket m\u1edbi/\u0111ang x\u1eed l\u00fd v\u1eabn
    \u0111\u01b0\u1ee3c l\u1ea5y b\u00ecnh th\u01b0\u1eddng)."""
    col = "voms_status" if side == "voms" else "ccts_status"
    sql = "SELECT rc, cses, voms_status FROM tickets WHERE active=1"
    if only_missing:
        sql += " AND (COALESCE(%s,'')='' OR %s LIKE 'L\u1ed6I%%')" % (col, col)
    sql += " ORDER BY rc"
    out = []
    with db() as c:
        for r in c.execute(sql):
            if cse:
                try:
                    if cse not in json.loads(r["cses"] or "[]"):
                        continue
                except Exception:
                    continue
            if skip_voms_closed and _vgroup(r["voms_status"]) in ("closed", "cancelled"):
                continue
            out.append(r["rc"])
    return out


MAX_RETRY_ROUNDS = 2  # số vòng thử lại thêm cho mã bị lỗi mạng/timeout (không tính lần đầu)
RETRY_ROUND_DELAY = 2.0  # nghỉ giữa các vòng, tránh dồn tải ngay khi vừa lỗi


def _run_pool(kind, job_id, rcs, worker, write, workers, only_missing):
    """Chạy 1 lượt cho toàn bộ rcs; mã nào bị lỗi mạng/timeout (retryable) sẽ
    tự động được xếp vào vòng sau để gọi lại, tối đa MAX_RETRY_ROUNDS vòng,
    thay vì bỏ cuộc ngay -> mọi ticket đều được cố gắng lấy tới cùng trong 1 job."""
    st = JOBS[kind][job_id]
    st["total"] = len(rcs)
    st["workers"] = max(1, min(12, int(workers or 6)))
    st["only_missing"] = bool(only_missing)
    if not rcs:
        HEALTH[kind] = {"status": "OK", "checked_at": now_str()}
        return

    pending = list(rcs)
    round_no = 0
    while pending:
        if st.get("cancel"):
            st["cancelled"] = True
            return
        round_no += 1
        is_last_round = round_no > MAX_RETRY_ROUNDS
        retry_batch = []
        ex = ThreadPoolExecutor(max_workers=st["workers"])
        futs = {ex.submit(worker, rc): rc for rc in pending}
        try:
            for fut in as_completed(futs):
                if st.get("cancel"):
                    ex.shutdown(wait=False, cancel_futures=True)
                    st["cancelled"] = True
                    return
                res = fut.result()
                if res.get("fatal"):
                    st["error"] = res["fatal"][1]
                    HEALTH[kind] = {"status": "BỊ CHẶN 511" if res["fatal"][0] == "blocked" else "HẾT HẠN",
                                    "checked_at": now_str()}
                    ex.shutdown(wait=False, cancel_futures=True)
                    return
                write(res)
                st["current"] = ("(thử lại vòng %d) " % round_no if round_no > 1 else "") + res["rc"]
                if res.get("ok"):
                    st["ok"] += 1
                    st["done"] += 1
                elif res.get("retryable") and not is_last_round:
                    retry_batch.append(res["rc"])  # chưa tính done, để vòng sau thử lại
                else:
                    st["done"] += 1  # hết lượt thử lại hoặc lỗi không đáng thử lại -> coi là xong (dù fail)
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
        pending = retry_batch
        if pending:
            st["retry_pending"] = len(pending)
            # nghỉ giữa vòng nhưng vẫn phải phản hồi nhanh nếu người dùng bấm Dừng
            for _ in range(int(RETRY_ROUND_DELAY / 0.2)):
                if st.get("cancel"):
                    st["cancelled"] = True
                    return
                time.sleep(0.2)
    st.pop("retry_pending", None)
    if not st["error"]:
        HEALTH[kind] = {"status": "OK", "checked_at": now_str()}


def _voms_fetch_one(rc, headers):
    with API_SEM["voms"]:
        r, err = voms_get_one(_sess(), rc, headers)
    out = {"rc": rc, "status": "", "raw": "", "station": "", "ok": False, "fatal": None}
    if r is None:
        out["status"] = "L\u1ed6I: " + (err or "m\u1ea1ng")
    elif r.status_code in (401, 403):
        out["fatal"] = ("auth", "Token VOMS h\u1ebft h\u1ea1n/sai (HTTP %d). L\u1ea5y l\u1ea1i token." % r.status_code)
    elif r.status_code == 400 and re.search(r"tenant", r.text or "", re.I):
        out["fatal"] = ("tenant", "X-Tenant-Id sai/thi\u1ebfu (HTTP 400).")
    elif r.ok:
        try:
            d = r.json()
        except Exception:
            d = {}
        items = ((d or {}).get("data") or {}).get("items") or []
        if items:
            it = next((x for x in items if str(x.get("code", "")).strip() == rc), items[0])
            out["raw"] = it.get("status") or ""
            out["status"] = VOMS_STATUS_VI.get(out["raw"], out["raw"] or "(tr\u1ed1ng)")
            stn = it.get("station") or {}
            out["station"] = stn.get("stationCode", "") if isinstance(stn, dict) else ""
            out["ok"] = True
        else:
            out["status"] = "Kh\u00f4ng c\u00f3 d\u1eef li\u1ec7u"
    else:
        out["status"] = "L\u1ed6I API (HTTP %d)" % r.status_code
    out["retryable"] = (not out["fatal"]) and (not out["ok"]) and out["status"].startswith("L\u1ed6I")
    return out


def job_voms(job_id, token, tenant, workers=6, only_missing=False, cse=None, skip_voms_closed=False):
    st = JOBS["voms"][job_id]
    try:
        headers = voms_headers(token, tenant)
        rcs = _rcs_to_fetch("voms", only_missing, cse, skip_voms_closed=skip_voms_closed)

        def write(res):
            with DB_WRITE_LOCK, db() as c:
                c.execute("UPDATE tickets SET voms_status=?, voms_raw=?, voms_station=?, voms_time=? WHERE rc_key=?",
                          (res["status"], res["raw"], res["station"], now_str(), norm_key(res["rc"])))
        _run_pool("voms", job_id, rcs, lambda rc: _voms_fetch_one(rc, headers), write, workers, only_missing)
    except Exception as e:
        st["error"] = str(e)[:300]
    finally:
        st["running"] = False
        st["finished"] = True
        st["_fin_ts"] = time.time()


def _ccts_fetch_one(rc, headers, token):
    out = {"rc": rc, "status": "", "create": "", "ok": False, "fatal": None, "retryable": False}
    body = {"page": {"pageNum": 1, "pageSize": 10}, "timezoneOffset": 420,
            "thirdTicketId": rc, "token": token}
    try:
        with API_SEM["ccts"]:
            r = _sess().post(CCTS_API, json=body, headers=headers, timeout=25)
    except requests.exceptions.RequestException as e:
        out["status"] = "L\u1ed6I m\u1ea1ng: " + str(e)[:120]
        out["retryable"] = True
        return out
    if r.status_code in (401, 403):
        out["fatal"] = ("auth", "Phi\u00ean CCTS h\u1ebft h\u1ea1n (HTTP %d)." % r.status_code)
        return out
    try:
        d = r.json() if r.ok else None
    except Exception:
        d = None
    code = str((d or {}).get("code", "")) if d else ""
    if code == "511":
        out["fatal"] = ("blocked", "CCTS ch\u1eb7n g\u1ecdi ngo\u00e0i tr\u00ecnh duy\u1ec7t (code 511). D\u00f9ng script trong tab r\u1ed3i d\u00e1n TSV.")
        return out
    if d and code == "200":
        items = ((d.get("data") or {}).get("list")) or []
        hit = next((it for it in items if norm_key(it.get("thirdTicketId", "")) == norm_key(rc)), None)
        if hit:
            out["status"] = hit.get("cctsTicketStatus", "") or "(tr\u1ed1ng)"
            out["create"] = hit.get("createTime", "")
            out["ok"] = True
        else:
            out["status"] = "Kh\u00f4ng kh\u1edbp m\u00e3" if items else "Kh\u00f4ng c\u00f3 d\u1eef li\u1ec7u"
    else:
        out["status"] = "L\u1ed6I API" + ((" (code %s)" % code) if code else (" (HTTP %d)" % r.status_code))
        out["retryable"] = True
    return out


def job_ccts(job_id, token, cookie, workers=6, only_missing=False, cse=None):
    st = JOBS["ccts"][job_id]
    try:
        headers = ccts_headers(cookie)
        tok = (token or "").strip()
        rcs = _rcs_to_fetch("ccts", only_missing, cse)

        def write(res):
            with DB_WRITE_LOCK, db() as c:
                c.execute("UPDATE tickets SET ccts_status=?, ccts_create=COALESCE(NULLIF(?, ''), ccts_create), ccts_time=? WHERE rc_key=?",
                          (res["status"], res["create"], now_str(), norm_key(res["rc"])))
        _run_pool("ccts", job_id, rcs, lambda rc: _ccts_fetch_one(rc, headers, tok), write, workers, only_missing)
    except Exception as e:
        st["error"] = str(e)[:300]
    finally:
        st["running"] = False
        st["finished"] = True
        st["_fin_ts"] = time.time()


def health_check_now():
    """Test nhanh token đang lưu (1 call nhẹ mỗi hệ)."""
    if CREDS["voms"]["token"]:
        try:
            r = requests.get(VOMS_API, params={"page": 1, "limit": 1},
                             headers=voms_headers(CREDS["voms"]["token"], CREDS["voms"]["tenant"]), timeout=15)
            HEALTH["voms"] = {"status": "OK" if r.ok else ("HẾT HẠN" if r.status_code in (401, 403) else f"LỖI HTTP {r.status_code}"),
                              "checked_at": now_str()}
        except Exception as e:
            HEALTH["voms"] = {"status": "LỖI mạng: " + str(e)[:80], "checked_at": now_str()}
    else:
        HEALTH["voms"] = {"status": "chưa có token", "checked_at": now_str()}
    if CREDS["ccts"]["token"]:
        try:
            r = requests.post(CCTS_API, json={"page": {"pageNum": 1, "pageSize": 1},
                                              "timezoneOffset": 420, "token": CREDS["ccts"]["token"]},
                              headers=ccts_headers(CREDS["ccts"]["cookie"]), timeout=20)
            code = ""
            try:
                code = str(r.json().get("code", ""))
            except Exception:
                pass
            if r.status_code in (401, 403) or code in ("401", "403"):
                s = "HẾT HẠN"
            elif code == "511":
                s = "BỊ CHẶN 511 (dùng TSV)"
            elif r.ok and code == "200":
                s = "OK"
            else:
                s = f"LỖI (HTTP {r.status_code}{', code '+code if code else ''})"
            HEALTH["ccts"] = {"status": s, "checked_at": now_str()}
        except Exception as e:
            HEALTH["ccts"] = {"status": "LỖI mạng: " + str(e)[:80], "checked_at": now_str()}
    else:
        HEALTH["ccts"] = {"status": "chưa có token", "checked_at": now_str()}
    return HEALTH


def _auto_loop():
    while True:
        time.sleep(30)
        try:
            if not AUTO["enabled"] or not CREDS["voms"]["token"]:
                continue
            # Phát hiện ticket mới (export VOMS theo khoảng ngày) — nhịp riêng,
            # thưa hơn refresh status, không phụ thuộc JOBS/_any_running vì đây
            # chỉ là 1 lượt gọi+merge nhanh, không phải job lấy status hàng loạt.
            due_discover = True
            if DISCOVER_STATE["last_run"]:
                dt = datetime.strptime(DISCOVER_STATE["last_run"], "%Y-%m-%d %H:%M:%S")
                due_discover = (datetime.now() - dt).total_seconds() >= DISCOVER_INTERVAL_MIN * 60
            if due_discover:
                DISCOVER_STATE["last_run"] = now_str()
                try:
                    res_d = _voms_discover_new(CREDS["voms"]["token"], CREDS["voms"]["tenant"])
                    DISCOVER_STATE["last_result"] = (f"quét {res_d['scanned']}, mới {res_d['new']}"
                                                     + (f", chưa rõ tỉnh {sum(res_d['unmapped'].values())}"
                                                        if res_d["unmapped"] else ""))
                except Exception as e:
                    DISCOVER_STATE["last_result"] = "lỗi: " + str(e)[:200]
            # Tự động chỉ bỏ qua nếu đã có job "tự động"/thủ công cùng loại đang chạy
            # (tránh tự bắn trùng job toàn bộ) — không liên quan tới người dùng
            # đang bấm "cập nhật phần của tôi", các job đó chạy song song bình thường.
            if _any_running("voms") or _any_running("ccts"):
                continue
            last = AUTO["last_run"]
            due = True
            if last:
                dt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
                due = (datetime.now() - dt).total_seconds() >= AUTO["interval_min"] * 60
            if not due:
                continue
            AUTO["last_run"] = now_str()
            vjob = _init_job("voms", "tự động", "trừ VOMS đã đóng")
            job_voms(vjob, CREDS["voms"]["token"], CREDS["voms"]["tenant"], workers=6, skip_voms_closed=True)
            vst = JOBS["voms"][vjob]
            res = ["VOMS " + ("lỗi: " + vst.get("error") if vst.get("error")
                              else f"ok {vst.get('ok',0)}/{vst.get('total',0)}")]
            if CREDS["ccts"]["token"] and "511" not in HEALTH["ccts"]["status"]:
                cjob = _init_job("ccts", "tự động", "toàn bộ")
                job_ccts(cjob, CREDS["ccts"]["token"], CREDS["ccts"]["cookie"], workers=6)
                cst = JOBS["ccts"][cjob]
                res.append("CCTS " + ("lỗi: " + cst.get("error") if cst.get("error")
                                      else f"ok {cst.get('ok',0)}/{cst.get('total',0)}"))
            AUTO["last_result"] = " · ".join(res)
        except Exception as e:
            AUTO["last_result"] = "lỗi auto: " + str(e)[:200]


# =========================================================
#  API
# =========================================================
app = FastAPI(title="Ticket Tracker VOMS × CCTS")


@app.middleware("http")
async def site_auth(request: Request, call_next):
    """Chặn toàn bộ app bằng HTTP Basic Auth khi SITE_PASSWORD được đặt (deploy
    ra internet công khai). Không đặt SITE_PASSWORD (mặc định khi chạy LAN nội
    bộ) thì bỏ qua hoàn toàn, không đổi hành vi cũ."""
    if not SITE_PASSWORD:
        return await call_next(request)
    auth = request.headers.get("authorization", "")
    ok = False
    if auth.lower().startswith("basic "):
        try:
            _, pwd = base64.b64decode(auth[6:].strip()).decode("utf-8", "replace").split(":", 1)
            ok = secrets.compare_digest(pwd, SITE_PASSWORD)
        except Exception:
            ok = False
    if not ok:
        return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Ticket Tracker"'})
    return await call_next(request)


def require_admin(x_admin_key: str = Header(default="")):
    if ADMIN_KEY and x_admin_key != ADMIN_KEY:
        raise HTTPException(401, "Sai mật khẩu quản trị.")
    return True


@app.get("/api/admin/check", dependencies=[Depends(require_admin)])
def admin_check():
    return {"ok": True}


class VomsFetchIn(BaseModel):
    token: str = ""
    tenant: str = ""
    workers: int = 6
    only_missing: bool = False


class CctsFetchIn(BaseModel):
    token: str = ""
    cookie: str = ""
    workers: int = 6
    only_missing: bool = False


class CctsPasteIn(BaseModel):
    tsv: str


class NoteIn(BaseModel):
    rc_key: str
    author: str
    text: str


class CredsIn(BaseModel):
    voms_token: str = ""
    voms_tenant: str = ""
    ccts_token: str = ""
    ccts_cookie: str = ""


class AutoIn(BaseModel):
    enabled: bool
    interval_min: int = 20


class UpdateMineIn(BaseModel):
    cse: str
    workers: int = 6
    only_missing: bool = False


class JobCancelIn(BaseModel):
    kind: str
    job_id: str


@app.get("/api/meta")
def meta():
    with db() as c:
        total = c.execute("SELECT COUNT(*) n FROM tickets WHERE active=1").fetchone()["n"]
        by_asp = {r["asp"]: r["n"] for r in c.execute(
            "SELECT asp, COUNT(*) n FROM tickets WHERE active=1 GROUP BY asp")}
        vt = c.execute("SELECT MAX(voms_time) t FROM tickets WHERE active=1").fetchone()["t"] or ""
        ct = c.execute("SELECT MAX(ccts_time) t FROM tickets WHERE active=1").fetchone()["t"] or ""
    jobs_view = {
        "voms": sorted(JOBS["voms"].values(), key=lambda j: j["started_at"], reverse=True),
        "ccts": sorted(JOBS["ccts"].values(), key=lambda j: j["started_at"], reverse=True),
    }
    return {"cses": ALL_CSES, "asps": ASPS, "total": total, "by_asp": by_asp,
            "voms_updated": vt, "ccts_updated": ct,
            "jobs": jobs_view, "auto": AUTO, "health": HEALTH,
            "admin_locked": bool(ADMIN_KEY)}


def _parse_master_bytes(content):
    """Đọc file tổng (.xlsx) -> (sheet_name, id_col, rows, unmapped). Dùng chung
    cho cả import tay (/api/import) lẫn tự phát hiện ticket mới từ export VOMS.
    rows: list (rc_key, rc, province_name, pcode, asp, cses_json, station)."""
    try:
        sheets = pd.read_excel(BytesIO(content), sheet_name=None)
    except Exception as e:
        raise HTTPException(400, f"Không đọc được file: {e}")
    df = sheet_name = prov_col = None
    for name, d in sheets.items():
        pc = find_col_fuzzy(list(d.columns), PROVINCE_COL_CANDIDATES)
        if pc:
            df, sheet_name, prov_col = d, name, pc
            break
    if df is None:
        raise HTTPException(400, "Không thấy cột Tỉnh/Thành phố ở sheet nào. Các sheet: "
                            + ", ".join(sheets.keys()))
    id_col = find_col_fuzzy(list(df.columns), ID_COL_CANDIDATES)
    if not id_col:
        raise HTTPException(400, f"Sheet '{sheet_name}' không có cột mã ticket. "
                            f"Các cột: {', '.join(map(str, df.columns))}")
    station_col = find_col_fuzzy(list(df.columns), STATION_COL_CANDIDATES)

    rows, seen, unmapped = [], set(), {}
    for _, r in df.iterrows():
        rc = clean_rc(r[id_col])
        if not rc:
            continue
        k = norm_key(rc)
        if k in seen:
            continue
        seen.add(k)
        prov_raw = r[prov_col]
        station = str(r[station_col]).strip() if station_col is not None and not pd.isna(r[station_col]) else ""
        pcode = province_code_of(prov_raw, station)
        asp = ASP_BY_CODE.get(pcode, "")
        pname, cses = PROVINCE_DATA.get(pcode, (str(prov_raw or "").strip(), []))
        if not pcode:
            key = str(prov_raw or "(trống)").strip() or "(trống)"
            unmapped[key] = unmapped.get(key, 0) + 1
        rows.append((k, rc, pname, pcode, asp, json.dumps(cses, ensure_ascii=False), station))
    if not rows:
        raise HTTPException(400, f"Cột '{id_col}' không có mã nào.")
    return sheet_name, id_col, rows, unmapped


@app.post("/api/import", dependencies=[Depends(require_admin)])
async def import_master(file: UploadFile = File(...)):
    content = await file.read()
    sheet_name, id_col, rows, unmapped = _parse_master_bytes(content)
    ts = now_str()
    with db() as c:
        c.execute("UPDATE tickets SET active=0")
        for k, rc, pname, pcode, asp, cses, station in rows:
            c.execute("""INSERT INTO tickets(rc_key, rc, province, pcode, asp, cses, station, active, updated_at)
                         VALUES(?,?,?,?,?,?,?,1,?)
                         ON CONFLICT(rc_key) DO UPDATE SET
                           rc=excluded.rc, province=excluded.province, pcode=excluded.pcode,
                           asp=excluded.asp, cses=excluded.cses, station=excluded.station,
                           active=1, updated_at=excluded.updated_at""",
                      (k, rc, pname, pcode, asp, cses, station, ts))
        by_asp = {r["asp"] or "(chưa rõ)": r["n"] for r in c.execute(
            "SELECT asp, COUNT(*) n FROM tickets WHERE active=1 GROUP BY asp")}
    return {"sheet": sheet_name, "id_col": id_col, "total": len(rows),
            "by_asp": by_asp, "unmapped": unmapped}


def _merge_new_tickets(content):
    """Giống import_master nhưng CHỈ thêm/cập nhật ticket có trong file, không
    đụng active của ticket khác (không có UPDATE tickets SET active=0). Dùng cho
    tự động phát hiện ticket mới từ export theo khoảng ngày — file này chỉ chứa
    1 phần dữ liệu (vd 4 ngày gần nhất), không phải toàn bộ, nên không được coi
    là nguồn thay thế hoàn toàn như import tay."""
    sheet_name, _id_col, rows, unmapped = _parse_master_bytes(content)
    ts = now_str()
    new_count = 0
    with db() as c:
        existing = {r["rc_key"] for r in c.execute("SELECT rc_key FROM tickets")}
        for k, rc, pname, pcode, asp, cses, station in rows:
            if k not in existing:
                new_count += 1
            c.execute("""INSERT INTO tickets(rc_key, rc, province, pcode, asp, cses, station, active, updated_at)
                         VALUES(?,?,?,?,?,?,?,1,?)
                         ON CONFLICT(rc_key) DO UPDATE SET
                           rc=excluded.rc, province=excluded.province, pcode=excluded.pcode,
                           asp=excluded.asp, cses=excluded.cses, station=excluded.station,
                           active=1, updated_at=excluded.updated_at""",
                      (k, rc, pname, pcode, asp, cses, station, ts))
    return {"sheet": sheet_name, "scanned": len(rows), "new": new_count, "unmapped": unmapped}


def _voms_discover_new(token, tenant, days_back=DISCOVER_DAYS_BACK):
    """Tự phát hiện ticket mới: gọi export VOMS theo khoảng ngày, chờ xong, tải
    file, merge (chỉ thêm/cập nhật, không tắt ticket khác). Không dùng cơ chế
    JOBS/job_id vì đây là thao tác nhanh 1 lần, không phải job lấy status hàng loạt."""
    headers = voms_headers(token, tenant)
    since = voms_trigger_export(headers, days_back)
    link = voms_wait_export_link(headers, since)
    if not link:
        raise RuntimeError("Export VOMS không xong trong thời gian chờ (90s).")
    r = requests.get(link, timeout=60)
    r.raise_for_status()
    return _merge_new_tickets(r.content)


@app.get("/api/tickets")
def list_tickets(cse: str = "", asp: str = "", search: str = "", level: str = "",
                 vstat: str = "", cstat: str = "", overdue: str = ""):
    with db() as c:
        rows = c.execute("SELECT * FROM tickets WHERE active=1 ORDER BY rc").fetchall()
        notes_latest, notes_count = {}, {}
        for n in c.execute("SELECT rc_key, author, text, created_at FROM notes ORDER BY id"):
            notes_latest[n["rc_key"]] = {"author": n["author"], "text": n["text"], "time": n["created_at"]}
            notes_count[n["rc_key"]] = notes_count.get(n["rc_key"], 0) + 1
    out = []
    q = norm_key(search) if search else ""
    now = datetime.now()
    for r in rows:
        cses = json.loads(r["cses"] or "[]")
        if cse and cse not in cses:
            continue
        if asp and (r["asp"] or "") != asp:
            continue
        ftext, flevel = make_flag(r["voms_status"], r["ccts_status"])
        if level and flevel != level:
            continue
        if vstat and (r["voms_status"] or "") != vstat:
            continue
        if cstat and (r["ccts_status"] or "") != cstat:
            continue
        # overdue: hạn = ccts_create + 48h; chỉ tính khi chưa xong cả 2 bên
        deadline = ""
        remain_min = None
        closed_both = _vgroup(r["voms_status"]) in ("closed", "cancelled") and \
            _cgroup(r["ccts_status"]) in ("closed", "closure")
        if r["ccts_create"]:
            try:
                dl = datetime.strptime(r["ccts_create"].strip()[:19], "%Y-%m-%d %H:%M:%S") + timedelta(hours=48)
                deadline = dl.strftime("%Y-%m-%d %H:%M:%S")
                remain_min = int((dl - now).total_seconds() // 60)
            except Exception:
                pass
        is_over = (remain_min is not None and remain_min < 0 and not closed_both)
        if overdue == "1" and not is_over:
            continue
        if overdue == "soon" and not (remain_min is not None and 0 <= remain_min <= 720 and not closed_both):
            continue
        if q and q not in norm_key(r["rc"]) and q not in norm_key(r["station"] or "") \
           and q not in norm_key(r["province"] or ""):
            continue
        out.append({"rc_key": r["rc_key"], "rc": r["rc"], "province": r["province"],
                    "pcode": r["pcode"], "asp": r["asp"], "cses": cses, "station": r["station"],
                    "voms_status": r["voms_status"], "voms_time": r["voms_time"],
                    "ccts_status": r["ccts_status"],
                    "ccts_create": r["ccts_create"], "deadline": deadline,
                    "remain_min": remain_min, "closed_both": closed_both, "overdue": is_over,
                    "flag": ftext, "flag_level": flevel,
                    "note": notes_latest.get(r["rc_key"]), "note_count": notes_count.get(r["rc_key"], 0)})
    return {"tickets": out, "count": len(out)}


@app.get("/api/ids", dependencies=[Depends(require_admin)])
def id_lists():
    with db() as c:
        rows = c.execute("SELECT rc, asp FROM tickets WHERE active=1 ORDER BY rc").fetchall()
    by = {a: [] for a in ASPS}
    allids, other = [], []
    for r in rows:
        allids.append(r["rc"])
        (by.get(r["asp"]) if r["asp"] in by else other).append(r["rc"])
    return {"all": allids, "by_asp": by, "unmapped": other}


@app.post("/api/voms/fetch", dependencies=[Depends(require_admin)])
def voms_fetch(body: VomsFetchIn):
    token = body.token.strip() or CREDS["voms"]["token"]
    tenant = body.tenant.strip() or CREDS["voms"]["tenant"]
    if not token or not tenant:
        raise HTTPException(400, "Chưa có Authorization / X-Tenant-Id (nhập hoặc lưu ở mục Token).")
    if body.token.strip():
        CREDS["voms"] = {"token": token, "tenant": tenant, "saved_at": now_str()}
    job_id = start_job("voms", lambda jid: job_voms(jid, token, tenant, workers=body.workers, only_missing=body.only_missing),
                       by="quản trị", scope=("phần còn thiếu" if body.only_missing else "toàn bộ"))
    return {"started": True, "job_id": job_id}


@app.post("/api/ccts/fetch", dependencies=[Depends(require_admin)])
def ccts_fetch(body: CctsFetchIn):
    token = body.token.strip() or CREDS["ccts"]["token"]
    cookie = body.cookie.strip() or CREDS["ccts"]["cookie"]
    if not token:
        raise HTTPException(400, "Chưa có CCTS token (nhập hoặc lưu ở mục Token).")
    if body.token.strip():
        CREDS["ccts"] = {"token": token, "cookie": cookie, "saved_at": now_str()}
    job_id = start_job("ccts", lambda jid: job_ccts(jid, token, cookie, workers=body.workers, only_missing=body.only_missing),
                       by="quản trị", scope=("phần còn thiếu" if body.only_missing else "toàn bộ"))
    return {"started": True, "job_id": job_id}


@app.post("/api/update_mine")
def update_mine(body: UpdateMineIn):
    """Mỗi CSE tự bấm cập nhật phần của mình. Không cần mật khẩu admin;
    dùng token đã lưu sẵn. Chỉ lấy các ticket thuộc CSE đó."""
    cse = body.cse.strip()
    if not cse:
        raise HTTPException(400, "Thiếu tên CSE.")
    if not CREDS["voms"]["token"]:
        raise HTTPException(400, "Chưa có token VOMS trên hệ thống — nhờ quản trị lưu token trước.")
    scope_txt = ("phần còn thiếu của " if body.only_missing else "phần của ") + cse
    jobs = {"voms": start_job("voms", lambda jid: job_voms(jid, CREDS["voms"]["token"], CREDS["voms"]["tenant"],
                                                           workers=body.workers, only_missing=body.only_missing, cse=cse),
                              by=cse, scope=scope_txt)}
    if CREDS["ccts"]["token"] and "511" not in HEALTH["ccts"].get("status", ""):
        jobs["ccts"] = start_job("ccts", lambda jid: job_ccts(jid, CREDS["ccts"]["token"], CREDS["ccts"]["cookie"],
                                                              workers=body.workers, only_missing=body.only_missing, cse=cse),
                                 by=cse, scope=scope_txt)
    return {"started": True, "jobs": jobs}


@app.post("/api/job/cancel")
def job_cancel(body: JobCancelIn):
    """Dừng 1 job đang chạy (VOMS/CCTS). Không khoá admin — cùng mức tin cậy
    như /api/update_mine, ai cũng bấm dừng được job đang chạy (kể cả của người khác)
    vì đây chỉ dừng việc lấy dữ liệu, không đổi token/health/dữ liệu ai cả."""
    if body.kind not in JOBS:
        raise HTTPException(400, "kind không hợp lệ.")
    st = JOBS[body.kind].get(body.job_id)
    if not st:
        raise HTTPException(404, "Không tìm thấy job (có thể đã xong).")
    if not st.get("running"):
        return {"ok": True, "already_stopped": True}
    st["cancel"] = True
    return {"ok": True}


@app.post("/api/ccts/paste", dependencies=[Depends(require_admin)])
def ccts_paste(body: CctsPasteIn):
    rows = parse_ccts_tsv(body.tsv)
    if not rows:
        raise HTTPException(400, "Không đọc được dòng nào từ TSV.")
    ts = now_str()
    updated = 0
    with db() as c:
        active = {r["rc_key"] for r in c.execute("SELECT rc_key FROM tickets WHERE active=1")}
        for row in rows:
            k = norm_key(row["query"])
            if k not in active:
                continue
            c.execute("UPDATE tickets SET ccts_status=?, ccts_create=COALESCE(NULLIF(?, ''), ccts_create), ccts_time=? WHERE rc_key=?",
                      (row["status"], row["create_time"], ts, k))
            updated += 1
    return {"parsed": len(rows), "updated": updated}


@app.post("/api/admin/creds", dependencies=[Depends(require_admin)])
def save_creds(body: CredsIn):
    if body.voms_token.strip():
        CREDS["voms"] = {"token": body.voms_token.strip(), "tenant": body.voms_tenant.strip(),
                         "saved_at": now_str()}
    elif body.voms_tenant.strip():
        CREDS["voms"]["tenant"] = body.voms_tenant.strip()
    if body.ccts_token.strip():
        CREDS["ccts"] = {"token": body.ccts_token.strip(), "cookie": body.ccts_cookie.strip(),
                         "saved_at": now_str()}
    elif body.ccts_cookie.strip():
        CREDS["ccts"]["cookie"] = body.ccts_cookie.strip()
    _persist_creds()
    health_check_now()
    return {"saved": True, "health": HEALTH,
            "creds": {"voms": {"has_token": bool(CREDS["voms"]["token"]), "saved_at": CREDS["voms"]["saved_at"]},
                      "ccts": {"has_token": bool(CREDS["ccts"]["token"]), "saved_at": CREDS["ccts"]["saved_at"]}}}


@app.get("/api/admin/health", dependencies=[Depends(require_admin)])
def health(live: int = 0):
    if live:
        health_check_now()
    return {"health": HEALTH,
            "creds": {"voms": {"has_token": bool(CREDS["voms"]["token"]), "saved_at": CREDS["voms"]["saved_at"]},
                      "ccts": {"has_token": bool(CREDS["ccts"]["token"]), "saved_at": CREDS["ccts"]["saved_at"]}}}


@app.post("/api/admin/auto", dependencies=[Depends(require_admin)])
def set_auto(body: AutoIn):
    AUTO["enabled"] = bool(body.enabled)
    AUTO["interval_min"] = max(5, int(body.interval_min or 20))
    return {"auto": AUTO}


@app.get("/api/notes/{rc_key}")
def get_notes(rc_key: str):
    with db() as c:
        rows = c.execute("SELECT id, author, text, created_at FROM notes WHERE rc_key=? ORDER BY id DESC",
                         (rc_key,)).fetchall()
    return {"notes": [dict(r) for r in rows]}


@app.post("/api/notes")
def add_note(body: NoteIn):
    if not body.text.strip():
        raise HTTPException(400, "Note trống.")
    if not body.author.strip():
        raise HTTPException(400, "Chọn tên CSE trước khi note.")
    with db() as c:
        cur = c.execute("INSERT INTO notes(rc_key, author, text, created_at) VALUES(?,?,?,?)",
                        (body.rc_key, body.author.strip(), body.text.strip(), now_str()))
        nid = cur.lastrowid
    return {"ok": True, "id": nid}


@app.delete("/api/notes/{note_id}")
def del_note(note_id: int):
    with db() as c:
        c.execute("DELETE FROM notes WHERE id=?", (note_id,))
    return {"ok": True}


@app.get("/api/export")
def export_xlsx(cse: str = "", asp: str = "", level: str = "", overdue: str = "",
                search: str = "", vstat: str = "", cstat: str = ""):
    data = list_tickets(cse=cse, asp=asp, level=level, overdue=overdue,
                        search=search, vstat=vstat, cstat=cstat)["tickets"]
    cols = ["STT", "ID Yêu cầu", "Tỉnh", "ASP", "Mã trạm", "Trạng thái (VOMS)", "Trạng thái CCTS",
            "Create time CCTS", "Hạn xử lý (48h)", "Quá hạn?", "Cảnh báo", "Note mới nhất"]
    rows = []
    for i, t in enumerate(data, 1):
        note = t["note"]
        rows.append([i, t["rc"], t["province"], t["asp"], t["station"],
                     t["voms_status"], t["ccts_status"], t["ccts_create"], t["deadline"],
                     "QUÁ HẠN" if t["overdue"] else "", t["flag"],
                     (f"[{note['author']}] {note['text']}" if note else "")])
    df = pd.DataFrame(rows, columns=cols)
    df_warn = df[df["Cảnh báo"].astype(str).str.strip() != ""]
    out = BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as w:
        df.to_excel(w, sheet_name="Theo_doi", index=False)
        (df_warn if len(df_warn) else pd.DataFrame([{"Thong_bao": "Không có cảnh báo"}])) \
            .to_excel(w, sheet_name="Canh_bao", index=False)
        for sh, d in (("Theo_doi", df), ("Canh_bao", df_warn)):
            ws = w.sheets.get(sh)
            if ws is None or not len(d):
                continue
            for idx, col in enumerate(d.columns):
                width = max([len(str(x)) for x in d[col].fillna("")] + [len(str(col))])
                ws.set_column(idx, idx, min(width + 2, 60))
    out.seek(0)
    tag = ("_" + cse) if cse else (("_" + asp) if asp else "")
    fn = f"bang_theo_doi{tag}_{datetime.now().date().isoformat()}.xlsx"
    return Response(out.getvalue(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{fn}"'})


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin")
def admin_page():
    return FileResponse(STATIC_DIR / "admin.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

init_db()
_load_creds_file()
threading.Thread(target=_auto_loop, daemon=True).start()

if __name__ == "__main__":
    _port = int(os.environ.get("PORT", 8000))
    print(f"Ticket Tracker:  http://localhost:{_port}   (quản trị: /admin)")
    print(f"Trong LAN:       http://<ip-máy-này>:{_port}")
    uvicorn.run(app, host="0.0.0.0", port=_port)
