import ast
import json
import pandas as pd

from rules import process_alert


INPUT_FILE = "Template_Anotasi_Alert_READY.xlsx"
OUTPUT_FILE = "Hasil_Pengujian_Ekstraksi.xlsx"


# ============================================================
# NORMALISASI NAMA KOLOM
# ============================================================

def normalize_column_name(value):
    return (
        str(value)
        .strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )


def find_column(df, candidates):
    normalized_columns = {
        normalize_column_name(col): col
        for col in df.columns
    }

    for candidate in candidates:
        key = normalize_column_name(candidate)

        if key in normalized_columns:
            return normalized_columns[key]

    return None


# ============================================================
# KONVERSI EXPECTED INFORMATION
# ============================================================

def parse_expected_information(value):
    """
    Expected information pada Excel harus berupa dictionary.

    Contoh:

    {"service": "bi-aljabor-tmf",
     "total": 53176,
     "success": 29334,
     "be": 0,
     "te": 23842,
     "undefined": 0,
     "sr": 55.16}

    Mendukung format JSON maupun Python dictionary.
    """

    if pd.isna(value):
        return {}

    if isinstance(value, dict):
        return value

    text = str(value).strip()

    if not text:
        return {}

    # Coba JSON
    try:
        result = json.loads(text)

        if isinstance(result, dict):
            return result

    except (json.JSONDecodeError, TypeError):
        pass

    # Coba Python dictionary
    try:
        result = ast.literal_eval(text)

        if isinstance(result, dict):
            return result

    except (ValueError, SyntaxError):
        pass

    raise ValueError(
        f"Expected Information tidak valid:\n{text}"
    )


# ============================================================
# NORMALISASI NILAI
# ============================================================

def normalize_value(value):
    """
    Normalisasi ringan agar perbandingan tidak gagal hanya
    karena perbedaan tipe data sederhana.

    Contoh:
    0       == 0.0
    "DOWN"  == "down"
    """

    if value is None:
        return None

    if isinstance(value, str):
        return value.strip().lower()

    if isinstance(value, float):
        return round(value, 6)

    return value


# ============================================================
# MEMBANDINGKAN EXPECTED VS ACTUAL
# ============================================================

def compare_features(expected, actual):
    """
    Membandingkan field yang terdapat pada expected information.

    Field tambahan pada actual information tidak menyebabkan
    kasus menjadi TIDAK SESUAI.

    SESUAI:
        seluruh field expected tersedia dan nilainya sama.

    TIDAK SESUAI:
        minimal satu field expected hilang atau berbeda.
    """

    differences = []

    for key, expected_value in expected.items():

        if key not in actual:

            differences.append(
                f"Field '{key}' tidak ditemukan"
            )

            continue

        actual_value = actual[key]

        if (
            normalize_value(expected_value)
            != normalize_value(actual_value)
        ):

            differences.append(
                f"{key}: expected={expected_value}, "
                f"actual={actual_value}"
            )

    if differences:

        return (
            "TIDAK SESUAI",
            "; ".join(differences),
        )

    return "SESUAI", "-"


# ============================================================
# MAIN
# ============================================================

