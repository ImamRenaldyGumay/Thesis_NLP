"""
chatbot.py
Lapisan chatbot: mendeteksi MAKSUD (intent) pertanyaan analis, lalu menjawab
dengan penjelasan. Mengadaptasi (dengan modifikasi) konsep "tipe kalimat input"
dari Priandana & Indra (2024) ke 8 tipe pertanyaan OCC (termasuk Tipe 8: Akurasi).

CATATAN PENTING (VERSI INI):
Jawaban spesifik per-kondisi (diagnosis, rekomendasi, tim eskalasi) TIDAK lagi
ditulis ulang di sini, melainkan DIAMBIL LANGSUNG dari rules.py melalui
process_alert(). Dengan begitu jawaban chatbot SELALU sama dengan hasil di
Tab 1 (Single Alert) -> satu sumber kebenaran (single source of truth).

STREAM_KB di bawah kini hanya berisi DESKRIPSI UMUM tiap stream (pengetahuan
level-stream untuk pertanyaan "apa arti X?"), bukan rekomendasi spesifik.
"""

import re
from rules import process_alert, detect_stream
from database import get_all_alerts, get_alert_stats

# ============================================================
# DESKRIPSI UMUM PER STREAM (untuk Tipe 1 "apa arti" — level stream)
# Rekomendasi/diagnosis spesifik per-kondisi diambil dari rules.py.
# ============================================================

STREAM_KB = {
    'BWCE': {
        'nama': 'Performa Transaksi Bisnis',
        'arti': 'memantau Success Rate (SR) transaksi pada sebuah job/aplikasi. SR yang turun jauh di bawah ambang 98.5% berarti sebagian besar atau seluruh transaksi gagal.',
        'tindakan': 'Periksa job yang SR-nya turun, cek backend error (BE) dan timeout (TE), lalu eskalasi ke tim VAS/NGSSP sesuai instruksi pada alert.'
    },
    'NGSSP': {
        'nama': 'Middleware (Node Exporter / Stuck Thread)',
        'arti': 'memantau kesehatan middleware. Nilai val=0 pada Node Exporter berarti node mati (down); val>0 pada Stuck Thread berarti jumlah thread yang macet.',
        'tindakan': 'Untuk node down, periksa status server/exporter; untuk stuck thread tinggi, periksa antrian dan pertimbangkan restart managed server. Informasikan ke tim middleware.'
    },
    'USSD': {
        'nama': 'Ketersediaan Proses',
        'arti': 'memantau apakah proses layanan berjalan. Pesan "Process is not running" berarti proses mati sehingga layanan tidak tersedia.',
        'tindakan': 'Restart proses yang mati pada host terkait. Bila banyak proses mati serentak (alert flood), tangani sebagai satu insiden besar dan telusuri penyebab umum (server/jaringan).'
    },
    'CRM': {
        'nama': 'Ketersediaan Layanan Legacy (OMNI)',
        'arti': 'memantau ketersediaan komponen OMNI. Status DOWN pada host ber-prefix "omni" diperlakukan sebagai legacy dan disaring (Negative Weighting) untuk mengurangi alert fatigue.',
        'tindakan': 'Tidak perlu eskalasi segera; cukup dicatat untuk pemantauan tren. Sesuaikan aturan bila kebijakan terhadap OMNI berubah.'
    },
}

# ============================================================
# DETEKSI INTENT (8 TIPE) — [DIPERBARUI: URUTAN PRIORITAS DIBENAHI]
# Urutan dari yang PALING SPESIFIK ke paling umum, agar "tampilkan statistik"
# tidak salah tertangkap sebagai 'daftar' (kata 'tampilkan').
# ============================================================

INTENT_PATTERNS = [
    ('akurasi',   r'\b(akurasi|tingkat akurasi|keakuratan|berapa persen|ketepatan|berhasil|gagal|confusion matrix)\b'),
    ('statistik', r'\b(total|jumlah|statistik|berapa banyak|berapa alert|ada berapa)\b'),
    ('skor',      r'\b(berapa skor|seberapa urgent|urgensi|seberapa penting|level berapa)\b'),
    ('tindak',    r'\b(tindakan|rekomendasi|solusi|harus apa|apa yang harus|saran|eskalasi)\b'),
    ('sebab',     r'\b(kenapa|mengapa|penyebab|knp|diagnosis)\b'),
    ('jelas',     r'\b(apa arti|apa itu|jelaskan|maksud|artinya)\b'),
    ('waktu',     r'\b(jam|pukul|tanggal|hari ini|kemarin)\b'),
    ('daftar',    r'\b(tampilkan|lihat|daftar|list|sebutkan)\b'),
]

