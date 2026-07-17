"""
rules.py
Engine Rule-Based Natural Language Processing untuk
Ekstraksi Informasi dan Penyajian Rekomendasi Tindakan
dari Teks Alert pada Operation Command Center.

Pipeline:
    Input Alert
        -> Detect Stream
        -> Scanner
        -> Parser
        -> Translator
        -> Evaluator (Production Rules)
        -> Output

Basis Aturan Produksi:
    R-BWCE-01  : SR Degraded + Technical Error
    R-BWCE-02  : SR Degraded dengan TE > 0 disertai BE > 0
                 dan/atau Undefined > 0 (error campuran)
    R-NGSSP-01 : Node Exporter Status dengan val = 0
    R-NGSSP-02 : JVM Managed Server Status dengan val = 0
    R-NGSSP-03 : CPU Utilization dengan val >= ambang batas
    R-NGSSP-04 : Stuck Thread dengan val >= ambang batas
    R-USSD-01  : Process is not running
    R-USSD-02  : Errors found
    R-USSD-03  : PROCS CRITICAL (jumlah proses tidak wajar)
    R-USSD-04  : MEMORY CRITICAL (penggunaan memori kritis)
    R-USSD-05  : DISK CRITICAL (kapasitas partisi kritis)
    R-CRM-01   : Service DOWN

Output utama:
    - stream
    - hasil_pembacaan
    - alasan_pembacaan
    - rekomendasi
    - tim_terkait
    - aturan_aktif

Output pipeline:
    - tokens
    - parsed_data
    - facts

Kompatibilitas project lama:
    - condition
    - diagnosis
    - features
"""

import re
from typing import Dict, Any, List, Optional

from scoring import score_result


# ============================================================
# AMBANG BATAS METRIC BERSKALA
# ============================================================
#
# Metric NGSSP terbagi dua jenis:
#
#   1. BINER  - Node Exporter Status, JVM Managed Server Status.
#               Nilai val=0 berarti tidak tersedia. Aturannya
#               membandingkan nilai dengan nol (R-NGSSP-01/02).
#
#   2. BERSKALA - CPU Utilization (rentang 0-100 persen).
#               Nilai 0 justru berarti normal, sehingga aturannya
#               TIDAK boleh membandingkan dengan nol, melainkan
#               dengan sebuah AMBANG BATAS (threshold).
#
# PERHATIAN
# ---------
# Nilai di bawah ini masih berupa ASUMSI dan WAJIB disesuaikan
# dengan standar ambang batas yang benar-benar berlaku di OCC
# (lihat konfigurasi alerting pada Grafana atau dokumen SOP).
# Nilai ambang merupakan ketentuan operasional, bukan sesuatu
# yang dapat disimpulkan dari teks alert semata, dan perlu
# dicantumkan sumbernya di dalam naskah.

AMBANG_CPU_TINGGI = 80.0

# Stuck thread merupakan metric BERSKALA berupa CACAH (jumlah
# thread yang macet), bukan persentase. Nilai 0 berarti normal.
#
# PERHATIAN: sama seperti ambang CPU, angka di bawah ini WAJIB
# disesuaikan dengan standar yang berlaku di OCC. Nilai 1 dipakai
# sebagai default karena satu stuck thread pun secara umum sudah
# menandakan adanya masalah, sehingga bersifat konservatif
# (menangkap seluruh kejadian).

AMBANG_STUCK_THREAD = 1

# Ambang persentase ruang TERPAKAI yang dianggap bermasalah pada
# pemeriksaan disk USSD.
#
# Catatan penting: ambang ini TIDAK dipakai untuk memutuskan
# apakah alert bersifat kritis - keputusan itu sudah diambil oleh
# sistem pemantauan dan tertulis pada detail alert. Ambang ini
# hanya dipakai untuk MENUNJUK partisi mana yang bermasalah,
# karena satu alert disk memuat banyak partisi sekaligus.
#
# Karena perannya sekadar penunjuk, ketidaktepatan kecil pada
# nilai ini tidak membuat pembacaan alert menjadi salah. Meski
# begitu, nilainya tetap sebaiknya disesuaikan dengan standar OCC.

AMBANG_DISK_TERPAKAI = 80.0


# ============================================================
# STREAM INFORMATION
# ============================================================

STREAM_INFO = {
    "BWCE": {
        "nama": "Performa Transaksi Bisnis",
        "tim_default": "NGSSP/VAS Team",
    },
    "NGSSP": {
        "nama": "Middleware",
        "tim_default": "Middleware/NGSSP Team",
    },
    "USSD": {
        "nama": "Ketersediaan Proses Layanan",
        "tim_default": "Tim Pemilik Layanan",
    },
    "CRM": {
        "nama": "Ketersediaan Layanan OMNI",
        "tim_default": "Tim Pemilik Layanan OMNI",
    },
}


# ============================================================
# UTILITY
# ============================================================

def _to_number(value: Optional[str]):
    """Mengubah string numerik menjadi int atau float."""

    if value is None:
        return None

    # Buang pemisah ribuan sebelum konversi, mis. "1,828" -> 1828.
    if isinstance(value, str):
        value = value.replace(",", "")

    try:
        number = float(value)

        if number.is_integer():
            return int(number)

        return number

    except (TypeError, ValueError):
        return None