def main():

    # --------------------------------------------------------
    # BACA EXCEL
    # --------------------------------------------------------

    df = pd.read_excel(INPUT_FILE)

    print("=" * 70)
    print("PENGUJIAN EKSTRAKSI INFORMASI")
    print("=" * 70)

    print("\nKolom Excel:")

    for col in df.columns:
        print(f"- {col}")


    # --------------------------------------------------------
    # DETEKSI KOLOM
    # --------------------------------------------------------

    alert_col = find_column(
        df,
        [
            "MESSAGE",
            "alert_text",
            "raw_text",
            "teks_alert",
        ],
    )

    stream_col = find_column(
        df,
        [
            "stream",
            "stream_expected",
        ],
    )

    id_col = find_column(
        df,
        [
            "id_kasus",
            "case_id",
            "id",
            "no",
        ],
    )

    expected_col = find_column(
        df,
        [
            "expected_information",
            "expected_features",
            "expected_info",
        ],
    )


    # --------------------------------------------------------
    # VALIDASI KOLOM
    # --------------------------------------------------------

    if alert_col is None:
        raise ValueError(
            "Kolom teks alert tidak ditemukan."
        )

    if stream_col is None:
        raise ValueError(
            "Kolom stream tidak ditemukan."
        )

    if expected_col is None:
        raise ValueError(
            "\nKolom Expected Information tidak ditemukan.\n\n"
            "Tambahkan kolom:\n"
            "expected_information\n\n"
            "Isi dengan dictionary fitur yang diharapkan."
        )


    print()
    print(f"Kolom alert    : {alert_col}")
    print(f"Kolom stream   : {stream_col}")
    print(f"Kolom ID       : {id_col}")
    print(f"Kolom expected : {expected_col}")


    # --------------------------------------------------------
    # PROSES 80 ALERT
    # --------------------------------------------------------

    hasil = []

    for index, row in df.iterrows():

        alert_text = str(row[alert_col]).strip()

        if (
            not alert_text
            or alert_text.lower() == "nan"
        ):
            continue


        # ----------------------------------------------------
        # ID KASUS
        # ----------------------------------------------------

        stream_expected = str(
            row[stream_col]
        ).strip().upper()

        if id_col is not None:

            id_kasus = str(
                row[id_col]
            ).strip()

        else:

            id_kasus = (
                f"{stream_expected}-{index + 1:03d}"
            )


        # ----------------------------------------------------
        # EXPECTED INFORMATION
        # ----------------------------------------------------

        try:

            expected_information = (
                parse_expected_information(
                    row[expected_col]
                )
            )

        except ValueError as error:

            hasil.append({

                "id_kasus": id_kasus,

                "stream": stream_expected,

                "raw_text": alert_text,

                "expected_information":
                    str(row[expected_col]),

                "actual_information": "",

                "status": "ERROR EXPECTED",

                "catatan": str(error),

            })

            continue


        # ----------------------------------------------------
        # JALANKAN MODEL
        # ----------------------------------------------------

        result = process_alert(alert_text)

        actual_information = result.get(
            "features",
            {},
        )


        # ----------------------------------------------------
        # PERBANDINGAN
        # ----------------------------------------------------

        status, catatan = compare_features(

            expected_information,

            actual_information,

        )


        # ----------------------------------------------------
        # SIMPAN HASIL
        # ----------------------------------------------------

        hasil.append({

            "id_kasus":
                id_kasus,

            "stream":
                stream_expected,

            "raw_text":
                alert_text,

            "expected_information":
                json.dumps(
                    expected_information,
                    ensure_ascii=False,
                ),

            "actual_information":
                json.dumps(
                    actual_information,
                    ensure_ascii=False,
                ),

            "status":
                status,

            "catatan":
                catatan,

        })


    # ========================================================
    # DATAFRAME HASIL DETAIL
    # ========================================================

    hasil_df = pd.DataFrame(hasil)


    # ========================================================
    # REKAP TABEL 4.7
    # ========================================================

    rekap = (

        hasil_df

        .groupby("stream")

        .agg(

            jumlah_kasus_uji=(
                "id_kasus",
                "count",
            ),

            sesuai=(
                "status",
                lambda x:
                    (x == "SESUAI").sum(),
            ),

            tidak_sesuai=(
                "status",
                lambda x:
                    (x == "TIDAK SESUAI").sum(),
            ),

            error_expected=(
                "status",
                lambda x:
                    (x == "ERROR EXPECTED").sum(),
            ),

        )

        .reset_index()

    )


    # --------------------------------------------------------
    # TEMUAN UTAMA OTOMATIS
    # --------------------------------------------------------

    def buat_temuan(row):

        if row["error_expected"] > 0:

            return (
                f"{row['error_expected']} kasus belum memiliki "
                "expected information yang valid."
            )

        if row["tidak_sesuai"] == 0:

            return (
                "Seluruh informasi target berhasil diekstraksi "
                "sesuai expected output."
            )

        return (
            f"{row['tidak_sesuai']} kasus mengalami "
            "ketidaksesuaian pada satu atau lebih "
            "informasi target."
        )


    rekap["temuan_utama"] = rekap.apply(
        buat_temuan,
        axis=1,
    )


    # ========================================================
    # TOTAL
    # ========================================================

    total = pd.DataFrame([{

        "stream":
            "Total",

        "jumlah_kasus_uji":
            len(hasil_df),

        "sesuai":
            (hasil_df["status"] == "SESUAI").sum(),

        "tidak_sesuai":
            (
                hasil_df["status"]
                == "TIDAK SESUAI"
            ).sum(),

        "error_expected":
            (
                hasil_df["status"]
                == "ERROR EXPECTED"
            ).sum(),

        "temuan_utama":
            "-",

    }])


    rekap_final = pd.concat(
        [
            rekap,
            total,
        ],
        ignore_index=True,
    )


    # ========================================================
    # SIMPAN EXCEL
    # ========================================================

    with pd.ExcelWriter(
        OUTPUT_FILE,
        engine="openpyxl",
    ) as writer:

        hasil_df.to_excel(
            writer,
            sheet_name="Detail Pengujian",
            index=False,
        )

        rekap_final.to_excel(
            writer,
            sheet_name="Rekap Tabel 4.7",
            index=False,
        )


    # ========================================================
    # OUTPUT TERMINAL
    # ========================================================

    print()
    print("=" * 70)
    print("HASIL PENGUJIAN")
    print("=" * 70)

    print()

    print(
        rekap_final.to_string(
            index=False
        )
    )

    print()

    print(f"Total data          : {len(hasil_df)}")

    print(
        "SESUAI             :",
        (
            hasil_df["status"]
            == "SESUAI"
        ).sum(),
    )

    print(
        "TIDAK SESUAI       :",
        (
            hasil_df["status"]
            == "TIDAK SESUAI"
        ).sum(),
    )

    print(
        "ERROR EXPECTED     :",
        (
            hasil_df["status"]
            == "ERROR EXPECTED"
        ).sum(),
    )

    print()

    print(
        f"File hasil disimpan : {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()