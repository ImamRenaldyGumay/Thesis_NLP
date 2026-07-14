"""
database.py

Lapisan penyimpanan SQLite untuk aplikasi:

Model Rule-Based Natural Language Processing untuk
Ekstraksi Informasi dan Penyajian Rekomendasi Tindakan
dari Teks Alert pada Operation Command Center.

Tabel utama:
    alerts

Menyimpan:
    - raw_text
    - stream
    - hasil_pembacaan
    - alasan_pembacaan
    - rekomendasi
    - tim_terkait
    - aturan_aktif
    - tokens
    - parsed_data
    - facts

Kolom lama seperti condition, diagnosis, reasoning,
recommendation, team, fired_rules, dan features
tidak langsung dihapus untuk menjaga kompatibilitas
database lama.
"""

import json
import sqlite3

import pandas as pd


DB_NAME = "alerts.db"


# ============================================================
# CONNECTION
# ============================================================

def get_connection():
    """
    Membuat koneksi baru ke database SQLite.
    """

    return sqlite3.connect(DB_NAME)


# ============================================================
# DATABASE UTILITY
# ============================================================

def _get_existing_columns(cursor, table):
    """
    Mengambil nama kolom yang tersedia pada tabel.
    """

    cursor.execute(f"PRAGMA table_info({table})")

    return {
        row[1]
        for row in cursor.fetchall()
    }


def _ensure_columns(cursor, table, columns):
    """
    Menambahkan kolom yang belum tersedia.

    columns:
        {
            "nama_kolom": "TIPE_DATA",
        }
    """

    existing_columns = _get_existing_columns(
        cursor,
        table,
    )

    for column_name, column_type in columns.items():

        if column_name not in existing_columns:

            cursor.execute(
                f"""
                ALTER TABLE {table}
                ADD COLUMN {column_name} {column_type}
                """
            )


# ============================================================
# INITIALIZATION
# ============================================================

def init_db():
    """
    Membuat tabel alerts apabila belum tersedia.

    Jika database lama digunakan, kolom baru akan
    ditambahkan melalui migrasi ringan.

    Data lama tidak dihapus.
    """

    conn = get_connection()
    cursor = conn.cursor()

    # --------------------------------------------------------
    # CREATE TABLE
    # --------------------------------------------------------

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS alerts (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            timestamp DATETIME
                DEFAULT CURRENT_TIMESTAMP,

            raw_text TEXT NOT NULL,

            stream TEXT,

            hasil_pembacaan TEXT,

            alasan_pembacaan TEXT,

            rekomendasi TEXT,

            tim_terkait TEXT,

            aturan_aktif TEXT,

            tokens TEXT,

            parsed_data TEXT,

            facts TEXT
        )
        """
    )

    # --------------------------------------------------------
    # MIGRATION FOR OLD DATABASE
    # --------------------------------------------------------

    _ensure_columns(
        cursor,
        "alerts",
        {
            "hasil_pembacaan": "TEXT",
            "alasan_pembacaan": "TEXT",
            "rekomendasi": "TEXT",
            "tim_terkait": "TEXT",
            "aturan_aktif": "TEXT",
            "tokens": "TEXT",
            "parsed_data": "TEXT",
            "facts": "TEXT",
        },
    )

    conn.commit()
    conn.close()


# ============================================================
# SAVE ALERT
# ============================================================

def save_alert(result):
    """
    Menyimpan hasil process_alert() ke tabel alerts.

    Mapping langsung:

        result["raw_text"]
            -> raw_text

        result["stream"]
            -> stream

        result["hasil_pembacaan"]
            -> hasil_pembacaan

        result["alasan_pembacaan"]
            -> alasan_pembacaan

        result["rekomendasi"]
            -> rekomendasi

        result["tim_terkait"]
            -> tim_terkait

        result["aturan_aktif"]
            -> aturan_aktif

        result["tokens"]
            -> tokens

        result["parsed_data"]
            -> parsed_data

        result["facts"]
            -> facts
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO alerts (

            raw_text,

            stream,

            hasil_pembacaan,

            alasan_pembacaan,

            rekomendasi,

            tim_terkait,

            aturan_aktif,

            tokens,

            parsed_data,

            facts
        )

        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,

        (
            result.get(
                "raw_text",
                "",
            ),

            result.get(
                "stream",
                "UNKNOWN",
            ),

            result.get(
                "hasil_pembacaan",
                "",
            ),

            result.get(
                "alasan_pembacaan",
                "",
            ),

            result.get(
                "rekomendasi",
                "",
            ),

            result.get(
                "tim_terkait",
                "",
            ),

            json.dumps(
                result.get(
                    "aturan_aktif",
                    [],
                ),
                ensure_ascii=False,
            ),

            json.dumps(
                result.get(
                    "tokens",
                    {},
                ),
                ensure_ascii=False,
            ),

            json.dumps(
                result.get(
                    "parsed_data",
                    {},
                ),
                ensure_ascii=False,
            ),

            json.dumps(
                result.get(
                    "facts",
                    [],
                ),
                ensure_ascii=False,
            ),
        ),
    )

    alert_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return alert_id


