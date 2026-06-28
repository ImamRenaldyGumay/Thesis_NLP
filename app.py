import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import time
from datetime import datetime

# Import modul lokal
from rules import process_alert, process_alerts_batch, detect_stream
from chatbot import chatbot_respond
from database import (
    init_database, 
    insert_alert, 
    insert_alerts_batch,
    get_all_alerts, 
    get_alert_stats, 
    clear_database,
    # ========== FUNGSI BARU UNTUK AKURASI ==========
    calculate_accuracy,
    get_confusion_matrix_data,
    get_unprocessed_alerts,
    update_alert_with_nlp,
    count_unprocessed
)

init_database()

st.set_page_config(page_title="Alert Re-Scoring System + DB", page_icon="🚨", layout="wide")
st.title("🚨 Alert Re-Scoring System with Database")
st.markdown("### Rule-Based NLP + Sistem Pakar (Adaptasi Jurnal NLP)")
st.markdown("---")

# ============================================================
# SIDEBAR
# ============================================================
with st.sidebar:
    st.header("📋 Aturan Produksi")

    st.subheader("BWCE (Performa Bisnis)")
    st.markdown("""
    - **SR < 98.5%** → Skor 10 (Kritis)
    - **SR 98.5-99.5%** → Skor 7 (Waspada)
    - **TE > 20** → +2 modifier
    - **"SR Degraded"** → +1 modifier
    """)

    st.subheader("NGSSP (Middleware)")
    st.markdown("""
    - **val = 0 (Node Exporter)** → Skor 9 (DOWN)
    - **val > 100** → Skor 9 (Kritis)
    - **val 50-100** → Skor 6 (Waspada)
    - **Durasi > 30 menit** → +2 modifier
    """)

    st.subheader("USSD (Ketersediaan Proses)")
    st.markdown("""
    - **"Process is not running"** → Skor 9
    - **CRITICAL** → +1 modifier
    - **Layanan inti (Billing/CDR)** → +1 modifier
    """)

    st.subheader("CRM (Legacy / Noise)")
    st.markdown("""
    - **DOWN + host mengandung 'omni'/'crm'** → Skor 0 (Diabaikan)
    - *Negative Weighting untuk mengurangi alert fatigue*
    """)

    st.markdown("---")
    stats = get_alert_stats()
    st.metric("📦 Total Alert di DB", stats['total'])
    if stats['avg_score'] > 0:
        st.metric("📊 Rata-rata Skor", f"{stats['avg_score']:.1f}/10")
    
    # ========== [TAMBAHAN] Status Data Uji ==========
    unprocessed = count_unprocessed()
    if unprocessed > 0:
        st.warning(f"⏳ {unprocessed} alert belum diproses NLP.")

# ============================================================
# TAB: SEKARANG 6 TAB (AKURASI JADI TAB KE-6)
# ============================================================
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📝 Single Alert", 
    "📤 Upload Excel (Batch)", 
    "🗄️ Database", 
    "💬 Chatbot", 
    "📈 Dashboard",
    "🎯 Uji Akurasi"  # <-- TAB BARU UNTUK BAB IV
])

