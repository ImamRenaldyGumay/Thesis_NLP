"""
extraction.py

Lapisan VERIFIKASI EKSTRAKSI (Information Extraction) untuk
pengujian model Rule-Based NLP pada teks alert OCC.

Latar belakang
--------------
Evaluator model bersifat deterministik: begitu fakta terbentuk,
hasil aturan IF-THEN tidak lagi mengandung ketidakpastian
(mis. BE=7 sudah pasti tidak memenuhi syarat BE=0). Karena
pelabel manusia juga menerapkan aturan yang sama saat melabeli,
"akurasi aturan" cenderung mendekati 100% secara otomatis dan
tidak banyak menguji kemampuan model.

Bagian yang benar-benar dapat gagal adalah SCANNER dan PARSER,
yaitu proses EKSTRAKSI INFORMASI dari teks yang formatnya
beragam. Contoh kegagalan nyata yang pernah ditemukan:
    - metric baru tidak dikenali sehingga stream terbaca UNKNOWN
    - "Total: 1,828" terbaca 1 karena regex berhenti di koma

Modul ini menyediakan pengujian ekstraksi per field.

Mengapa pengujian ini TIDAK melingkar
-------------------------------------
Pada pelabelan aturan, acuan kebenarannya adalah PENILAIAN
pelabel, yang prosesnya sama dengan yang dilakukan model,
sehingga kesepakatan terjadi dengan sendirinya.

Pada verifikasi ekstraksi, acuan kebenarannya adalah TEKS ALERT
ITU SENDIRI. Bila teks tertulis "BE: 7", maka nilai yang benar
adalah 7 - terlepas dari pendapat pelabel maupun keluaran model.
Acuannya berada di luar keduanya, sehingga pengujian bersifat
objektif.

Keterbatasan yang perlu disadari
--------------------------------
Verifikasi tetap rentan terhadap automation bias: pelabel dapat
menyetujui hasil ekstraksi tanpa benar-benar membaca teks.
Untuk menekan risiko itu, modul ini menyediakan pemeriksaan
konsistensi otomatis (lihat cek_konsistensi) yang menandai
ekstraksi yang patut dicurigai, sehingga perhatian pelabel
terarah pada baris yang berisiko.

Struktur tabel extraction_checks
--------------------------------
Satu baris untuk setiap PASANGAN (alert, field):

    id              : primary key
    timestamp       : waktu verifikasi
    alert_no        : nomor pengelompokan; seluruh field milik
                      satu alert memiliki alert_no yang sama
    raw_text        : teks alert asli
    stream          : stream hasil deteksi model
    field_name      : nama field (TOTAL, BE, METRIC, dst.)
    extracted_value : nilai hasil ekstraksi model
    is_correct      : 1 bila benar, 0 bila salah
    correct_value   : nilai yang seharusnya (diisi bila salah)
    pelabel         : nama/inisial pemeriksa
"""

import sqlite3
from typing import Dict, Any, List, Optional

import pandas as pd

from database import get_connection
from rules import process_alert


# ============================================================
# FIELD YANG DIPERIKSA PER STREAM
# ============================================================
#
# Daftar ini menentukan field mana saja yang wajib ada dan
# diperiksa untuk tiap stream. Field yang gagal diekstraksi
# akan tetap muncul dengan nilai kosong, sehingga kegagalan
# ekstraksi ikut terhitung sebagai kesalahan, bukan terlewat.

FIELD_PER_STREAM = {
    "BWCE": [
        "APP",
        "TOTAL",
        "SUCCESS",
        "BE",
        "TE",
        "UNDEFINED",
        "SR",
        "TE_INFO",
        "SR_DEGRADED",
        "TEAM",
    ],
    "NGSSP": [
        "METRIC",
        "COMPONENT",
        "VALUE",
        "ISSUE_START",
        "TEAM",
    ],
    "USSD": [
        "CHECK",
        "HOST",
        "IP",
        "SEVERITY",
        "TIMESTAMP",
        "DETAIL",
    ],
    "CRM": [
        "SERVICE",
        "HOSTNAME",
        "STATUS",
    ],
    "UNKNOWN": [],
}


def ambil_ekstraksi(text: str) -> Dict[str, Any]:
    """
    Menjalankan model pada satu teks alert dan menyusun hasil
    ekstraksinya menjadi daftar field siap diperiksa.

    Return:
        {
            "stream": str,
            "fields": [ {field, nilai}, ... ],
            "curiga": [str, ...],   # catatan konsistensi
        }
    """
    hasil = process_alert(text)

    stream = hasil.get("stream", "UNKNOWN")

    fakta = {
        f["predicate"]: f["value"]
        for f in hasil.get("facts", [])
    }

    daftar_field = FIELD_PER_STREAM.get(stream, [])

    fields = []

    for nama in daftar_field:

        nilai = fakta.get(nama)

        fields.append({
            "field": nama,
            "nilai_terekstraksi": (
                "" if nilai is None else str(nilai)
            ),
        })

    return {
        "stream": stream,
        "fields": fields,
        "curiga": cek_konsistensi(stream, fakta),
    }


