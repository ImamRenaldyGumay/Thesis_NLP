"""
labeling.py

Lapisan PELABELAN (ground truth) untuk pengujian model
Rule-Based NLP pada teks alert OCC.

Latar belakang
--------------
Pengujian akurasi memerlukan LABEL KEBENARAN (ground truth)
yang berasal dari penilaian manusia (domain expert OCC),
BUKAN dari keluaran model itu sendiri.

Modul ini menyediakan:
    1. Tabel `labeled_alerts` (terpisah dari tabel `alerts`)
       untuk menyimpan hasil pelabelan manual.
    2. Fungsi CRUD pelabelan satu per satu (1-1).
    3. Fungsi import batch dari CSV/Excel.
    4. Generator file contoh (template) Excel/CSV.

PRINSIP PENTING
---------------
Label disimpan TERPISAH dari hasil model. Model tidak pernah
menulis ke tabel ini. Dengan demikian ground truth tetap
independen dan pengujian tidak melingkar (circular).

Tabel labeled_alerts:
    id            : primary key
    timestamp     : waktu pelabelan
    raw_text      : teks alert asli
    label_stream  : stream sebenarnya menurut pelabel
    label_rule    : aturan sebenarnya menurut pelabel (atau NONE)
    pelabel       : nama/inisial pelabel (untuk uji Kappa)
    catatan       : catatan pelabel (opsional)

    label_awal_stream : label stream SEBELUM revisi
    label_awal_rule   : label aturan SEBELUM revisi
    direvisi          : 1 bila label diubah setelah melihat model
    alasan_revisi     : alasan perubahan label

PROSEDUR PELABELAN DUA TAHAP
----------------------------
Tahap 1 : pelabel menentukan label TANPA melihat keluaran model.
          Label langsung disimpan (terkunci).

Tahap 2 : keluaran model baru ditampilkan sebagai pembanding.

Bila pelabel menyadari kekeliruan sendiri (mis. salah baca teks),
label boleh direvisi, TETAPI:
    - label awal tetap tersimpan pada kolom label_awal_*,
    - baris ditandai direvisi = 1,
    - alasan revisi wajib dicatat.

Dengan demikian revisi bersifat transparan dan dapat dilaporkan
di dalam naskah, bukan disembunyikan.
"""

import io
import sqlite3
from typing import List, Dict, Any, Optional

import pandas as pd

from database import get_connection, _ensure_columns


# ============================================================
# PILIHAN LABEL
# ============================================================

LABEL_STREAM_OPTIONS = [
    "BWCE",
    "NGSSP",
    "USSD",
    "CRM",
    "UNKNOWN",
]

LABEL_RULE_OPTIONS = [
    "NONE",
    "R-BWCE-01",
    "R-BWCE-02",
    "R-NGSSP-01",
    "R-NGSSP-02",
    "R-NGSSP-03",
    "R-NGSSP-04",
    "R-USSD-01",
    "R-USSD-02",
    "R-CRM-01",
]

# Aturan yang valid untuk tiap stream.
# Dipakai untuk validasi konsistensi label.
VALID_RULE_BY_STREAM = {
    "BWCE": ["NONE", "R-BWCE-01", "R-BWCE-02"],
    "NGSSP": [
        "NONE",
        "R-NGSSP-01",
        "R-NGSSP-02",
        "R-NGSSP-03",
        "R-NGSSP-04",
    ],
    "USSD": ["NONE", "R-USSD-01", "R-USSD-02"],
    "CRM": ["NONE", "R-CRM-01"],
    "UNKNOWN": ["NONE"],
}


# Penjelasan singkat tiap label, ditampilkan sebagai
# panduan pelabelan di dalam aplikasi.
LABEL_GUIDE = {
    "R-BWCE-01": (
        "Alert BWCE dengan flag SR Degraded, Technical Error > 0, "
        "Business Error = 0, dan Undefined Error = 0."
    ),
    "R-BWCE-02": (
        "Alert BWCE dengan SR Degraded disertai Technical Error, "
        "dan terdapat pula Business Error dan/atau Undefined "
        "Error (error campuran)."
    ),
    "R-NGSSP-01": (
        "Alert NGSSP metric Node Exporter Status dengan val = 0."
    ),
    "R-NGSSP-02": (
        "Alert NGSSP metric JVM Managed Server Status dengan val = 0."
    ),
    "R-NGSSP-03": (
        "Alert NGSSP metric CPU Utilization dengan nilai val "
        "mencapai atau melampaui ambang batas."
    ),
    "R-NGSSP-04": (
        "Alert NGSSP metric Stuck Thread dengan jumlah thread "
        "macet mencapai atau melampaui ambang batas."
    ),
    "R-USSD-01": (
        "Alert USSD dengan detail 'Process is not running'."
    ),
    "R-USSD-02": (
        "Alert USSD dengan detail 'Errors found'."
    ),
    "R-CRM-01": (
        "Alert CRM/OMNI dengan status service DOWN."
    ),
    "NONE": (
        "Teks alert dikenali stream-nya, tetapi TIDAK ada aturan "
        "produksi yang seharusnya aktif. Dipakai juga untuk teks "
        "yang bukan alert (stream UNKNOWN)."
    ),
}