# ---------- TAB 1 (SINGLE ALERT) - [DIPERBARUI: TAMPILKAN JAWABAN SISTEM PAKAR] ----------
with tab1:
    st.header("🔍 Proses Satu Alert")
    alert_text = st.text_area("Masukkan teks alert:",
        placeholder="Contoh: 2:- Billing_3 3:- XPTPSDPPROV03 5 :- CRITICAL 7 :- CRITICAL - Process is not running!",
        height=100)
    col1, col2 = st.columns([1, 5])
    with col1:
        process_btn = st.button("🚀 Proses", type="primary")

    if process_btn and alert_text.strip():
        with st.spinner("Memproses..."):
            result = process_alert(alert_text)

        # Ringkasan skor (re-scoring)
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Stream", result['stream'])
        col_b.metric("Skor", f"{result['score']}/10")
        col_c.metric("Level", result['level'])

        # ===== [BARU] JAWABAN SISTEM PAKAR (Diagnosis + Rekomendasi + Eskalasi) =====
        st.markdown("#### 🧠 Jawaban Sistem")
        jc1, jc2 = st.columns(2)
        with jc1:
            st.info(f"**🩺 Diagnosis**\n\n{result.get('diagnosis', '-')}")
        with jc2:
            st.warning(f"**🛠️ Rekomendasi Tindakan**\n\n{result.get('rekomendasi', '-')}")
        st.markdown(f"**👥 Eskalasi ke:** `{result.get('tim_eskalasi', '-')}`")

        # Detail teknis dipindah ke expander (tertutup) agar jawabannya yang menonjol
        with st.expander("📋 Detail Teknis (alasan skor & fitur terekstrak)", expanded=False):
            st.markdown(f"**Alasan skor:** {result['reason']}")
            st.json(result.get('features', {}))
            st.code(result['raw_text'])

        if st.button("💾 Simpan Alert Ini ke Database"):
            insert_alert({
                'timestamp': datetime.now().isoformat(), 
                'stream': result['stream'],
                'raw_message': result['raw_text'], 
                'score': result['score'],
                'level': result['level'], 
                'reason': result['reason'],
                'extracted_features': result.get('features', {}), 
                'original_severity': ''
            })
            st.success(f"✅ Tersimpan! Total sekarang: {get_alert_stats()['total']}")

    # --- VERSI LAMA (ARSIP) blok hasil Tab 1 ---------------------------------
    # if process_btn and alert_text.strip():
    #     with st.spinner("Memproses..."):
    #         result = process_alert(alert_text)
    #     col_a, col_b, col_c = st.columns(3)
    #     col_a.metric("Stream", result['stream'])
    #     col_b.metric("Skor", f"{result['score']}/10")
    #     col_c.metric("Level", result['level'])
    #     with st.expander("📋 Detail", expanded=True):
    #         st.markdown(f"**Alasan:** {result['reason']}")
    #         st.json(result.get('features', {}))
    #         st.code(result['raw_text'])
    #     if st.button("💾 Simpan Alert Ini ke Database"):
    #         insert_alert({...})
    #         st.success(f"✅ Tersimpan! Total sekarang: {get_alert_stats()['total']}")
    # -------------------------------------------------------------------------