# ============================================================
# GET ALL ALERTS
# ============================================================

def get_all_alerts():
    """
    Mengambil seluruh alert.

    Digunakan oleh:
        - Database
        - Dashboard
        - Sidebar
    """

    conn = get_connection()

    query = """
        SELECT

            id,

            timestamp,

            raw_text,

            stream,

            hasil_pembacaan,

            alasan_pembacaan,

            rekomendasi,

            tim_terkait,

            aturan_aktif,

            tokens,

            parsed_data,

            facts

        FROM alerts

        ORDER BY id DESC
    """

    dataframe = pd.read_sql_query(
        query,
        conn,
    )

    conn.close()

    return dataframe


# ============================================================
# GET ALERT BY ID
# ============================================================

def get_alert_by_id(alert_id):
    """
    Mengambil satu alert berdasarkan ID.
    """

    conn = get_connection()

    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT

            id,

            timestamp,

            raw_text,

            stream,

            hasil_pembacaan,

            alasan_pembacaan,

            rekomendasi,

            tim_terkait,

            aturan_aktif,

            tokens,

            parsed_data,

            facts

        FROM alerts

        WHERE id = ?
        """,

        (
            alert_id,
        ),
    )

    row = cursor.fetchone()

    conn.close()

    if row is None:
        return None

    return dict(row)


# ============================================================
# DELETE ONE ALERT
# ============================================================

def delete_alert(alert_id):
    """
    Menghapus satu alert berdasarkan ID.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        DELETE FROM alerts
        WHERE id = ?
        """,
        (
            alert_id,
        ),
    )

    conn.commit()
    conn.close()


# ============================================================
# DELETE ALL ALERTS
# ============================================================

def delete_all_alerts():
    """
    Menghapus seluruh data alert.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        DELETE FROM alerts
        """
    )

    conn.commit()
    conn.close()


# ============================================================
# DATABASE STATISTICS
# ============================================================

def get_database_statistics():
    """
    Mengambil statistik sederhana database.

    Digunakan oleh Sidebar dan Dashboard.
    """

    alert_df = get_all_alerts()

    if alert_df.empty:

        return {
            "total_alert": 0,
            "jumlah_stream": 0,
            "jumlah_aturan_aktif": 0,
            "stream_terbanyak": "-",
            "aturan_terbanyak": "-",
        }

    # --------------------------------------------------------
    # STREAM
    # --------------------------------------------------------

    jumlah_stream = (
        alert_df["stream"]
        .dropna()
        .nunique()
    )

    stream_counts = (
        alert_df["stream"]
        .dropna()
        .value_counts()
    )

    stream_terbanyak = (
        stream_counts.index[0]
        if not stream_counts.empty
        else "-"
    )

    # --------------------------------------------------------
    # ATURAN PRODUKSI
    # --------------------------------------------------------

    rule_counter = {}

    for value in alert_df["aturan_aktif"]:

        try:

            rules = (
                json.loads(value)
                if isinstance(value, str)
                else value
            )

        except Exception:

            rules = []

        if not isinstance(rules, list):
            continue

        for rule in rules:

            rule_counter[rule] = (
                rule_counter.get(rule, 0) + 1
            )

    jumlah_aturan_aktif = len(rule_counter)

    if rule_counter:

        aturan_terbanyak = max(
            rule_counter,
            key=rule_counter.get,
        )

    else:

        aturan_terbanyak = "-"

    return {
        "total_alert":
            len(alert_df),

        "jumlah_stream":
            jumlah_stream,

        "jumlah_aturan_aktif":
            jumlah_aturan_aktif,

        "stream_terbanyak":
            stream_terbanyak,

        "aturan_terbanyak":
            aturan_terbanyak,
    }