# --- VERSI LAMA (ARSIP) INTENT_PATTERNS --------------------------------------
# INTENT_PATTERNS = [
#     ('jelas',     r'\b(apa arti|apa itu|jelaskan|maksud|artinya)\b'),
#     ('sebab',     r'\b(kenapa|mengapa|penyebab|knp)\b'),
#     ('tindak',    r'\b(tindakan|rekomendasi|solusi|harus apa|apa yang harus|saran)\b'),
#     ('skor',      r'\b(berapa skor|seberapa urgent|urgensi|seberapa penting|level berapa)\b'),
#     ('waktu',     r'\b(jam|pukul|tanggal|hari ini|kemarin)\b'),
#     ('statistik', r'\b(total|jumlah|statistik|berapa banyak|berapa alert|ada berapa)\b'),
#     ('daftar',    r'\b(tampilkan|lihat|daftar|list|sebutkan)\b'),
#     ('akurasi',   r'\b(akurasi|tingkat akurasi|keakuratan|berapa persen|ketepatan|berhasil|gagal|confusion matrix)\b'),
# ]
# -----------------------------------------------------------------------------


def detect_intent(text: str):
    t = text.lower()
    for name, pat in INTENT_PATTERNS:
        if re.search(pat, t):
            return name
    return None


def extract_stream_ref(text: str):
    t = text.lower()
    if 'bwce' in t:
        return 'BWCE'
    if any(k in t for k in ('ngssp', 'rvs', 'stuck thread', 'node exporter', 'middleware')):
        return 'NGSSP'
    if any(k in t for k in ('ussd', 'process', 'proses', 'billing', 'cdr')):
        return 'USSD'
    if any(k in t for k in ('crm', 'omni', 'agent-desktop')):
        return 'CRM'
    return None


def extract_level_ref(text: str):
    t = text.lower()
    if 'kritis' in t:
        return '\U0001F534 KRITIS'
    if 'tinggi' in t:
        return '\U0001F7E0 TINGGI'
    if 'sedang' in t:
        return '\U0001F7E1 SEDANG'
    if 'rendah' in t:
        return '\U0001F7E2 RENDAH'
    return None


# ============================================================
# HANDLER PER TIPE (1 s.d 7)
# ============================================================

def _latest_alert(stream: str):
    try:
        df = get_all_alerts(limit=1, stream_filter=stream)
        if not df.empty:
            return df.iloc[0]
    except Exception:
        pass
    return None


def _expert_for_stream(stream: str):
    """
    [BARU] Ambil alert TERBARU stream tsb dari database, lalu jalankan ulang
    process_alert() untuk mendapatkan jawaban pakar (diagnosis/rekomendasi/tim)
    yang KONSISTEN dengan rules.py & Tab 1.
    Mengembalikan (hasil_process_alert, raw_text) atau (None, None) bila kosong.
    """
    row = _latest_alert(stream)
    if row is not None:
        raw = str(row['raw_message'])
        try:
            return process_alert(raw), raw
        except Exception:
            return None, None
    return None, None


def handle_jelas(stream: str) -> str:
    kb = STREAM_KB[stream]
    msg = f"**Tipe 1 - Penjelasan Makna Alert**\n\nAlert **{stream}** ({kb['nama']}) {kb['arti']}"
    res, raw = _expert_for_stream(stream)
    if res is not None:
        msg += f"\n\n*Contoh terbaru di database:* `{raw[:120]}`\n→ {res.get('diagnosis', '-')}"
    return msg