# ---------- TAB 2 (UPLOAD EXCEL) - [DIPERBARUI: KOLOM JAWABAN PAKAR DI HASIL] ----------
with tab2:
    st.header("📤 Upload File Excel & Proses Batch (Dengan Ground Truth)")
    st.markdown("""
    Upload file Excel (`.xlsx` / `.xls`) yang berisi kolom:
    - **Teks Alert** (wajib)
    - **Expected Score** (opsional, untuk uji akurasi) → nama kolom: `expected_score`, `SKOR_ENGINEER`, `Ground Truth`, atau `GT`
    """)
    uploaded_file = st.file_uploader("Pilih file Excel", type=['xlsx', 'xls'],
        help="File harus memiliki kolom berisi teks alert.")

    if uploaded_file is not None:
        try:
            df = pd.read_excel(uploaded_file)
            st.success(f"✅ File berhasil dibaca! Ditemukan {len(df)} baris data.")
            with st.expander("👀 Preview Data (5 baris pertama)"):
                st.dataframe(df.head())

            # ========== DETEKSI KOLOM TEKS ==========
            possible_text_cols = ['MESSAGE', 'Message', 'ALERT', 'Alert', 'alert', 'Teks', 'TEKS', 'text', 'TEXT', 'Pesan', 'pesan']
            detected_text_col = next((c for c in possible_text_cols if c in df.columns), None)
            if detected_text_col is None:
                st.warning("⚠️ Tidak dapat mendeteksi kolom teks alert secara otomatis.")
                text_col = st.selectbox("Pilih kolom teks alert:", df.columns)
            else:
                st.info(f"✅ Kolom teks terdeteksi: **'{detected_text_col}'**")
                text_col = detected_text_col

            # ========== [TAMBAHAN] DETEKSI KOLOM EXPECTED SCORE (GROUND TRUTH) ==========
            possible_expected_cols = ['expected_score', 'EXPECTED_SCORE', 'SKOR_ENGINEER', 'Ground Truth', 'GT', 'ENGINEER_SCORE']
            detected_expected_col = next((c for c in possible_expected_cols if c in df.columns), None)
            
            expected_col = None
            if detected_expected_col:
                st.info(f"✅ Kolom Expected Score (Ground Truth) terdeteksi: **'{detected_expected_col}'**")
                expected_col = detected_expected_col
            else:
                st.warning("⚠️ Kolom 'expected_score' tidak ditemukan. Akurasi tidak bisa dihitung.")
                st.markdown("*Jika ingin menguji akurasi, tambahkan kolom bernama `expected_score` berisi skor dari engineer (1-10).*")
                # Tetap beri pilihan manual
                expected_col = st.selectbox("Pilih kolom yang berisi Expected Score (opsional):", [None] + list(df.columns))

            save_to_db = st.checkbox("💾 Simpan hasil ke database", value=True)

            if st.button(f"🚀 Proses {len(df)} Baris Alert", type="primary"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                results = []
                total_rows = len(df)
                
                for i, (_, row) in enumerate(df.iterrows()):
                    status_text.text(f"⏳ Memproses baris {i+1} dari {total_rows}...")
                    raw_text = str(row[text_col]) if pd.notna(row[text_col]) else ""
                    if raw_text.strip() == "" or raw_text == "nan":
                        result = {
                            'stream': 'EMPTY', 
                            'score': 0, 
                            'level': '⚪ KOSONG',
                            'reason': 'Teks alert kosong', 
                            'diagnosis': 'Baris kosong.',
                            'rekomendasi': '-',
                            'tim_eskalasi': '-',
                            'features': {}, 
                            'raw_text': raw_text
                        }
                    else:
                        result = process_alert(raw_text)
                    
                    # ========== [TAMBAHAN] EKSTRAK EXPECTED SCORE ==========
                    expected_score = None
                    if expected_col and expected_col in df.columns:
                        val = row[expected_col]
                        if pd.notna(val):
                            try:
                                expected_score = int(val)
                            except:
                                pass
                    
                    result['expected_score'] = expected_score
                    
                    if 'SEVERITY' in df.columns:
                        result['original_severity'] = str(row['SEVERITY'])
                    if 'TIME' in df.columns:
                        result['time'] = str(row['TIME'])
                    results.append(result)
                    progress_bar.progress((i + 1) / total_rows)
                
                status_text.text("✅ Pemrosesan Selesai!")

                if save_to_db:
                    alerts_to_save = []
                    for r in results:
                        alert_data = {
                            'timestamp': datetime.now().isoformat(), 
                            'stream': r['stream'],
                            'raw_message': r['raw_text'], 
                            'score': r['score'], 
                            'level': r['level'],
                            'reason': r['reason'], 
                            'extracted_features': r.get('features', {}),
                            'original_severity': r.get('original_severity', ''),
                            # ========== [TAMBAHAN] SIMPAN EXPECTED_SCORE ==========
                            'expected_score': r.get('expected_score')
                        }
                        alerts_to_save.append(alert_data)
                    
                    # Gunakan insert_alerts_batch yang sudah diperbarui (support expected_score)
                    insert_alerts_batch(alerts_to_save)
                    st.success(f"✅ {len(results)} alert berhasil disimpan ke database!")

                # Tampilkan hasil
                st.subheader("📊 Hasil Pemrosesan Batch")
                # [BARU] Kolom Tim_Eskalasi, Diagnosis, Rekomendasi ikut ditampilkan
                df_results = pd.DataFrame([{
                    'Stream': r['stream'], 
                    'Score': r['score'], 
                    'Level': r['level'],
                    'Expected_Score': r.get('expected_score', '-'),
                    'Cocok': '✅' if r.get('expected_score') is not None and r['score'] == r.get('expected_score') else ('-' if r.get('expected_score') is None else '❌'),
                    'Tim_Eskalasi': r.get('tim_eskalasi', '-'),
                    'Diagnosis': r.get('diagnosis', '-'),
                    'Rekomendasi': r.get('rekomendasi', '-'),
                    'Reason': r['reason'],
                    'Alert_Text': r['raw_text'][:150] + ('...' if len(r['raw_text']) > 150 else '')
                } for r in results])
                st.dataframe(df_results, use_container_width=True, hide_index=True,
                    column_config={
                        'Alert_Text': st.column_config.TextColumn('Teks Alert', width='large'),
                        'Diagnosis': st.column_config.TextColumn('Diagnosis', width='large'),
                        'Rekomendasi': st.column_config.TextColumn('Rekomendasi', width='large'),
                        'Score': st.column_config.NumberColumn('Skor', format='%d/10')
                    })
                
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Total Alert", len(results))
                c2.metric("Rata-rata Skor", f"{df_results['Score'].mean():.1f}/10")
                c3.metric("Skor Tertinggi", f"{int(df_results['Score'].max())}/10")
                c4.metric("Tidak Terdeteksi", len(df_results[df_results['Stream'] == 'UNKNOWN']))
                
                if not df_results.empty:
                    lc = df_results['Level'].value_counts().reset_index()
                    lc.columns = ['Level', 'Count']
                    st.plotly_chart(px.bar(lc, x='Level', y='Count', title='Distribusi Level Prioritas', color='Level'), use_container_width=True)
                
                csv = df_results.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Download Hasil (CSV)", data=csv, file_name="hasil_re_scoring.csv", mime="text/csv")
        except Exception as e:
            st.error(f"❌ Terjadi kesalahan saat membaca file: {e}")
    else:
        st.info("👆 Silakan upload file Excel untuk memulai pemrosesan batch.")
        st.markdown("---")
        st.subheader("🧪 Atau coba dengan data sampel (format nyata)")
        if st.button("📥 Load & Proses 6 Data Sampel"):
            sample_alerts = [
                "BWCE bi-air-update - Total: 1697, Success: 0, BE: 0, TE: 0, SR: 0.00% - BWCE SR Degraded, ngssp/vas team pls check!",
                "MMOlZMsWz|RVS SOAD10 - Node Exporter Status ~ xptrvssoa127:9092 with val: 0, Issue start at: 2024-11-13T23:49:00.000+07:00, Pls inform middleware Team!",
                "2:- Billing_3  3:- XPTPSDPPROV03 4 :- 10.49.73.91 5 :- CRITICAL 6 :- Wed May 13 00:20:12 WIB 2026 7 :- CRITICAL - Process is not running!",
                "agent-desktop3 in jktmmpvomnilad01 DOWN",
                "ESB STANDALONE Domain - Stuck Thread alert with val: 124, Issue start at: 2026-04-23T16:26:00",
                "BWCE lms-job - Total: 1000, Success: 998, BE: 1, TE: 1, SR: 99.80%",
            ]
            with st.spinner("Memproses sampel..."):
                results = process_alerts_batch(sample_alerts)
                # [BARU] sertakan kolom jawaban pakar pada tabel sampel
                df_sample = pd.DataFrame([{
                    'Stream': r['stream'], 'Score': r['score'], 'Level': r['level'],
                    'Tim_Eskalasi': r.get('tim_eskalasi', '-'),
                    'Diagnosis': r.get('diagnosis', '-'),
                    'Rekomendasi': r.get('rekomendasi', '-'),
                    'Alert': r['raw_text'][:100]
                } for r in results])
                st.dataframe(df_sample, use_container_width=True, hide_index=True,
                    column_config={
                        'Diagnosis': st.column_config.TextColumn('Diagnosis', width='large'),
                        'Rekomendasi': st.column_config.TextColumn('Rekomendasi', width='large'),
                    })

    # --- VERSI LAMA (ARSIP) tabel hasil batch Tab 2 --------------------------
    # df_results = pd.DataFrame([{
    #     'Stream': r['stream'], 'Score': r['score'], 'Level': r['level'],
    #     'Expected_Score': r.get('expected_score', '-'),
    #     'Cocok': '✅' if r.get('expected_score') is not None and r['score'] == r.get('expected_score') else ('-' if r.get('expected_score') is None else '❌'),
    #     'Reason': r['reason'],
    #     'Alert_Text': r['raw_text'][:150] + ('...' if len(r['raw_text']) > 150 else '')
    # } for r in results])
    # df_sample = pd.DataFrame([{
    #     'Stream': r['stream'], 'Score': r['score'], 'Level': r['level'],
    #     'Reason': r['reason'], 'Alert': r['raw_text'][:100]
    # } for r in results])
    # -------------------------------------------------------------------------

# ---------- TAB 3 (DATABASE) - TIDAK BERUBAH ----------
with tab3:
    st.header("🗄️ Manajemen Database (SQLite)")
    cf1, cf2 = st.columns(2)
    with cf1:
        stream_filter = st.selectbox("Filter Stream:", ['ALL', 'BWCE', 'NGSSP', 'USSD', 'CRM', 'UNKNOWN'])
    with cf2:
        level_filter = st.selectbox("Filter Level:", ['ALL', '🔴 KRITIS', '🟠 TINGGI', '🟡 SEDANG', '🟢 RENDAH', '⚪ DIABAIKAN'])
    if st.button("🔄 Refresh Data"):
        st.rerun()
    df_db = get_all_alerts(limit=500, stream_filter=stream_filter, level_filter=level_filter)
    if df_db.empty:
        st.info("📭 Belum ada data. Upload Excel atau proses single alert dulu.")
    else:
        stats = get_alert_stats()
        s1, s2, s3 = st.columns(3)
        s1.metric("Total Data", stats['total'])
        s2.metric("Data Tampil", len(df_db))
        s3.metric("Rata-rata Skor", f"{stats['avg_score']:.1f}/10")
        
        # Tampilkan kolom expected_score jika ada
        display_cols = ['id', 'timestamp', 'stream', 'score', 'level', 'raw_message']
        if 'expected_score' in df_db.columns:
            display_cols.insert(4, 'expected_score')
        
        st.dataframe(df_db[display_cols],
            use_container_width=True, hide_index=True,
            column_config={'raw_message': st.column_config.TextColumn('Pesan Alert', width='large'),
                           'score': st.column_config.NumberColumn('Skor', format='%d/10')})
        if st.button("🗑️ Hapus Semua Data", type="secondary"):
            if st.checkbox("⚠️ Saya yakin ingin menghapus semua data"):
                clear_database(); st.success("✅ Database dikosongkan!"); st.rerun()
        csv = df_db.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download CSV", data=csv, file_name="database_alerts.csv", mime="text/csv")

# ---------- TAB 4 (CHATBOT) - TIDAK BERUBAH ----------
with tab4:
    st.header("💬 Chatbot (Tanya-Jawab Alert)")
    st.markdown("""
    Ajukan **pertanyaan** atau tempel **teks alert**. Tipe pertanyaan yang dikenali:
    1. *Apa arti alert BWCE?* — penjelasan  •  2. *Berapa skor NGSSP?* — urgensi
    3. *Kenapa alert USSD kritis?* — penyebab  •  4. *Apa tindakan untuk CRM?* — rekomendasi
    5. *Tampilkan alert kritis* — daftar  •  6. *Berapa total alert?* — statistik
    7. *Alert apa saja jam 00:20?* — filter waktu
    **8. *Berapa akurasi sistem?* — uji akurasi**  (BARU!)
    """)

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    user_input = st.chat_input("Ketik pertanyaan atau alert...")
    if user_input:
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)
        with st.chat_message("assistant"):
            with st.spinner("Memproses..."):
                response = chatbot_respond(user_input)
            st.markdown(response)
            st.session_state.chat_history.append({"role": "assistant", "content": response})

    if st.button("🧹 Clear Chat"):
        st.session_state.chat_history = []
        st.rerun()

