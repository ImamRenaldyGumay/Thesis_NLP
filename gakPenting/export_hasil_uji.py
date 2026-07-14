import json
import pandas as pd

from rules import process_alert


INPUT_FILE = "Template_Alert.xlsx"
OUTPUT_FILE = "Hasil_Aktual_80_Alert.xlsx"


def main():
    df = pd.read_excel(INPUT_FILE)

    hasil = []

    for index, row in df.iterrows():

        alert_text = str(row["MESSAGE"]).strip()

        if not alert_text or alert_text.lower() == "nan":
            continue

        result = process_alert(alert_text)

        hasil.append({
            # IDENTITAS KASUS
            "id_kasus": f"{str(row['stream']).upper()}-{int(row['no']):02d}",
            "no": row["no"],
            "time": row["TIME"],
            "stream_expected": row["stream"],
            "application": row["application"],
            "raw_text": alert_text,
            "severity_original": row["SEVERITY"],

            # HASIL AKTUAL MODEL
            "stream_actual": result.get("stream", ""),

            "actual_information": json.dumps(
                result.get("features", {}),
                ensure_ascii=False
            ),

            "actual_rule": ", ".join(
                result.get("aturan_aktif", [])
            ),

            "actual_diagnosis": result.get(
                "diagnosis",
                ""
            ),

            "actual_reasoning": result.get(
                "alasan_pembacaan",
                ""
            ),

            "actual_recommendation": result.get(
                "rekomendasi",
                ""
            ),

            "actual_team": result.get(
                "tim_terkait",
                ""
            ),
        })

    hasil_df = pd.DataFrame(hasil)

    hasil_df.to_excel(
        OUTPUT_FILE,
        index=False
    )

    print("=" * 60)
    print("EXPORT HASIL AKTUAL SELESAI")
    print("=" * 60)
    print(f"Jumlah alert diproses : {len(hasil_df)}")
    print(f"File output           : {OUTPUT_FILE}")


if __name__ == "__main__":
    main()