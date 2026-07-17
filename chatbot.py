"""
chatbot.py

Lapisan chatbot Rule-Based untuk tanya-jawab mengenai
hasil pemrosesan teks alert OCC.

Chatbot TIDAK melakukan ekstraksi atau inferensi sendiri.

Seluruh analisis alert diperoleh dari:
    rules.py -> process_alert()

Dengan demikian rules.py tetap menjadi single source of truth.

Chatbot mendukung pertanyaan mengenai:
    1. Deskripsi umum stream.
    2. Penjelasan model dan pipeline.
    3. Daftar aturan produksi.
    4. Analisis teks alert.
    5. Pembacaan alert.
    6. Alasan pembacaan.
    7. Rekomendasi tindakan.
    8. Tim terkait.
    9. Aturan produksi yang aktif.
"""

import re

from rules import process_alert


# ============================================================
# DESKRIPSI UMUM STREAM
# ============================================================

STREAM_KB = {
    "BWCE": (
        "BWCE merupakan kelompok teks alert monitoring transaksi. "
        "Model mengekstraksi informasi aplikasi, Total, Success, "
        "Business Error, Technical Error, Undefined Error, "
        "Success Rate, informasi Technical Error, dan tim terkait. "
        "Pada basis aturan penelitian, alert BWCE diproses untuk "
        "membaca degradasi Success Rate yang disertai Technical Error."
    ),

    "NGSSP": (
        "NGSSP merupakan kelompok teks alert monitoring middleware. "
        "Model mengekstraksi jenis metric, component, nilai status, "
        "waktu mulai issue, dan tim terkait. Basis aturan penelitian "
        "mencakup Node Exporter Status dan JVM Managed Server Status "
        "dengan nilai val=0."
    ),

    "USSD": (
        "USSD merupakan kelompok teks alert monitoring proses layanan. "
        "Model mengekstraksi nama pemeriksaan atau proses, host, "
        "alamat IP, severity, timestamp, dan detail alert. "
        "Basis aturan penelitian mencakup pola "
        "'Process is not running' dan 'Errors found'."
    ),

    "CRM": (
        "CRM/OMNI merupakan kelompok teks alert monitoring "
        "ketersediaan service. Model mengekstraksi nama service, "
        "hostname, dan status service. Basis aturan penelitian "
        "mencakup service dengan status DOWN."
    ),
}


# ============================================================
# BASIS INFORMASI ATURAN PRODUKSI
# ============================================================

RULE_KB = {
    "R-BWCE-01": (
        "Alert BWCE memiliki flag SR Degraded, "
        "Technical Error lebih dari 0, Business Error sama dengan 0, "
        "dan Undefined Error sama dengan 0."
    ),

    "R-NGSSP-01": (
        "Alert NGSSP memiliki metric Node Exporter Status "
        "dengan nilai val=0."
    ),

    "R-NGSSP-02": (
        "Alert NGSSP memiliki metric JVM Managed Server Status "
        "dengan nilai val=0."
    ),

    "R-NGSSP-03": (
        "Alert NGSSP memiliki metric CPU Utilization dengan "
        "nilai val yang mencapai atau melampaui ambang batas."
    ),

    "R-USSD-01": (
        "Detail alert USSD mengandung pola "
        "'Process is not running'."
    ),

    "R-USSD-02": (
        "Detail alert USSD mengandung pola "
        "'Errors found'."
    ),

    "R-CRM-01": (
        "Alert CRM/OMNI memiliki status service DOWN."
    ),
}


# ============================================================
# NORMALISASI PERTANYAAN
# ============================================================

def normalize_question(question):
    """
    Melakukan normalisasi sederhana terhadap pertanyaan.
    """

    question = str(question).lower().strip()

    question = re.sub(
        r"\s+",
        " ",
        question,
    )

    return question


# ============================================================
# FORMAT HASIL ANALISIS
# ============================================================

def format_analysis_result(result):
    """
    Membentuk jawaban lengkap berdasarkan hasil process_alert().
    """

    stream = result.get(
        "stream",
        "UNKNOWN",
    )

    hasil_pembacaan = result.get(
        "hasil_pembacaan",
        "Informasi alert tidak tersedia.",
    )

    alasan = result.get(
        "alasan_pembacaan",
        "Alasan pembacaan tidak tersedia.",
    )

    rekomendasi = result.get(
        "rekomendasi",
        "Rekomendasi tidak tersedia.",
    )

    tim = result.get(
        "tim_terkait",
        "Tim terkait tidak ditentukan.",
    )

    aturan = result.get(
        "aturan_aktif",
        [],
    )

    aturan_text = (
        ", ".join(aturan)
        if aturan
        else "Tidak ada aturan produksi yang aktif"
    )

    return (
        f"Stream: {stream}\n\n"
        f"Pembacaan Alert: {hasil_pembacaan}\n\n"
        f"Alasan Pembacaan: {alasan}\n\n"
        f"Rekomendasi Tindakan: {rekomendasi}\n\n"
        f"Tim Terkait: {tim}\n\n"
        f"Aturan Produksi Aktif: {aturan_text}"
    )


# ============================================================
# EKSTRAKSI TEKS ALERT DARI PERTANYAAN
# ============================================================