def handle_skor(stream: str) -> str:
    row = _latest_alert(stream)
    if row is not None:
        return (f"**Tipe 2 - Tingkat Urgensi / Skor**\n\n"
                f"Alert **{stream}** terbaru: skor **{row['score']}/10** ({row['level']}).\n"
                f"Alasan: {row['reason']}")
    return (f"**Tipe 2 - Tingkat Urgensi / Skor**\n\n"
            f"Belum ada alert **{stream}** di database. Tempel teks alert-nya di sini agar skornya bisa dihitung langsung.")


def handle_sebab(stream: str) -> str:
    # [DIPERBARUI] gunakan diagnosis dari rules.py (bukan sekadar reason teknis)
    res, raw = _expert_for_stream(stream)
    if res is not None:
        return (f"**Tipe 3 - Penyebab / Diagnosis**\n\n"
                f"Alert **{stream}** terbaru: {res.get('diagnosis', '-')}\n\n"
                f"*(Alasan skor: {res.get('reason', '-')})*")
    kb = STREAM_KB[stream]
    return f"**Tipe 3 - Penyebab Kondisi**\n\nSecara umum, alert **{stream}** muncul ketika {kb['arti']}"


def handle_tindak(stream: str) -> str:
    # [DIPERBARUI] rekomendasi spesifik dari rules.py; fallback ke deskripsi umum
    res, raw = _expert_for_stream(stream)
    if res is not None:
        return (f"**Tipe 4 - Rekomendasi Tindakan**\n\n"
                f"Untuk alert **{stream}** terbaru:\n\n"
                f"- 🩺 Diagnosis: {res.get('diagnosis', '-')}\n"
                f"- 🛠️ Rekomendasi: {res.get('rekomendasi', '-')}\n"
                f"- 👥 Eskalasi ke: {res.get('tim_eskalasi', '-')}")
    kb = STREAM_KB[stream]
    return (f"**Tipe 4 - Rekomendasi Tindakan**\n\n"
            f"Secara umum, untuk alert **{stream}**: {kb['tindakan']}\n\n"
            f"*(Belum ada contoh alert {stream} di database; tempel teks alert-nya untuk rekomendasi spesifik.)*")

# --- VERSI LAMA (ARSIP) handler 1/3/4 ----------------------------------------
# def handle_jelas(stream):
#     kb = STREAM_KB[stream]
#     msg = f"**Tipe 1 - Penjelasan Makna Alert**\n\nAlert **{stream}** ({kb['nama']}) {kb['arti']}"
#     row = _latest_alert(stream)
#     if row is not None:
#         msg += f"\n\n*Contoh terbaru di database:* `{str(row['raw_message'])[:120]}` -> {row['reason']}"
#     return msg
#
# def handle_sebab(stream):
#     row = _latest_alert(stream)
#     if row is not None:
#         return (f"**Tipe 3 - Penyebab Kondisi**\n\n"
#                 f"Alert **{stream}** terbaru muncul karena: {row['reason']}.")
#     kb = STREAM_KB[stream]
#     return f"**Tipe 3 - Penyebab Kondisi**\n\nSecara umum, alert **{stream}** muncul ketika {kb['arti']}"
#
# def handle_tindak(stream):
#     kb = STREAM_KB[stream]
#     return f"**Tipe 4 - Rekomendasi Tindakan**\n\nUntuk alert **{stream}**: {kb['tindakan']}"
# -----------------------------------------------------------------------------


def handle_daftar(text: str) -> str:
    level = extract_level_ref(text)
    stream = extract_stream_ref(text)
    df = get_all_alerts(limit=200,
                        stream_filter=stream if stream else 'ALL',
                        level_filter=level if level else 'ALL')
    if df.empty:
        return "**Tipe 5 - Daftar/Filter**\n\nTidak ada alert yang cocok dengan kriteria tersebut."
    df = df.sort_values('score', ascending=False).head(10)
    krit = f"level {level}" if level else (f"stream {stream}" if stream else "semua")
    lines = [f"**Tipe 5 - Daftar/Filter** ({krit}, {len(df)} teratas):\n"]
    for _, r in df.iterrows():
        lines.append(f"- [{r['score']}/10] {r['stream']}: `{str(r['raw_message'])[:80]}`")
    return "\n".join(lines)


