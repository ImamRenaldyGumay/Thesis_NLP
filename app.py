"""
app.py

Aplikasi Rule-Based Natural Language Processing untuk
Ekstraksi Informasi dan Penyajian Rekomendasi Tindakan
dari Teks Alert pada Operation Command Center.

Menu:
    1. Single Alert
    2. Upload Dataset
    3. Database
    4. Dashboard
    5. Chatbot

Pipeline:
    Input Alert
        -> Detect Stream
        -> Scanner
        -> Parser
        -> Translator
        -> Evaluator
        -> Output

Pengujian model tidak dilakukan di dalam aplikasi.
"""

import json

import pandas as pd
import plotly.express as px
import streamlit as st

from rules import process_alert

from database import (
    init_db,
    save_alert,
    get_all_alerts,
    get_alert_by_id,
    delete_alert,
    delete_all_alerts,
    get_database_statistics,
)

from chatbot import chatbot_response

from extraction import (
    init_extraction_db,
    ambil_ekstraksi,
    simpan_verifikasi,
    get_extraction_checks,
    hapus_semua_verifikasi,
    jumlah_alert_terverifikasi,
    evaluasi_ekstraksi,
)

from labeling import (
    init_labeling_db,
    save_label,
    revise_label,
    get_label_by_id,
    delete_label,
    delete_all_labels,
    get_all_labels,
    count_labels,
    label_statistics,
    import_labels_from_dataframe,
    validate_label,
    build_template_excel,
    build_template_csv,
    LABEL_STREAM_OPTIONS,
    LABEL_RULE_OPTIONS,
    VALID_RULE_BY_STREAM,
    LABEL_GUIDE,
)


# ============================================================
# KONFIGURASI APLIKASI
# ============================================================

st.set_page_config(
    page_title="OCC Alert Rule-Based NLP",
    page_icon="🚨",
    layout="wide",
)

init_db()
init_labeling_db()
init_extraction_db()


# ============================================================
# HELPER
# ============================================================

def safe_json_load(value, default):
    """
    Mengubah JSON string dari database menjadi object Python.
    """

    if value is None:
        return default

    if isinstance(value, type(default)):
        return value

    if isinstance(value, str):

        try:
            return json.loads(value)

        except (json.JSONDecodeError, TypeError):
            return default

    return default


def safe_join(value):
    """
    Mengubah list menjadi teks.
    """

    if isinstance(value, list):
        return ", ".join(map(str, value))

    if value is None:
        return ""

    return str(value)


def read_uploaded_file(uploaded_file):
    """
    Membaca file CSV atau Excel.
    """

    if uploaded_file.name.lower().endswith(".csv"):
        return pd.read_csv(uploaded_file)

    return pd.read_excel(uploaded_file)


def facts_to_dataframe(facts):
    """
    Mengubah fakta hasil Translator menjadi DataFrame.
    """

    rows = []

    for number, fact in enumerate(facts, start=1):

        rows.append(
            {
                "No": number,
                "Predicate": fact.get("predicate", ""),
                "Value": str(fact.get("value", "")),
            }
        )

    return pd.DataFrame(rows)


def lexemes_to_dataframe(tokens):
    """
    Mengubah token hasil Scanner menjadi DataFrame.
    """

    lexemes = tokens.get("lexemes", [])

    rows = []

    for number, lexeme in enumerate(lexemes, start=1):

        rows.append(
            {
                "No": number,
                "Token": lexeme.get("type", ""),
                "Lexeme": str(lexeme.get("value", "")),
            }
        )

    return pd.DataFrame(rows)


def count_active_rules(alert_df):
    """
    Menghitung distribusi aturan produksi aktif.
    """

    rule_counter = {}

    if alert_df.empty:
        return rule_counter

    for value in alert_df["aturan_aktif"]:

        rules = safe_json_load(value, [])

        for rule in rules:

            rule_counter[rule] = (
                rule_counter.get(rule, 0) + 1
            )

    return rule_counter


# ============================================================
# REFERENSI ATURAN PRODUKSI
# ============================================================

RULE_REFERENCE = {
    "BWCE": [
        (
            "R-BWCE-01",
            "SR Degraded AND TE > 0 AND BE = 0 "
            "AND Undefined = 0",
        ),
        (
            "R-BWCE-02",
            "SR Degraded AND TE > 0 "
            "AND (BE > 0 OR Undefined > 0)",
        ),
    ],

    "NGSSP": [
        (
            "R-NGSSP-01",
            "Node Exporter Status AND val = 0",
        ),
        (
            "R-NGSSP-02",
            "JVM Managed Server Status AND val = 0",
        ),
        (
            "R-NGSSP-03",
            "CPU Utilization AND val >= ambang batas",
        ),
        (
            "R-NGSSP-04",
            "Stuck Thread AND val >= ambang batas",
        ),
    ],

    "USSD": [
        (
            "R-USSD-01",
            "Detail contains 'Process is not running'",
        ),
        (
            "R-USSD-02",
            "Detail contains 'Errors found'",
        ),
        (
            "R-USSD-03",
            "Detail contains 'PROCS CRITICAL'",
        ),
        (
            "R-USSD-04",
            "Detail contains 'MEMORY CRITICAL'",
        ),
        (
            "R-USSD-05",
            "Detail contains 'DISK CRITICAL'",
        ),
    ],

    "CRM": [
        (
            "R-CRM-01",
            "Service Status = DOWN",
        ),
    ],
}


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.header("📋 Basis Aturan Produksi")

    st.caption(
        "Enam aturan produksi yang digunakan "
        "oleh Evaluator."
    )

    for stream_name, stream_rules in RULE_REFERENCE.items():

        st.markdown(f"### {stream_name}")

        for rule_id, premise in stream_rules:

            st.markdown(
                f"**{rule_id}**  \n"
                f"`{premise}`"
            )

    st.divider()

    statistics = get_database_statistics()

    st.subheader("📊 Statistik Database")

    st.metric(
        "Total Alert",
        statistics["total_alert"],
    )

    st.metric(
        "Jumlah Stream",
        statistics["jumlah_stream"],
    )

    st.metric(
        "Aturan Pernah Aktif",
        statistics["jumlah_aturan_aktif"],
    )

    st.caption(
        f"Stream terbanyak: "
        f"{statistics['stream_terbanyak']}"
    )

    st.caption(
        f"Aturan terbanyak: "
        f"{statistics['aturan_terbanyak']}"
    )


# ============================================================
# HEADER
# ============================================================

st.title(
    "🚨 Rule-Based Natural Language Processing"
)

st.markdown(
    "### Ekstraksi Informasi dan Penyajian "
    "Rekomendasi Tindakan dari Teks Alert OCC"
)

st.caption(
    "Pipeline: Detect Stream → Scanner → Parser → "
    "Translator → Evaluator → Output"
)

st.divider()


# ============================================================
# NAVIGASI
# ============================================================

(
    tab_single,
    tab_upload,
    tab_database,
    tab_dashboard,
    tab_pelabelan,
    tab_evaluasi,
    tab_chatbot,
) = st.tabs(
    [
        "📝 Single Alert",
        "📁 Upload Dataset",
        "🗄️ Database",
        "📈 Dashboard",
        "🏷️ Pelabelan",
        "🧪 Pengujian",
        "💬 Chatbot",
    ]
)


# ============================================================
# 1. SINGLE ALERT
# ============================================================