# ============================================================
# PEMERIKSAAN KONSISTENSI OTOMATIS
# ============================================================

def cek_konsistensi(
    stream: str,
    fakta: Dict[str, Any],
) -> List[str]:
    """
    Menandai hasil ekstraksi yang patut dicurigai TANPA
    memerlukan pelabelan manusia.

    Tujuannya menekan automation bias: pemeriksa diarahkan pada
    baris yang berisiko, bukan sekadar menyetujui semuanya.

    Pemeriksaan yang dilakukan:

    1. BWCE - identitas aritmetika.
       Total seharusnya sama dengan Success + BE + TE + Undefined.
       Bila tidak sama, hampir pasti ada field yang salah baca.
       Justru pemeriksaan inilah yang mampu menangkap bug
       "Total: 1,828" terbaca 1.

    2. BWCE - kewajaran Success Rate.
       SR seharusnya mendekati Success/Total * 100.

    3. Umum - field kosong.
       Field yang gagal diekstraksi ditandai.
    """
    catatan: List[str] = []

    if stream == "BWCE":

        total = fakta.get("TOTAL")
        success = fakta.get("SUCCESS")
        be = fakta.get("BE")
        te = fakta.get("TE")
        undefined = fakta.get("UNDEFINED")

        angka = [total, success, be, te, undefined]

        if all(isinstance(x, (int, float)) for x in angka):

            jumlah = success + be + te + undefined

            if total != jumlah:
                catatan.append(
                    f"Total ({total}) tidak sama dengan "
                    f"Success+BE+TE+Undefined ({jumlah}). "
                    "Kemungkinan ada field yang salah terbaca."
                )

            if total and total > 0:

                sr_baca = fakta.get("SR")

                # Rumus SR yang dipakai OCC belum dipastikan.
                # Dari dua alert nyata terlihat dua kemungkinan:
                #
                #   (a) Success / Total
                #   (b) (Total - TE) / Total
                #       -> hanya Technical Error yang dihitung
                #          sebagai kegagalan; Business Error dan
                #          Undefined tidak.
                #
                # Pada alert dengan BE=0 dan Undefined=0 kedua
                # rumus menghasilkan angka yang sama, sehingga
                # tidak dapat dibedakan. Selama belum dipastikan
                # ke OCC, SR dianggap wajar bila cocok dengan
                # SALAH SATU rumus, agar tidak menimbulkan alarm
                # palsu yang membuat pemeriksa mengabaikan
                # peringatan.
                kandidat = [
                    ("Success/Total", success / total * 100),
                    ("(Total-TE)/Total", (total - te) / total * 100),
                ]

                if isinstance(sr_baca, (int, float)):

                    cocok = any(
                        abs(nilai - sr_baca) <= 1.0
                        for _, nilai in kandidat
                    )

                    if not cocok:
                        rincian = ", ".join(
                            f"{nama}={nilai:.2f}%"
                            for nama, nilai in kandidat
                        )
                        catatan.append(
                            f"SR terbaca {sr_baca}%, tidak cocok "
                            f"dengan rumus mana pun ({rincian}). "
                            "Kemungkinan ada field yang salah "
                            "terbaca."
                        )

    # Field kosong pada stream yang dikenali.
    if stream != "UNKNOWN":

        for nama in FIELD_PER_STREAM.get(stream, []):

            if fakta.get(nama) is None:
                catatan.append(
                    f"Field {nama} gagal diekstraksi (kosong)."
                )

    return catatan


# ============================================================
# TABEL
# ============================================================

def init_extraction_db() -> None:
    """Membuat tabel extraction_checks bila belum tersedia."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS extraction_checks (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            timestamp DATETIME
                DEFAULT CURRENT_TIMESTAMP,

            alert_no INTEGER,

            raw_text TEXT,

            stream TEXT,

            field_name TEXT,

            extracted_value TEXT,

            is_correct INTEGER,

            correct_value TEXT,

            pelabel TEXT
        )
        """
    )

    conn.commit()
    conn.close()


def _alert_no_berikutnya() -> int:
    """Menentukan nomor alert berikutnya."""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "SELECT COALESCE(MAX(alert_no), 0) "
            "FROM extraction_checks"
        )
        terakhir = cursor.fetchone()[0] or 0
    except sqlite3.Error:
        terakhir = 0
    finally:
        conn.close()

    return terakhir + 1


