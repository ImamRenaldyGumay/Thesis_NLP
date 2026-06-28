import re
from datetime import datetime
from typing import Dict, Tuple, Any

# ============================================================
# REFERENSI ATURAN PRODUKSI (DARI DOKUMEN TESIS)
# ============================================================
# M-01 s.d M-05 : Router Utama (Klasifikasi Tipe Input)
# B-01 s.d B-10 : Aturan BWCE (Performa Bisnis)
# N-01 s.d N-11 : Aturan NGSSP (Middleware)
# U-01 s.d U-09 : Aturan USSD (Process)
# C-01 s.d C-04 : Aturan CRM (Legacy / Negative Weighting)
# ============================================================
#
# >>> CATATAN VERSI INI (PERUBAHAN UTAMA) <<<
# Evaluator kini tidak hanya menghasilkan SKOR, tetapi juga JAWABAN
# bergaya sistem pakar untuk tiap alert:
#   - diagnosis     : apa masalahnya / kenapa kondisi ini muncul
#   - rekomendasi   : tindakan yang disarankan
#   - tim_eskalasi  : ke tim mana alert sebaiknya diteruskan
#
# Logika SKOR TIDAK DIUBAH dari versi lama (angka tetap sama), sehingga
# hasil pengujian akurasi Anda tidak bergeser. Yang ditambahkan hanya
# lapisan "jawaban" di atas skor.
#
# ASAL PENGETAHUAN (PENTING UNTUK BAB III - Akuisisi Pengetahuan):
# Teks diagnosis/rekomendasi/tim di bawah DIAMBIL & DIKEMBANGKAN dari
#   (a) STREAM_KB yang sudah Anda tulis sendiri di chatbot.py, dan
#   (b) instruksi tim yang tertulis langsung pada teks alert
#       (mis. "ngssp/vas team pls check!", "Pls inform middleware Team!").
# Ini BUKAN pengetahuan karangan, tetapi MASIH HARUS DIVERIFIKASI &
# DIPERINCI oleh Anda sebagai pakar OCC. Bagian bertanda [VERIFIKASI]
# adalah yang paling perlu Anda koreksi.
# ============================================================


# ============================================================
# BASIS PENGETAHUAN SISTEM PAKAR (EXPERT KNOWLEDGE BASE)
# ------------------------------------------------------------
# Hanya berisi metadata dasar per stream (nama & tim default).
# Diagnosis & rekomendasi yang spesifik-kondisi ditentukan di dalam
# masing-masing fungsi evaluator (score_*) di bawah.
# ============================================================

EXPERT_KB = {
    'BWCE':  {'nama': 'Performa Transaksi Bisnis',                 'tim': 'NGSSP/VAS Team'},
    'NGSSP': {'nama': 'Middleware (Node Exporter / Stuck Thread)', 'tim': 'Middleware Team'},
    'USSD':  {'nama': 'Ketersediaan Proses',                       'tim': 'Tim Infrastruktur/Server'},  # [VERIFIKASI]
    'CRM':   {'nama': 'Layanan Legacy (OMNI)',                     'tim': '\u2014 (di-suppress)'},
}


# ============================================================
# FUNGSI PEMBANTU: MAP SKOR KE LEVEL (Digunakan di Evaluator)
# ============================================================

def map_score_to_level(score: int) -> str:
    """Mengkonversi skor numerik (1-10) ke Level Urgensi."""
    if score >= 8:
        return "\U0001F534 KRITIS"
    elif score >= 5:
        return "\U0001F7E0 TINGGI"
    elif score >= 3:
        return "\U0001F7E1 SEDANG"
    else:
        return "\U0001F7E2 RENDAH"


def _parse_issue_time(s: str):
    """[BARU] Parse timestamp 'Issue start at' secara aman terhadap zona waktu.
    Menangani bentuk seperti '2024-11-13T23:49:00.000+07:00'. Mengembalikan
    objek datetime (aware bila ada offset zona waktu) atau None bila gagal."""
    if not s:
        return None
    m = re.search(r'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?)(?:\.\d+)?([+-]\d{2}:?\d{2})?', s)
    if not m:
        return None
    base = m.group(1).replace('T', ' ')
    off = m.group(2) or ''
    if off and ':' not in off:            # ubah +0700 -> +07:00
        off = off[:3] + ':' + off[3:]
    for candidate in (base + off, base):  # coba dengan offset dulu, lalu tanpa
        try:
            return datetime.fromisoformat(candidate)
        except Exception:
            continue
    return None