with tab_single:

    # --------------------------------------------------------
    # RESET FORM
    # --------------------------------------------------------
    # Menghapus kunci session_state saja TIDAK cukup untuk
    # mengosongkan text_area: nilai lama masih dikirim ulang dari
    # sisi browser pada rerun berikutnya, sehingga teks muncul lagi.
    #
    # Cara yang pasti berhasil adalah MENGGANTI key widget. Key
    # yang berbeda dianggap Streamlit sebagai widget yang benar-
    # benar baru, sehingga tampil dengan nilai awal (kosong).
    # Nomor urut form di bawah ini dinaikkan setiap kali reset.

    if st.session_state.get("single_alert_pending_reset"):

        # Buang sisa state milik form sebelumnya.
        for kunci in list(st.session_state.keys()):
            if str(kunci).startswith("single_alert_input_"):
                st.session_state.pop(kunci, None)

        for kunci in (
            "analysis_result",
            "analysis_input",
            "analysis_saved",
        ):
            st.session_state.pop(kunci, None)

        st.session_state["single_alert_form_no"] = (
            st.session_state.get("single_alert_form_no", 0) + 1
        )

        st.session_state["single_alert_pending_reset"] = False

    st.header("🔍 Analisis Single Alert")

    st.write(
        """
        Menu ini digunakan untuk memproses satu teks alert
        menggunakan model Rule-Based NLP.

        Sistem melakukan ekstraksi informasi, membentuk fakta,
        mengevaluasi aturan produksi, kemudian menghasilkan
        pembacaan alert dan rekomendasi tindakan.
        """
    )

    # Pemberitahuan hasil simpan dari proses sebelumnya.
    if st.session_state.get("single_alert_last_saved_id"):

        st.success(
            f"Hasil sebelumnya tersimpan ke database dengan ID "
            f"{st.session_state['single_alert_last_saved_id']}. "
            "Form telah dikosongkan, silakan masukkan alert berikutnya."
        )

        st.session_state["single_alert_last_saved_id"] = None

    # Key text_area mengandung nomor urut form agar dapat
    # dikosongkan sepenuhnya saat reset (lihat penjelasan di atas).
    nomor_form = st.session_state.get("single_alert_form_no", 0)

    raw_text = st.text_area(
        "Masukkan teks alert:",
        height=220,
        placeholder="Masukkan satu teks alert OCC...",
        key=f"single_alert_input_{nomor_form}",
    )

    tombol_proses, tombol_reset = st.columns([3, 1])

    with tombol_proses:
        proses_ditekan = st.button(
            "🚀 Proses Alert",
            type="primary",
            use_container_width=True,
        )

    with tombol_reset:
        if st.button(
            "🔄 Alert Baru",
            use_container_width=True,
            help=(
                "Mengosongkan teks dan hasil analisis, "
                "siap untuk alert berikutnya."
            ),
        ):
            st.session_state["single_alert_pending_reset"] = True
            st.rerun()

    if proses_ditekan:

        if not raw_text.strip():

            st.warning(
                "Masukkan teks alert terlebih dahulu."
            )

        else:

            with st.spinner(
                "Menjalankan pipeline Rule-Based NLP..."
            ):

                result = process_alert(raw_text)

            result["raw_text"] = raw_text

            st.session_state["analysis_result"] = result
            st.session_state["analysis_input"] = raw_text
            st.session_state["analysis_saved"] = False


    # ========================================================
    # HASIL PEMROSESAN
    # ========================================================

    if "analysis_result" in st.session_state:

        result = st.session_state["analysis_result"]

        analysis_input = st.session_state.get(
            "analysis_input",
            "",
        )

        stream = result.get(
            "stream",
            "UNKNOWN",
        )

        hasil_pembacaan = result.get(
            "hasil_pembacaan",
            "",
        )

        alasan_pembacaan = result.get(
            "alasan_pembacaan",
            "",
        )

        rekomendasi = result.get(
            "rekomendasi",
            "",
        )

        tim_terkait = result.get(
            "tim_terkait",
            "",
        )

        aturan_aktif = result.get(
            "aturan_aktif",
            [],
        )

        tokens = result.get(
            "tokens",
            {},
        )

        parsed_data = result.get(
            "parsed_data",
            {},
        )

        facts = result.get(
            "facts",
            [],
        )

        st.divider()

        # ====================================================
        # OUTPUT UTAMA
        # ====================================================

        st.header("🚨 Hasil Pembacaan Alert")

        col_stream, col_rule = st.columns(2)

        col_stream.metric(
            "Stream Terdeteksi",
            stream,
        )

        col_rule.metric(
            "Jumlah Aturan Aktif",
            len(aturan_aktif),
        )

        st.subheader("📖 Pembacaan Alert")

        if stream == "UNKNOWN":

            st.warning(hasil_pembacaan)

        else:

            st.info(hasil_pembacaan)

        st.subheader("🔎 Alert Ini Kenapa?")

        st.warning(alasan_pembacaan)

        st.subheader("🛠️ Rekomendasi Tindakan")

        st.success(rekomendasi)

        st.subheader("👥 Tim Terkait")

        st.info(tim_terkait)

        st.subheader("📐 Aturan Produksi Aktif")

        if aturan_aktif:

            for rule in aturan_aktif:

                st.success(
                    f"✅ {rule}"
                )

        else:

            st.warning(
                "Tidak ada aturan produksi yang aktif."
            )

        st.divider()


        # ====================================================
        # PIPELINE
        # ====================================================

        st.header("⚙️ Pipeline Rule-Based NLP")

        (
            pipeline_1,
            arrow_1,
            pipeline_2,
            arrow_2,
            pipeline_3,
            arrow_3,
            pipeline_4,
            arrow_4,
            pipeline_5,
        ) = st.columns(
            [
                2,
                0.4,
                2,
                0.4,
                2,
                0.4,
                2,
                0.4,
                2,
            ]
        )

        with pipeline_1:

            st.info(
                "🔎 **SCANNER**\n\n"
                "Tokenisasi Pola"
            )

        with arrow_1:

            st.markdown(
                "<h2 style='text-align:center;'>→</h2>",
                unsafe_allow_html=True,
            )

        with pipeline_2:

            st.info(
                "🧩 **PARSER**\n\n"
                "Struktur Informasi"
            )

        with arrow_2:

            st.markdown(
                "<h2 style='text-align:center;'>→</h2>",
                unsafe_allow_html=True,
            )

        with pipeline_3:

            st.info(
                "🔄 **TRANSLATOR**\n\n"
                "Pembentukan Fakta"
            )

        with arrow_3:

            st.markdown(
                "<h2 style='text-align:center;'>→</h2>",
                unsafe_allow_html=True,
            )

        with pipeline_4:

            st.info(
                "📐 **EVALUATOR**\n\n"
                "Aturan Produksi"
            )

        with arrow_4:

            st.markdown(
                "<h2 style='text-align:center;'>→</h2>",
                unsafe_allow_html=True,
            )

        with pipeline_5:

            st.success(
                "📤 **OUTPUT**\n\n"
                "Informasi + Rekomendasi"
            )

        st.divider()


        # ====================================================
        # DETAIL PIPELINE
        # ====================================================

        st.header("🔬 Detail Pipeline")


        # ====================================================
        # SCANNER
        # ====================================================

        with st.expander(
            "1️⃣ SCANNER — Pengenalan Pola Leksikal",
            expanded=True,
        ):

            st.write(
                """
                Scanner mengenali pola leksikal penting
                dari teks alert sesuai format masing-masing
                stream.
                """
            )

            st.write("**Raw Alert:**")

            st.code(
                analysis_input,
                language=None,
            )

            st.write("**Stream Terdeteksi:**")

            st.info(stream)

            st.write("**Token/Lexeme yang Dikenali:**")

            lexeme_df = lexemes_to_dataframe(tokens)

            if not lexeme_df.empty:

                st.dataframe(
                    lexeme_df,
                    use_container_width=True,
                    hide_index=True,
                )

            else:

                st.warning(
                    "Tidak ada token yang dikenali."
                )

            with st.expander(
                "Lihat Hasil Scanner dalam JSON"
            ):

                st.json(tokens)


        # ====================================================
        # PARSER
        # ====================================================

        with st.expander(
            "2️⃣ PARSER — Penyusunan Informasi Terstruktur",
            expanded=True,
        ):

            st.write(
                """
                Parser menyusun token hasil Scanner menjadi
                informasi terstruktur dan melakukan normalisasi
                nilai yang diperlukan.
                """
            )

            if parsed_data:

                parser_rows = []

                for key, value in parsed_data.items():

                    parser_rows.append(
                        {
                            "Informasi": key,
                            "Nilai": str(value),
                        }
                    )

                parser_df = pd.DataFrame(parser_rows)

                st.dataframe(
                    parser_df,
                    use_container_width=True,
                    hide_index=True,
                )

                with st.expander(
                    "Lihat Hasil Parser dalam JSON"
                ):

                    st.json(parsed_data)

            else:

                st.warning(
                    "Parser tidak menghasilkan "
                    "informasi terstruktur."
                )


        # ====================================================
        # TRANSLATOR
        # ====================================================

        with st.expander(
            "3️⃣ TRANSLATOR — Pembentukan Fakta",
            expanded=True,
        ):

            st.write(
                """
                Translator mengubah informasi terstruktur
                hasil Parser menjadi fakta yang digunakan
                sebagai masukan Evaluator.
                """
            )

            if facts:

                facts_df = facts_to_dataframe(facts)

                st.dataframe(
                    facts_df,
                    use_container_width=True,
                    hide_index=True,
                )

                st.write("**Representasi Fakta:**")

                fact_text = []

                for fact in facts:

                    fact_text.append(
                        f"{fact.get('predicate')} = "
                        f"{fact.get('value')}"
                    )

                st.code(
                    "\n".join(fact_text),
                    language=None,
                )

            else:

                st.warning(
                    "Translator tidak menghasilkan fakta."
                )


        # ====================================================
        # EVALUATOR
        # ====================================================

        with st.expander(
            "4️⃣ EVALUATOR — Evaluasi Aturan Produksi",
            expanded=True,
        ):

            st.write(
                """
                Evaluator mencocokkan fakta dengan premis
                aturan produksi yang tersedia pada basis aturan.
                """
            )

            if aturan_aktif:

                rule_rows = []

                for number, rule in enumerate(
                    aturan_aktif,
                    start=1,
                ):

                    rule_rows.append(
                        {
                            "No": number,
                            "Rule ID": rule,
                            "Status": "TERPENUHI",
                        }
                    )

                st.dataframe(
                    pd.DataFrame(rule_rows),
                    use_container_width=True,
                    hide_index=True,
                )

                for rule in aturan_aktif:

                    st.success(
                        f"✅ {rule} → TERPENUHI"
                    )

            else:

                st.warning(
                    "Tidak ada aturan produksi "
                    "yang terpenuhi."
                )


        # ====================================================
        # OUTPUT
        # ====================================================

        with st.expander(
            "5️⃣ OUTPUT — Hasil Akhir",
            expanded=True,
        ):

            st.write(
                """
                Output merupakan hasil akhir pemrosesan
                berdasarkan fakta dan aturan produksi yang aktif.
                """
            )

            output_col1, output_col2 = st.columns(2)

            with output_col1:

                st.write("**Stream:**")
                st.info(stream)

                st.write("**Pembacaan Alert:**")
                st.info(hasil_pembacaan)

                st.write("**Tim Terkait:**")
                st.info(tim_terkait)

            with output_col2:

                st.write("**Alasan Pembacaan:**")
                st.warning(alasan_pembacaan)

                st.write("**Rekomendasi Tindakan:**")
                st.success(rekomendasi)

                st.write("**Aturan Aktif:**")
                st.info(
                    safe_join(aturan_aktif)
                    or "Tidak ada aturan aktif"
                )


        # ====================================================
        # SIMPAN DATABASE
        # ====================================================

        st.divider()

        st.header("💾 Simpan Hasil Pemrosesan")

        st.caption(
            "Setelah disimpan, form otomatis dikosongkan agar siap "
            "menerima alert berikutnya."
        )

        if st.button(
            "💾 Simpan ke Database",
            use_container_width=True,
        ):

            result_to_save = result.copy()

            result_to_save["raw_text"] = (
                analysis_input
            )

            alert_id = save_alert(result_to_save)

            # Alert ini sudah selesai diurus, sehingga form
            # dikosongkan otomatis agar siap menerima alert
            # berikutnya tanpa perlu menghapus manual.
            st.session_state["single_alert_last_saved_id"] = alert_id
            st.session_state["single_alert_pending_reset"] = True

            st.rerun()