def _extract_team(text: str) -> Optional[str]:
    """Mengekstrak nama tim dari teks alert."""

    patterns = [
        r"inform\s+([\w/\-]+)\s+team",
        r"([\w/\-]+)\s+team\s+pls",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            return f"{match.group(1).upper()} Team"

    return None


def _lexeme(token_type: str, value: Any) -> Dict[str, Any]:
    """Membentuk token hasil Scanner."""

    return {
        "type": token_type,
        "value": value,
    }


def get_fact(
    facts: List[Dict[str, Any]],
    predicate: str,
    default=None,
):
    """Mengambil nilai fakta berdasarkan predicate."""

    for fact in facts:
        if fact["predicate"] == predicate:
            return fact["value"]

    return default


# ============================================================
# DETECT STREAM
# ============================================================

def detect_stream(text: str) -> str:
    """
    Menentukan stream alert berdasarkan pola teks aktual.
    """

    lowered = text.lower()

    # BWCE
    if (
        "total:" in lowered
        and "success:" in lowered
        and "sr:" in lowered
    ):
        return "BWCE"

    # NGSSP
    # Deteksi didasarkan pada STRUKTUR alert NGSSP, bukan pada
    # daftar nama metric tertentu. Seluruh alert NGSSP berpola:
    #
    #     <nama metric> ~ <komponen> with val: <nilai>,
    #     Issue start at: <waktu>
    #
    # Sebelumnya stream hanya dikenali bila metric-nya Node
    # Exporter Status atau JVM Managed Server Status, sehingga
    # metric lain (mis. CPU Utilization) terbaca UNKNOWN padahal
    # jelas merupakan alert NGSSP. Dengan mengenali strukturnya,
    # metric baru tetap terdeteksi sebagai NGSSP; bila belum ada
    # aturan produksi yang cocok, hasilnya "tidak ada aturan
    # aktif" (bukan UNKNOWN) sehingga celah aturan tetap terlihat.
    if (
        "with val:" in lowered
        and "issue start at:" in lowered
    ):
        return "NGSSP"

    # USSD
    if (
        re.search(r"2\s*:-", text)
        and re.search(r"3\s*:-", text)
        and re.search(r"5\s*:-", text)
        and re.search(r"7\s*:-", text)
    ):
        return "USSD"

    # CRM / OMNI
    if re.search(
        r"^\s*[\w\-]+\s+in\s+[\w\-]+\s+DOWN\s*$",
        text,
        re.IGNORECASE,
    ):
        return "CRM"

    return "UNKNOWN"


# ============================================================
# SCANNER
# ============================================================

def scanner(text: str, stream: str) -> Dict[str, Any]:
    """
    Scanner mengenali pola leksikal penting.

    Scanner hanya menghasilkan token.
    Scanner belum melakukan interpretasi alert.
    """

    tokens = {
        "stream": stream,
        "lexemes": [],
    }

    # --------------------------------------------------------
    # BWCE
    # --------------------------------------------------------

    if stream == "BWCE":

        # Pola bilangan bulat yang MENDUKUNG pemisah ribuan.
        # Sebelumnya dipakai [0-9]+ sehingga "Total: 1,828"
        # terbaca 1 (regex berhenti di koma) dan seluruh
        # pembacaan alert menjadi salah tanpa disadari.
        #
        # Alternatif pertama menangkap bilangan berpemisah
        # (1,828). Bila tidak cocok, alternatif kedua menangkap
        # bilangan biasa (828 atau 12345). Urutannya penting.
        BIL = r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)"

        patterns = {
            "APP": r"^\s*([\w\-]+)\s*-\s*Total\s*:",
            "TOTAL": r"Total:\s*" + BIL,
            "SUCCESS": r"Success:\s*" + BIL,
            "BE": r"BE:\s*" + BIL,
            "TE": r"TE:\s*" + BIL,
            "UNDEFINED": r"Undefined:\s*" + BIL,
            "SR": r"SR:\s*([0-9.]+)\s*%",
            "TE_INFO": r"TE Info:\s*(.*?)\s*\|",
        }

        for token_type, pattern in patterns.items():

            match = re.search(pattern, text, re.IGNORECASE)

            if match:
                tokens["lexemes"].append(
                    _lexeme(token_type, match.group(1).strip())
                )

        if re.search(r"\bSR\s+Degraded\b", text, re.IGNORECASE):
            tokens["lexemes"].append(
                _lexeme("SR_DEGRADED", True)
            )

    # --------------------------------------------------------
    # NGSSP
    # --------------------------------------------------------

    elif stream == "NGSSP":

        # Nama metric tidak lagi dibatasi pada daftar tertentu,
        # agar metric baru ikut terekstraksi. Pola yang dikenali:
        # "- <nama metric> [alert] ~".
        # Tanda hubung dikecualikan dari nama metric supaya regex
        # tidak salah menangkap bila terdapat tanda hubung lain
        # sebelum nama metric.
        metric_match = re.search(
            r"-\s*([^~\-]+?)(?:\s+alert)?\s*~",
            text,
            re.IGNORECASE,
        )

        if metric_match:
            tokens["lexemes"].append(
                _lexeme(
                    "METRIC",
                    metric_match.group(1).strip(),
                )
            )

        component_match = re.search(
            r"~\s*([^\s,]+)\s+with\s+val:",
            text,
            re.IGNORECASE,
        )

        if component_match:
            tokens["lexemes"].append(
                _lexeme(
                    "COMPONENT",
                    component_match.group(1).strip(),
                )
            )

        # Mendukung pemisah ribuan, mis. "with val: 1,234"
        # pada metric bertipe cacah seperti Stuck Thread.
        value_match = re.search(
            r"with\s+val:\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9.]+)",
            text,
            re.IGNORECASE,
        )

        if value_match:
            tokens["lexemes"].append(
                _lexeme(
                    "VALUE",
                    value_match.group(1),
                )
            )

        issue_match = re.search(
            r"Issue start at:\s*"
            r"([^,]+)",
            text,
            re.IGNORECASE,
        )

        if issue_match:
            tokens["lexemes"].append(
                _lexeme(
                    "ISSUE_START",
                    issue_match.group(1).strip(),
                )
            )

    # --------------------------------------------------------
    # USSD
    # --------------------------------------------------------

    elif stream == "USSD":

        patterns = {
            "CHECK": r"2\s*:-\s*(.*?)\s+3\s*:-",
            "HOST": r"3\s*:-\s*(.*?)\s+4\s*:-",
            "IP": r"4\s*:-\s*([0-9.]+)",
            "SEVERITY": r"5\s*:-\s*(\w+)",
            "TIMESTAMP": r"6\s*:-\s*(.*?)\s+7\s*:-",
            "DETAIL": r"7\s*:-\s*(.+)$",
        }

        for token_type, pattern in patterns.items():

            match = re.search(pattern, text, re.IGNORECASE)

            if match:
                tokens["lexemes"].append(
                    _lexeme(
                        token_type,
                        match.group(1).strip(),
                    )
                )

    # --------------------------------------------------------
    # CRM / OMNI
    # --------------------------------------------------------

    elif stream == "CRM":

        match = re.search(
            r"^\s*([\w\-]+)\s+in\s+([\w\-]+)\s+(DOWN)\s*$",
            text,
            re.IGNORECASE,
        )

        if match:

            tokens["lexemes"].extend([
                _lexeme(
                    "SERVICE",
                    match.group(1),
                ),
                _lexeme(
                    "HOSTNAME",
                    match.group(2),
                ),
                _lexeme(
                    "STATUS",
                    match.group(3).upper(),
                ),
            ])

    # --------------------------------------------------------
    # TEAM
    # --------------------------------------------------------

    team = _extract_team(text)

    if team:
        tokens["lexemes"].append(
            _lexeme("TEAM", team)
        )

    return tokens


