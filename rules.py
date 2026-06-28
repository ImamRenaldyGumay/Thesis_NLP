import re
from datetime import datetime
from typing import Dict, Tuple

# ============================================================
# REFERENSI ATURAN PRODUKSI (DARI DOKUMEN TESIS)
# ============================================================
# M-01 s.d M-05 : Router Utama (Klasifikasi Tipe Input)
# B-01 s.d B-10 : Aturan BWCE (Performa Bisnis)
# N-01 s.d N-11 : Aturan NGSSP (Middleware)
# U-01 s.d U-09 : Aturan USSD (Process)
# C-01 s.d C-04 : Aturan CRM (Legacy / Negative Weighting)
# ============================================================


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


# ============================================================
# STREAM 1: BWCE (Aturan B-01 s.d B-10)
# ============================================================
# Pemicu: Router M-03 (mendeteksi kata "SR:" atau "Success:")
# Logika Skor: B-01 s.d B-04 (SR < 98.5 -> 10, TE > 20 +2, Degraded +1)
# ============================================================

def extract_bwce_features(text: str) -> Dict[str, any]:
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


def score_bwce(features: Dict[str, any]) -> Tuple[int, str, str]:
    """
    Evaluator untuk BWCE.
    Menerapkan R-BWCE-01 s.d R-BWCE-04.
    """
    sr = features.get('sr')
    te = features.get('te') or 0
    has_degraded = features.get('has_degraded', False)

    # R-BWCE-01 & R-BWCE-02: Penentuan Skor Dasar berdasarkan SR
    if sr is None:
        score, reason = 3, "SR tidak terdeteksi"
    elif sr < 98.5:
        score, reason = 10, f"SR {sr}% < 98.5% (Kritis)"
    elif sr < 99.5:
        score, reason = 7, f"SR {sr}% antara 98.5-99.5% (Waspada)"
    else:
        score, reason = 3, f"SR {sr}% >= 99.5% (Normal)"

    # R-BWCE-03: Jika TE > 20, tambah 2 poin (tapi maksimal 10)
    if te > 20:
        score = min(score + 2, 10)
        reason += f" | TE {te} > 20 (+2)"

    # R-BWCE-04: Jika ada frasa "SR Degraded", tambah 1 poin
    if has_degraded:
        score = min(score + 1, 10)
        reason += " | SR Degraded (+1)"

    return score, map_score_to_level(score), reason


# ============================================================
# STREAM 2: NGSSP (Aturan N-01 s.d N-11)
# ============================================================
# Pemicu: Router M-02 (mendeteksi "val:", "stuck thread", "node exporter")
# Logika Skor: R-NGS-01 s.d R-NGS-03 (val=0 -> down, val>100 -> kritis, durasi+2)
# ============================================================

def extract_ngssp_features(text: str) -> Dict[str, any]:
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

    # Aturan N-09: Ekstrak waktu mulai (issue start)
    time_match = re.search(r'Issue start at:?\s*([\d\-T:]+)', text, re.IGNORECASE)
    if time_match:
        features['issue_start'] = time_match.group(1)

    return features


def score_ngssp(features: Dict[str, any]) -> Tuple[int, str, str]:
    """
    Evaluator untuk NGSSP.
    Menerapkan R-NGS-01 s.d R-NGS-03.
    """
    val = features.get('val')
    issue_start = features.get('issue_start')
    is_node = features.get('is_node_exporter', False)

    # R-NGS-01 & Penanganan Khusus: val=0 pada Node Exporter = DOWN Total
    if val == 0 and is_node:
        score, reason = 9, "val=0 -> Node Exporter DOWN (Kritis)"
    elif val is None:
        score, reason = 2, "Nilai val tidak terdeteksi"
    elif val > 100:
        score, reason = 9, f"val {val} > 100 (Kritis - Thread Macet)"
    elif val > 50:
        score, reason = 6, f"val {val} antara 50-100 (Waspada)"
    else:
        score, reason = 2, f"val {val} <= 50 (Normal)"

    # R-NGS-03: Jika durasi > 30 menit, tambah 2 poin
    if issue_start:
        try:
            clean = issue_start.replace('T', ' ').split('.')[0]
            start_time = datetime.fromisoformat(clean)
            duration = (datetime.now() - start_time).total_seconds() / 60
            if duration > 30:
                score = min(score + 2, 10)
                reason += f" | Durasi {duration:.0f} menit > 30 (+2)"
        except Exception:
            pass

    return score, map_score_to_level(score), reason


# ============================================================
# STREAM 3: USSD (Aturan U-01 s.d U-09)
# ============================================================
# Pemicu: Router M-05 (mendeteksi "2:-" atau "not running")
# Logika Skor: R-USD-01 s.d R-USD-03 (process_down -> 9, CRITICAL +1, Core +1)
# ============================================================