# ============================================================
# 2. UPLOAD DATASET
# ============================================================

with tab_upload:

    st.header("📁 Upload Dataset Alert OCC")

    st.write(
        """
        Menu ini digunakan untuk menerapkan model Rule-Based NLP
        pada sekumpulan teks alert OCC.

        Hasil pemrosesan dapat disimpan ke database dan
        diunduh dalam bentuk CSV.
        """
    )

    uploaded_file = st.file_uploader(
        "Upload file CSV atau Excel:",
        type=[
            "csv",
            "xlsx",
        ],
        key="dataset_upload",
    )

    if uploaded_file is not None:

        try:

            df = read_uploaded_file(uploaded_file)

        except Exception as error:

            st.error(
                f"Gagal membaca file: {error}"
            )

            st.stop()

        st.subheader("Preview Dataset")

        st.write(
            f"Jumlah baris: **{len(df)}**"
        )

        st.dataframe(
            df.head(10),
            use_container_width=True,
            hide_index=True,
        )

        text_column = st.selectbox(
            "Pilih kolom teks alert:",
            options=df.columns.tolist(),
        )

        if st.button(
            "🚀 Proses Dataset",
            type="primary",
            use_container_width=True,
        ):

            if df.empty:

                st.warning(
                    "Dataset kosong."
                )

            else:

                results = []

                progress = st.progress(0)
                status = st.empty()

                total_rows = len(df)

                for position, (_, row) in enumerate(
                    df.iterrows(),
                    start=1,
                ):

                    value = row[text_column]

                    if (
                        pd.notna(value)
                        and str(value).strip()
                    ):

                        text = str(value)

                        result = process_alert(text)

                        result["raw_text"] = text

                        alert_id = save_alert(result)

                        results.append(
                            {
                                "database_id": alert_id,

                                "raw_text": text,

                                "stream": result.get(
                                    "stream",
                                    "UNKNOWN",
                                ),

                                "hasil_pembacaan":
                                    result.get(
                                        "hasil_pembacaan",
                                        "",
                                    ),

                                "aturan_aktif":
                                    safe_join(
                                        result.get(
                                            "aturan_aktif",
                                            [],
                                        )
                                    ),

                                "rekomendasi":
                                    result.get(
                                        "rekomendasi",
                                        "",
                                    ),
                            }
                        )

                    progress.progress(
                        position / total_rows
                    )

                    status.text(
                        f"Memproses {position} "
                        f"dari {total_rows} baris"
                    )

                st.success(
                    f"{len(results)} alert berhasil "
                    "diproses dan disimpan."
                )

                if results:

                    result_df = pd.DataFrame(results)

                    st.subheader(
                        "📋 Hasil Pemrosesan"
                    )

                    st.dataframe(
                        result_df,
                        use_container_width=True,
                        hide_index=True,
                    )

                    st.download_button(
                        "⬇️ Download Hasil Pemrosesan",
                        data=result_df.to_csv(
                            index=False
                        ),
                        file_name=(
                            "hasil_pemrosesan_alert.csv"
                        ),
                        mime="text/csv",
                        use_container_width=True,
                    )


# ============================================================
# 3. DATABASE
# ============================================================

with tab_database:

    st.header("🗄️ Database Hasil Pemrosesan")

    alert_df = get_all_alerts()

    if alert_df.empty:

        st.info(
            "Belum ada data alert tersimpan."
        )

    else:

        st.write(
            f"Total alert tersimpan: "
            f"**{len(alert_df)}**"
        )

        display_columns = [
            "id",
            "timestamp",
            "stream",
            "hasil_pembacaan",
            "tim_terkait",
            "aturan_aktif",
        ]

        display_columns = [
            column
            for column in display_columns
            if column in alert_df.columns
        ]

        st.dataframe(
            alert_df[display_columns],
            use_container_width=True,
            hide_index=True,
        )

        st.divider()

        st.subheader("📄 Detail Alert")

        selected_alert_id = st.selectbox(
            "Pilih ID Alert:",
            options=alert_df["id"].tolist(),
        )

        detail = get_alert_by_id(
            selected_alert_id
        )

        if detail:

            aturan_aktif_db = safe_json_load(
                detail.get(
                    "aturan_aktif",
                    "[]",
                ),
                [],
            )

            tokens_db = safe_json_load(
                detail.get(
                    "tokens",
                    "{}",
                ),
                {},
            )

            parsed_data_db = safe_json_load(
                detail.get(
                    "parsed_data",
                    "{}",
                ),
                {},
            )

            facts_db = safe_json_load(
                detail.get(
                    "facts",
                    "[]",
                ),
                [],
            )

            col1, col2 = st.columns(2)

            with col1:

                st.write(
                    "**ID:**",
                    detail.get("id"),
                )

                st.write(
                    "**Timestamp:**",
                    detail.get("timestamp"),
                )

                st.write(
                    "**Stream:**",
                    detail.get("stream"),
                )

                st.write(
                    "**Tim Terkait:**",
                    detail.get("tim_terkait"),
                )

                st.write(
                    "**Aturan Aktif:**",
                    safe_join(aturan_aktif_db)
                    or "-",
                )

            with col2:

                st.write(
                    "**Pembacaan Alert:**"
                )

                st.info(
                    detail.get(
                        "hasil_pembacaan",
                        "",
                    )
                )

                st.write(
                    "**Alasan Pembacaan:**"
                )

                st.warning(
                    detail.get(
                        "alasan_pembacaan",
                        "",
                    )
                )

                st.write(
                    "**Rekomendasi Tindakan:**"
                )

                st.success(
                    detail.get(
                        "rekomendasi",
                        "",
                    )
                )

            with st.expander(
                "🔎 Hasil Scanner"
            ):

                st.json(tokens_db)

            with st.expander(
                "🧩 Hasil Parser"
            ):

                st.json(parsed_data_db)

            with st.expander(
                "🔄 Fakta Translator"
            ):

                st.json(facts_db)

            with st.expander(
                "📄 Raw Alert Text"
            ):

                st.code(
                    detail.get(
                        "raw_text",
                        "",
                    ),
                    language=None,
                )

        st.divider()

        st.subheader(
            "🗑️ Kelola Database"
        )

        selected_alert_ids = st.multiselect(
            "Pilih ID alert yang akan dihapus:",
            options=alert_df["id"].tolist(),
        )

        col_delete, col_delete_all = st.columns(2)

        with col_delete:

            if st.button(
                "Hapus Alert Terpilih",
                use_container_width=True,
            ):

                if not selected_alert_ids:

                    st.warning(
                        "Pilih minimal satu alert."
                    )

                else:

                    for alert_id in selected_alert_ids:

                        delete_alert(alert_id)

                    st.success(
                        "Alert berhasil dihapus."
                    )

                    st.rerun()

        with col_delete_all:

            confirm_delete = st.checkbox(
                "Konfirmasi hapus seluruh alert"
            )

            if st.button(
                "Hapus Semua Alert",
                use_container_width=True,
            ):

                if not confirm_delete:

                    st.warning(
                        "Centang konfirmasi terlebih dahulu."
                    )

                else:

                    delete_all_alerts()

                    st.success(
                        "Seluruh alert berhasil dihapus."
                    )

                    st.rerun()