# ============================================================
# PARSER
# ============================================================

def parser(scanner_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parser menyusun token hasil Scanner menjadi
    struktur informasi alert.
    """

    stream = scanner_result["stream"]

    parsed_data = {
        "stream": stream,
    }

    for lexeme in scanner_result.get("lexemes", []):

        key = lexeme["type"].lower()
        value = lexeme["value"]

        parsed_data[key] = value

    # Normalisasi numerik BWCE

    if stream == "BWCE":

        numeric_fields = [
            "total",
            "success",
            "be",
            "te",
            "undefined",
            "sr",
        ]

        for field in numeric_fields:
            parsed_data[field] = _to_number(
                parsed_data.get(field)
            )

        parsed_data["sr_degraded"] = bool(
            parsed_data.get("sr_degraded", False)
        )

    # Normalisasi numerik NGSSP

    elif stream == "NGSSP":

        parsed_data["value"] = _to_number(
            parsed_data.get("value")
        )

        metric = parsed_data.get("metric")

        if metric:
            metric_lower = metric.lower()

            if "node exporter" in metric_lower:
                parsed_data["metric_code"] = (
                    "NODE_EXPORTER_STATUS"
                )

            elif "jvm managed server" in metric_lower:
                parsed_data["metric_code"] = (
                    "JVM_MANAGED_SERVER_STATUS"
                )

            elif "cpu utilization" in metric_lower:
                parsed_data["metric_code"] = (
                    "CPU_UTILIZATION"
                )

            elif "stuck thread" in metric_lower:
                parsed_data["metric_code"] = (
                    "STUCK_THREAD"
                )

            else:
                # Metric NGSSP yang belum memiliki aturan produksi
                # tetap diberi kode agar terekam sebagai fakta.
                # Alert seperti ini akan menghasilkan "tidak ada
                # aturan aktif", sehingga celah aturan mudah
                # ditemukan saat pengujian.
                parsed_data["metric_code"] = re.sub(
                    r"[^A-Z0-9]+",
                    "_",
                    metric.upper(),
                ).strip("_")

    # Normalisasi USSD

    elif stream == "USSD":

        detail = parsed_data.get("detail", "")

        if re.search(
            r"Process\s+is\s+not\s+running",
            detail,
            re.IGNORECASE,
        ):
            parsed_data["detail_code"] = (
                "PROCESS_NOT_RUNNING"
            )

        elif re.search(
            r"Errors\s+found",
            detail,
            re.IGNORECASE,
        ):
            parsed_data["detail_code"] = (
                "ERRORS_FOUND"
            )

        elif re.search(
            r"PROCS\s+CRITICAL",
            detail,
            re.IGNORECASE,
        ):
            parsed_data["detail_code"] = (
                "PROCS_CRITICAL"
            )

        elif re.search(
            r"MEMORY\s+CRITICAL",
            detail,
            re.IGNORECASE,
        ):
            parsed_data["detail_code"] = (
                "MEMORY_CRITICAL"
            )

        elif re.search(
            r"DISK\s+CRITICAL",
            detail,
            re.IGNORECASE,
        ):
            parsed_data["detail_code"] = (
                "DISK_CRITICAL"
            )

        # ----------------------------------------------------
        # Penguraian daftar partisi pada detail disk
        # ----------------------------------------------------
        #
        # Contoh detail:
        #   "DISK CRITICAL used : /boot 85.02% free
        #    /home 70.51% free /tmp 99.58% free / 18.92% free"
        #
        # Perhatikan bahwa kata "used" muncul pada judul,
        # sedangkan setiap angka diikuti kata "free". Keduanya
        # bertentangan, dan artinya berkebalikan: 99.58% free
        # berarti partisi nyaris KOSONG, sedangkan 99.58% used
        # berarti nyaris PENUH.
        #
        # Agar tidak bergantung pada asumsi, kata kunci dibaca
        # PER ANGKA langsung dari teks, bukan dari judul. Dengan
        # demikian alert yang menuliskan "used" juga terbaca
        # dengan benar tanpa perubahan kode.
        #
        # CATATAN: pertentangan judul vs nilai ini sebaiknya
        # dikonfirmasi ke OCC. Bila ternyata judul yang benar dan
        # kata "free" pada tiap nilai keliru, pembacaan akan
        # terbalik.

        pasangan = re.findall(
            r"(/[^\s]*)\s+([0-9.]+)\s*%\s*(free|used)",
            detail,
            re.IGNORECASE,
        )

        if pasangan:

            ringkas = []
            bermasalah = []
            maksimum = None

            for mount, persen_teks, jenis in pasangan:

                persen = _to_number(persen_teks)

                if persen is None:
                    continue

                jenis = jenis.lower()

                # Nilai dinormalisasi menjadi PERSEN TERPAKAI
                # agar seluruh partisi dapat dibandingkan.
                terpakai = (
                    100 - persen
                    if jenis == "free"
                    else persen
                )

                terpakai = round(terpakai, 2)

                ringkas.append(f"{mount} {terpakai}% terpakai")

                if maksimum is None or terpakai > maksimum:
                    maksimum = terpakai

                if terpakai >= AMBANG_DISK_TERPAKAI:
                    bermasalah.append(
                        f"{mount} ({terpakai}% terpakai)"
                    )

            parsed_data["disk_ringkas"] = "; ".join(ringkas)
            parsed_data["disk_jumlah_partisi"] = len(pasangan)

            if maksimum is not None:
                parsed_data["disk_maks_terpakai"] = maksimum

            if bermasalah:
                parsed_data["disk_bermasalah"] = ", ".join(
                    bermasalah
                )

        # Jumlah proses pada detail "PROCS CRITICAL : count N".
        proc_count_match = re.search(
            r"count\s+([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)",
            detail,
            re.IGNORECASE,
        )

        if proc_count_match:
            parsed_data["proc_count"] = _to_number(
                proc_count_match.group(1)
            )

        # Persentase pada detail
        # "MEMORY CRITICAL : Mem used: X%, Swap used: Y%".
        mem_match = re.search(
            r"Mem\s+used:\s*([0-9.]+)\s*%",
            detail,
            re.IGNORECASE,
        )

        if mem_match:
            parsed_data["mem_used"] = _to_number(
                mem_match.group(1)
            )

        swap_match = re.search(
            r"Swap\s+used:\s*([0-9.]+)\s*%",
            detail,
            re.IGNORECASE,
        )

        if swap_match:
            parsed_data["swap_used"] = _to_number(
                swap_match.group(1)
            )

        error_count_match = re.search(
            r"occured\s*=\s*([0-9]+)",
            detail,
            re.IGNORECASE,
        )

        if error_count_match:
            parsed_data["error_count"] = int(
                error_count_match.group(1)
            )

    # Normalisasi CRM

    elif stream == "CRM":

        parsed_data["status"] = (
            parsed_data.get("status", "").upper()
        )

    return parsed_data


# ============================================================
# TRANSLATOR
# ============================================================

def translator(
    parsed_data: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Translator mengubah hasil Parser menjadi fakta.

    Fakta merupakan input untuk Evaluator.
    """

    facts = []

    for key, value in parsed_data.items():

        if value is not None and value != "":

            facts.append({
                "predicate": key.upper(),
                "value": value,
            })

    return facts


# ============================================================
# UNKNOWN OUTPUT
# ============================================================

def unknown_output(
    reason: str,
    stream: str = "UNKNOWN",
) -> Dict[str, Any]:
    """
    Output ketika tidak ada aturan produksi yang cocok.
    """

    return {
        "condition": "UNKNOWN",

        "hasil_pembacaan":
            "Informasi alert belum dapat diinterpretasikan "
            "oleh aturan produksi yang tersedia.",

        "alasan_pembacaan": reason,

        "rekomendasi":
            "Lakukan verifikasi manual terhadap teks alert "
            "dan evaluasi kebutuhan penambahan aturan produksi.",

        "tim_terkait":
            "OCC (verifikasi manual)",

        "aturan_aktif": [],
    }


# ============================================================
# EVALUATOR BWCE
# ============================================================

def evaluate_bwce(
    facts: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    R-BWCE-01

    IF:
        STREAM = BWCE
        AND SR_DEGRADED = TRUE
        AND TE > 0
        AND BE = 0
        AND UNDEFINED = 0

    THEN:
        hasil pembacaan + alasan + rekomendasi.
    """

    app = get_fact(facts, "APP", "module terkait")
    sr = get_fact(facts, "SR")
    te = get_fact(facts, "TE")
    be = get_fact(facts, "BE")
    undefined = get_fact(facts, "UNDEFINED")
    sr_degraded = get_fact(
        facts,
        "SR_DEGRADED",
        False,
    )

    te_info = get_fact(
        facts,
        "TE_INFO",
        "",
    )

    team = get_fact(
        facts,
        "TEAM",
        STREAM_INFO["BWCE"]["tim_default"],
    )

    if (
        sr_degraded is True
        and te is not None
        and te > 0
        and be == 0
        and undefined == 0
    ):

        error_info = (
            f" Informasi Technical Error: {te_info}."
            if te_info
            else ""
        )

        return {
            "condition":
                "BWCE_SR_DEGRADED_TE",

            "hasil_pembacaan":
                f"Success Rate transaksi pada {app} "
                f"mengalami degradasi disertai "
                f"Technical Error.",

            "alasan_pembacaan":
                f"Alert memiliki flag SR Degraded, "
                f"SR={sr}%, TE={te}, BE={be}, "
                f"dan Undefined={undefined}."
                f"{error_info}",

            "rekomendasi":
                f"Verifikasi Technical Error pada "
                f"transaksi {app}, periksa informasi "
                f"error dan log terkait, kemudian "
                f"informasikan kepada {team}.",

            "tim_terkait": team,

            "aturan_aktif": [
                "R-BWCE-01"
            ],
        }

    # --------------------------------------------------------
    # R-BWCE-02
    #
    # IF:
    #     STREAM = BWCE
    #     AND SR_DEGRADED = TRUE
    #     AND TE > 0
    #     AND (BE > 0 OR UNDEFINED > 0)
    #
    # THEN:
    #     hasil pembacaan + alasan + rekomendasi.
    #
    # Dasar pemisahan dari R-BWCE-01
    # ------------------------------
    # Success Rate pada alert BWCE dihitung sebagai
    # (Total - TE) / Total, yaitu hanya Technical Error yang
    # diperhitungkan sebagai kegagalan. Akibatnya SR Degraded
    # selalu disertai TE > 0, sedangkan Business Error dan
    # Undefined Error tidak menurunkan SR.
    #
    # Karena itu keberadaan BE atau Undefined pada alert yang
    # SR-nya degraded menandakan adanya persoalan TAMBAHAN di
    # luar penyebab turunnya SR, sehingga perlu ditinjau
    # terpisah. Inilah yang membedakannya dari R-BWCE-01 yang
    # menangani kasus bersih (BE = 0 dan Undefined = 0).
    #
    # CATATAN: rumus SR di atas disimpulkan dari alert nyata dan
    # MASIH PERLU DIKONFIRMASI ke OCC.

    if (
        sr_degraded is True
        and te is not None
        and te > 0
        and (
            (be is not None and be > 0)
            or (undefined is not None and undefined > 0)
        )
    ):

        error_info = (
            f" Informasi Technical Error: {te_info}."
            if te_info
            else ""
        )

        # Rincian jenis error tambahan yang tercatat.
        tambahan = []

        if be is not None and be > 0:
            tambahan.append(f"Business Error sebanyak {be}")

        if undefined is not None and undefined > 0:
            tambahan.append(f"Undefined Error sebanyak {undefined}")

        rincian_tambahan = " dan ".join(tambahan)

        return {
            "condition":
                "BWCE_SR_DEGRADED_MIXED",

            "hasil_pembacaan":
                f"Success Rate transaksi pada {app} "
                f"mengalami degradasi disertai Technical "
                f"Error, dan pada periode yang sama juga "
                f"tercatat {rincian_tambahan} yang perlu "
                f"ditinjau terpisah.",

            "alasan_pembacaan":
                f"Alert memiliki flag SR Degraded, "
                f"SR={sr}%, TE={te}, BE={be}, "
                f"dan Undefined={undefined}. Terdapat "
                f"lebih dari satu jenis error."
                f"{error_info}",

            "rekomendasi":
                f"Tangani Technical Error pada transaksi "
                f"{app} terlebih dahulu karena menjadi "
                f"penyebab turunnya SR; periksa informasi "
                f"error dan log terkait. Selanjutnya tinjau "
                f"{rincian_tambahan} secara terpisah bersama "
                f"pemilik aplikasi. Informasikan kepada "
                f"{team}.",

            "tim_terkait": team,

            "aturan_aktif": [
                "R-BWCE-02"
            ],
        }

    return unknown_output(
        reason=(
            "Pola BWCE tidak memenuhi aturan produksi "
            "yang tersedia."
        ),
        stream="BWCE",
    )


# ============================================================
# EVALUATOR NGSSP
# ============================================================

def evaluate_ngssp(
    facts: List[Dict[str, Any]]
) -> Dict[str, Any]:

    metric_code = get_fact(
        facts,
        "METRIC_CODE",
    )

    component = get_fact(
        facts,
        "COMPONENT",
        "komponen terkait",
    )

    value = get_fact(
        facts,
        "VALUE",
    )

    team = get_fact(
        facts,
        "TEAM",
        STREAM_INFO["NGSSP"]["tim_default"],
    )

    # --------------------------------------------------------
    # R-NGSSP-01
    # Node Exporter Status + val = 0
    # --------------------------------------------------------

    if (
        metric_code == "NODE_EXPORTER_STATUS"
        and value == 0
    ):

        return {
            "condition":
                "NGSSP_NODE_EXPORTER_UNAVAILABLE",

            "hasil_pembacaan":
                f"Node Exporter pada {component} "
                f"teridentifikasi tidak tersedia.",

            "alasan_pembacaan":
                "Alert Node Exporter Status memiliki "
                "nilai val=0.",

            "rekomendasi":
                f"Verifikasi status host dan Node Exporter "
                f"pada {component}, periksa konektivitas "
                f"serta proses monitoring, kemudian "
                f"informasikan kepada {team}.",

            "tim_terkait": team,

            "aturan_aktif": [
                "R-NGSSP-01"
            ],
        }

    # --------------------------------------------------------
    # R-NGSSP-02
    # JVM Managed Server Status + val = 0
    # --------------------------------------------------------

    if (
        metric_code == "JVM_MANAGED_SERVER_STATUS"
        and value == 0
    ):

        return {
            "condition":
                "NGSSP_MANAGED_SERVER_UNAVAILABLE",

            "hasil_pembacaan":
                f"Managed Server {component} "
                f"teridentifikasi tidak berjalan "
                f"atau tidak tersedia.",

            "alasan_pembacaan":
                "Alert JVM Managed Server Status memiliki "
                "nilai val=0.",

            "rekomendasi":
                f"Verifikasi status Managed Server "
                f"{component}, periksa log dan status "
                f"layanan terkait, kemudian informasikan "
                f"kepada {team}.",

            "tim_terkait": team,

            "aturan_aktif": [
                "R-NGSSP-02"
            ],
        }

    # --------------------------------------------------------
    # R-NGSSP-03
    # CPU Utilization + val >= AMBANG_CPU_TINGGI
    # --------------------------------------------------------
    #
    # Berbeda dengan R-NGSSP-01/02 yang menguji val = 0, aturan
    # ini menguji pelampauan ambang batas karena CPU Utilization
    # merupakan metric berskala persen.

    if (
        metric_code == "CPU_UTILIZATION"
        and isinstance(value, (int, float))
        and value >= AMBANG_CPU_TINGGI
    ):

        return {
            "condition":
                "NGSSP_CPU_HIGH",

            "hasil_pembacaan":
                f"Penggunaan CPU pada {component} "
                f"teridentifikasi tinggi, yaitu "
                f"{value:.2f}%.",

            "alasan_pembacaan":
                f"Alert CPU Utilization memiliki nilai val="
                f"{value:.2f}, telah mencapai atau melampaui "
                f"ambang batas {AMBANG_CPU_TINGGI:.0f}%.",

            "rekomendasi":
                f"Periksa beban proses pada {component}, "
                f"identifikasi proses dengan konsumsi CPU "
                f"tertinggi, evaluasi kapasitas serta tren "
                f"penggunaan, kemudian informasikan kepada "
                f"{team}.",

            "tim_terkait": team,

            "aturan_aktif": [
                "R-NGSSP-03"
            ],
        }

    # --------------------------------------------------------
    # R-NGSSP-04
    # Stuck Thread + val >= AMBANG_STUCK_THREAD
    # --------------------------------------------------------
    #
    # Nilai val pada metric ini merupakan JUMLAH thread yang
    # macet, sehingga aturannya menguji pelampauan ambang batas
    # cacah, bukan persentase seperti R-NGSSP-03.

    if (
        metric_code == "STUCK_THREAD"
        and isinstance(value, (int, float))
        and value >= AMBANG_STUCK_THREAD
    ):

        return {
            "condition":
                "NGSSP_STUCK_THREAD",

            "hasil_pembacaan":
                f"Terdapat {int(value)} stuck thread pada "
                f"{component}, menandakan thread aplikasi "
                f"tertahan dan tidak menyelesaikan proses.",

            "alasan_pembacaan":
                f"Alert Stuck Thread memiliki nilai val="
                f"{int(value)}, telah mencapai atau melampaui "
                f"ambang batas {AMBANG_STUCK_THREAD} thread.",

            "rekomendasi":
                f"Ambil thread dump pada {component}, "
                f"identifikasi thread yang tertahan beserta "
                f"proses atau koneksi backend yang menjadi "
                f"penyebab, evaluasi kebutuhan restart managed "
                f"server, kemudian informasikan kepada {team}.",

            "tim_terkait": team,

            "aturan_aktif": [
                "R-NGSSP-04"
            ],
        }

    return unknown_output(
        reason=(
            "Pola NGSSP tidak memenuhi aturan produksi "
            "yang tersedia."
        ),
        stream="NGSSP",
    )


# ============================================================
# EVALUATOR USSD
# ============================================================

def evaluate_ussd(
    facts: List[Dict[str, Any]]
) -> Dict[str, Any]:

    check = get_fact(
        facts,
        "CHECK",
        "proses terkait",
    )

    host = get_fact(
        facts,
        "HOST",
        "host terkait",
    )

    severity = get_fact(
        facts,
        "SEVERITY",
        "-",
    )

    detail_code = get_fact(
        facts,
        "DETAIL_CODE",
    )

    error_count = get_fact(
        facts,
        "ERROR_COUNT",
    )

    team = STREAM_INFO["USSD"]["tim_default"]

    # --------------------------------------------------------
    # R-USSD-01
    # Process is not running
    # --------------------------------------------------------

    if detail_code == "PROCESS_NOT_RUNNING":

        return {
            "condition":
                "USSD_PROCESS_NOT_RUNNING",

            "hasil_pembacaan":
                f"Proses {check} pada {host} "
                f"teridentifikasi tidak berjalan.",

            "alasan_pembacaan":
                f"Detail alert menyatakan "
                f"'Process is not running' "
                f"dengan severity {severity}.",

            "rekomendasi":
                f"Verifikasi status proses {check} pada "
                f"{host}, periksa log dan dependensi "
                f"proses terkait, kemudian informasikan "
                f"kepada tim terkait.",

            "tim_terkait": team,

            "aturan_aktif": [
                "R-USSD-01"
            ],
        }

    # --------------------------------------------------------
    # R-USSD-02
    # Errors found
    # --------------------------------------------------------

    if detail_code == "ERRORS_FOUND":

        count_text = (
            f" sebanyak {error_count} kejadian"
            if error_count is not None
            else ""
        )

        return {
            "condition":
                "USSD_ERROR_DETECTED",

            "hasil_pembacaan":
                f"Error terdeteksi pada pemeriksaan "
                f"{check} di {host}.",

            "alasan_pembacaan":
                f"Detail alert menyatakan 'Errors found'"
                f"{count_text} dengan severity {severity}.",

            "rekomendasi":
                f"Verifikasi error yang terdeteksi pada "
                f"{check}, periksa log terkait, "
                f"identifikasi penyebab error, kemudian "
                f"informasikan kepada tim terkait.",

            "tim_terkait": team,

            "aturan_aktif": [
                "R-USSD-02"
            ],
        }

    # --------------------------------------------------------
    # R-USSD-03
    #
    # IF:
    #     STREAM = USSD
    #     AND DETAIL_CODE = PROCS_CRITICAL
    #
    # THEN:
    #     hasil pembacaan + alasan + rekomendasi.
    #
    # Aturan ini TIDAK memakai ambang batas sendiri. Berbeda
    # dengan metric NGSSP yang hanya menyajikan angka mentah,
    # detail alert USSD sudah memuat status "CRITICAL" yang
    # ditetapkan oleh sistem pemantauan. Menambahkan ambang
    # batas sendiri berisiko bertentangan dengan keputusan
    # sistem tersebut. Pendekatan ini konsisten dengan
    # R-USSD-01 dan R-USSD-02 yang juga mencocokkan pola detail.

    if detail_code == "PROCS_CRITICAL":

        proc_count = get_fact(facts, "PROC_COUNT")

        jumlah = (
            f"sebanyak {int(proc_count)}"
            if isinstance(proc_count, (int, float))
            else "dalam jumlah yang tidak wajar"
        )

        return {
            "condition":
                "USSD_PROCS_CRITICAL",

            "hasil_pembacaan":
                f"Jumlah proses pada {host} tercatat "
                f"{jumlah} dan berstatus CRITICAL menurut "
                f"pemeriksaan {check}.",

            "alasan_pembacaan":
                f"Detail alert memuat status PROCS CRITICAL "
                f"pada pemeriksaan {check}.",

            "rekomendasi":
                f"Periksa daftar proses yang berjalan pada "
                f"{host}, identifikasi proses yang menumpuk "
                f"atau tidak berhenti sebagaimana mestinya "
                f"(process leak), evaluasi kebutuhan restart "
                f"layanan terkait, kemudian informasikan "
                f"kepada tim terkait.",

            "tim_terkait": team,

            "aturan_aktif": [
                "R-USSD-03"
            ],
        }

    # --------------------------------------------------------
    # R-USSD-04
    #
    # IF:
    #     STREAM = USSD
    #     AND DETAIL_CODE = MEMORY_CRITICAL
    #
    # THEN:
    #     hasil pembacaan + alasan + rekomendasi.
    #
    # Alasan tidak memakai ambang batas sendiri sama dengan
    # R-USSD-03.

    if detail_code == "MEMORY_CRITICAL":

        mem_used = get_fact(facts, "MEM_USED")
        swap_used = get_fact(facts, "SWAP_USED")

        rincian = []

        if isinstance(mem_used, (int, float)):
            rincian.append(f"penggunaan memori {mem_used}%")

        if isinstance(swap_used, (int, float)):
            rincian.append(f"penggunaan swap {swap_used}%")

        keterangan = (
            " dengan " + " dan ".join(rincian)
            if rincian
            else ""
        )

        return {
            "condition":
                "USSD_MEMORY_CRITICAL",

            "hasil_pembacaan":
                f"Penggunaan memori pada {host} berstatus "
                f"CRITICAL{keterangan}.",

            "alasan_pembacaan":
                f"Detail alert memuat status MEMORY CRITICAL "
                f"pada pemeriksaan {check}.",

            "rekomendasi":
                f"Identifikasi proses dengan konsumsi memori "
                f"tertinggi pada {host}, periksa kemungkinan "
                f"memory leak, tinjau penggunaan swap sebagai "
                f"indikasi tekanan memori, evaluasi kapasitas "
                f"serta kebutuhan restart layanan, kemudian "
                f"informasikan kepada tim terkait.",

            "tim_terkait": team,

            "aturan_aktif": [
                "R-USSD-04"
            ],
        }

    # --------------------------------------------------------
    # R-USSD-05
    #
    # IF:
    #     STREAM = USSD
    #     AND DETAIL_CODE = DISK_CRITICAL
    #
    # THEN:
    #     hasil pembacaan + alasan + rekomendasi.
    #
    # Berbeda dengan aturan USSD lainnya, detail alert disk
    # memuat BANYAK partisi sekaligus dengan jumlah yang
    # berubah-ubah. Karena itu aturan ini menunjuk partisi mana
    # yang benar-benar bermasalah; menyebut "disk kritis" tanpa
    # menyebut partisinya tidak menolong engineer.
    #
    # Persentase tiap partisi telah dinormalisasi menjadi persen
    # TERPAKAI oleh normalizer, dengan membaca kata kunci
    # free/used langsung dari teks.

    if detail_code == "DISK_CRITICAL":

        bermasalah = get_fact(facts, "DISK_BERMASALAH")
        ringkas = get_fact(facts, "DISK_RINGKAS", "")
        jumlah = get_fact(facts, "DISK_JUMLAH_PARTISI")

        if bermasalah:

            pembacaan = (
                f"Kapasitas disk pada {host} berstatus "
                f"CRITICAL. Partisi yang hampir penuh: "
                f"{bermasalah}."
            )

            rekomendasi = (
                f"Periksa partisi {bermasalah} pada {host}, "
                f"identifikasi berkas atau direktori dengan "
                f"konsumsi ruang terbesar, lakukan pembersihan "
                f"log atau berkas sementara yang sudah tidak "
                f"diperlukan, evaluasi kebutuhan penambahan "
                f"kapasitas, kemudian informasikan kepada tim "
                f"terkait."
            )

        else:

            # Status CRITICAL tetapi tidak ada partisi yang
            # melewati ambang penunjuk. Kondisi ini tidak
            # diklaim sebagai kesalahan sistem pemantauan,
            # melainkan dilaporkan apa adanya agar dapat
            # ditelusuri.
            pembacaan = (
                f"Kapasitas disk pada {host} berstatus "
                f"CRITICAL, namun tidak terdapat partisi yang "
                f"melampaui ambang penunjuk "
                f"{AMBANG_DISK_TERPAKAI:.0f}% terpakai."
            )

            rekomendasi = (
                f"Tinjau kondisi seluruh partisi pada {host} "
                f"secara manual, dan periksa kembali kesesuaian "
                f"ambang batas yang digunakan, kemudian "
                f"informasikan kepada tim terkait."
            )

        keterangan_partisi = (
            f" Kondisi seluruh partisi: {ringkas}."
            if ringkas
            else ""
        )

        return {
            "condition":
                "USSD_DISK_CRITICAL",

            "hasil_pembacaan":
                pembacaan,

            "alasan_pembacaan":
                f"Detail alert memuat status DISK CRITICAL "
                f"pada pemeriksaan {check} dengan "
                f"{jumlah} partisi terpantau."
                f"{keterangan_partisi}",

            "rekomendasi":
                rekomendasi,

            "tim_terkait": team,

            "aturan_aktif": [
                "R-USSD-05"
            ],
        }

    return unknown_output(
        reason=(
            "Detail alert USSD tidak memenuhi pola "
            "'Process is not running' atau 'Errors found'."
        ),
        stream="USSD",
    )


# ============================================================
# EVALUATOR CRM / OMNI
# ============================================================

def evaluate_crm(
    facts: List[Dict[str, Any]]
) -> Dict[str, Any]:

    service = get_fact(
        facts,
        "SERVICE",
        "service terkait",
    )

    hostname = get_fact(
        facts,
        "HOSTNAME",
        "host terkait",
    )

    status = get_fact(
        facts,
        "STATUS",
        "",
    )

    team = STREAM_INFO["CRM"]["tim_default"]

    # --------------------------------------------------------
    # R-CRM-01
    # Service DOWN
    # --------------------------------------------------------

    if status == "DOWN":

        return {
            "condition":
                "CRM_SERVICE_UNAVAILABLE",

            "hasil_pembacaan":
                f"Service {service} pada {hostname} "
                f"teridentifikasi tidak tersedia.",

            "alasan_pembacaan":
                f"Teks alert menyatakan status DOWN "
                f"pada service {service}.",

            "rekomendasi":
                f"Verifikasi status service {service} "
                f"pada {hostname}, periksa log dan "
                f"dependensi layanan terkait, kemudian "
                f"informasikan kepada {team}.",

            "tim_terkait": team,

            "aturan_aktif": [
                "R-CRM-01"
            ],
        }

    return unknown_output(
        reason=(
            "Status service CRM/OMNI tidak memenuhi "
            "aturan R-CRM-01."
        ),
        stream="CRM",
    )


# ============================================================
# EVALUATOR ROUTER
# ============================================================

def evaluator(
    stream: str,
    facts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Evaluator mencocokkan fakta dengan aturan produksi.
    """

    if stream == "BWCE":
        return evaluate_bwce(facts)

    if stream == "NGSSP":
        return evaluate_ngssp(facts)

    if stream == "USSD":
        return evaluate_ussd(facts)

    if stream == "CRM":
        return evaluate_crm(facts)

    return unknown_output(
        reason="Stream alert tidak dikenali."
    )


# ============================================================
# MAIN PIPELINE
# ============================================================

def process_alert(text: str) -> Dict[str, Any]:
    """
    Menjalankan pipeline Rule-Based NLP:

        1. Detect Stream
        2. Scanner
        3. Parser
        4. Translator
        5. Evaluator
        6. Output
    """

    stream = detect_stream(text)

    # --------------------------------------------------------
    # UNKNOWN STREAM
    # --------------------------------------------------------

    if stream == "UNKNOWN":

        evaluation = unknown_output(
            reason=(
                "Teks tidak sesuai dengan pola alert "
                "yang tersedia pada basis aturan."
            )
        )

        return score_result({
            "stream": "UNKNOWN",

            "hasil_pembacaan":
                evaluation["hasil_pembacaan"],

            "alasan_pembacaan":
                evaluation["alasan_pembacaan"],

            "rekomendasi":
                evaluation["rekomendasi"],

            "tim_terkait":
                evaluation["tim_terkait"],

            "aturan_aktif":
                evaluation["aturan_aktif"],

            # Compatibility

            "condition":
                evaluation["condition"],

            "diagnosis":
                evaluation["hasil_pembacaan"],

            "features": {},

            # Pipeline trace

            "tokens": {
                "stream": "UNKNOWN",
                "lexemes": [],
            },

            "parsed_data": {},

            "facts": [],

            "raw_text": text,
        })

    # --------------------------------------------------------
    # SCANNER
    # --------------------------------------------------------

    scanner_result = scanner(
        text,
        stream,
    )

    # --------------------------------------------------------
    # PARSER
    # --------------------------------------------------------

    parsed_data = parser(
        scanner_result,
    )

    # --------------------------------------------------------
    # TRANSLATOR
    # --------------------------------------------------------

    facts = translator(
        parsed_data,
    )

    # --------------------------------------------------------
    # EVALUATOR
    # --------------------------------------------------------

    evaluation = evaluator(
        stream,
        facts,
    )

    # --------------------------------------------------------
    # OUTPUT
    # --------------------------------------------------------

    return score_result({
        "stream": stream,

        # Output utama penelitian

        "hasil_pembacaan":
            evaluation["hasil_pembacaan"],

        "alasan_pembacaan":
            evaluation["alasan_pembacaan"],

        "rekomendasi":
            evaluation["rekomendasi"],

        "tim_terkait":
            evaluation["tim_terkait"],

        "aturan_aktif":
            evaluation["aturan_aktif"],

        # Compatibility project lama

        "condition":
            evaluation["condition"],

        "diagnosis":
            evaluation["hasil_pembacaan"],

        "features":
            parsed_data,

        # Pipeline trace

        "tokens":
            scanner_result,

        "parsed_data":
            parsed_data,

        "facts":
            facts,

        "raw_text":
            text,
    })


# ============================================================
# COMPATIBILITY FUNCTION
# ============================================================

def get_all_conditions():
    """
    Dipertahankan sementara agar file lama yang masih
    mengimpor fungsi ini tidak langsung error.

    Condition bukan output utama penelitian.
    """

    return sorted([
        "BWCE_SR_DEGRADED_TE",
        "BWCE_SR_DEGRADED_MIXED",
        "NGSSP_NODE_EXPORTER_UNAVAILABLE",
        "NGSSP_MANAGED_SERVER_UNAVAILABLE",
        "NGSSP_CPU_HIGH",
        "NGSSP_STUCK_THREAD",
        "USSD_PROCESS_NOT_RUNNING",
        "USSD_PROCS_CRITICAL",
        "USSD_MEMORY_CRITICAL",
        "USSD_DISK_CRITICAL",
        "USSD_ERROR_DETECTED",
        "CRM_SERVICE_UNAVAILABLE",
        "UNKNOWN",
    ])