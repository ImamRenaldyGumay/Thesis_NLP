"""
metrics.py

Modul evaluasi untuk pengujian kesesuaian keluaran
model Rule-Based NLP.

Pengujian dilakukan dengan membandingkan:

expected_condition
        vs
system_condition

Hasil setiap kasus:
- SESUAI
- TIDAK SESUAI

Kemudian dihitung persentase keberhasilan pengujian.
"""

import pandas as pd


# ============================================================
# EVALUASI KASUS UJI
# ============================================================

def evaluate_test_cases(df):
    """
    Mengevaluasi hasil pengujian model Rule-Based NLP.

    Parameter
    ---------
    df : pandas.DataFrame

        DataFrame harus memiliki kolom:

        - alert_text
        - expected_condition
        - system_condition

    Return
    ------
    dict

        Berisi:

        - total_pengujian
        - jumlah_sesuai
        - jumlah_tidak_sesuai
        - persentase_keberhasilan
        - detail
    """

    # ========================================================
    # VALIDASI DATAFRAME
    # ========================================================

    if df is None or df.empty:

        return {
            "error": "Data pengujian kosong."
        }


    # ========================================================
    # VALIDASI KOLOM
    # ========================================================

    required_columns = [

        "alert_text",

        "expected_condition",

        "system_condition",

    ]


    missing_columns = [

        column

        for column in required_columns

        if column not in df.columns

    ]


    if missing_columns:

        return {

            "error": (

                "Kolom yang diperlukan tidak ditemukan: "

                f"{missing_columns}"

            )

        }


    # ========================================================
    # COPY DATA
    # ========================================================

    result = df.copy()


    # ========================================================
    # NORMALISASI EXPECTED CONDITION
    # ========================================================

    result["expected_condition"] = (

        result["expected_condition"]

        .fillna("")

        .astype(str)

        .str.strip()

        .str.upper()

    )


    # ========================================================
    # NORMALISASI SYSTEM CONDITION
    # ========================================================

    result["system_condition"] = (

        result["system_condition"]

        .fillna("")

        .astype(str)

        .str.strip()

        .str.upper()

    )


    # ========================================================
    # PERBANDINGAN EXPECTED VS SYSTEM
    # ========================================================

    result["hasil"] = (

        result["expected_condition"]

        ==

        result["system_condition"]

    ).map({

        True: "SESUAI",

        False: "TIDAK SESUAI",

    })


    # ========================================================
    # HITUNG TOTAL PENGUJIAN
    # ========================================================

    total_pengujian = len(result)


    # ========================================================
    # HITUNG JUMLAH SESUAI
    # ========================================================

    jumlah_sesuai = int(

        (

            result["hasil"]

            ==

            "SESUAI"

        ).sum()

    )


    # ========================================================
    # HITUNG JUMLAH TIDAK SESUAI
    # ========================================================

    jumlah_tidak_sesuai = int(

        (

            result["hasil"]

            ==

            "TIDAK SESUAI"

        ).sum()

    )


    # ========================================================
    # HITUNG PERSENTASE KEBERHASILAN
    # ========================================================

    if total_pengujian > 0:

        persentase_keberhasilan = (

            jumlah_sesuai

            /

            total_pengujian

            *

            100

        )

    else:

        persentase_keberhasilan = 0.0


    # ========================================================
    # RETURN HASIL EVALUASI
    # ========================================================

    return {

        "total_pengujian":
            total_pengujian,

        "jumlah_sesuai":
            jumlah_sesuai,

        "jumlah_tidak_sesuai":
            jumlah_tidak_sesuai,

        "persentase_keberhasilan":
            persentase_keberhasilan,

        "detail":
            result,

    }