def simpan_verifikasi(
    raw_text: str,
    stream: str,
    hasil_periksa: List[Dict[str, Any]],
    pelabel: str = "",
) -> int:
    """
    Menyimpan hasil verifikasi satu alert.

    hasil_periksa berisi daftar:
        {
            "field": str,
            "nilai_terekstraksi": str,
            "benar": bool,
            "nilai_seharusnya": str,
        }

    Return:
        alert_no yang dipakai.
    """
    alert_no = _alert_no_berikutnya()

    conn = get_connection()
    cursor = conn.cursor()

    for baris in hasil_periksa:

        cursor.execute(
            """
            INSERT INTO extraction_checks (
                alert_no,
                raw_text,
                stream,
                field_name,
                extracted_value,
                is_correct,
                correct_value,
                pelabel
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert_no,
                str(raw_text),
                str(stream),
                str(baris.get("field", "")),
                str(baris.get("nilai_terekstraksi", "")),
                1 if baris.get("benar") else 0,
                str(baris.get("nilai_seharusnya", "") or ""),
                str(pelabel),
            ),
        )

    conn.commit()
    conn.close()

    return alert_no


def get_extraction_checks() -> pd.DataFrame:
    """Mengambil seluruh hasil verifikasi ekstraksi."""
    conn = get_connection()

    try:
        df = pd.read_sql_query(
            """
            SELECT
                id,
                timestamp,
                alert_no,
                raw_text,
                stream,
                field_name,
                extracted_value,
                is_correct,
                correct_value,
                pelabel
            FROM extraction_checks
            ORDER BY alert_no ASC, id ASC
            """,
            conn,
        )
    except Exception:
        df = pd.DataFrame(
            columns=[
                "id", "timestamp", "alert_no", "raw_text",
                "stream", "field_name", "extracted_value",
                "is_correct", "correct_value", "pelabel",
            ]
        )
    finally:
        conn.close()

    return df


def hapus_semua_verifikasi() -> None:
    """Menghapus seluruh hasil verifikasi."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM extraction_checks")
    conn.commit()
    conn.close()


def jumlah_alert_terverifikasi() -> int:
    """Menghitung jumlah alert yang sudah diverifikasi."""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "SELECT COUNT(DISTINCT alert_no) "
            "FROM extraction_checks"
        )
        total = cursor.fetchone()[0] or 0
    except sqlite3.Error:
        total = 0
    finally:
        conn.close()

    return total


# ============================================================
# PERHITUNGAN AKURASI EKSTRAKSI
# ============================================================

def evaluasi_ekstraksi(
    df: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """
    Menghitung akurasi ekstraksi model.

    Metrik yang dihasilkan:

    - akurasi_field   : proporsi field yang benar diekstraksi,
                        dihitung atas seluruh pasangan
                        (alert, field).
    - akurasi_alert   : proporsi alert yang SELURUH field-nya
                        benar. Ukuran yang lebih ketat, karena
                        satu field salah membuat pembacaan
                        alert berpotensi keliru.
    - per_field       : rincian akurasi tiap field.
    - per_stream      : rincian akurasi tiap stream.
    - kesalahan       : daftar field yang salah beserta nilai
                        yang seharusnya, sebagai bahan analisis.
    """
    if df is None:
        df = get_extraction_checks()

    if df.empty:
        return {
            "n_alert": 0,
            "n_field": 0,
            "akurasi_field": 0.0,
            "akurasi_alert": 0.0,
            "per_field": pd.DataFrame(),
            "per_stream": pd.DataFrame(),
            "kesalahan": pd.DataFrame(),
        }

    df = df.copy()
    df["is_correct"] = df["is_correct"].astype(int)

    n_field = len(df)
    n_alert = df["alert_no"].nunique()

    akurasi_field = df["is_correct"].mean()

    # Sebuah alert dianggap benar bila seluruh field-nya benar.
    per_alert = df.groupby("alert_no")["is_correct"].min()
    akurasi_alert = per_alert.mean()

    per_field = (
        df.groupby("field_name")["is_correct"]
        .agg(diperiksa="count", benar="sum")
        .reset_index()
    )
    per_field["akurasi"] = (
        per_field["benar"] / per_field["diperiksa"]
    ).round(4)
    per_field = per_field.sort_values("akurasi")

    per_stream = (
        df.groupby("stream")["is_correct"]
        .agg(diperiksa="count", benar="sum")
        .reset_index()
    )
    per_stream["akurasi"] = (
        per_stream["benar"] / per_stream["diperiksa"]
    ).round(4)

    kesalahan = df[df["is_correct"] == 0][
        [
            "alert_no",
            "stream",
            "field_name",
            "extracted_value",
            "correct_value",
        ]
    ].copy()

    return {
        "n_alert": int(n_alert),
        "n_field": int(n_field),
        "akurasi_field": round(float(akurasi_field), 4),
        "akurasi_alert": round(float(akurasi_alert), 4),
        "per_field": per_field,
        "per_stream": per_stream,
        "kesalahan": kesalahan,
    }