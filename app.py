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


# ============================================================
# KONFIGURASI APLIKASI
# ============================================================

st.set_page_config(
    page_title="OCC Alert Rule-Based NLP",
    page_icon="🚨",
    layout="wide",
)

init_db()


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
    tab_chatbot,
) = st.tabs(
    [
        "📝 Single Alert",
        "📁 Upload Dataset",
        "🗄️ Database",
        "📈 Dashboard",
        "💬 Chatbot",
    ]
)


# ============================================================
# 1. SINGLE ALERT
# ============================================================

with tab_single:

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

    raw_text = st.text_area(
        "Masukkan teks alert:",
        height=220,
        placeholder="Masukkan satu teks alert OCC...",
        key="single_alert_input",
    )

    if st.button(
        "🚀 Proses Alert",
        type="primary",
        use_container_width=True,
    ):

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

        if st.session_state.get(
            "analysis_saved",
            False,
        ):

            st.success(
                "Hasil pemrosesan sudah disimpan "
                "ke database."
            )

        else:

            if st.button(
                "💾 Simpan ke Database",
                use_container_width=True,
            ):

                result_to_save = result.copy()

                result_to_save["raw_text"] = (
                    analysis_input
                )

                alert_id = save_alert(result_to_save)

                st.session_state["analysis_saved"] = True

                st.success(
                    f"Hasil berhasil disimpan "
                    f"dengan ID {alert_id}."
                )

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