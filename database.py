import sqlite3
import pandas as pd
import json
from datetime import datetime

DB_NAME = "alerts.db"

# ============================================================
# [BARU] TOLERANSI AKURASI
# ------------------------------------------------------------
# Selisih |skor_sistem - skor_engineer| <= TOLERANSI dianggap COCOK.
# Alasan: skor urgensi bersifat ORDINAL (1-10), sehingga selisih 1 poin
# (mis. 9 vs 8) praktis berada pada level urgensi yang sama. Ubah nilai di
# sini bila pembimbing meminta toleransi berbeda.
# ============================================================
ACCURACY_TOLERANCE = 1


def get_connection():
    """Mendapatkan koneksi ke database SQLite."""
    return sqlite3.connect(DB_NAME)

# ============================================================
# INISIALISASI & MIGRASI DATABASE (HANYA 1 FUNGSI)
# ============================================================

def init_database():
    """
    Membuat tabel alerts jika belum ada.
    - is_processed: 0 = mentah, 1 = sudah diproses NLP.
    - expected_score: skor dari engineer (untuk uji akurasi).
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Membuat tabel utama
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            stream TEXT,
            raw_message TEXT,
            score INTEGER,
            level TEXT,
            reason TEXT,
            extracted_features TEXT,        -- JSON string
            original_severity TEXT,         -- Severity asli dari sistem (opsional)
            expected_score INTEGER,         -- GROUND TRUTH dari engineer (UNTUK AKURASI)
            is_processed INTEGER DEFAULT 0, -- 0=mentah, 1=selesai diproses
            imported_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Cek apakah kolom 'expected_score' sudah ada, jika belum tambahkan (migrasi)
    cursor.execute("PRAGMA table_info(alerts)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'is_processed' not in columns:
        cursor.execute("ALTER TABLE alerts ADD COLUMN is_processed INTEGER DEFAULT 0")
    if 'expected_score' not in columns:
        cursor.execute("ALTER TABLE alerts ADD COLUMN expected_score INTEGER")
    
    conn.commit()
    conn.close()
    print("✅ Database initialized (table 'alerts' ready with is_processed & expected_score)")

# ============================================================
# FUNGSI INSERT UNTUK DATA MENTAH (DARI EXCEL / BATCH)
# ============================================================

def insert_alerts_batch(alerts_list: list):
    """
    Menyimpan banyak alert sekaligus ke database (batch insert).
    Sekarang mendukung kolom 'expected_score'.
    """
    if not alerts_list:
        return
    
    conn = get_connection()
    cursor = conn.cursor()
    
    data_to_insert = []
    for alert in alerts_list:
        data_to_insert.append((
            alert.get('timestamp', datetime.now().isoformat()),
            alert.get('stream', 'UNKNOWN'),
            alert.get('raw_message', ''),
            alert.get('score', 0),
            alert.get('level', ''),
            alert.get('reason', ''),
            json.dumps(alert.get('extracted_features', {})),
            alert.get('original_severity', ''),
            alert.get('expected_score', None),  # <-- TAMBAHKAN INI
            1  # is_processed = 1 (langsung diproses)
        ))
    
    cursor.executemany('''
        INSERT INTO alerts (
            timestamp, stream, raw_message, score, level, reason, 
            extracted_features, original_severity, expected_score, is_processed
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', data_to_insert)
    
    conn.commit()
    conn.close()

# ============================================================
# FUNGSI UPDATE HASIL NLP
# ============================================================

def update_alert_with_nlp(alert_id: int, stream: str, score: int, level: str, reason: str, features: dict):
    """Update hasil NLP ke database untuk satu alert."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE alerts 
        SET stream = ?, score = ?, level = ?, reason = ?, 
            extracted_features = ?, is_processed = 1
        WHERE id = ?
    ''', (
        stream, score, level, reason, 
        json.dumps(features), alert_id
    ))
    
    conn.commit()
    conn.close()

def get_unprocessed_alerts(limit=10000):
    """Mengambil semua alert yang belum diproses NLP (is_processed = 0)."""
    conn = get_connection()
    query = "SELECT id, raw_message, timestamp, expected_score FROM alerts WHERE is_processed = 0 ORDER BY id LIMIT ?"
    df = pd.read_sql_query(query, conn, params=[limit])
    conn.close()
    return df

def count_unprocessed():
    """Menghitung jumlah alert yang belum diproses."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM alerts WHERE is_processed = 0")
    count = cursor.fetchone()[0]
    conn.close()
    return count

# ============================================================
# FUNGSI UNTUK MELIHAT DATA & STATISTIK
# ============================================================

def get_processed_alerts(limit=1000):
    """Mengambil hanya alert yang sudah diproses (untuk dashboard)."""
    conn = get_connection()
    query = "SELECT * FROM alerts WHERE is_processed = 1 ORDER BY id DESC LIMIT ?"
    df = pd.read_sql_query(query, conn, params=[limit])
    conn.close()
    return df

def get_all_alerts(limit=1000, offset=0, stream_filter=None, level_filter=None):
    """Mengambil data alert dari database dengan filter opsional."""
    conn = get_connection()
    
    query = "SELECT * FROM alerts WHERE 1=1"
    params = []
    
    if stream_filter and stream_filter != 'ALL':
        query += " AND stream = ?"
        params.append(stream_filter)
    if level_filter and level_filter != 'ALL':
        query += " AND level = ?"
        params.append(level_filter)
    
    query += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

def get_alert_stats():
    """Mendapatkan statistik dari database.
    [DIPERBAIKI] Distribusi & rata-rata skor dihitung HANYA dari alert yang
    sudah diproses (is_processed = 1), agar baris mentah (skor 0) tidak
    mengotori rata-rata. 'total' tetap menghitung seluruh baris di DB."""
    conn = get_connection()

    total = pd.read_sql_query("SELECT COUNT(*) as count FROM alerts", conn).iloc[0]['count']
    stream_dist = pd.read_sql_query("SELECT stream, COUNT(*) as count FROM alerts WHERE is_processed = 1 GROUP BY stream", conn)
    level_dist = pd.read_sql_query("SELECT level, COUNT(*) as count FROM alerts WHERE is_processed = 1 GROUP BY level", conn)
    avg_score = pd.read_sql_query("SELECT AVG(score) as avg FROM alerts WHERE is_processed = 1", conn).iloc[0]['avg']

    conn.close()
    return {
        'total': total,
        'stream_dist': stream_dist,
        'level_dist': level_dist,
        'avg_score': avg_score if avg_score else 0
    }

# --- VERSI LAMA (ARSIP) get_alert_stats --------------------------------------
# def get_alert_stats():
#     conn = get_connection()
#     total = pd.read_sql_query("SELECT COUNT(*) as count FROM alerts", conn).iloc[0]['count']
#     stream_dist = pd.read_sql_query("SELECT stream, COUNT(*) as count FROM alerts GROUP BY stream", conn)
#     level_dist = pd.read_sql_query("SELECT level, COUNT(*) as count FROM alerts GROUP BY level", conn)
#     avg_score = pd.read_sql_query("SELECT AVG(score) as avg FROM alerts", conn).iloc[0]['avg']  # ikut baris mentah
#     conn.close()
#     return {'total': total, 'stream_dist': stream_dist, 'level_dist': level_dist,
#             'avg_score': avg_score if avg_score else 0}
# -----------------------------------------------------------------------------

# ============================================================
# 🎯 FUNGSI UTAMA UNTUK BAB IV (PERHITUNGAN AKURASI)
# ============================================================

def calculate_accuracy() -> dict:
    """
    [DIPERBARUI] Menghitung Akurasi dengan TOLERANSI +/- ACCURACY_TOLERANCE.

    Skor urgensi bersifat ordinal, sehingga selisih 1 poin (mis. 9 vs 8) masih
    dianggap cocok. Fungsi ini mengembalikan:
      - accuracy / correct        : akurasi utama (toleransi +/-1)  <-- dipakai UI
      - exact_accuracy / exact_*  : akurasi "tepat sama persis" (pembanding)
    Kunci lama (total_data, correct, accuracy, message) tetap ada agar app.py &
    chatbot.py tidak rusak.
    """
    conn = get_connection()
    
    # Ambil semua data yang sudah diproses DAN memiliki expected_score
    query = """
        SELECT id, score, expected_score 
        FROM alerts 
        WHERE is_processed = 1 AND expected_score IS NOT NULL
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    total = len(df)
    if total == 0:
        return {
            'total_data': 0,
            'correct': 0,
            'accuracy': 0.0,
            'exact_correct': 0,
            'exact_accuracy': 0.0,
            'tolerance': ACCURACY_TOLERANCE,
            'message': 'Belum ada data uji dengan expected_score.'
        }
    
    # Selisih absolut antara skor sistem dan skor engineer
    selisih = (df['score'] - df['expected_score']).abs()

    # Cocok dengan toleransi (metrik utama) dan cocok tepat sama (pembanding)
    tol_match = selisih <= ACCURACY_TOLERANCE
    exact_match = selisih == 0

    correct = int(tol_match.sum())
    exact_correct = int(exact_match.sum())
    accuracy = round(correct / total * 100, 2)
    exact_accuracy = round(exact_correct / total * 100, 2)
    
    return {
        'total_data': total,
        'correct': correct,                 # cocok (toleransi +/-1)
        'accuracy': accuracy,               # akurasi utama (toleransi +/-1)
        'exact_correct': exact_correct,     # cocok tepat sama
        'exact_accuracy': exact_accuracy,   # akurasi tepat sama (pembanding)
        'tolerance': ACCURACY_TOLERANCE,
        'message': (f'Akurasi (toleransi \u00b1{ACCURACY_TOLERANCE}): {accuracy}% ({correct}/{total}) | '
                    f'Tepat sama: {exact_accuracy}% ({exact_correct}/{total})')
    }

# --- VERSI LAMA (ARSIP) calculate_accuracy -----------------------------------
# def calculate_accuracy():
#     conn = get_connection()
#     query = "SELECT id, score, expected_score FROM alerts WHERE is_processed = 1 AND expected_score IS NOT NULL"
#     df = pd.read_sql_query(query, conn); conn.close()
#     total = len(df)
#     if total == 0:
#         return {'total_data': 0, 'correct': 0, 'accuracy': 0.0,
#                 'message': 'Belum ada data uji dengan expected_score.'}
#     df['match'] = df['score'] == df['expected_score']   # <-- harus sama PERSIS (terlalu kaku)
#     correct = df['match'].sum()
#     accuracy = (correct / total) * 100
#     return {'total_data': total, 'correct': int(correct), 'accuracy': round(accuracy, 2),
#             'message': f'Akurasi: {accuracy:.2f}% ({correct}/{total})'}
# -----------------------------------------------------------------------------

def get_confusion_matrix_data() -> pd.DataFrame:
    """
    [DIPERBARUI] Mengembalikan DataFrame untuk Confusion Matrix di BAB IV.
    Status 'Cocok' kini memakai TOLERANSI +/- ACCURACY_TOLERANCE agar konsisten
    dengan calculate_accuracy(). Ditambahkan kolom 'selisih'.
    """
    conn = get_connection()
    query = f"""
        SELECT 
            id, 
            stream, 
            score as skor_sistem, 
            expected_score as skor_engineer,
            ABS(score - expected_score) as selisih,
            CASE 
                WHEN ABS(score - expected_score) <= {ACCURACY_TOLERANCE} THEN '✅ Cocok' 
                ELSE '❌ Tidak Cocok' 
            END as status
        FROM alerts 
        WHERE is_processed = 1 AND expected_score IS NOT NULL
        ORDER BY id
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

# --- VERSI LAMA (ARSIP) get_confusion_matrix_data ----------------------------
# def get_confusion_matrix_data():
#     conn = get_connection()
#     query = """
#         SELECT id, stream, score as skor_sistem, expected_score as skor_engineer,
#             CASE WHEN score = expected_score THEN '✅ Cocok' ELSE '❌ Tidak Cocok' END as status
#         FROM alerts WHERE is_processed = 1 AND expected_score IS NOT NULL ORDER BY id
#     """
#     df = pd.read_sql_query(query, conn); conn.close(); return df
# -----------------------------------------------------------------------------

# ============================================================
# FUNGSI UTILITY LAINNYA
# ============================================================

def insert_alert(alert_data: dict):
    """Menyimpan satu hasil proses alert ke database (kompatibilitas lama)."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO alerts (
            timestamp, stream, raw_message, score, level, reason, 
            extracted_features, original_severity, is_processed
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        alert_data.get('timestamp', datetime.now().isoformat()),
        alert_data.get('stream', 'UNKNOWN'),
        alert_data.get('raw_message', ''),
        alert_data.get('score', 0),
        alert_data.get('level', ''),
        alert_data.get('reason', ''),
        json.dumps(alert_data.get('extracted_features', {})),
        alert_data.get('original_severity', ''),
        1  # langsung ditandai processed
    ))
    
    conn.commit()
    conn.close()

def clear_database():
    """Menghapus semua data dari tabel alerts (reset)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM alerts")
    conn.commit()
    conn.close()
    print("🗑️ Database cleared")

# ============================================================
# DEMO SINGKAT (Jika dijalankan langsung)
# ============================================================
if __name__ == "__main__":
    init_database()
    print("✅ Database siap digunakan.")
    print(f"📊 Total alert belum diproses: {count_unprocessed()}")
    print(f"🎯 Toleransi akurasi yang dipakai: \u00b1{ACCURACY_TOLERANCE}")