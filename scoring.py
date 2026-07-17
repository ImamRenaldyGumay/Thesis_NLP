"""
scoring.py

Lapisan Pembobotan (Weighting) dan Skoring Kepercayaan
untuk engine Rule-Based NLP pada teks alert OCC.

Latar belakang
--------------
Pada engine dasar (rules.py), sebuah aturan produksi bersifat
boolean: seluruh kondisi harus terpenuhi (AND) agar aturan aktif.
Model tidak memberi tahu seberapa "kuat" bukti yang mendukung
sebuah pembacaan.

Modul ini menambahkan skema pembobotan (certainty factor sederhana)
pada NLP. Setiap aturan produksi dipecah menjadi beberapa
kondisi/fitur leksikal, dan setiap fitur diberi BOBOT.
Skor kepercayaan sebuah aturan dihitung sebagai:

    skor(R) = Σ  bobot(fitur_i)   untuk fitur yang TERPENUHI
              ----------------------------------------------
              Σ  bobot(fitur_i)   untuk seluruh fitur aturan R

Nilai skor berada pada rentang 0..1 (0%..100%).

Fitur PEMICU UTAMA (misalnya "Process is not running",
"val=0", "status DOWN") diberi bobot terbesar karena menjadi
penentu aturan. Fitur PENDUKUNG / KONTEKS (host, error_count,
service name, dsb.) diberi bobot lebih kecil; kehadirannya
menaikkan keyakinan, ketidakhadirannya menurunkan keyakinan
tanpa membatalkan aturan.

Manfaat
-------
1. Setiap pembacaan alert memiliki SKOR KEPERCAYAAN (confidence),
   sehingga hasil model dapat diranking / diprioritaskan.
2. Untuk alert yang tidak memenuhi aturan apa pun (UNKNOWN),
   modul tetap menghitung "aturan terdekat" beserta skor
   parsialnya, berguna untuk verifikasi manual.
3. Skor dapat dijadikan bahan pengujian: membandingkan tingkat
   keyakinan pada prediksi yang benar vs salah.
"""

from typing import Dict, Any, List


# ============================================================
# TABEL BOBOT FITUR PER ATURAN PRODUKSI
# ============================================================
#
# Setiap fitur berupa (nama_fitur, fungsi_cek, bobot).
# fungsi_cek menerima dict fakta {PREDIKAT: nilai} dan
# mengembalikan True/False.
#
# Jumlah bobot per aturan = 1.0 (dinormalisasi otomatis
# jika tidak tepat 1.0).
# ============================================================


def _f(facts_dict: Dict[str, Any], key: str, default=None):
    """Ambil nilai fakta berdasarkan predikat (uppercase)."""
    return facts_dict.get(key, default)


def _ambang_stuck_thread() -> float:
    """
    Mengambil ambang batas stuck thread dari rules.py.
    Import di dalam fungsi, alasannya sama dengan _ambang_cpu().
    """
    from rules import AMBANG_STUCK_THREAD

    return AMBANG_STUCK_THREAD


def _ambang_cpu() -> float:
    """
    Mengambil ambang batas CPU dari rules.py.

    Import sengaja dilakukan di DALAM fungsi, bukan di kepala
    modul, karena rules.py sudah mengimpor modul ini. Import di
    kepala modul akan menimbulkan circular import.
    """
    from rules import AMBANG_CPU_TINGGI

    return AMBANG_CPU_TINGGI