def extract_alert_text(question):
    """
    Mengambil teks alert setelah prefix perintah chatbot.

    Contoh:
        cek alert: <teks alert>
        analisis alert: <teks alert>
        baca alert: <teks alert>
        kenapa alert: <teks alert>
        rekomendasi alert: <teks alert>
        tim alert: <teks alert>
        aturan alert: <teks alert>

    Return:
        intent, alert_text

    Jika tidak cocok:
        None, None
    """

    prefixes = {
        "cek alert:": "FULL_ANALYSIS",
        "analisis alert:": "FULL_ANALYSIS",
        "baca alert:": "READING",
        "kenapa alert:": "REASON",
        "rekomendasi alert:": "RECOMMENDATION",
        "tim alert:": "TEAM",
        "aturan alert:": "RULE",
    }

    normalized = normalize_question(question)

    for prefix, intent in prefixes.items():

        if normalized.startswith(prefix):

            # Mengambil teks asli agar kapitalisasi alert tidak berubah.

            colon_position = str(question).find(":")

            if colon_position == -1:
                return intent, ""

            alert_text = str(question)[
                colon_position + 1:
            ].strip()

            return intent, alert_text

    return None, None


# ============================================================
# CHATBOT RESPONSE
# ============================================================

def chatbot_response(question):
    """
    Entry point utama chatbot.

    Chatbot hanya:
        - mengenali bentuk pertanyaan,
        - memanggil process_alert() jika terdapat teks alert,
        - menyajikan hasil model.

    Chatbot tidak memiliki production rules tambahan.
    """

    if question is None or not str(question).strip():

        return (
            "Silakan masukkan pertanyaan mengenai stream, "
            "model Rule-Based NLP, aturan produksi, atau "
            "gunakan format 'cek alert: <teks alert>'."
        )

    q = normalize_question(question)


    # ========================================================
    # INTENT 1
    # ANALISIS TEKS ALERT
    # ========================================================

    intent, alert_text = extract_alert_text(question)

    if intent is not None:

        if not alert_text:

            return (
                "Masukkan teks alert setelah tanda titik dua."
            )

        result = process_alert(alert_text)


        # ----------------------------------------------------
        # FULL ANALYSIS
        # ----------------------------------------------------

        if intent == "FULL_ANALYSIS":

            return format_analysis_result(result)


        # ----------------------------------------------------
        # READING
        # ----------------------------------------------------

        if intent == "READING":

            return (
                "Pembacaan Alert:\n\n"
                + result.get(
                    "hasil_pembacaan",
                    "Informasi alert tidak tersedia.",
                )
            )


        # ----------------------------------------------------
        # REASON
        # ----------------------------------------------------

        if intent == "REASON":

            return (
                "Alasan Pembacaan:\n\n"
                + result.get(
                    "alasan_pembacaan",
                    "Alasan pembacaan tidak tersedia.",
                )
            )


        # ----------------------------------------------------
        # RECOMMENDATION
        # ----------------------------------------------------

        if intent == "RECOMMENDATION":

            return (
                "Rekomendasi Tindakan:\n\n"
                + result.get(
                    "rekomendasi",
                    "Rekomendasi tidak tersedia.",
                )
            )


        # ----------------------------------------------------
        # TEAM
        # ----------------------------------------------------

        if intent == "TEAM":

            return (
                "Tim Terkait:\n\n"
                + result.get(
                    "tim_terkait",
                    "Tim terkait tidak ditentukan.",
                )
            )


        # ----------------------------------------------------
        # RULE
        # ----------------------------------------------------

        if intent == "RULE":

            aturan = result.get(
                "aturan_aktif",
                [],
            )

            if not aturan:

                return (
                    "Tidak ada aturan produksi yang aktif "
                    "untuk teks alert tersebut."
                )

            return (
                "Aturan Produksi Aktif:\n\n- "
                + "\n- ".join(aturan)
            )


    # ========================================================
    # INTENT 2
    # DAFTAR ATURAN PRODUKSI
    # ========================================================

    if (
        "aturan apa saja" in q
        or "daftar aturan" in q
        or "aturan produksi apa saja" in q
        or "basis aturan" in q
    ):

        lines = []

        for rule_id, description in RULE_KB.items():

            lines.append(
                f"{rule_id}: {description}"
            )

        return (
            "Basis aturan produksi yang digunakan model:\n\n- "
            + "\n- ".join(lines)
        )


    # ========================================================
    # INTENT 3
    # PENJELASAN ATURAN TERTENTU
    # ========================================================

    for rule_id, description in RULE_KB.items():

        if rule_id.lower() in q:

            return (
                f"{rule_id}\n\n"
                f"{description}"
            )


    # ========================================================
    # INTENT 4
    # DESKRIPSI STREAM
    # ========================================================

    for stream, description in STREAM_KB.items():

        stream_lower = stream.lower()

        if (
            stream_lower in q
            and (
                "apa" in q
                or "arti" in q
                or "jelaskan" in q
                or "stream" in q
            )
        ):

            return description


    # ========================================================
    # INTENT 5
    # PENJELASAN MODEL
    # ========================================================

    if (
        "model" in q
        or "rule based" in q
        or "rule-based" in q
        or "nlp" in q
        or "pipeline" in q
        or "cara kerja" in q
    ):

        return (
            "Model Rule-Based NLP memproses teks alert melalui "
            "tahapan identifikasi stream, Scanner, Parser, "
            "Translator, dan Evaluator. Scanner mengenali pola "
            "leksikal penting, Parser menyusun hasil ekstraksi "
            "menjadi informasi terstruktur, Translator mengubah "
            "informasi tersebut menjadi fakta, dan Evaluator "
            "mencocokkan fakta dengan aturan produksi. "
            "Keluaran model berupa pembacaan alert, alasan "
            "pembacaan, rekomendasi tindakan, tim terkait, "
            "dan aturan produksi yang aktif."
        )


    # ========================================================
    # FALLBACK
    # ========================================================

    return (
        "Pertanyaan belum dikenali. Kamu dapat bertanya mengenai "
        "BWCE, NGSSP, USSD, CRM, model Rule-Based NLP, "
        "daftar aturan produksi, atau menggunakan format "
        "'cek alert: <teks alert>'."
    )