def validate_label(label_stream: str, label_rule: str) -> Optional[str]:
    """
    Memeriksa konsistensi antara label stream dan label aturan.

    Return:
        None jika valid, atau string pesan kesalahan.
    """
    if label_stream not in LABEL_STREAM_OPTIONS:
        return f"Label stream '{label_stream}' tidak dikenali."

    if label_rule not in LABEL_RULE_OPTIONS:
        return f"Label aturan '{label_rule}' tidak dikenali."

    allowed = VALID_RULE_BY_STREAM.get(label_stream, [])

    if label_rule not in allowed:
        return (
            f"Aturan '{label_rule}' tidak berlaku untuk stream "
            f"'{label_stream}'. Pilihan yang sah: {', '.join(allowed)}."
        )

    return None


# ============================================================
# INISIALISASI TABEL
# ============================================================

def init_labeling_db() -> None:
    """
    Membuat tabel labeled_alerts apabila belum tersedia.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS labeled_alerts (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            timestamp DATETIME
                DEFAULT CURRENT_TIMESTAMP,

            raw_text TEXT NOT NULL,

            label_stream TEXT,

            label_rule TEXT,

            pelabel TEXT,

            catatan TEXT,

            label_awal_stream TEXT,

            label_awal_rule TEXT,

            direvisi INTEGER DEFAULT 0,

            alasan_revisi TEXT
        )
        """
    )

    # Migrasi ringan untuk database yang sudah terlanjur dibuat
    # sebelum kolom revisi ditambahkan.
    _ensure_columns(
        cursor,
        "labeled_alerts",
        {
            "label_awal_stream": "TEXT",
            "label_awal_rule": "TEXT",
            "direvisi": "INTEGER DEFAULT 0",
            "alasan_revisi": "TEXT",
        },
    )

    conn.commit()
    conn.close()


# ============================================================
# SIMPAN LABEL (SATU PER SATU)
# ============================================================

def save_label(
    raw_text: str,
    label_stream: str,
    label_rule: str,
    pelabel: str = "",
    catatan: str = "",
) -> int:
    """
    Menyimpan satu hasil pelabelan manual.

    Return:
        id baris yang tersimpan.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO labeled_alerts (
            raw_text,
            label_stream,
            label_rule,
            pelabel,
            catatan
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            str(raw_text),
            str(label_stream),
            str(label_rule),
            str(pelabel),
            str(catatan),
        ),
    )

    row_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return row_id


def get_label_by_id(row_id: int) -> Optional[Dict[str, Any]]:
    """Mengambil satu baris label berdasarkan id."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM labeled_alerts WHERE id = ?",
        (int(row_id),),
    )

    row = cursor.fetchone()
    conn.close()

    return dict(row) if row else None