RULE_FEATURE_WEIGHTS = {

    # --------------------------------------------------------
    # R-BWCE-01 : SR Degraded + Technical Error
    # --------------------------------------------------------
    "R-BWCE-01": [
        (
            "Flag SR Degraded terdeteksi",
            lambda f: _f(f, "SR_DEGRADED") is True,
            0.40,
        ),
        (
            "Technical Error > 0",
            lambda f: isinstance(_f(f, "TE"), (int, float))
            and _f(f, "TE") > 0,
            0.30,
        ),
        (
            "Business Error = 0",
            lambda f: _f(f, "BE") == 0,
            0.15,
        ),
        (
            "Undefined Error = 0",
            lambda f: _f(f, "UNDEFINED") == 0,
            0.15,
        ),
    ],

    # --------------------------------------------------------
    # R-NGSSP-01 : Node Exporter Status val=0
    # --------------------------------------------------------
    "R-NGSSP-01": [
        (
            "Metric = Node Exporter Status",
            lambda f: _f(f, "METRIC_CODE") == "NODE_EXPORTER_STATUS",
            0.55,
        ),
        (
            "Nilai val = 0",
            lambda f: _f(f, "VALUE") == 0,
            0.45,
        ),
    ],

    # --------------------------------------------------------
    # R-NGSSP-02 : JVM Managed Server Status val=0
    # --------------------------------------------------------
    "R-NGSSP-02": [
        (
            "Metric = JVM Managed Server Status",
            lambda f: _f(f, "METRIC_CODE") == "JVM_MANAGED_SERVER_STATUS",
            0.55,
        ),
        (
            "Nilai val = 0",
            lambda f: _f(f, "VALUE") == 0,
            0.45,
        ),
    ],

    # --------------------------------------------------------
    # R-NGSSP-03 : CPU Utilization melampaui ambang batas
    # --------------------------------------------------------
    "R-NGSSP-03": [
        (
            "Metric = CPU Utilization",
            lambda f: _f(f, "METRIC_CODE") == "CPU_UTILIZATION",
            0.55,
        ),
        (
            "Nilai val mencapai/melampaui ambang batas",
            lambda f: isinstance(_f(f, "VALUE"), (int, float))
            and _f(f, "VALUE") >= _ambang_cpu(),
            0.45,
        ),
    ],

    # --------------------------------------------------------
    # R-NGSSP-04 : Stuck Thread melampaui ambang batas
    # --------------------------------------------------------
    "R-NGSSP-04": [
        (
            "Metric = Stuck Thread",
            lambda f: _f(f, "METRIC_CODE") == "STUCK_THREAD",
            0.55,
        ),
        (
            "Jumlah stuck thread mencapai/melampaui ambang batas",
            lambda f: isinstance(_f(f, "VALUE"), (int, float))
            and _f(f, "VALUE") >= _ambang_stuck_thread(),
            0.45,
        ),
    ],

    # --------------------------------------------------------
    # R-USSD-01 : Process is not running
    # --------------------------------------------------------
    "R-USSD-01": [
        (
            "Pola 'Process is not running'",
            lambda f: _f(f, "DETAIL_CODE") == "PROCESS_NOT_RUNNING",
            0.70,
        ),
        (
            "Nama pemeriksaan/proses terekstraksi",
            lambda f: bool(_f(f, "CHECK")),
            0.15,
        ),
        (
            "Host terekstraksi",
            lambda f: bool(_f(f, "HOST")),
            0.15,
        ),
    ],

    # --------------------------------------------------------
    # R-USSD-02 : Errors found
    # --------------------------------------------------------
    "R-USSD-02": [
        (
            "Pola 'Errors found'",
            lambda f: _f(f, "DETAIL_CODE") == "ERRORS_FOUND",
            0.70,
        ),
        (
            "Jumlah error (occured=) terekstraksi",
            lambda f: _f(f, "ERROR_COUNT") is not None,
            0.20,
        ),
        (
            "Nama pemeriksaan/proses terekstraksi",
            lambda f: bool(_f(f, "CHECK")),
            0.10,
        ),
    ],

    # --------------------------------------------------------
    # R-CRM-01 : Service DOWN
    # --------------------------------------------------------
    "R-CRM-01": [
        (
            "Status service = DOWN",
            lambda f: _f(f, "STATUS") == "DOWN",
            0.70,
        ),
        (
            "Nama service terekstraksi",
            lambda f: bool(_f(f, "SERVICE")),
            0.15,
        ),
        (
            "Hostname terekstraksi",
            lambda f: bool(_f(f, "HOSTNAME")),
            0.15,
        ),
    ],
}


