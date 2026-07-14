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
    R-NGSSP-01 : Node Exporter Status dengan val = 0
    R-NGSSP-02 : JVM Managed Server Status dengan val = 0
    R-USSD-01  : Process is not running
    R-USSD-02  : Errors found
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
    if (
        (
            "node exporter status" in lowered
            or "jvm managed server status" in lowered
        )
        and "with val:" in lowered
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

        patterns = {
            "APP": r"^\s*([\w\-]+)\s*-\s*Total\s*:",
            "TOTAL": r"Total:\s*([0-9]+)",
            "SUCCESS": r"Success:\s*([0-9]+)",
            "BE": r"BE:\s*([0-9]+)",
            "TE": r"TE:\s*([0-9]+)",
            "UNDEFINED": r"Undefined:\s*([0-9]+)",
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

        metric_match = re.search(
            r"-\s*(Node Exporter Status|JVM Managed Server Status)"
            r"(?:\s+alert)?\s*~",
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

        value_match = re.search(
            r"with\s+val:\s*([0-9.]+)",
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

    return unknown_output(
        reason=(
            "Pola BWCE tidak memenuhi aturan "
            "R-BWCE-01 yang tersedia."
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

        return {
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
        }

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

    return {
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
    }


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
        "NGSSP_NODE_EXPORTER_UNAVAILABLE",
        "NGSSP_MANAGED_SERVER_UNAVAILABLE",
        "USSD_PROCESS_NOT_RUNNING",
        "USSD_ERROR_DETECTED",
        "CRM_SERVICE_UNAVAILABLE",
        "UNKNOWN",
    ])