# ============================================================
# 4. DASHBOARD
# ============================================================

with tab_dashboard:

    st.header(
        "📈 Dashboard Hasil Pemrosesan"
    )

    alert_df = get_all_alerts()

    if alert_df.empty:

        st.info(
            "Belum ada data untuk dashboard."
        )

    else:

        rule_counter = count_active_rules(
            alert_df
        )

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "Total Alert",
            len(alert_df),
        )

        col2.metric(
            "Jumlah Stream",
            alert_df["stream"].nunique(),
        )

        col3.metric(
            "Aturan Pernah Aktif",
            len(rule_counter),
        )


        # ====================================================
        # DISTRIBUSI STREAM
        # ====================================================

        st.subheader(
            "Distribusi Stream"
        )

        stream_counts = (
            alert_df["stream"]
            .value_counts(dropna=False)
            .rename_axis("stream")
            .reset_index(name="jumlah")
        )

        fig_stream = px.bar(
            stream_counts,
            x="stream",
            y="jumlah",
            title="Distribusi Alert Berdasarkan Stream",
        )

        st.plotly_chart(
            fig_stream,
            use_container_width=True,
        )


        # ====================================================
        # DISTRIBUSI ATURAN
        # ====================================================

        st.subheader(
            "Distribusi Aturan Produksi Aktif"
        )

        if rule_counter:

            rule_df = pd.DataFrame(
                [
                    {
                        "aturan_produksi": rule,
                        "jumlah": count,
                    }
                    for rule, count
                    in rule_counter.items()
                ]
            )

            rule_df = rule_df.sort_values(
                "jumlah",
                ascending=False,
            )

            fig_rule = px.bar(
                rule_df,
                x="aturan_produksi",
                y="jumlah",
                title=(
                    "Frekuensi Aktivasi "
                    "Aturan Produksi"
                ),
            )

            st.plotly_chart(
                fig_rule,
                use_container_width=True,
            )

        else:

            st.info(
                "Belum ada aturan produksi "
                "yang pernah aktif."
            )


        # ====================================================
        # RINGKASAN STREAM DAN ATURAN
        # ====================================================

        st.subheader(
            "Ringkasan Stream dan Aturan Produksi"
        )

        summary_rows = []

        for _, row in alert_df.iterrows():

            rules = safe_json_load(
                row["aturan_aktif"],
                [],
            )

            if rules:

                for rule in rules:

                    summary_rows.append(
                        {
                            "stream": row["stream"],
                            "aturan_produksi": rule,
                        }
                    )

            else:

                summary_rows.append(
                    {
                        "stream": row["stream"],
                        "aturan_produksi":
                            "TIDAK ADA ATURAN",
                    }
                )

        summary_df = pd.DataFrame(
            summary_rows
        )

        summary = (
            summary_df
            .groupby(
                [
                    "stream",
                    "aturan_produksi",
                ],
                dropna=False,
            )
            .size()
            .reset_index(name="jumlah")
        )

        st.dataframe(
            summary,
            use_container_width=True,
            hide_index=True,
        )


# ============================================================
# 5. CHATBOT
# ============================================================

with tab_chatbot:

    st.header(
        "💬 Chatbot Informasi Alert"
    )

    st.write(
        """
        Chatbot menyediakan antarmuka tanya-jawab
        mengenai stream, model Rule-Based NLP,
        aturan produksi, serta hasil pemrosesan
        teks alert.
        """
    )

    st.info(
        "Contoh pertanyaan:\n\n"
        "- Apa itu NGSSP?\n"
        "- Aturan produksi apa saja?\n"
        "- Jelaskan R-NGSSP-02\n"
        "- cek alert: <teks alert>\n"
        "- kenapa alert: <teks alert>\n"
        "- rekomendasi alert: <teks alert>"
    )

    question = st.text_area(
        "Masukkan pertanyaan:",
        height=180,
        key="chatbot_question",
    )

    if st.button(
        "💬 Kirim Pertanyaan",
        type="primary",
        use_container_width=True,
    ):

        if not question.strip():

            st.warning(
                "Masukkan pertanyaan terlebih dahulu."
            )

        else:

            try:

                answer = chatbot_response(
                    question
                )

                st.info(answer)

            except Exception as error:

                st.error(
                    "Chatbot gagal memproses "
                    f"pertanyaan: {error}"
                )

# ============================================================
# 5. PENGUJIAN (AKURASI + PEMBOBOTAN NLP)
# ============================================================