def revise_label(
    row_id: int,
    label_stream_baru: str,
    label_rule_baru: str,
    alasan_revisi: str,
) -> Optional[str]:
    """
    Merevisi label yang sudah tersimpan, dengan mencatat jejaknya.

    Label AWAL tidak ditimpa: disalin ke kolom label_awal_*
    (hanya pada revisi pertama, agar label asli sebelum melihat
    model tetap terjaga meskipun direvisi berulang kali).

    Baris ditandai direvisi = 1 sehingga dapat dilaporkan
    secara terbuka pada bab pengujian.

    Return:
        None bila berhasil, atau pesan kesalahan.
    """
    error = validate_label(label_stream_baru, label_rule_baru)

    if error:
        return error

    if not str(alasan_revisi).strip():
        return (
            "Alasan revisi wajib diisi agar perubahan label "
            "dapat dipertanggungjawabkan."
        )

    baris = get_label_by_id(row_id)

    if baris is None:
        return f"Label dengan ID {row_id} tidak ditemukan."

    # Simpan label awal hanya bila belum pernah direvisi,
    # supaya label asli tidak hilang pada revisi berikutnya.
    if not baris.get("direvisi"):
        awal_stream = baris.get("label_stream")
        awal_rule = baris.get("label_rule")
    else:
        awal_stream = baris.get("label_awal_stream")
        awal_rule = baris.get("label_awal_rule")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE labeled_alerts
        SET label_stream = ?,
            label_rule = ?,
            label_awal_stream = ?,
            label_awal_rule = ?,
            direvisi = 1,
            alasan_revisi = ?
        WHERE id = ?
        """,
        (
            str(label_stream_baru),
            str(label_rule_baru),
            awal_stream,
            awal_rule,
            str(alasan_revisi).strip(),
            int(row_id),
        ),
    )

    conn.commit()
    conn.close()

    return None


def delete_label(row_id: int) -> None:
    """Menghapus satu baris label."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM labeled_alerts WHERE id = ?",
        (int(row_id),),
    )

    conn.commit()
    conn.close()