def handle_statistik() -> str:
    stats = get_alert_stats()
    msg = "**Tipe 6 - Statistik**\n\n"
    msg += f"- Total alert: **{stats['total']}**\n"
    msg += f"- Rata-rata skor: **{stats['avg_score']:.1f}/10**\n"
    if not stats['level_dist'].empty:
        msg += "\n*Distribusi level:*\n"
        for _, r in stats['level_dist'].iterrows():
            msg += f"- {r['level']}: {r['count']}\n"
    return msg


def handle_waktu(text: str) -> str:
    # Ekstrak token jam (HH:MM) atau tanggal sederhana
    jam = re.search(r'(\d{1,2}[:.]\d{2})', text)
    tgl = re.search(r'(\d{1,2}[/\-]\d{1,2}[/\-]?\d{0,4})', text)
    token = (jam.group(1) if jam else (tgl.group(1) if tgl else None))
    if not token:
        return "**Tipe 7 - Filter Waktu**\n\nMohon sebutkan jam (mis. 00:20) atau tanggal yang ingin dicari."
    token = token.replace('.', ':')
    df = get_all_alerts(limit=1000)
    if df.empty:
        return "**Tipe 7 - Filter Waktu**\n\nBelum ada data di database."
    mask = df['raw_message'].astype(str).str.contains(token, case=False, na=False) | \
           df['timestamp'].astype(str).str.contains(token, case=False, na=False)
    hit = df[mask].head(10)
    if hit.empty:
        return f"**Tipe 7 - Filter Waktu**\n\nTidak ditemukan alert pada waktu '{token}'."
    lines = [f"**Tipe 7 - Filter Waktu** ('{token}', {len(hit)} ditemukan):\n"]
    for _, r in hit.iterrows():
        lines.append(f"- [{r['score']}/10] {r['stream']}: `{str(r['raw_message'])[:80]}`")
    return "\n".join(lines)


# ============================================================
# HANDLER TIPE 8: AKURASI (HUBUNGAN DENGAN DATABASE.PY)
# ============================================================

def handle_akurasi() -> str:
    """
    Menampilkan hasil uji akurasi sistem dengan membandingkan 
    skor sistem (score) vs skor engineer (expected_score).
    Ini adalah implementasi dari Tabel Confusion Matrix di BAB IV.
    """
    # Import di dalam fungsi agar tidak terjadi circular import jika database.py memanggil rules.py
    from database import calculate_accuracy, get_confusion_matrix_data
    
    res = calculate_accuracy()
    msg = "**📊 Tipe 8 - Uji Akurasi Sistem (Ground Truth vs Prediksi)**\n\n"
    
    # Cek apakah ada data uji
    if res['total_data'] == 0:
        return msg + (
            "⚠️ **Belum ada data uji!**\n\n"
            "Untuk melihat akurasi, Anda harus:\n"
            "1. Upload file Excel yang berisi kolom `raw_message` dan `expected_score` (skor dari engineer).\n"
            "2. Jalankan proses batch untuk memproses alert tersebut.\n"
            "3. Kembali ke sini dan tanyakan 'akurasi' lagi."
        )
    
    # Tampilkan hasil utama
    msg += f"- Total data uji: **{res['total_data']}** alert\n"
    msg += f"- Prediksi BENAR (Cocok): **{res['correct']}** alert\n"
    msg += f"- Prediksi SALAH (Tidak Cocok): **{res['total_data'] - res['correct']}** alert\n"
    msg += f"- **Akurasi Sistem: {res['accuracy']}%**\n\n"
    
    # Bandingkan dengan target 84% (seperti jurnal acuan)
    if res['accuracy'] >= 84:
        msg += "✅ **Status:** Akurasi **memenuhi target** (≥ 84%), setara dengan jurnal acuan Priandana & Indra (2024)."
    else:
        msg += "📌 **Status:** Akurasi **masih di bawah 84%**. Saran: tambahkan aturan produksi atau sesuaikan ambang batas skor di `rules.py`."
    
    # Tampilkan contoh ketidakcocokan (untuk bahan evaluasi)
    df = get_confusion_matrix_data()
    if not df.empty:
        mismatch = df[df['status'] == '❌ Tidak Cocok']
        if not mismatch.empty:
            msg += "\n\n*🔍 Contoh ketidakcocokan (5 data teratas):*\n"
            for _, row in mismatch.head(5).iterrows():
                msg += f"- ID {row['id']} ({row['stream']}): Sistem={row['skor_sistem']} vs Engineer={row['skor_engineer']}\n"
        else:
            msg += "\n\n🎉 **Selamat!** Tidak ada ketidakcocokan sama sekali (Akurasi 100%)."
    
    return msg


