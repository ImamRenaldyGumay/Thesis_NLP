"""
evaluation.py

Modul PENGUJIAN model Rule-Based NLP untuk teks alert OCC.

Fungsi utama
------------
Membandingkan keluaran model (process_alert) terhadap label
kebenaran (ground truth) pada sebuah dataset berlabel, lalu
menghitung metrik pengujian:

    - Akurasi klasifikasi STREAM
    - Akurasi prediksi ATURAN PRODUKSI (R-*-* atau NONE)
    - Precision, Recall, F1-score per kelas (macro average)
    - Confusion matrix
    - Rata-rata SKOR KEPERCAYAAN (pembobotan NLP) pada
      prediksi benar vs salah

Format dataset (CSV / Excel), minimal 3 kolom:
    text          : teks alert
    label_stream  : stream sebenarnya (BWCE/NGSSP/USSD/CRM/UNKNOWN)
    label_rule    : aturan sebenarnya (R-BWCE-01, ..., atau NONE)

Cara pakai (terminal):
    python evaluation.py sample_dataset_berlabel.csv

Metrik dihitung manual (tanpa scikit-learn) agar tidak menambah
dependensi baru di luar pandas.
"""

import sys
from typing import List, Dict, Any

import pandas as pd

from rules import process_alert


# ============================================================
# METRIK DASAR
# ============================================================

def _accuracy(y_true: List[str], y_pred: List[str]) -> float:
    benar = sum(1 for t, p in zip(y_true, y_pred) if t == p)
    return benar / len(y_true) if y_true else 0.0


def _per_class_metrics(
    y_true: List[str],
    y_pred: List[str],
) -> Dict[str, Dict[str, float]]:
    """
    Menghitung precision, recall, F1 per kelas.
    """
    labels = sorted(set(y_true) | set(y_pred))
    hasil = {}

    for label in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred) if p == label and t == label)
        fp = sum(1 for t, p in zip(y_true, y_pred) if p == label and t != label)
        fn = sum(1 for t, p in zip(y_true, y_pred) if p != label and t == label)
        support = sum(1 for t in y_true if t == label)

        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall)
            else 0.0
        )

        hasil[label] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": support,
        }

    return hasil


def _macro_avg(per_class: Dict[str, Dict[str, float]]) -> Dict[str, float]:
    if not per_class:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    n = len(per_class)
    return {
        "precision": round(sum(v["precision"] for v in per_class.values()) / n, 4),
        "recall": round(sum(v["recall"] for v in per_class.values()) / n, 4),
        "f1": round(sum(v["f1"] for v in per_class.values()) / n, 4),
    }


def _confusion_matrix(
    y_true: List[str],
    y_pred: List[str],
) -> pd.DataFrame:
    labels = sorted(set(y_true) | set(y_pred))
    matrix = pd.DataFrame(
        0,
        index=[f"actual_{l}" for l in labels],
        columns=[f"pred_{l}" for l in labels],
    )
    for t, p in zip(y_true, y_pred):
        matrix.loc[f"actual_{t}", f"pred_{p}"] += 1
    return matrix


# ============================================================
# PIPELINE PENGUJIAN
# ============================================================