# Aturan yang menjadi kandidat untuk tiap stream.
STREAM_RULES = {
    "BWCE": ["R-BWCE-01"],
    "NGSSP": [
        "R-NGSSP-01",
        "R-NGSSP-02",
        "R-NGSSP-03",
        "R-NGSSP-04",
    ],
    "USSD": ["R-USSD-01", "R-USSD-02"],
    "CRM": ["R-CRM-01"],
}


# ============================================================
# PERHITUNGAN SKOR
# ============================================================

def _facts_to_dict(facts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Ubah list fakta menjadi dict {PREDIKAT: nilai}."""
    result = {}
    for fact in facts:
        result[fact["predicate"]] = fact["value"]
    return result


def score_rule(rule_id: str, facts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Menghitung skor kepercayaan satu aturan produksi terhadap
    kumpulan fakta.

    Return:
        {
            "rule": rule_id,
            "skor": float 0..1,
            "fitur_terpenuhi": [...],
            "fitur_tidak_terpenuhi": [...],
        }
    """
    features = RULE_FEATURE_WEIGHTS.get(rule_id, [])
    facts_dict = _facts_to_dict(facts)

    total_weight = sum(w for _, _, w in features) or 1.0
    gained = 0.0

    terpenuhi = []
    tidak = []

    for name, check, weight in features:
        try:
            ok = bool(check(facts_dict))
        except Exception:
            ok = False

        if ok:
            gained += weight
            terpenuhi.append((name, round(weight, 3)))
        else:
            tidak.append((name, round(weight, 3)))

    skor = round(gained / total_weight, 4)

    return {
        "rule": rule_id,
        "skor": skor,
        "fitur_terpenuhi": terpenuhi,
        "fitur_tidak_terpenuhi": tidak,
    }


def compute_scores(
    stream: str,
    facts: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Menghitung skor untuk seluruh aturan kandidat pada stream.
    Jika stream tidak dikenal, seluruh aturan diuji.
    Hasil diurutkan menurun berdasarkan skor.
    """
    if stream in STREAM_RULES:
        candidate_rules = STREAM_RULES[stream]
    else:
        candidate_rules = list(RULE_FEATURE_WEIGHTS.keys())

    scores = [score_rule(rid, facts) for rid in candidate_rules]
    scores.sort(key=lambda s: s["skor"], reverse=True)
    return scores


def score_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Menempelkan hasil pembobotan pada output process_alert().

    Menambahkan field:
        - skor_kepercayaan   : skor aturan yang aktif (0..1)
        - persen_kepercayaan : skor dalam persen (string)
        - skor_rule_terbaik  : aturan dengan skor tertinggi
        - skor_rincian       : daftar skor seluruh aturan kandidat
    """
    stream = result.get("stream", "UNKNOWN")
    facts = result.get("facts", [])
    aturan_aktif = result.get("aturan_aktif", [])

    rincian = compute_scores(stream, facts)

    # Skor aturan yang benar-benar aktif (jika ada).
    if aturan_aktif:
        active_rule = aturan_aktif[0]
        active_score = next(
            (s["skor"] for s in rincian if s["rule"] == active_rule),
            0.0,
        )
        skor_kepercayaan = active_score
        rule_terbaik = active_rule
    else:
        # Tidak ada aturan aktif: laporkan aturan terdekat
        # (skor parsial tertinggi) untuk keperluan verifikasi.
        if rincian:
            skor_kepercayaan = rincian[0]["skor"]
            rule_terbaik = rincian[0]["rule"]
        else:
            skor_kepercayaan = 0.0
            rule_terbaik = None

    result["skor_kepercayaan"] = skor_kepercayaan
    result["persen_kepercayaan"] = f"{skor_kepercayaan * 100:.1f}%"
    result["skor_rule_terbaik"] = rule_terbaik
    result["skor_rincian"] = rincian

    return result