def _format_alert_result(r: dict) -> str:
    if r['stream'] == 'UNKNOWN':
        return ("\u26A0\uFE0F **Tidak dikenali sebagai alert maupun pertanyaan.**\n\n"
                "Coba tempel teks alert yang lengkap, atau ajukan pertanyaan seperti "
                "*\"apa arti alert BWCE?\"*, *\"berapa skor NGSSP?\"*, *\"tampilkan alert kritis\"*.\n\n"
                "💡 *Atau tanyakan 'akurasi' untuk melihat hasil uji sistem.*")
    # [DIPERBARUI] tampilkan jawaban pakar (sama dengan Tab 1)
    msg = f"**Hasil pemrosesan alert**\n\n"
    msg += f"- Stream: **{r['stream']}**\n"
    msg += f"- Skor: **{r['score']}/10** ({r['level']})\n"
    msg += f"- 🩺 Diagnosis: {r.get('diagnosis', '-')}\n"
    msg += f"- 🛠️ Rekomendasi: {r.get('rekomendasi', '-')}\n"
    msg += f"- 👥 Eskalasi ke: {r.get('tim_eskalasi', '-')}\n"
    msg += f"- _Alasan skor: {r['reason']}_"
    return msg

# --- VERSI LAMA (ARSIP) _format_alert_result ---------------------------------
# def _format_alert_result(r):
#     if r['stream'] == 'UNKNOWN':
#         return ("...pesan tidak dikenali...")
#     msg = f"**Hasil pemrosesan alert**\n\n"
#     msg += f"- Stream: **{r['stream']}**\n"
#     msg += f"- Skor: **{r['score']}/10**\n"
#     msg += f"- Level: {r['level']}\n"
#     msg += f"- Alasan: {r['reason']}"
#     return msg
# -----------------------------------------------------------------------------


# ============================================================
# ROUTER UTAMA (CHATBOT RESPOND)
# ============================================================

def chatbot_respond(text: str) -> str:
    """Titik masuk tunggal yang dipanggil app.py."""
    text = (text or "").strip()
    if not text:
        return "Silakan ketik teks alert atau pertanyaan."

    intent = detect_intent(text)

    # ==========================================================
    # BAGIAN 1: Jika tidak ada kata tanya -> anggap sebagai alert mentah
    # ==========================================================
    if intent is None:
        if detect_stream(text) != 'UNKNOWN':
            return _format_alert_result(process_alert(text))
        return _format_alert_result({'stream': 'UNKNOWN'})

    # ==========================================================
    # BAGIAN 2: Intent yang TIDAK membutuhkan stream (langsung dieksekusi)
    # ==========================================================
    if intent == 'statistik':
        return handle_statistik()
    if intent == 'daftar':
        return handle_daftar(text)
    if intent == 'waktu':
        return handle_waktu(text)
    if intent == 'akurasi':
        return handle_akurasi()

    # ==========================================================
    # BAGIAN 3: Intent penjelasan (1-4) yang MEMBUTUHKAN stream
    # ==========================================================
    stream = extract_stream_ref(text)
    if stream is None:
        return ("Pertanyaan dikenali, namun belum jelas stream yang dimaksud. "
                "Sebutkan salah satu: **BWCE**, **NGSSP**, **USSD**, atau **CRM**. "
                "Contoh: *\"apa arti alert BWCE?\"*")

    if intent == 'jelas':
        return handle_jelas(stream)
    if intent == 'skor':
        return handle_skor(stream)
    if intent == 'sebab':
        return handle_sebab(stream)
    if intent == 'tindak':
        return handle_tindak(stream)

    # Fallback (seharusnya tidak terjadi)
    return _format_alert_result(process_alert(text))