def delete_all_labels() -> None:
    """Menghapus seluruh baris label."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM labeled_alerts")

    conn.commit()
    conn.close()


# ============================================================
# AMBIL DATA LABEL
# ============================================================

def get_all_labels() -> pd.DataFrame:
    """
    Mengambil seluruh data pelabelan sebagai DataFrame.

    Kolom yang dikembalikan kompatibel dengan evaluation.py:
        text, label_stream, label_rule
    """
    conn = get_connection()

    try:
        df = pd.read_sql_query(
            """
            SELECT
                id,
                timestamp,
                raw_text AS text,
                label_stream,
                label_rule,
                pelabel,
                catatan,
                label_awal_stream,
                label_awal_rule,
                COALESCE(direvisi, 0) AS direvisi,
                alasan_revisi
            FROM labeled_alerts
            ORDER BY id ASC
            """,
            conn,
        )
    except Exception:
        df = pd.DataFrame(
            columns=[
                "id",
                "timestamp",
                "text",
                "label_stream",
                "label_rule",
                "pelabel",
                "catatan",
                "label_awal_stream",
                "label_awal_rule",
                "direvisi",
                "alasan_revisi",
            ]
        )
    finally:
        conn.close()

    return df


def count_labels() -> int:
    """Menghitung jumlah baris yang sudah dilabeli."""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT COUNT(*) FROM labeled_alerts")
        total = cursor.fetchone()[0]
    except sqlite3.Error:
        total = 0
    finally:
        conn.close()

    return total


def label_statistics() -> Dict[str, Any]:
    """
    Statistik ringkas hasil pelabelan.
    """
    df = get_all_labels()

    if df.empty:
        return {
            "total": 0,
            "per_stream": {},
            "per_rule": {},
            "jumlah_pelabel": 0,
            "jumlah_direvisi": 0,
            "persen_direvisi": 0.0,
        }

    jumlah_direvisi = int(df["direvisi"].fillna(0).sum())

    return {
        "total": len(df),
        "per_stream": df["label_stream"].value_counts().to_dict(),
        "per_rule": df["label_rule"].value_counts().to_dict(),
        "jumlah_pelabel": df["pelabel"].replace("", pd.NA).nunique(),
        "jumlah_direvisi": jumlah_direvisi,
        "persen_direvisi": round(
            jumlah_direvisi / len(df) * 100,
            2,
        ),
    }


# ============================================================
# IMPORT BATCH
# ============================================================

def import_labels_from_dataframe(
    df: pd.DataFrame,
    text_col: str = "text",
    stream_col: str = "label_stream",
    rule_col: str = "label_rule",
    pelabel_col: Optional[str] = None,
    pelabel_default: str = "",
) -> Dict[str, Any]:
    """
    Mengimpor label secara batch dari DataFrame.

    Baris dengan label tidak valid akan DILEWATI dan
    dilaporkan, bukan disimpan diam-diam.

    Return:
        {
            "tersimpan": int,
            "dilewati": int,
            "kesalahan": [ {baris, alasan}, ... ],
        }
    """
    tersimpan = 0
    kesalahan: List[Dict[str, Any]] = []

    for position, (_, row) in enumerate(df.iterrows(), start=1):

        text = row.get(text_col)

        if pd.isna(text) or not str(text).strip():
            kesalahan.append({
                "baris": position,
                "alasan": "Teks alert kosong.",
            })
            continue

        label_stream = str(row.get(stream_col, "")).strip().upper()
        label_rule = str(row.get(rule_col, "")).strip().upper()

        error = validate_label(label_stream, label_rule)

        if error:
            kesalahan.append({
                "baris": position,
                "alasan": error,
            })
            continue

        if pelabel_col and pelabel_col in df.columns:
            pelabel = str(row.get(pelabel_col, "") or "")
        else:
            pelabel = pelabel_default

        save_label(
            raw_text=str(text),
            label_stream=label_stream,
            label_rule=label_rule,
            pelabel=pelabel,
        )

        tersimpan += 1

    return {
        "tersimpan": tersimpan,
        "dilewati": len(kesalahan),
        "kesalahan": kesalahan,
    }


# ============================================================
# TEMPLATE / CONTOH FILE
# ============================================================

def _template_rows() -> List[Dict[str, str]]:
    """
    Baris contoh untuk template pelabelan.

    Berisi contoh untuk setiap aturan produksi, contoh
    kasus negatif (NONE), dan contoh teks bukan alert.
    """
    return [
        {
            "text": (
                "PAYMENT - Total: 1000 | Success: 940 | BE: 0 | TE: 60 | "
                "Undefined: 0 | SR: 94.0 % | SR Degraded | "
                "TE Info: connection timeout | inform NGSSP team"
            ),
            "label_stream": "BWCE",
            "label_rule": "R-BWCE-01",
            "pelabel": "",
            "catatan": "Contoh: SR Degraded disertai Technical Error.",
        },
        {
            "text": (
                "TRANSFER - Total: 1000 | Success: 900 | BE: 80 | TE: 20 | "
                "Undefined: 0 | SR: 90.0 % | SR Degraded | "
                "TE Info: mixed error |"
            ),
            "label_stream": "BWCE",
            "label_rule": "R-BWCE-02",
            "pelabel": "",
            "catatan": "Contoh: error campuran (BE > 0) -> R-BWCE-02.",
        },
        {
            "text": (
                "NGSSP Alert - Node Exporter Status ~ server-node-01 "
                "with val: 0, Issue start at: 2025-01-10 10:00:00, "
                "inform Middleware team"
            ),
            "label_stream": "NGSSP",
            "label_rule": "R-NGSSP-01",
            "pelabel": "",
            "catatan": "Contoh: Node Exporter val=0.",
        },
        {
            "text": (
                "NGSSP Alert - JVM Managed Server Status ~ managed-server-02 "
                "with val: 0, Issue start at: 2025-01-10 11:00:00"
            ),
            "label_stream": "NGSSP",
            "label_rule": "R-NGSSP-02",
            "pelabel": "",
            "catatan": "Contoh: JVM Managed Server val=0.",
        },
        {
            "text": (
                "8iAaqn3Zk|NGSSP OSB MC4A - CPU Utilization alert ~ "
                "xptngssposb80:9100_Total with val: 88.9111111085448, "
                "Issue start at: 2026-03-19T03:06:00.000+07:00, "
                "Pls inform ngssp Team!"
            ),
            "label_stream": "NGSSP",
            "label_rule": "R-NGSSP-03",
            "pelabel": "",
            "catatan": "Contoh: CPU Utilization melampaui ambang batas.",
        },
        {
            "text": (
                "1:- ALERT 2:- ussd_gateway_check 3:- ussd-host-01 "
                "4:- 10.20.30.40 5:- CRITICAL 6:- 2025-01-10 12:00:00 "
                "7:- Process is not running"
            ),
            "label_stream": "USSD",
            "label_rule": "R-USSD-01",
            "pelabel": "",
            "catatan": "Contoh: proses tidak berjalan.",
        },
        {
            "text": (
                "1:- ALERT 2:- log_monitor_check 3:- ussd-host-02 "
                "4:- 10.20.30.41 5:- WARNING 6:- 2025-01-10 13:00:00 "
                "7:- Errors found occured=5"
            ),
            "label_stream": "USSD",
            "label_rule": "R-USSD-02",
            "pelabel": "",
            "catatan": "Contoh: error ditemukan.",
        },
        {
            "text": "omni-payment-service in omni-host-01 DOWN",
            "label_stream": "CRM",
            "label_rule": "R-CRM-01",
            "pelabel": "",
            "catatan": "Contoh: service DOWN.",
        },
        {
            "text": "CPU usage tinggi pada host aplikasi",
            "label_stream": "UNKNOWN",
            "label_rule": "NONE",
            "pelabel": "",
            "catatan": "Contoh: teks bukan alert terstruktur.",
        },
    ]


def build_template_dataframe() -> pd.DataFrame:
    """DataFrame template pelabelan."""
    return pd.DataFrame(_template_rows())


def _guide_dataframe() -> pd.DataFrame:
    """DataFrame panduan label untuk sheet kedua."""
    rows = []

    for label, penjelasan in LABEL_GUIDE.items():

        stream_terkait = [
            stream
            for stream, rules in VALID_RULE_BY_STREAM.items()
            if label in rules and label != "NONE"
        ]

        rows.append({
            "label_rule": label,
            "berlaku_untuk_stream": (
                ", ".join(stream_terkait)
                if stream_terkait
                else "semua stream"
            ),
            "penjelasan": penjelasan,
        })

    return pd.DataFrame(rows)


def _instruction_dataframe() -> pd.DataFrame:
    """Sheet berisi aturan pengisian."""
    instruksi = [
        "PANDUAN PENGISIAN TEMPLATE PELABELAN",
        "",
        "1. Kolom 'text' diisi teks alert ASLI (salin apa adanya, "
        "termasuk format aslinya).",
        "2. Kolom 'label_stream' diisi salah satu dari: "
        + ", ".join(LABEL_STREAM_OPTIONS)
        + ".",
        "3. Kolom 'label_rule' diisi salah satu dari: "
        + ", ".join(LABEL_RULE_OPTIONS)
        + ". Lihat sheet 'panduan_label' untuk definisinya.",
        "4. Kolom 'pelabel' diisi nama/inisial pelabel. Wajib bila "
        "pelabelan dilakukan lebih dari satu orang (untuk uji Kappa).",
        "5. Kolom 'catatan' opsional, untuk mencatat alasan atau keraguan.",
        "",
        "ATURAN PENTING",
        "",
        "- Labeli BERDASARKAN PENILAIAN ANDA sebagai personel OCC, "
        "yaitu kondisi apa yang sebenarnya terjadi dan bagaimana "
        "seharusnya alert ditangani.",
        "- JANGAN melabeli dengan cara melihat keluaran program. "
        "Label harus independen agar pengujian tidak melingkar.",
        "- Labeli SEBELUM menjalankan pengujian, dan jangan mengubah "
        "label setelah melihat hasil model.",
        "- Isi 'label_rule' dengan NONE bila memang tidak ada aturan "
        "produksi yang seharusnya aktif.",
        "- Ambil alert apa adanya dari periode tertentu. Jangan hanya "
        "memilih alert yang formatnya rapi (selection bias).",
        "",
        "CATATAN: baris contoh pada sheet 'template' hanya ilustrasi "
        "format. Hapus baris contoh tersebut dan ganti dengan alert asli.",
    ]

    return pd.DataFrame({"petunjuk": instruksi})


def build_template_excel() -> bytes:
    """
    Membuat file Excel contoh (template) pelabelan.

    Berisi 3 sheet:
        - template       : baris contoh siap diganti alert asli
        - panduan_label  : definisi tiap label
        - petunjuk       : aturan pengisian

    Return:
        bytes file .xlsx
    """
    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:

        build_template_dataframe().to_excel(
            writer,
            sheet_name="template",
            index=False,
        )

        _guide_dataframe().to_excel(
            writer,
            sheet_name="panduan_label",
            index=False,
        )

        _instruction_dataframe().to_excel(
            writer,
            sheet_name="petunjuk",
            index=False,
        )

        # Pelebaran kolom agar mudah dibaca.
        lebar = {
            "template": {"A": 70, "B": 14, "C": 14, "D": 12, "E": 45},
            "panduan_label": {"A": 14, "B": 22, "C": 70},
            "petunjuk": {"A": 100},
        }

        for sheet_name, kolom in lebar.items():
            worksheet = writer.sheets[sheet_name]
            for huruf, ukuran in kolom.items():
                worksheet.column_dimensions[huruf].width = ukuran

    buffer.seek(0)

    return buffer.getvalue()


def build_template_csv() -> bytes:
    """
    Membuat file CSV contoh (template) pelabelan.
    """
    return build_template_dataframe().to_csv(index=False).encode("utf-8")