def _human_duration(minutes: float) -> str:
    """[BARU] Format durasi agar mudah dibaca (menit / jam / hari)."""
    if minutes < 60:
        return f"{minutes:.0f} menit"
    if minutes < 60 * 24:
        return f"{minutes / 60:.1f} jam"
    return f"{minutes / 1440:.1f} hari"


# ============================================================
# STREAM 1: BWCE (Aturan B-01 s.d B-10)
# ============================================================
# Pemicu: Router M-03 (mendeteksi kata "SR:" atau "Success:")
# Logika Skor: B-01 s.d B-04 (SR < 98.5 -> 10, TE > 20 +2, Degraded +1)
# ============================================================

def extract_bwce_features(text: str) -> Dict[str, Any]:
    """
    Scanner + Parser untuk BWCE.
    Mengekstrak: app, total, success, be, te, sr, dan status Degraded.
    """
    features = {
        'stream': 'BWCE',
        'app': None,
        'sr': None,
        'te': None,
        'be': None,
        'total': None,
        'has_degraded': False,
        'raw_text': text
    }

    # Regex untuk menangkap nama aplikasi (contoh: bi-air-update)
    app_match = re.search(r'BWCE\s+([\w\-]+)', text, re.IGNORECASE)
    if app_match:
        features['app'] = app_match.group(1)

    # Regex untuk menangkap Success Rate (SR)
    sr_match = re.search(r'SR:\s*([0-9.]+)\s*%', text, re.IGNORECASE)
    if sr_match:
        features['sr'] = float(sr_match.group(1))

    # Regex untuk menangkap Technical Error (TE)
    te_match = re.search(r'TE:\s*([0-9]+)', text, re.IGNORECASE)
    if te_match:
        features['te'] = int(te_match.group(1))

    # Regex untuk menangkap Business Error (BE)
    be_match = re.search(r'BE:\s*([0-9]+)', text, re.IGNORECASE)
    if be_match:
        features['be'] = int(be_match.group(1))

    # Regex untuk menangkap Total Transaksi
    total_match = re.search(r'Total:\s*([0-9]+)', text, re.IGNORECASE)
    if total_match:
        features['total'] = int(total_match.group(1))

    # Aturan B-09: Deteksi frasa "SR Degraded" (cocok dengan data nyata)
    if re.search(r'SR\s+Degraded', text, re.IGNORECASE):
        features['has_degraded'] = True

    return features