def evaluate_dataframe(
    df: pd.DataFrame,
    text_col: str = "text",
    stream_col: str = "label_stream",
    rule_col: str = "label_rule",
) -> Dict[str, Any]:
    """
    Menjalankan model pada seluruh baris dataframe dan
    menghitung metrik pengujian.
    """
    y_true_stream, y_pred_stream = [], []
    y_true_rule, y_pred_rule = [], []
    detail_rows = []

    # Bila dataset berasal dari menu Pelabelan, kolom 'direvisi'
    # menandai label yang diubah SETELAH pelabel melihat keluaran
    # model. Baris seperti itu tidak sepenuhnya independen, sehingga
    # akurasinya dilaporkan terpisah.
    ada_kolom_revisi = "direvisi" in df.columns

    for _, row in df.iterrows():
        text = str(row[text_col])
        result = process_alert(text)

        pred_stream = result.get("stream", "UNKNOWN")
        aturan = result.get("aturan_aktif", [])
        pred_rule = aturan[0] if aturan else "NONE"
        skor = result.get("skor_kepercayaan", 0.0)

        true_stream = str(row[stream_col]).strip()
        true_rule = str(row[rule_col]).strip()

        y_true_stream.append(true_stream)
        y_pred_stream.append(pred_stream)
        y_true_rule.append(true_rule)
        y_pred_rule.append(pred_rule)

        baris_detail = {
            "text": text[:60] + ("..." if len(text) > 60 else ""),
            "true_stream": true_stream,
            "pred_stream": pred_stream,
            "stream_ok": true_stream == pred_stream,
            "true_rule": true_rule,
            "pred_rule": pred_rule,
            "rule_ok": true_rule == pred_rule,
            "skor_kepercayaan": skor,
        }

        if ada_kolom_revisi:
            baris_detail["direvisi"] = bool(
                row.get("direvisi", 0)
            )

        detail_rows.append(baris_detail)

    detail_df = pd.DataFrame(detail_rows)

    # Skor kepercayaan rata-rata: prediksi aturan benar vs salah.
    benar_mask = detail_df["rule_ok"]
    skor_benar = detail_df.loc[benar_mask, "skor_kepercayaan"]
    skor_salah = detail_df.loc[~benar_mask, "skor_kepercayaan"]

    # ----------------------------------------------------------
    # AKURASI PADA LABEL YANG BELUM PERNAH DIREVISI
    # ----------------------------------------------------------
    # Label yang direvisi setelah pelabel melihat keluaran model
    # berpotensi terpengaruh model (automation bias). Angka ini
    # merupakan estimasi yang lebih konservatif.

    if ada_kolom_revisi and "direvisi" in detail_df.columns:

        murni = detail_df[~detail_df["direvisi"]]

        n_direvisi = int(detail_df["direvisi"].sum())

        if len(murni):
            akurasi_stream_murni = _accuracy(
                murni["true_stream"].tolist(),
                murni["pred_stream"].tolist(),
            )
            akurasi_rule_murni = _accuracy(
                murni["true_rule"].tolist(),
                murni["pred_rule"].tolist(),
            )
        else:
            akurasi_stream_murni = None
            akurasi_rule_murni = None
    else:
        n_direvisi = 0
        akurasi_stream_murni = None
        akurasi_rule_murni = None

    return {
        "n": len(df),

        "akurasi_stream": _accuracy(y_true_stream, y_pred_stream),
        "akurasi_rule": _accuracy(y_true_rule, y_pred_rule),

        "n_direvisi": n_direvisi,
        "n_murni": len(df) - n_direvisi,
        "akurasi_stream_murni": akurasi_stream_murni,
        "akurasi_rule_murni": akurasi_rule_murni,

        "stream_per_class": _per_class_metrics(y_true_stream, y_pred_stream),
        "rule_per_class": _per_class_metrics(y_true_rule, y_pred_rule),

        "stream_macro": _macro_avg(
            _per_class_metrics(y_true_stream, y_pred_stream)
        ),
        "rule_macro": _macro_avg(
            _per_class_metrics(y_true_rule, y_pred_rule)
        ),

        "stream_confusion": _confusion_matrix(y_true_stream, y_pred_stream),
        "rule_confusion": _confusion_matrix(y_true_rule, y_pred_rule),

        "skor_rata_benar": round(skor_benar.mean(), 4) if len(skor_benar) else 0.0,
        "skor_rata_salah": round(skor_salah.mean(), 4) if len(skor_salah) else 0.0,

        "detail": detail_df,
    }


# ============================================================
# LAPORAN
# ============================================================

def print_report(hasil: Dict[str, Any]) -> None:
    print("=" * 60)
    print("LAPORAN PENGUJIAN MODEL RULE-BASED NLP")
    print("=" * 60)
    print(f"Jumlah data uji : {hasil['n']}")
    print()

    print("-" * 60)
    print("AKURASI")
    print("-" * 60)
    print(f"Akurasi klasifikasi stream : {hasil['akurasi_stream'] * 100:.2f}%")
    print(f"Akurasi prediksi aturan    : {hasil['akurasi_rule'] * 100:.2f}%")
    print()

    if hasil.get("n_direvisi"):
        print(
            f"Catatan: {hasil['n_direvisi']} label direvisi setelah "
            "pelabel melihat keluaran model."
        )
        print(
            f"Akurasi pada {hasil['n_murni']} label yang TIDAK direvisi "
            "(estimasi lebih konservatif):"
        )
        if hasil["akurasi_stream_murni"] is not None:
            print(
                f"  - stream : {hasil['akurasi_stream_murni'] * 100:.2f}%"
            )
            print(
                f"  - aturan : {hasil['akurasi_rule_murni'] * 100:.2f}%"
            )
        print()

    print("-" * 60)
    print("METRIK PREDIKSI ATURAN (per kelas)")
    print("-" * 60)
    rule_df = pd.DataFrame(hasil["rule_per_class"]).T
    print(rule_df.to_string())
    print()
    m = hasil["rule_macro"]
    print(
        f"Macro-average -> precision: {m['precision']:.4f} | "
        f"recall: {m['recall']:.4f} | f1: {m['f1']:.4f}"
    )
    print()

    print("-" * 60)
    print("CONFUSION MATRIX - ATURAN")
    print("-" * 60)
    print(hasil["rule_confusion"].to_string())
    print()

    print("-" * 60)
    print("CONFUSION MATRIX - STREAM")
    print("-" * 60)
    print(hasil["stream_confusion"].to_string())
    print()

    print("-" * 60)
    print("PEMBOBOTAN / SKOR KEPERCAYAAN NLP")
    print("-" * 60)
    print(f"Rata-rata skor pada prediksi BENAR : {hasil['skor_rata_benar'] * 100:.2f}%")
    print(f"Rata-rata skor pada prediksi SALAH : {hasil['skor_rata_salah'] * 100:.2f}%")
    print()

    print("-" * 60)
    print("DETAIL PER BARIS")
    print("-" * 60)
    print(hasil["detail"].to_string(index=False))
    print("=" * 60)


# ============================================================
# ENTRY POINT
# ============================================================

def run(path: str) -> Dict[str, Any]:
    if path.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path)

    hasil = evaluate_dataframe(df)
    print_report(hasil)
    return hasil


if __name__ == "__main__":
    dataset_path = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "sample_dataset_berlabel.csv"
    )
    run(dataset_path)