def extract_ussd_features(text: str) -> Dict[str, any]:
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


def score_ussd(features: Dict[str, any]) -> Tuple[int, str, str]:
    """
    Evaluator untuk USSD.
    Menerapkan R-USD-01 s.d R-USD-03.
    """
    # R-USD-01: Prioritas utama -> Proses Mati
    if features.get('process_down'):
        score, reason = 9, "Process is not running (proses mati)"
        
        # R-USD-02: Jika severity CRITICAL, +1
        if features.get('is_critical'):
            score = min(score + 1, 10)
            reason += " | CRITICAL (+1)"
        
        # R-USD-03: Jika service adalah layanan inti (Billing/CDR/SDP), +1
        svc = (features.get('service') or '').lower()
        if any(k in svc for k in ('billing', 'cdr', 'sdp')):
            score = min(score + 1, 10)
            reason += " | layanan inti (+1)"
        
        return score, map_score_to_level(score), reason

    # Fallback: Jika bukan proses mati, cek apakah ada format load-average
    avg = features.get('avg_load')
    if avg is not None:
        if avg > 8.0:
            score, reason = 10, f"Load {avg:.2f} > 8.0 (Darurat)"
        elif avg > 5.0:
            score, reason = 6, f"Load {avg:.2f} antara 5.0-8.0 (Waspada)"
        else:
            score, reason = 1, f"Load {avg:.2f} <= 5.0 (Normal)"
        
        if features.get('is_critical'):
            score = min(score + 1, 10)
            reason += " | CRITICAL (+1)"
        return score, map_score_to_level(score), reason

    return 1, map_score_to_level(1), "Pola USSD tidak terdeteksi"


# ============================================================
# STREAM 4: CRM (Aturan C-01 s.d C-04) - NEGATIVE WEIGHTING
# ============================================================
# Pemicu: Router M-04 (mendeteksi "DOWN" + host mengandung "omni"/"crm")
# Logika Skor: R-CRM-01 (DOWN + Legacy -> skor 0 / Diabaikan)
# ============================================================

def extract_crm_features(text: str) -> Dict[str, any]:
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


def score_crm(features: Dict[str, any]) -> Tuple[int, str, str]:
    """
    Evaluator untuk CRM.
    Menerapkan R-CRM-01 (Negative Weighting).
    """
    is_down = features.get('is_down', False)
    is_legacy = features.get('is_legacy', False)
    hostname = features.get('hostname', 'unknown')

    # R-CRM-01: Jika DOWN dan Legacy, beri skor 0 (diabaikan)
    if is_down and is_legacy:
        return 0, "\u26AA DIABAIKAN", f"DOWN pada sistem legacy ({hostname}) -> Negative Weighting, skor 0"
    
    # Jika DOWN tapi bukan legacy, tetap waspada (skor 7)
    if is_down:
        return 7, map_score_to_level(7), f"DOWN pada sistem {hostname} (non-legacy)"
    
    return 1, map_score_to_level(1), "Tidak ada indikasi masalah"


# ============================================================
# ROUTER UTAMA (M-01 s.d M-05)
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
    if 'down' in t and ('omni' in t or 'crm' in t):
        return 'CRM'
    
    # Tidak ada pola yang cocok
    return 'UNKNOWN'


def process_alert(text: str) -> Dict[str, any]:
    """
    Proses utama (Scanner -> Parser -> Translator -> Evaluator).
    Menerima teks alert mentah, mengembalikan dictionary hasil analisis.
    """
    stream = detect_stream(text)

    # Peta extractor dan scorer sesuai stream
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
            'features': {}, 
            'raw_text': text
        }

    # Eksekusi Parser (Ekstraksi Fitur) -> Translator + Evaluator (Skoring)
    features = extractors[stream](text)
    score, level, reason = scorers[stream](features)

    return {
        'stream': stream, 
        'score': score, 
        'level': level,
        'reason': reason, 
        'features': features, 
        'raw_text': text
    }


def process_alerts_batch(alerts: list) -> list:
    """Memproses banyak alert sekaligus (untuk batch testing)."""
    return [process_alert(a) for a in alerts]


# ============================================================
# DEMO / TESTING (Jika file dijalankan langsung)
# ============================================================

if __name__ == "__main__":
    print("=" * 70)
    print("DEMO EKSEKUSI RULES.PY (BERDASARKAN 4 SAMPEL DOKUMEN)")
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
        print(f"Stream   : {result['stream']}")
        print(f"Skor     : {result['score']} / 10")
        print(f"Level    : {result['level']}")
        print(f"Alasan   : {result['reason']}")
        print(f"Raw Text : {alert[:80]}...")