# ---------- TAB 5 (DASHBOARD) - TIDAK BERUBAH ----------
with tab5:
    st.header("📈 Dashboard & Visualisasi")
    stats = get_alert_stats()
    if stats['total'] == 0:
        st.warning("Belum ada data. Upload Excel atau proses single alert dulu.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Alert", stats['total'])
        c2.metric("Rata-rata Skor", f"{stats['avg_score']:.1f}/10")
        if not stats['stream_dist'].empty:
            st.plotly_chart(px.pie(stats['stream_dist'], values='count', names='stream', title='Distribusi Stream'), use_container_width=True)
        if not stats['level_dist'].empty:
            st.plotly_chart(px.bar(stats['level_dist'], x='level', y='count', title='Distribusi Level Prioritas',
                color='level', color_discrete_map={'🔴 KRITIS': 'red', '🟠 TINGGI': 'orange', '🟡 SEDANG': 'gold', '🟢 RENDAH': 'green', '⚪ DIABAIKAN': 'lightgray'}), use_container_width=True)
        df_trend = get_all_alerts(limit=100)
        if not df_trend.empty:
            df_trend['timestamp_dt'] = pd.to_datetime(df_trend['timestamp'], errors='coerce')
            df_trend = df_trend.sort_values('timestamp_dt')
            st.plotly_chart(px.line(df_trend, x='timestamp_dt', y='score', title='Tren Skor 100 Alert Terakhir', markers=True, range_y=[0, 10]), use_container_width=True)