def score_bwce(features: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluator untuk BWCE (VERSI BARU - menghasilkan skor + jawaban pakar).
    Logika skor SAMA dengan versi lama; ditambahkan diagnosis/rekomendasi/tim.
    """
    sr = features.get('sr')
    te = features.get('te') or 0
    be = features.get('be') or 0
    has_degraded = features.get('has_degraded', False)
    app = features.get('app') or 'job terkait'
    tim = EXPERT_KB['BWCE']['tim']

    # R-BWCE-01 & R-BWCE-02: Penentuan Skor Dasar berdasarkan SR
    if sr is None:
        score, reason = 3, "SR tidak terdeteksi"
        diagnosis = "Success Rate tidak terbaca dari teks alert (kemungkinan format berbeda)."
        rekomendasi = "Verifikasi manual job terkait dan periksa pola parsing alert."
        tim = "OCC (verifikasi manual)"
    elif sr < 98.5:
        score, reason = 10, f"SR {sr}% < 98.5% (Kritis)"
        diagnosis = (f"Success Rate {sr}% jauh di bawah ambang 98.5% pada {app} \u2014 "
                     f"mayoritas transaksi gagal (degradasi berat).")
        rekomendasi = (f"Periksa {app}; cek Backend Error (BE={be}) dan Technical Error/timeout "
                       f"(TE={te}); telusuri kondisi backend/koneksi; eskalasi segera.")
    elif sr < 99.5:
        score, reason = 7, f"SR {sr}% antara 98.5-99.5% (Waspada)"
        diagnosis = f"Success Rate {sr}% sedikit di bawah normal pada {app} \u2014 sebagian transaksi gagal."
        rekomendasi = "Pantau tren SR; cek BE/TE; siapkan eskalasi bila terus menurun."
    else:
        score, reason = 3, f"SR {sr}% >= 99.5% (Normal)"
        diagnosis = f"Success Rate {sr}% dalam batas normal pada {app}."
        rekomendasi = "Tidak perlu tindakan khusus; cukup monitoring rutin."
        tim = "\u2014"

    # R-BWCE-03: Jika TE > 20, tambah 2 poin (tapi maksimal 10)
    if te > 20:
        score = min(score + 2, 10)
        reason += f" | TE {te} > 20 (+2)"
        rekomendasi += f" Catatan: Technical Error tinggi (TE={te}) mengindikasikan masalah teknis/timeout."

    # R-BWCE-04: Jika ada frasa "SR Degraded", tambah 1 poin
    if has_degraded:
        score = min(score + 1, 10)
        reason += " | SR Degraded (+1)"

    return {
        'score': score,
        'level': map_score_to_level(score),
        'reason': reason,
        'diagnosis': diagnosis,
        'rekomendasi': rekomendasi,
        'tim_eskalasi': tim,
    }

# --- VERSI LAMA (ARSIP) score_bwce -------------------------------------------
# def score_bwce(features):
#     sr = features.get('sr')
#     te = features.get('te') or 0
#     has_degraded = features.get('has_degraded', False)
#     if sr is None:
#         score, reason = 3, "SR tidak terdeteksi"
#     elif sr < 98.5:
#         score, reason = 10, f"SR {sr}% < 98.5% (Kritis)"
#     elif sr < 99.5:
#         score, reason = 7, f"SR {sr}% antara 98.5-99.5% (Waspada)"
#     else:
#         score, reason = 3, f"SR {sr}% >= 99.5% (Normal)"
#     if te > 20:
#         score = min(score + 2, 10); reason += f" | TE {te} > 20 (+2)"
#     if has_degraded:
#         score = min(score + 1, 10); reason += " | SR Degraded (+1)"
#     return score, map_score_to_level(score), reason
# -----------------------------------------------------------------------------


# ============================================================
# STREAM 2: NGSSP (Aturan N-01 s.d N-11)
# ============================================================
# Pemicu: Router M-02 (mendeteksi "val:", "stuck thread", "node exporter")
# Logika Skor: R-NGS-01 s.d R-NGS-03 (val=0 -> down, val>100 -> kritis, durasi+2)
# ============================================================

def extract_ngssp_features(text: str) -> Dict[str, Any]:
    """
    Scanner + Parser untuk NGSSP.
    Mengekstrak: val, issue_start, host, serta flag stuck_thread / node_exporter.
    """
    features = {
        'stream': 'NGSSP',
        'val': None,
        'issue_start': None,
        'has_stuck_thread': False,
        'is_node_exporter': False,
        'host': None,
        'raw_text': text
    }

    # Aturan N-07: Deteksi tipe komponen
    if re.search(r'Stuck\s+Thread', text, re.IGNORECASE):
        features['has_stuck_thread'] = True
    if re.search(r'Node\s+Exporter', text, re.IGNORECASE):
        features['is_node_exporter'] = True

    # Aturan N-06 & N-08: Ekstrak host dan nilai (val)
    host_match = re.search(r'~\s*([\w\.\-]+:[0-9]+)', text)
    if host_match:
        features['host'] = host_match.group(1)

    val_match = re.search(r'val:\s*([0-9]+)', text, re.IGNORECASE)
    if val_match:
        features['val'] = int(val_match.group(1))

    # Aturan N-09: Ekstrak waktu mulai (issue start) — kini ikut menangkap
    # pecahan detik & offset zona waktu (mis. .000+07:00) agar tidak hilang.
    time_match = re.search(r'Issue start at:?\s*([\d\-T:.\+]+)', text, re.IGNORECASE)
    if time_match:
        features['issue_start'] = time_match.group(1)

    return features


def score_ngssp(features: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluator untuk NGSSP (VERSI BARU - skor + jawaban pakar).
    Logika skor SAMA dengan versi lama.
    """
    val = features.get('val')
    issue_start = features.get('issue_start')
    is_node = features.get('is_node_exporter', False)
    host = features.get('host') or 'host terkait'
    tim = EXPERT_KB['NGSSP']['tim']

    # R-NGS-01 & Penanganan Khusus: val=0 pada Node Exporter = DOWN Total
    if val == 0 and is_node:
        score, reason = 9, "val=0 -> Node Exporter DOWN (Kritis)"
        diagnosis = f"Node Exporter pada {host} melaporkan val=0 \u2014 node/komponen middleware mati (DOWN)."
        rekomendasi = (f"Periksa status server/exporter pada {host}; pastikan service hidup; "
                       f"bila perlu lakukan restart. Informasikan ke tim middleware.")
    elif val is None:
        score, reason = 2, "Nilai val tidak terdeteksi"
        diagnosis = "Nilai val tidak terbaca \u2014 status komponen tidak dapat dipastikan dari teks."
        rekomendasi = "Verifikasi manual komponen middleware terkait."
        tim = "OCC (verifikasi manual)"
    elif val > 100:
        score, reason = 9, f"val {val} > 100 (Kritis - Thread Macet)"
        diagnosis = (f"Jumlah stuck thread tinggi (val={val}) pada {host} \u2014 antrean thread macet, "
                     f"berisiko menghentikan layanan.")
        rekomendasi = "Periksa antrean/threads; pertimbangkan restart managed server; informasikan ke tim middleware."
    elif val > 50:
        score, reason = 6, f"val {val} antara 50-100 (Waspada)"
        diagnosis = f"Stuck thread sedang (val={val}) pada {host} \u2014 perlu dipantau."
        rekomendasi = "Pantau perkembangan stuck thread; siapkan tindakan bila terus naik."
    else:
        score, reason = 2, f"val {val} <= 50 (Normal)"
        diagnosis = f"Nilai val={val} pada {host} dalam batas wajar."
        rekomendasi = "Cukup monitoring rutin."
        tim = "\u2014"

    # R-NGS-03: Jika durasi > 30 menit, tambah 2 poin
    # [DIPERBAIKI] parsing zona-waktu aman + format durasi manusiawi + guard.
    # CATATAN: modifier ini mengukur durasi terhadap WAKTU SAAT INI (real-time).
    # Untuk dataset historis (uji batch), durasi akan hampir selalu > 30 menit,
    # sehingga modifier cenderung selalu aktif. Pertimbangkan implikasinya di Bab IV.
    start_time = _parse_issue_time(issue_start)
    if start_time is not None:
        now = datetime.now(start_time.tzinfo) if start_time.tzinfo else datetime.now()
        duration = (now - start_time).total_seconds() / 60
        if duration > 30:  # hanya berlaku untuk durasi positif yang wajar
            score = min(score + 2, 10)
            reason += f" | Durasi {_human_duration(duration)} > 30 menit (+2)"
            rekomendasi += f" Kondisi sudah berlangsung ~{_human_duration(duration)}; prioritaskan penanganan."

    return {
        'score': score,
        'level': map_score_to_level(score),
        'reason': reason,
        'diagnosis': diagnosis,
        'rekomendasi': rekomendasi,
        'tim_eskalasi': tim,
    }

# --- VERSI LAMA (ARSIP) score_ngssp ------------------------------------------
# def score_ngssp(features):
#     val = features.get('val')
#     issue_start = features.get('issue_start')
#     is_node = features.get('is_node_exporter', False)
#     if val == 0 and is_node:
#         score, reason = 9, "val=0 -> Node Exporter DOWN (Kritis)"
#     elif val is None:
#         score, reason = 2, "Nilai val tidak terdeteksi"
#     elif val > 100:
#         score, reason = 9, f"val {val} > 100 (Kritis - Thread Macet)"
#     elif val > 50:
#         score, reason = 6, f"val {val} antara 50-100 (Waspada)"
#     else:
#         score, reason = 2, f"val {val} <= 50 (Normal)"
#     if issue_start:
#         try:
#             clean = issue_start.replace('T', ' ').split('.')[0]
#             start_time = datetime.fromisoformat(clean)
#             duration = (datetime.now() - start_time).total_seconds() / 60
#             if duration > 30:
#                 score = min(score + 2, 10); reason += f" | Durasi {duration:.0f} menit > 30 (+2)"
#         except Exception:
#             pass
#     return score, map_score_to_level(score), reason
# -----------------------------------------------------------------------------


# ============================================================
# STREAM 3: USSD (Aturan U-01 s.d U-09)
# ============================================================
# Pemicu: Router M-05 (mendeteksi "2:-" atau "not running")
# Logika Skor: R-USD-01 s.d R-USD-03 (process_down -> 9, CRITICAL +1, Core +1)
# ============================================================

def extract_ussd_features(text: str) -> Dict[str, Any]:
    """
    Scanner + Parser untuk USSD.
    Mengekstrak: service, host, ip, severity, process_down, is_critical.
    """
    features = {
        'stream': 'USSD',
        'service': None,
        'host': None,
        'ip': None,
        'severity': None,
        'process_down': False,
        'is_critical': False,
        'avg_load': None,
        'raw_text': text
    }

    # Aturan U-2 s.d U-6: Ekstrak field bernomor (2:- s.d 6:-)
    m2 = re.search(r'2\s*:-\s*(\S+)', text)
    if m2:
        features['service'] = m2.group(1)
    m3 = re.search(r'3\s*:-\s*(\S+)', text)
    if m3:
        features['host'] = m3.group(1)
    m4 = re.search(r'4\s*:-\s*([0-9.]+)', text)
    if m4:
        features['ip'] = m4.group(1)
    m5 = re.search(r'5\s*:-\s*(\w+)', text)
    if m5:
        features['severity'] = m5.group(1)

    # Aturan U-7 & U-9: Deteksi status proses mati
    if re.search(r'not\s+running', text, re.IGNORECASE):
        features['process_down'] = True
    if re.search(r'CRITICAL', text, re.IGNORECASE):
        features['is_critical'] = True

    # Fallback / Kompatibilitas: Untuk format load-average jika ada
    load = re.search(r'7\s*:-\s*.*?:\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)', text)
    if load:
        a, b, c = float(load.group(1)), float(load.group(2)), float(load.group(3))
        features['avg_load'] = (a + b + c) / 3

    return features


def score_ussd(features: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluator untuk USSD (VERSI BARU - skor + jawaban pakar).
    Logika skor SAMA dengan versi lama.
    """
    tim = EXPERT_KB['USSD']['tim']
    svc = features.get('service') or 'layanan terkait'
    host = features.get('host') or 'host terkait'

    # R-USD-01: Prioritas utama -> Proses Mati
    if features.get('process_down'):
        score, reason = 9, "Process is not running (proses mati)"
        diagnosis = f"Proses {svc} pada {host} tidak berjalan (mati) \u2014 layanan tidak tersedia."
        rekomendasi = (f"Restart proses {svc} pada {host}; verifikasi service pulih. "
                       f"Bila banyak proses mati serentak (alert flood), tangani sebagai satu insiden besar.")

        # R-USD-02: Jika severity CRITICAL, +1
        if features.get('is_critical'):
            score = min(score + 1, 10)
            reason += " | CRITICAL (+1)"

        # R-USD-03: Jika service adalah layanan inti (Billing/CDR/SDP), +1
        svc_l = svc.lower()
        if any(k in svc_l for k in ('billing', 'cdr', 'sdp')):
            score = min(score + 1, 10)
            reason += " | layanan inti (+1)"
            diagnosis += " Layanan ini tergolong inti (Billing/CDR/SDP) sehingga dampaknya tinggi."

        return {
            'score': score, 'level': map_score_to_level(score), 'reason': reason,
            'diagnosis': diagnosis, 'rekomendasi': rekomendasi, 'tim_eskalasi': tim,
        }

    # Fallback: Jika bukan proses mati, cek apakah ada format load-average
    avg = features.get('avg_load')
    if avg is not None:
        if avg > 8.0:
            score, reason = 10, f"Load {avg:.2f} > 8.0 (Darurat)"
            diagnosis = f"Beban sistem sangat tinggi (load {avg:.2f}) pada {host}."
            rekomendasi = "Telusuri proses pemicu beban; pertimbangkan penyeimbangan beban / penambahan kapasitas."
        elif avg > 5.0:
            score, reason = 6, f"Load {avg:.2f} antara 5.0-8.0 (Waspada)"
            diagnosis = f"Beban sistem meningkat (load {avg:.2f}) pada {host} \u2014 perlu dipantau."
            rekomendasi = "Pantau tren beban; identifikasi proses yang boros sumber daya."
        else:
            score, reason = 1, f"Load {avg:.2f} <= 5.0 (Normal)"
            diagnosis = f"Beban sistem normal (load {avg:.2f}) pada {host}."
            rekomendasi = "Cukup monitoring rutin."
            tim = "\u2014"

        if features.get('is_critical'):
            score = min(score + 1, 10)
            reason += " | CRITICAL (+1)"
        return {
            'score': score, 'level': map_score_to_level(score), 'reason': reason,
            'diagnosis': diagnosis, 'rekomendasi': rekomendasi, 'tim_eskalasi': tim,
        }

    return {
        'score': 1, 'level': map_score_to_level(1), 'reason': "Pola USSD tidak terdeteksi",
        'diagnosis': "Pola USSD tidak terbaca jelas dari teks.",
        'rekomendasi': "Verifikasi manual; periksa format alert.",
        'tim_eskalasi': "OCC (verifikasi manual)",
    }

# --- VERSI LAMA (ARSIP) score_ussd -------------------------------------------
# def score_ussd(features):
#     if features.get('process_down'):
#         score, reason = 9, "Process is not running (proses mati)"
#         if features.get('is_critical'):
#             score = min(score + 1, 10); reason += " | CRITICAL (+1)"
#         svc = (features.get('service') or '').lower()
#         if any(k in svc for k in ('billing', 'cdr', 'sdp')):
#             score = min(score + 1, 10); reason += " | layanan inti (+1)"
#         return score, map_score_to_level(score), reason
#     avg = features.get('avg_load')
#     if avg is not None:
#         if avg > 8.0:
#             score, reason = 10, f"Load {avg:.2f} > 8.0 (Darurat)"
#         elif avg > 5.0:
#             score, reason = 6, f"Load {avg:.2f} antara 5.0-8.0 (Waspada)"
#         else:
#             score, reason = 1, f"Load {avg:.2f} <= 5.0 (Normal)"
#         if features.get('is_critical'):
#             score = min(score + 1, 10); reason += " | CRITICAL (+1)"
#         return score, map_score_to_level(score), reason
#     return 1, map_score_to_level(1), "Pola USSD tidak terdeteksi"
# -----------------------------------------------------------------------------


# ============================================================
# STREAM 4: CRM (Aturan C-01 s.d C-04) - NEGATIVE WEIGHTING
# ============================================================
# Pemicu: Router M-04 (mendeteksi "DOWN" + host mengandung "omni"/"crm")
# Logika Skor: R-CRM-01 (DOWN + Legacy -> skor 0 / Diabaikan)
# ============================================================

def extract_crm_features(text: str) -> Dict[str, Any]:
    """
    Scanner + Parser untuk CRM.
    Mengekstrak: service, hostname, status down, dan flag legacy.
    """
    features = {
        'stream': 'CRM',
        'service': None,
        'is_down': False,
        'hostname': None,
        'is_legacy': False,
        'raw_text': text
    }

    # Aturan C-2: Ekstrak nama service (contoh: agent-desktop3)
    svc = re.search(r'^\s*([\w\-]+)\s+in\s+', text, re.IGNORECASE)
    if svc:
        features['service'] = svc.group(1)

    # Aturan C-4: Deteksi status DOWN
    if re.search(r'\bDOWN\b', text, re.IGNORECASE):
        features['is_down'] = True

    # Aturan C-3: Ekstrak hostname dan cek apakah mengandung "omni" atau "crm"
    host_match = re.search(r'\bin\s+([a-zA-Z0-9]+)', text, re.IGNORECASE)
    if host_match:
        hostname = host_match.group(1)
        features['hostname'] = hostname
        if re.search(r'omni|crm', hostname, re.IGNORECASE):
            features['is_legacy'] = True

    return features


def score_crm(features: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluator untuk CRM (VERSI BARU - skor + jawaban pakar).
    Logika skor SAMA dengan versi lama (legacy DOWN -> diabaikan).

    CATATAN INKONSISTENSI UNTUK TESIS:
    Kode memberi skor 0 untuk alert yang diabaikan, sedangkan dokumen
    Aturan Produksi Anda menyebut skor 1. Pilih SATU dan samakan di
    tesis. Versi ini mempertahankan perilaku lama (skor 0, level DIABAIKAN).
    """
    is_down = features.get('is_down', False)
    is_legacy = features.get('is_legacy', False)
    hostname = features.get('hostname', 'unknown')
    svc = features.get('service') or 'service'

    # R-CRM-01: Jika DOWN dan Legacy, beri skor 0 (diabaikan)
    if is_down and is_legacy:
        return {
            'score': 0,
            'level': "\u26AA DIABAIKAN",
            'reason': f"DOWN pada sistem legacy ({hostname}) -> Negative Weighting, skor 0",
            'diagnosis': (f"{svc} pada {hostname} berstatus DOWN, namun host tergolong legacy/OMNI yang "
                          f"sudah tidak relevan (kemungkinan besar false positive)."),
            'rekomendasi': ("Tidak perlu eskalasi. Cukup dicatat untuk pemantauan tren dan disembunyikan dari "
                            "dashboard utama. Tinjau konfigurasi monitoring agar berhenti memicu alert."),
            'tim_eskalasi': "\u2014 (di-suppress)",
        }

    # Jika DOWN tapi bukan legacy, tetap waspada (skor 7)
    if is_down:
        return {
            'score': 7,
            'level': map_score_to_level(7),
            'reason': f"DOWN pada sistem {hostname} (non-legacy)",
            'diagnosis': f"{svc} pada {hostname} berstatus DOWN (non-legacy) \u2014 perlu diperiksa.",
            'rekomendasi': "Verifikasi ketersediaan layanan; bila benar gangguan, eskalasi ke tim pemilik layanan.",
            'tim_eskalasi': "Tim pemilik layanan (verifikasi)",  # [VERIFIKASI]
        }

    return {
        'score': 1,
        'level': map_score_to_level(1),
        'reason': "Tidak ada indikasi masalah",
        'diagnosis': "Tidak ada indikasi gangguan dari teks.",
        'rekomendasi': "Tidak perlu tindakan.",
        'tim_eskalasi': "\u2014",
    }

# --- VERSI LAMA (ARSIP) score_crm --------------------------------------------
# def score_crm(features):
#     is_down = features.get('is_down', False)
#     is_legacy = features.get('is_legacy', False)
#     hostname = features.get('hostname', 'unknown')
#     if is_down and is_legacy:
#         return 0, "\u26AA DIABAIKAN", f"DOWN pada sistem legacy ({hostname}) -> Negative Weighting, skor 0"
#     if is_down:
#         return 7, map_score_to_level(7), f"DOWN pada sistem {hostname} (non-legacy)"
#     return 1, map_score_to_level(1), "Tidak ada indikasi masalah"
# -----------------------------------------------------------------------------


# ============================================================
# ROUTER UTAMA (M-01 s.d M-05) - TIDAK DIUBAH
# ============================================================

def detect_stream(text: str) -> str:
    """
    Menerapkan Router M-01 s.d M-05.
    Menentukan jenis stream berdasarkan kata kunci pemicu.
    """
    t = text.lower()

    # M-03: Prioritas BWCE (dicek lebih dulu agar tidak tertukar dengan NGSSP)
    if 'sr:' in t or 'success:' in t:
        return 'BWCE'

    # M-02: NGSSP
    if 'stuck thread' in t or 'node exporter' in t or 'with val:' in t:
        return 'NGSSP'

    # M-05: USSD (deteksi field bernomor atau frasa proses mati)
    if 'not running' in t or re.search(r'\d\s*:-\s*\S', text) or 'load average' in t:
        return 'USSD'

    # M-04: CRM (deteksi DOWN pada host legacy omni/crm)
    # CATATAN: 'down' di sini cocok sebagai substring (mis. bisa kena 'shutdown').
    #          Dibiarkan SAMA dengan versi lama agar perilaku tidak berubah.
    if 'down' in t and ('omni' in t or 'crm' in t):
        return 'CRM'

    # Tidak ada pola yang cocok
    return 'UNKNOWN'


def process_alert(text: str) -> Dict[str, Any]:
    """
    Proses utama (Scanner -> Parser -> Translator -> Evaluator).
    Menerima teks alert mentah, mengembalikan dictionary hasil analisis.

    VERSI BARU: hasil kini menyertakan diagnosis, rekomendasi, dan tim_eskalasi.
    Kunci lama (stream, score, level, reason, features, raw_text) tetap ada,
    sehingga chatbot.py dan app.py yang lama tidak rusak.
    """
    stream = detect_stream(text)

    extractors = {
        'BWCE': extract_bwce_features,
        'NGSSP': extract_ngssp_features,
        'USSD': extract_ussd_features,
        'CRM': extract_crm_features
    }
    scorers = {
        'BWCE': score_bwce,
        'NGSSP': score_ngssp,
        'USSD': score_ussd,
        'CRM': score_crm
    }

    # Jika stream tidak dikenali
    if stream == 'UNKNOWN':
        return {
            'stream': 'UNKNOWN',
            'score': 0,
            'level': '\u26AA TIDAK DIKENAL',
            'reason': 'Stream tidak dapat diidentifikasi',
            'diagnosis': 'Teks tidak cocok dengan pola alert mana pun yang dikenal.',
            'rekomendasi': 'Periksa format teks; bila ini alert baru, tambahkan aturan produksinya.',
            'tim_eskalasi': 'OCC (verifikasi manual)',
            'features': {},
            'raw_text': text
        }

    # Eksekusi Parser (Ekstraksi Fitur) -> Translator + Evaluator (Skoring)
    features = extractors[stream](text)
    ev = scorers[stream](features)  # dict: score, level, reason, diagnosis, rekomendasi, tim_eskalasi

    return {
        'stream': stream,
        'score': ev['score'],
        'level': ev['level'],
        'reason': ev['reason'],
        'diagnosis': ev['diagnosis'],
        'rekomendasi': ev['rekomendasi'],
        'tim_eskalasi': ev['tim_eskalasi'],
        'features': features,
        'raw_text': text
    }

# --- VERSI LAMA (ARSIP) process_alert ----------------------------------------
# def process_alert(text):
#     stream = detect_stream(text)
#     extractors = {'BWCE': extract_bwce_features, 'NGSSP': extract_ngssp_features,
#                   'USSD': extract_ussd_features, 'CRM': extract_crm_features}
#     scorers = {'BWCE': score_bwce, 'NGSSP': score_ngssp,
#                'USSD': score_ussd, 'CRM': score_crm}
#     if stream == 'UNKNOWN':
#         return {'stream': 'UNKNOWN', 'score': 0, 'level': '\u26AA TIDAK DIKENAL',
#                 'reason': 'Stream tidak dapat diidentifikasi', 'features': {}, 'raw_text': text}
#     features = extractors[stream](text)
#     score, level, reason = scorers[stream](features)   # versi lama: scorer mengembalikan tuple
#     return {'stream': stream, 'score': score, 'level': level,
#             'reason': reason, 'features': features, 'raw_text': text}
# -----------------------------------------------------------------------------


def process_alerts_batch(alerts: list) -> list:
    """Memproses banyak alert sekaligus (untuk batch testing)."""
    return [process_alert(a) for a in alerts]


# ============================================================
# DEMO / TESTING (Jika file dijalankan langsung)
# ============================================================

if __name__ == "__main__":
    print("=" * 70)
    print("DEMO EKSEKUSI RULES.PY (VERSI SISTEM PAKAR: SKOR + JAWABAN)")
    print("=" * 70)

    # Sampel alert dari dokumen Aturan Produksi
    sample_alerts = [
        # NGSSP (val=0 -> DOWN)
        "MMOlZMsWz|RVS SOAD10 - Node Exporter Status ~ xptrvssoa127:9092 with val: 0, Issue start at: 2024-11-13T23:49:00.000+07:00, Pls inform middleware Team!",

        # BWCE (SR 0.00% + Degraded)
        "BWCE bi-air-update - Total: 1697, Success: 0, BE: 0, TE: 0, Undefined: 1697, SR: 0.00% - TE Info: No Error | Snapshot date 26/08/2025 00:10 BWCE SR Degraded, ngssp/vas team pls check!",

        # CRM (Legacy DOWN -> skor 0)
        "agent-desktop3 in jktmmpvomnilad01 DOWN",

        # USSD (Process not running)
        "2:- Billing_3 3:- XPTPSDPPROV03 4 :- 10.49.73.91 5 :- CRITICAL 6 :- Wed May 13 00:20:12 WIB 2026 7 :- CRITICAL - Process is not running!"
    ]

    for i, alert in enumerate(sample_alerts, 1):
        result = process_alert(alert)
        print(f"\n--- SAMPLE {i} ---")
        print(f"Stream      : {result['stream']}")
        print(f"Skor        : {result['score']} / 10")
        print(f"Level       : {result['level']}")
        print(f"Alasan      : {result['reason']}")
        print(f"Diagnosis   : {result['diagnosis']}")
        print(f"Rekomendasi : {result['rekomendasi']}")
        print(f"Eskalasi ke : {result['tim_eskalasi']}")
        print(f"Raw Text    : {alert[:80]}...")