with tab_evaluasi:

    st.header("🧪 Pengujian Model Rule-Based NLP")

    st.write(
        """
        Menu ini mengukur performa model dengan membandingkan
        keluaran model terhadap **label kebenaran (ground truth)**
        pada dataset berlabel.

        Metrik yang dihitung: **akurasi**, precision, recall,
        F1-score, confusion matrix, serta rata-rata
        **skor kepercayaan (pembobotan NLP)** pada prediksi
        benar vs salah.

        Format dataset (CSV/Excel) memerlukan kolom:
        `text`, `label_stream`, `label_rule`
        (isi `label_rule` dengan kode aturan seperti `R-BWCE-01`
        atau `NONE` bila tidak ada aturan yang seharusnya aktif).
        """
    )

    # --------------------------------------------------------
    # BAGIAN 1 — AKURASI EKSTRAKSI (INFORMATION EXTRACTION)
    # --------------------------------------------------------

    st.subheader("1️⃣ Akurasi Ekstraksi Informasi")

    st.write(
        """
        Bagian ini mengukur kemampuan **Scanner dan Parser**
        mengekstraksi informasi dari teks alert — inti dari
        penelitian ini, dan satu-satunya bagian model yang
        benar-benar dapat gagal. Datanya berasal dari menu
        🏷️ Pelabelan → *Verifikasi Ekstraksi*.
        """
    )

    rekap_ekstraksi = evaluasi_ekstraksi()

    if rekap_ekstraksi["n_alert"] == 0:

        st.info(
            "Belum ada data verifikasi ekstraksi. Silakan periksa "
            "beberapa alert pada menu 🏷️ Pelabelan → Verifikasi "
            "Ekstraksi terlebih dahulu."
        )

    else:

        e1, e2, e3 = st.columns(3)
        e1.metric("Alert Diperiksa", rekap_ekstraksi["n_alert"])
        e2.metric(
            "Akurasi Field",
            f"{rekap_ekstraksi['akurasi_field'] * 100:.2f}%",
            help=(
                "Proporsi field yang benar diekstraksi, dihitung "
                "atas seluruh pasangan (alert, field)."
            ),
        )
        e3.metric(
            "Akurasi Alert",
            f"{rekap_ekstraksi['akurasi_alert'] * 100:.2f}%",
            help=(
                "Proporsi alert yang SELURUH field-nya benar. "
                "Ukuran yang lebih ketat."
            ),
        )

        st.markdown("**Akurasi per field** (terendah lebih dulu)")
        st.dataframe(
            rekap_ekstraksi["per_field"],
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            "Field dengan akurasi rendah menunjukkan pola regex "
            "yang belum menangani variasi format. Inilah bahan "
            "utama analisis kesalahan pada bab pengujian."
        )

        st.markdown("**Akurasi per stream**")
        st.dataframe(
            rekap_ekstraksi["per_stream"],
            use_container_width=True,
            hide_index=True,
        )

        if not rekap_ekstraksi["kesalahan"].empty:

            st.markdown("**Daftar kesalahan ekstraksi**")
            st.dataframe(
                rekap_ekstraksi["kesalahan"],
                use_container_width=True,
                hide_index=True,
            )

            st.download_button(
                "⬇️ Download Kesalahan Ekstraksi (CSV)",
                data=rekap_ekstraksi["kesalahan"]
                .to_csv(index=False)
                .encode("utf-8"),
                file_name="kesalahan_ekstraksi.csv",
                mime="text/csv",
                use_container_width=True,
            )

        st.download_button(
            "⬇️ Download Data Verifikasi Lengkap (CSV)",
            data=get_extraction_checks()
            .to_csv(index=False)
            .encode("utf-8"),
            file_name="verifikasi_ekstraksi.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.divider()

    # --------------------------------------------------------
    # BAGIAN 2 — AKURASI ATURAN (UJUNG-KE-UJUNG)
    # --------------------------------------------------------

    st.subheader("2️⃣ Akurasi Aturan (Ujung-ke-Ujung)")

    st.warning(
        "⚠️ **Bacalah angka di bagian ini dengan hati-hati.** "
        "Evaluator bersifat deterministik: bila fakta sudah benar, "
        "hasil aturan IF-THEN pasti benar. Karena pelabel juga "
        "menerapkan aturan yang sama, akurasi di sini cenderung "
        "mendekati 100% dengan sendirinya. Nilainya terletak pada "
        "kemampuannya menangkap kegagalan ekstraksi secara "
        "ujung-ke-ujung, bukan sebagai bukti kecerdasan model. "
        "Laporkan berdampingan dengan akurasi ekstraksi di atas."
    )

    sumber = st.radio(
        "Sumber data uji:",
        options=[
            "Dataset berlabel dari database (menu Pelabelan)",
            "Upload file berlabel",
        ],
        key="eval_sumber",
    )

    eval_df = None

    # --------------------------------------------------------
    # SUMBER: DATABASE
    # --------------------------------------------------------

    if sumber.startswith("Dataset berlabel dari database"):

        eval_df = get_all_labels()

        if eval_df.empty:

            st.info(
                "Belum ada data berlabel di database. Silakan labeli "
                "alert terlebih dahulu pada menu 🏷️ Pelabelan, atau "
                "pilih opsi upload file."
            )

            eval_df = None

        else:

            st.success(
                f"Menggunakan **{len(eval_df)}** alert berlabel "
                "dari database."
            )

    # --------------------------------------------------------
    # SUMBER: UPLOAD
    # --------------------------------------------------------

    else:

        eval_file = st.file_uploader(
            "Upload dataset berlabel (CSV atau Excel):",
            type=["csv", "xlsx"],
            key="eval_upload",
        )

        if eval_file is not None:

            try:
                eval_df = read_uploaded_file(eval_file)
            except Exception as error:
                st.error(f"Gagal membaca file: {error}")
                eval_df = None

    if eval_df is not None:

        st.subheader("Preview Dataset Uji")
        st.dataframe(
            eval_df.head(10),
            use_container_width=True,
            hide_index=True,
        )

        columns = eval_df.columns.tolist()

        col_a, col_b, col_c = st.columns(3)

        with col_a:
            text_col = st.selectbox(
                "Kolom teks alert:",
                options=columns,
                index=columns.index("text") if "text" in columns else 0,
            )

        with col_b:
            stream_col = st.selectbox(
                "Kolom label stream:",
                options=columns,
                index=(
                    columns.index("label_stream")
                    if "label_stream" in columns
                    else 0
                ),
            )

        with col_c:
            rule_col = st.selectbox(
                "Kolom label aturan:",
                options=columns,
                index=(
                    columns.index("label_rule")
                    if "label_rule" in columns
                    else 0
                ),
            )

        if st.button(
            "🚀 Jalankan Pengujian",
            type="primary",
            use_container_width=True,
        ):

            from evaluation import evaluate_dataframe

            hasil = evaluate_dataframe(
                eval_df,
                text_col=text_col,
                stream_col=stream_col,
                rule_col=rule_col,
            )

            st.subheader("📊 Ringkasan Akurasi")

            m1, m2, m3 = st.columns(3)
            m1.metric(
                "Akurasi Stream",
                f"{hasil['akurasi_stream'] * 100:.2f}%",
            )
            m2.metric(
                "Akurasi Aturan",
                f"{hasil['akurasi_rule'] * 100:.2f}%",
            )
            m3.metric(
                "Data Uji",
                f"{hasil['n']}",
            )

            # Bila sebagian label direvisi setelah pelabel melihat
            # keluaran model, akurasi pada label yang tidak direvisi
            # dilaporkan terpisah sebagai estimasi konservatif.
            if hasil.get("n_direvisi"):

                st.warning(
                    f"⚠️ **{hasil['n_direvisi']} dari {hasil['n']}** label "
                    "direvisi setelah pelabel melihat keluaran model, "
                    "sehingga tidak sepenuhnya independen."
                )

                if hasil.get("akurasi_rule_murni") is not None:

                    st.write(
                        f"Akurasi pada **{hasil['n_murni']}** label yang "
                        "**tidak direvisi** (estimasi lebih konservatif, "
                        "angka inilah yang sebaiknya dilaporkan di naskah):"
                    )

                    k1, k2 = st.columns(2)
                    k1.metric(
                        "Akurasi Stream (murni)",
                        f"{hasil['akurasi_stream_murni'] * 100:.2f}%",
                    )
                    k2.metric(
                        "Akurasi Aturan (murni)",
                        f"{hasil['akurasi_rule_murni'] * 100:.2f}%",
                    )

            st.subheader("🎯 Metrik Prediksi Aturan (per kelas)")
            rule_metric_df = pd.DataFrame(
                hasil["rule_per_class"]
            ).T.reset_index().rename(columns={"index": "aturan"})
            st.dataframe(
                rule_metric_df,
                use_container_width=True,
                hide_index=True,
            )

            mac = hasil["rule_macro"]
            st.caption(
                f"Macro-average — precision: {mac['precision']:.4f} | "
                f"recall: {mac['recall']:.4f} | f1: {mac['f1']:.4f}"
            )

            st.subheader("🔀 Confusion Matrix — Aturan")
            st.dataframe(
                hasil["rule_confusion"],
                use_container_width=True,
            )

            st.subheader("🔀 Confusion Matrix — Stream")
            st.dataframe(
                hasil["stream_confusion"],
                use_container_width=True,
            )

            st.subheader("⚖️ Pembobotan / Skor Kepercayaan NLP")
            s1, s2 = st.columns(2)
            s1.metric(
                "Rata-rata skor (prediksi BENAR)",
                f"{hasil['skor_rata_benar'] * 100:.2f}%",
            )
            s2.metric(
                "Rata-rata skor (prediksi SALAH)",
                f"{hasil['skor_rata_salah'] * 100:.2f}%",
            )
            st.caption(
                "Skor kepercayaan pada prediksi benar diharapkan "
                "lebih tinggi daripada prediksi salah."
            )

            st.subheader("📋 Detail Per Baris")
            st.dataframe(
                hasil["detail"],
                use_container_width=True,
                hide_index=True,
            )

            st.download_button(
                "⬇️ Download Hasil Pengujian (CSV)",
                data=hasil["detail"].to_csv(index=False).encode("utf-8"),
                file_name="hasil_pengujian.csv",
                mime="text/csv",
                use_container_width=True,
            )

    elif sumber == "Upload file berlabel":
        st.info(
            "Unggah dataset berlabel untuk memulai pengujian. "
            "Template pengisiannya dapat diunduh di menu 🏷️ Pelabelan."
        )


# ============================================================
# 7. PELABELAN (GROUND TRUTH)
# ============================================================

with tab_pelabelan:

    st.header("🏷️ Pelabelan Alert (Ground Truth)")

    st.write(
        """
        Menu ini digunakan untuk membuat **label kebenaran
        (ground truth)** yang menjadi dasar pengujian akurasi.

        Label diisi berdasarkan **penilaian manusia** (personel OCC),
        yaitu kondisi apa yang sebenarnya terjadi pada alert tersebut
        dan bagaimana seharusnya alert itu ditangani.
        """
    )

    st.warning(
        "⚠️ **Penting:** labeli berdasarkan penilaian Anda sendiri, "
        "**bukan** dengan melihat keluaran program. Label yang diambil "
        "dari hasil model membuat pengujian menjadi melingkar "
        "(model diuji dengan jawabannya sendiri) sehingga akurasinya "
        "tidak bermakna. Karena itu menu ini sengaja **tidak** "
        "menampilkan prediksi model saat Anda melabeli."
    )

    total_label = count_labels()

    st.info(f"Jumlah alert yang sudah dilabeli: **{total_label}**")

    # --------------------------------------------------------
    # UNDUH TEMPLATE
    # --------------------------------------------------------

    st.subheader("📥 Contoh / Template Pelabelan")

    st.write(
        """
        Unduh file contoh berikut sebagai acuan format. File Excel
        berisi 3 sheet: **template** (baris contoh), **panduan_label**
        (definisi tiap label), dan **petunjuk** (aturan pengisian).

        Hapus baris contoh di dalamnya, lalu ganti dengan **alert asli**
        yang Anda labeli sendiri.
        """
    )

    unduh_1, unduh_2 = st.columns(2)

    with unduh_1:
        st.download_button(
            "⬇️ Download Template Excel (.xlsx)",
            data=build_template_excel(),
            file_name="template_pelabelan.xlsx",
            mime=(
                "application/vnd.openxmlformats-officedocument"
                ".spreadsheetml.sheet"
            ),
            use_container_width=True,
        )

    with unduh_2:
        st.download_button(
            "⬇️ Download Template CSV (.csv)",
            data=build_template_csv(),
            file_name="template_pelabelan.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with st.expander("📖 Lihat panduan label"):

        for label, penjelasan in LABEL_GUIDE.items():
            st.markdown(f"**{label}** — {penjelasan}")

    st.divider()

    # --------------------------------------------------------
    # MODE PELABELAN
    # --------------------------------------------------------

    mode = st.radio(
        "Pilih cara pelabelan:",
        options=[
            "Verifikasi Ekstraksi (disarankan)",
            "Satu per satu (1-1)",
            "Batch (upload file)",
        ],
        key="mode_pelabelan",
    )

    # ========================================================
    # MODE 1-1
    # ========================================================

    # ========================================================
    # MODE VERIFIKASI EKSTRAKSI
    # ========================================================
    #
    # Menguji bagian model yang benar-benar dapat gagal, yaitu
    # Scanner dan Parser (ekstraksi informasi). Acuan kebenaran
    # adalah TEKS ALERT itu sendiri, bukan penilaian pemeriksa,
    # sehingga pengujian ini tidak melingkar.

    if mode == "Verifikasi Ekstraksi (disarankan)":

        if st.session_state.get("verif_pending_reset"):
            for kunci in list(st.session_state.keys()):
                if str(kunci).startswith("verif_text_"):
                    st.session_state.pop(kunci, None)
            st.session_state.pop("verif_hasil", None)
            st.session_state["verif_form_no"] = (
                st.session_state.get("verif_form_no", 0) + 1
            )
            st.session_state["verif_pending_reset"] = False

        st.subheader("🔎 Verifikasi Hasil Ekstraksi")

        st.info(
            "**Mengapa cara ini yang disarankan.** Evaluator model "
            "bersifat deterministik: bila fakta sudah benar, hasil "
            "aturan IF-THEN pasti benar. Karena pemeriksa juga "
            "menerapkan aturan yang sama, akurasi aturan cenderung "
            "mendekati 100% dengan sendirinya dan kurang bermakna.\n\n"
            "Bagian yang benar-benar dapat gagal adalah **ekstraksi** "
            "(Scanner dan Parser), dan itulah inti penelitian Anda. "
            "Di sini acuan kebenarannya adalah **teks alert itu "
            "sendiri** — bukan pendapat Anda, bukan keluaran model — "
            "sehingga hasilnya objektif."
        )

        st.warning(
            "⚠️ **Bacalah teks alert, jangan hanya menyetujui tabel.** "
            "Seluruh baris tercentang benar secara bawaan. Bila Anda "
            "menyetujui tanpa memeriksa, akurasinya menjadi 100% "
            "palsu. Baris yang ditandai mencurigakan oleh sistem "
            "wajib diperiksa lebih teliti."
        )

        verif_no = st.session_state.get("verif_form_no", 0)

        verif_text = st.text_area(
            "Teks alert asli:",
            height=150,
            key=f"verif_text_{verif_no}",
            placeholder="Tempel satu teks alert di sini...",
        )

        v1, v2 = st.columns([3, 1])

        with v1:
            ekstrak_ditekan = st.button(
                "🔍 Ekstrak & Periksa",
                type="primary",
                use_container_width=True,
            )

        with v2:
            if st.button(
                "🔄 Alert Baru",
                use_container_width=True,
                key="verif_reset",
            ):
                st.session_state["verif_pending_reset"] = True
                st.rerun()

        if ekstrak_ditekan:

            if not verif_text.strip():
                st.warning("Teks alert belum diisi.")
            else:
                st.session_state["verif_hasil"] = {
                    "text": verif_text.strip(),
                    "ekstraksi": ambil_ekstraksi(verif_text.strip()),
                }

        hasil_verif = st.session_state.get("verif_hasil")

        if hasil_verif:

            teks_alert = hasil_verif["text"]
            ekstraksi = hasil_verif["ekstraksi"]
            stream_terdeteksi = ekstraksi["stream"]

            st.markdown("#### Teks alert yang diperiksa")
            st.code(teks_alert, language=None)

            st.markdown(
                f"**Stream terdeteksi model:** `{stream_terdeteksi}`"
            )

            if stream_terdeteksi == "UNKNOWN":
                st.error(
                    "Model tidak mengenali stream alert ini. "
                    "Ini sendiri merupakan kegagalan Scanner dan "
                    "layak dicatat sebagai temuan."
                )

            if ekstraksi["curiga"]:
                st.error(
                    "🚩 **Sistem menandai ekstraksi ini "
                    "mencurigakan — periksa dengan teliti:**"
                )
                for c in ekstraksi["curiga"]:
                    st.write(f"- {c}")
            elif ekstraksi["fields"]:
                st.success(
                    "Pemeriksaan konsistensi otomatis tidak "
                    "menemukan kejanggalan. Tetap bandingkan "
                    "dengan teks di atas."
                )

            if not ekstraksi["fields"]:

                st.write(
                    "Tidak ada field yang dapat diperiksa untuk "
                    "stream ini."
                )

            else:

                st.markdown("#### Periksa tiap field")
                st.caption(
                    "Hapus centang pada field yang SALAH, lalu isi "
                    "nilai yang seharusnya sesuai teks alert."
                )

                tabel = pd.DataFrame([
                    {
                        "field": f["field"],
                        "nilai_terekstraksi": f["nilai_terekstraksi"],
                        "benar": True,
                        "nilai_seharusnya": "",
                    }
                    for f in ekstraksi["fields"]
                ])

                edited = st.data_editor(
                    tabel,
                    use_container_width=True,
                    hide_index=True,
                    disabled=["field", "nilai_terekstraksi"],
                    column_config={
                        "field": st.column_config.TextColumn(
                            "Field",
                        ),
                        "nilai_terekstraksi": (
                            st.column_config.TextColumn(
                                "Nilai hasil ekstraksi",
                            )
                        ),
                        "benar": st.column_config.CheckboxColumn(
                            "Benar?",
                            help=(
                                "Centang bila sesuai teks alert."
                            ),
                        ),
                        "nilai_seharusnya": (
                            st.column_config.TextColumn(
                                "Nilai seharusnya (bila salah)",
                            )
                        ),
                    },
                    key=f"verif_editor_{verif_no}",
                )

                nama_periksa = st.text_input(
                    "Nama/inisial pemeriksa:",
                    key=f"verif_pelabel_{verif_no}",
                    placeholder="mis. IRG",
                )

                if st.button(
                    "💾 Simpan Verifikasi",
                    type="primary",
                    use_container_width=True,
                ):

                    baris = edited.to_dict("records")

                    kurang = [
                        b["field"]
                        for b in baris
                        if not b["benar"]
                        and not str(
                            b.get("nilai_seharusnya", "")
                        ).strip()
                    ]

                    if kurang:
                        st.error(
                            "Field berikut ditandai salah tetapi "
                            "nilai seharusnya belum diisi: "
                            + ", ".join(kurang)
                        )

                    else:

                        no = simpan_verifikasi(
                            raw_text=teks_alert,
                            stream=stream_terdeteksi,
                            hasil_periksa=baris,
                            pelabel=nama_periksa.strip(),
                        )

                        salah = sum(
                            1 for b in baris if not b["benar"]
                        )

                        st.success(
                            f"Verifikasi tersimpan (alert #{no}): "
                            f"{len(baris) - salah} benar, "
                            f"{salah} salah."
                        )

                        st.session_state["verif_pending_reset"] = True
                        st.rerun()

        st.divider()

        st.subheader("📊 Rekap Verifikasi Ekstraksi")

        total_verif = jumlah_alert_terverifikasi()

        if total_verif == 0:

            st.info(
                "Belum ada alert yang diverifikasi. Hasil "
                "perhitungan akurasinya muncul di menu 🧪 Pengujian."
            )

        else:

            rekap = evaluasi_ekstraksi()

            r1, r2, r3 = st.columns(3)
            r1.metric("Alert Diperiksa", rekap["n_alert"])
            r2.metric(
                "Akurasi Field",
                f"{rekap['akurasi_field'] * 100:.2f}%",
            )
            r3.metric(
                "Akurasi Alert",
                f"{rekap['akurasi_alert'] * 100:.2f}%",
                help=(
                    "Alert dianggap benar hanya bila SELURUH "
                    "field-nya benar."
                ),
            )

            with st.expander("🗑️ Hapus semua verifikasi"):
                yakin = st.checkbox(
                    "Saya yakin ingin menghapus semua",
                    key="yakin_hapus_verif",
                )
                if st.button(
                    "Hapus Semua",
                    disabled=not yakin,
                ):
                    hapus_semua_verifikasi()
                    st.success("Seluruh verifikasi dihapus.")
                    st.rerun()

    elif mode == "Satu per satu (1-1)":

        # Pengosongan form dilakukan di awal, sebelum widget dibuat.
        if st.session_state.get("pelabelan_pending_reset"):

            for kunci in (
                "label_text_input",
                "label_stream_input",
                "label_rule_input",
                "catatan_input",
            ):
                st.session_state.pop(kunci, None)

            st.session_state["pelabelan_pending_reset"] = False

        st.subheader("✍️ Pelabelan Satu per Satu")

        st.caption(
            "Prosedur dua tahap — **Tahap 1:** Anda menentukan label "
            "tanpa melihat keluaran model. **Tahap 2:** setelah label "
            "tersimpan, keluaran model ditampilkan sebagai pembanding. "
            "Urutan ini menjaga label tetap independen sehingga akurasi "
            "yang dihitung nanti bermakna."
        )

        # ----------------------------------------------------
        # TAHAP 2 — PEMBANDING (setelah label tersimpan)
        # ----------------------------------------------------

        tersimpan_id = st.session_state.get("label_tersimpan_id")

        if tersimpan_id:

            baris = get_label_by_id(tersimpan_id)

            if baris:

                st.success(
                    f"✅ Tahap 1 selesai — label tersimpan "
                    f"(ID: {tersimpan_id})."
                )

                st.markdown("#### 🔍 Tahap 2 — Pembanding: Jawaban Model")

                hasil_model = process_alert(baris["raw_text"])

                model_stream = hasil_model.get("stream", "UNKNOWN")
                model_aturan = hasil_model.get("aturan_aktif", [])
                model_rule = model_aturan[0] if model_aturan else "NONE"

                cocok_stream = model_stream == baris["label_stream"]
                cocok_rule = model_rule == baris["label_rule"]

                banding = pd.DataFrame([
                    {
                        "aspek": "Stream",
                        "label_anda": baris["label_stream"],
                        "jawaban_model": model_stream,
                        "sepakat": "✅" if cocok_stream else "❌",
                    },
                    {
                        "aspek": "Aturan",
                        "label_anda": baris["label_rule"],
                        "jawaban_model": model_rule,
                        "sepakat": "✅" if cocok_rule else "❌",
                    },
                ])

                st.dataframe(
                    banding,
                    use_container_width=True,
                    hide_index=True,
                )

                if cocok_stream and cocok_rule:

                    st.info(
                        "Model sepakat dengan label Anda. "
                        "Lanjutkan ke alert berikutnya."
                    )

                else:

                    st.warning(
                        "**Model tidak sepakat dengan label Anda.** "
                        "Ini justru temuan yang berharga — bisa berarti "
                        "model keliru (bahan analisis kesalahan di bab "
                        "pengujian), atau Anda yang keliru membaca teks. "
                        "Bila model yang keliru, **biarkan label Anda "
                        "apa adanya** — ketidaksepakatan inilah yang "
                        "diukur oleh pengujian."
                    )

                with st.expander("Lihat penjelasan lengkap dari model"):

                    st.write(
                        f"**Pembacaan:** "
                        f"{hasil_model.get('hasil_pembacaan', '-')}"
                    )
                    st.write(
                        f"**Alasan:** "
                        f"{hasil_model.get('alasan_pembacaan', '-')}"
                    )
                    st.write(
                        f"**Skor kepercayaan:** "
                        f"{hasil_model.get('persen_kepercayaan', '-')}"
                    )

                aksi_1, aksi_2 = st.columns(2)

                with aksi_1:
                    if st.button(
                        "➡️ Lanjut ke Alert Berikutnya",
                        type="primary",
                        use_container_width=True,
                    ):
                        st.session_state["label_tersimpan_id"] = None
                        st.session_state["tampilkan_revisi"] = False
                        st.session_state["pelabelan_pending_reset"] = True
                        st.rerun()

                with aksi_2:
                    if st.button(
                        "✏️ Revisi Label Ini",
                        use_container_width=True,
                        help=(
                            "Hanya bila Anda menyadari kekeliruan Anda "
                            "sendiri, misalnya salah membaca teks alert. "
                            "Bukan untuk menyamakan label dengan model."
                        ),
                    ):
                        st.session_state["tampilkan_revisi"] = True

                # ------------------------------------------------
                # FORM REVISI
                # ------------------------------------------------

                if st.session_state.get("tampilkan_revisi"):

                    st.markdown("##### ✏️ Revisi Label")

                    st.caption(
                        "⚠️ Revisi dicatat secara terbuka: label awal "
                        "Anda tetap tersimpan, baris ditandai "
                        "`direvisi`, dan menu Pengujian akan melaporkan "
                        "akurasi pada label yang tidak direvisi secara "
                        "terpisah. Revisi hanya sah bila Anda memperbaiki "
                        "kekeliruan Anda sendiri — bukan mengikuti model."
                    )

                    rev_1, rev_2 = st.columns(2)

                    with rev_1:
                        rev_stream = st.selectbox(
                            "Label stream (revisi):",
                            options=LABEL_STREAM_OPTIONS,
                            index=LABEL_STREAM_OPTIONS.index(
                                baris["label_stream"]
                            ),
                            key="rev_stream",
                        )

                    with rev_2:
                        opsi_rev = VALID_RULE_BY_STREAM.get(
                            rev_stream,
                            LABEL_RULE_OPTIONS,
                        )

                        rev_rule = st.selectbox(
                            "Label aturan (revisi):",
                            options=opsi_rev,
                            key="rev_rule",
                        )

                    alasan_rev = st.text_input(
                        "Alasan revisi (wajib):",
                        key="alasan_rev",
                        placeholder=(
                            "mis. saya salah membaca nilai val pada teks"
                        ),
                    )

                    if st.button(
                        "💾 Simpan Revisi",
                        use_container_width=True,
                    ):

                        error_rev = revise_label(
                            row_id=tersimpan_id,
                            label_stream_baru=rev_stream,
                            label_rule_baru=rev_rule,
                            alasan_revisi=alasan_rev,
                        )

                        if error_rev:
                            st.error(error_rev)
                        else:
                            st.success(
                                "Revisi tersimpan dan tercatat "
                                "secara transparan."
                            )
                            st.session_state["tampilkan_revisi"] = False
                            st.rerun()

        # ----------------------------------------------------
        # TAHAP 1 — PELABELAN BUTA
        # ----------------------------------------------------

        else:

            st.markdown("#### 🏷️ Tahap 1 — Tentukan Label Anda")

            label_text = st.text_area(
                "Teks alert asli:",
                height=180,
                key="label_text_input",
                placeholder="Tempel satu teks alert di sini...",
            )

            kol_1, kol_2 = st.columns(2)

            with kol_1:
                pilih_stream = st.selectbox(
                    "Label stream (menurut Anda):",
                    options=LABEL_STREAM_OPTIONS,
                    key="label_stream_input",
                )

            with kol_2:
                # Pilihan aturan dibatasi sesuai stream yang dipilih
                # agar label tetap konsisten.
                opsi_rule = VALID_RULE_BY_STREAM.get(
                    pilih_stream,
                    LABEL_RULE_OPTIONS,
                )

                pilih_rule = st.selectbox(
                    "Label aturan (menurut Anda):",
                    options=opsi_rule,
                    key="label_rule_input",
                )

            st.caption(
                f"ℹ️ {LABEL_GUIDE.get(pilih_rule, '')}"
            )

            kol_3, kol_4 = st.columns(2)

            with kol_3:
                nama_pelabel = st.text_input(
                    "Nama/inisial pelabel:",
                    key="pelabel_input",
                    placeholder="mis. IRG",
                    help=(
                        "Diisi bila pelabelan dilakukan lebih dari satu "
                        "orang, untuk keperluan uji kesepakatan (Kappa)."
                    ),
                )

            with kol_4:
                catatan_label = st.text_input(
                    "Catatan (opsional):",
                    key="catatan_input",
                    placeholder="mis. format tidak biasa, sempat ragu",
                )

            if st.button(
                "💾 Simpan Label & Lihat Jawaban Model",
                type="primary",
                use_container_width=True,
            ):

                if not label_text.strip():

                    st.warning("Teks alert belum diisi.")

                else:

                    error = validate_label(pilih_stream, pilih_rule)

                    if error:

                        st.error(error)

                    else:

                        try:

                            row_id = save_label(
                                raw_text=label_text.strip(),
                                label_stream=pilih_stream,
                                label_rule=pilih_rule,
                                pelabel=nama_pelabel.strip(),
                                catatan=catatan_label.strip(),
                            )

                            st.session_state["label_tersimpan_id"] = row_id
                            st.session_state["tampilkan_revisi"] = False
                            st.rerun()

                        except Exception as error:

                            st.error(f"Gagal menyimpan label: {error}")

    # ========================================================
    # MODE BATCH
    # ========================================================

    else:

        st.subheader("📦 Pelabelan Batch (Upload File)")

        st.write(
            """
            Unggah file CSV/Excel yang **sudah Anda isi labelnya**
            (gunakan template di atas). Baris dengan label yang tidak
            valid akan dilewati dan dilaporkan, tidak disimpan diam-diam.
            """
        )

        label_file = st.file_uploader(
            "Upload file berlabel (CSV atau Excel):",
            type=["csv", "xlsx"],
            key="label_batch_upload",
        )

        if label_file is not None:

            try:
                batch_df = read_uploaded_file(label_file)
            except Exception as error:
                st.error(f"Gagal membaca file: {error}")
                st.stop()

            st.write(f"Jumlah baris: **{len(batch_df)}**")

            st.dataframe(
                batch_df.head(10),
                use_container_width=True,
                hide_index=True,
            )

            kolom_batch = batch_df.columns.tolist()

            b1, b2, b3 = st.columns(3)

            with b1:
                b_text = st.selectbox(
                    "Kolom teks alert:",
                    options=kolom_batch,
                    index=(
                        kolom_batch.index("text")
                        if "text" in kolom_batch
                        else 0
                    ),
                    key="b_text",
                )

            with b2:
                b_stream = st.selectbox(
                    "Kolom label stream:",
                    options=kolom_batch,
                    index=(
                        kolom_batch.index("label_stream")
                        if "label_stream" in kolom_batch
                        else 0
                    ),
                    key="b_stream",
                )

            with b3:
                b_rule = st.selectbox(
                    "Kolom label aturan:",
                    options=kolom_batch,
                    index=(
                        kolom_batch.index("label_rule")
                        if "label_rule" in kolom_batch
                        else 0
                    ),
                    key="b_rule",
                )

            opsi_pelabel = ["(tidak ada)"] + kolom_batch

            b_pelabel = st.selectbox(
                "Kolom pelabel (opsional):",
                options=opsi_pelabel,
                index=(
                    opsi_pelabel.index("pelabel")
                    if "pelabel" in opsi_pelabel
                    else 0
                ),
                key="b_pelabel",
            )

            if st.button(
                "📥 Import Label",
                type="primary",
                use_container_width=True,
            ):

                hasil_import = import_labels_from_dataframe(
                    batch_df,
                    text_col=b_text,
                    stream_col=b_stream,
                    rule_col=b_rule,
                    pelabel_col=(
                        None
                        if b_pelabel == "(tidak ada)"
                        else b_pelabel
                    ),
                )

                st.success(
                    f"{hasil_import['tersimpan']} label berhasil diimpor."
                )

                if hasil_import["dilewati"]:

                    st.warning(
                        f"{hasil_import['dilewati']} baris dilewati "
                        "karena label tidak valid:"
                    )

                    st.dataframe(
                        pd.DataFrame(hasil_import["kesalahan"]),
                        use_container_width=True,
                        hide_index=True,
                    )

    st.divider()

    # --------------------------------------------------------
    # DAFTAR LABEL TERSIMPAN
    # --------------------------------------------------------

    st.subheader("📋 Data Berlabel Tersimpan")

    label_df = get_all_labels()

    if label_df.empty:

        st.info(
            "Belum ada data berlabel. Silakan labeli alert "
            "menggunakan salah satu mode di atas."
        )

    else:

        statistik = label_statistics()

        s1, s2, s3, s4 = st.columns(4)

        s1.metric("Total Berlabel", statistik["total"])
        s2.metric(
            "Jumlah Stream",
            len(statistik["per_stream"]),
        )
        s3.metric(
            "Jumlah Pelabel",
            statistik["jumlah_pelabel"],
        )
        s4.metric(
            "Direvisi",
            f"{statistik['jumlah_direvisi']} "
            f"({statistik['persen_direvisi']}%)",
            help=(
                "Label yang diubah setelah pelabel melihat keluaran "
                "model. Semakin kecil semakin baik. Bila angkanya besar, "
                "pengujian berisiko terpengaruh model."
            ),
        )

        if statistik["persen_direvisi"] > 20:
            st.warning(
                f"⚠️ {statistik['persen_direvisi']}% label direvisi "
                "setelah melihat keluaran model. Proporsi setinggi ini "
                "membuat label kurang independen. Pertimbangkan melabeli "
                "ulang sampel baru tanpa revisi, atau laporkan angka "
                "akurasi pada label yang tidak direvisi saja."
            )

        st.dataframe(
            label_df,
            use_container_width=True,
            hide_index=True,
        )

        st.caption("Sebaran label aturan:")
        st.write(statistik["per_rule"])

        st.download_button(
            "⬇️ Download Dataset Berlabel (CSV)",
            data=label_df[
                ["text", "label_stream", "label_rule", "pelabel"]
            ].to_csv(index=False).encode("utf-8"),
            file_name="dataset_berlabel.csv",
            mime="text/csv",
            use_container_width=True,
        )

        st.caption(
            "Dataset ini otomatis tersedia di menu 🧪 Pengujian "
            "melalui pilihan sumber data 'Dataset berlabel dari database'."
        )

        # ----------------------------------------------------
        # HAPUS LABEL
        # ----------------------------------------------------

        with st.expander("🗑️ Hapus Data Label"):

            hapus_id = st.number_input(
                "ID label yang akan dihapus:",
                min_value=1,
                step=1,
                key="hapus_label_id",
            )

            h1, h2 = st.columns(2)

            with h1:
                if st.button(
                    "Hapus Label Ini",
                    use_container_width=True,
                ):
                    delete_label(int(hapus_id))
                    st.success(f"Label ID {hapus_id} dihapus.")
                    st.rerun()

            with h2:
                konfirmasi = st.checkbox(
                    "Saya yakin ingin menghapus SEMUA label",
                    key="konfirmasi_hapus_label",
                )

                if st.button(
                    "Hapus Semua Label",
                    use_container_width=True,
                    disabled=not konfirmasi,
                ):
                    delete_all_labels()
                    st.success("Seluruh data label dihapus.")
                    st.rerun()