# ========== [TAMBAHAN] TAB 6: UJI AKURASI (BAB IV) ==========
with tab6:
    st.header("🎯 Uji Akurasi Sistem (Confusion Matrix)")
    st.markdown("""
    Tab ini menampilkan hasil perbandingan antara **Skor Sistem** (hasil NLP Anda) dengan 
    **Skor Engineer** (Ground Truth / Expected Score). Ini adalah inti dari pengujian di BAB IV.
    """)

    col1, col2 = st.columns([1, 2])
    with col1:
        if st.button("📊 Hitung Akurasi Sekarang", type="primary"):
            with st.spinner("Menghitung..."):
                res = calculate_accuracy()
                st.session_state['accuracy_result'] = res
            st.rerun()

    # Tampilkan hasil akurasi
    if 'accuracy_result' in st.session_state:
        res = st.session_state['accuracy_result']
        
        if res['total_data'] == 0:
            st.warning("⚠️ **Belum ada data uji!**")
            st.info("""
            **Cara menambahkan data uji:**
            1. Upload file Excel di TAB **📤 Upload Excel**.
            2. Pastikan file memiliki kolom **`expected_score`** (berisi skor dari engineer).
            3. Proses batch, lalu kembali ke tab ini.
            """)
        else:
            # Metric utama
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total Data Uji", res['total_data'])
            m2.metric("✅ Prediksi Benar", res['correct'])
            m3.metric("❌ Prediksi Salah", res['total_data'] - res['correct'])
            m4.metric("🎯 Akurasi", f"{res['accuracy']}%")
            
            # Status terhadap target 84%
            if res['accuracy'] >= 84:
                st.success(f"✅ **Akurasi {res['accuracy']}%** — Memenuhi target ≥ 84% (setara jurnal Priandana & Indra, 2024).")
            else:
                st.warning(f"📌 **Akurasi {res['accuracy']}%** — Masih di bawah target 84%. Perbaiki aturan produksi di `rules.py`.")
            
            st.markdown("---")
            st.subheader("📋 Tabel Confusion Matrix (Per Data)")
            
            # Ambil data confusion matrix
            df_cm = get_confusion_matrix_data()
            if not df_cm.empty:
                # Tampilkan tabel
                st.dataframe(df_cm, use_container_width=True, hide_index=True,
                    column_config={
                        'id': 'ID Alert',
                        'stream': 'Stream',
                        'skor_sistem': st.column_config.NumberColumn('Skor Sistem', format='%d/10'),
                        'skor_engineer': st.column_config.NumberColumn('Skor Engineer', format='%d/10'),
                        'status': 'Status'
                    })
                
                # Grafik perbandingan
                fig = px.scatter(df_cm, x='skor_engineer', y='skor_sistem', 
                                 color='status', hover_data=['id', 'stream'],
                                 title='Perbandingan Skor Sistem vs Skor Engineer',
                                 labels={'skor_engineer': 'Skor Engineer (Ground Truth)', 'skor_sistem': 'Skor Sistem (NLP)'})
                fig.add_shape(type='line', x0=0, y0=0, x1=10, y1=10, 
                              line=dict(color='gray', dash='dash'), name='Perfect Match')
                st.plotly_chart(fig, use_container_width=True)
                
                # Download hasil confusion matrix
                csv_cm = df_cm.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Download Confusion Matrix (CSV)", data=csv_cm, file_name="confusion_matrix.csv", mime="text/csv")

# ============================================================
# FOOTER
# ============================================================
st.markdown("---")
st.caption("🚀 Alert Re-Scoring System | Rule-Based NLP + Sistem Pakar | Adaptasi Priandana & Indra (2024)")