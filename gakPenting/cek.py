"""
cek.py

Pengujian fungsional engine Rule-Based NLP.

Tujuan:
1. Memastikan stream terdeteksi dengan benar.
2. Memastikan Scanner menghasilkan token.
3. Memastikan Parser menghasilkan informasi terstruktur.
4. Memastikan Translator menghasilkan fakta.
5. Memastikan Evaluator mengaktifkan aturan produksi yang sesuai.
6. Memastikan output pembacaan dan rekomendasi tersedia.

File ini BUKAN pengujian model menggunakan F1-score.
File ini digunakan untuk validasi teknis/fungsional implementasi.
"""

from rules import process_alert


# ============================================================
# TEST DATA
# ============================================================

TEST_CASES = [

    # ========================================================
    # NGSSP - NODE EXPORTER
    # ========================================================

    {
        "name": "NGSSP Node Exporter",
        "alert": (
            "MMOlZMsWz|RVS SOAD9 - Node Exporter Status ~ "
            "xptrvssoa123:9092 with val: 0, "
            "Issue start at: 2024-11-08T01:00:00.000+07:00, "
            "Pls inform middleware Team! "
            "Url link:http://10.34.218.132:3000/"
            "alerting/grafana/Vo-SKp24z/view"
        ),
        "expected_stream": "NGSSP",
        "expected_rule": "R-NGSSP-01",
    },


    # ========================================================
    # NGSSP - JVM MANAGED SERVER
    # ========================================================

    {
        "name": "NGSSP JVM Managed Server",
        "alert": (
            "wXxyDUEGz|GEORED NGSSP SOAD7 - "
            "JVM Managed Server Status alert ~ "
            "WLS_SOA1@GEORED-NGSSP-SOAD7 with val: 0, "
            "Issue start at: 2025-03-15T21:24:00.000+07:00, "
            "Pls inform ngssp Team! "
            "Url link:http://10.34.218.132:3000/"
            "alerting/grafana/oXKtajG4z/view"
        ),
        "expected_stream": "NGSSP",
        "expected_rule": "R-NGSSP-02",
    },


    # ========================================================
    # BWCE
    # ========================================================

    {
        "name": "BWCE SR Degraded Technical Error",
        "alert": (
            "bi-aljabor-tmf - Total: 53176, "
            "Success: 29334, BE: 0, TE: 23842, "
            "Undefined: 0, SR: 55.16% - "
            "TE Info: TIBCO-BW-PALETTE-REST-100016 | "
            "Snapshot date 10/05/2026 10:00 "
            "BWCE SR Degraded, ngssp/vas team pls check!"
        ),
        "expected_stream": "BWCE",
        "expected_rule": "R-BWCE-01",
    },


    # ========================================================
    # USSD - PROCESS NOT RUNNING
    # ========================================================

    {
        "name": "USSD Process Not Running",
        "alert": (
            "2:- Billing_3 "
            "3:- XPTPSDPPROV02 "
            "4 :- 10.49.73.90 "
            "5 :- CRITICAL "
            "6 :- Sun May 10 01:18:12 WIB 2026 "
            "7 :- CRITICAL - Process is not running!"
        ),
        "expected_stream": "USSD",
        "expected_rule": "R-USSD-01",
    },


    # ========================================================
    # USSD - ERRORS FOUND
    # ========================================================

    {
        "name": "USSD Errors Found",
        "alert": (
            "2:- ERROR_TCPEV_CPT_DISCARD "
            "3:- jktmmpscpsig01 "
            "4 :- 10.64.65.187 "
            "5 :- CRITICAL "
            "6 :- Sun May 10 01:18:12 WIB 2026 "
            "7 :- CRITICAL : Errors found : "
            "Number of time occured= 1"
        ),
        "expected_stream": "USSD",
        "expected_rule": "R-USSD-02",
    },


    # ========================================================
    # CRM / OMNI
    # ========================================================

    {
        "name": "CRM OMNI Service Down",
        "alert": (
            "dashboard-data-provider "
            "in jktmmpvomnilbs01 DOWN"
        ),
        "expected_stream": "CRM",
        "expected_rule": "R-CRM-01",
    },
]


# ============================================================
# VALIDATION
# ============================================================

def validate_test_case(test_case):
    """
    Menjalankan satu kasus uji dan memeriksa hasil pipeline.
    """

    result = process_alert(
        test_case["alert"]
    )

    expected_stream = test_case[
        "expected_stream"
    ]

    expected_rule = test_case[
        "expected_rule"
    ]

    actual_stream = result.get(
        "stream",
        "UNKNOWN",
    )

    active_rules = result.get(
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


    # ========================================================
    # CHECKS
    # ========================================================

    checks = {
        "Stream sesuai":
            actual_stream == expected_stream,

        "Scanner menghasilkan token":
            bool(tokens.get("lexemes", [])),

        "Parser menghasilkan data":
            bool(parsed_data),

        "Translator menghasilkan fakta":
            bool(facts),

        "Aturan sesuai":
            expected_rule in active_rules,

        "Pembacaan tersedia":
            bool(hasil_pembacaan.strip()),

        "Alasan tersedia":
            bool(alasan_pembacaan.strip()),

        "Rekomendasi tersedia":
            bool(rekomendasi.strip()),
    }


    passed = all(
        checks.values()
    )


    return result, checks, passed


# ============================================================
# PRINT PIPELINE
# ============================================================

def print_pipeline(result):
    """
    Menampilkan ringkasan pipeline.
    """

    print("\n--- SCANNER ---")

    for token in result.get(
        "tokens",
        {}
    ).get(
        "lexemes",
        []
    ):

        print(
            f"{token.get('type')} "
            f"= {token.get('value')}"
        )


    print("\n--- PARSER ---")

    for key, value in result.get(
        "parsed_data",
        {}
    ).items():

        print(
            f"{key} = {value}"
        )


    print("\n--- TRANSLATOR ---")

    for fact in result.get(
        "facts",
        []
    ):

        print(
            f"{fact.get('predicate')}("
            f"{fact.get('value')})"
        )


    print("\n--- EVALUATOR ---")

    active_rules = result.get(
        "aturan_aktif",
        [],
    )

    if active_rules:

        for rule in active_rules:

            print(
                f"{rule} -> AKTIF"
            )

    else:

        print(
            "TIDAK ADA ATURAN AKTIF"
        )


    print("\n--- OUTPUT ---")

    print(
        "Pembacaan :",
        result.get(
            "hasil_pembacaan",
            "",
        ),
    )

    print(
        "Alasan    :",
        result.get(
            "alasan_pembacaan",
            "",
        ),
    )

    print(
        "Rekomendasi:",
        result.get(
            "rekomendasi",
            "",
        ),
    )

    print(
        "Tim       :",
        result.get(
            "tim_terkait",
            "",
        ),
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)

    print(
        "PENGUJIAN FUNGSIONAL ENGINE RULE-BASED NLP"
    )

    print("=" * 70)

    total = len(TEST_CASES)

    passed_count = 0

    failed_cases = []


    for number, test_case in enumerate(
        TEST_CASES,
        start=1,
    ):

        print("\n")
        print("=" * 70)

        print(
            f"TEST {number}/{total}"
        )

        print(
            f"NAMA : {test_case['name']}"
        )

        print(
            f"EXPECTED STREAM : "
            f"{test_case['expected_stream']}"
        )

        print(
            f"EXPECTED RULE   : "
            f"{test_case['expected_rule']}"
        )

        print("=" * 70)


        try:

            result, checks, passed = (
                validate_test_case(
                    test_case
                )
            )


            print(
                "\nHASIL VALIDASI:"
            )


            for check_name, check_result in (
                checks.items()
            ):

                status = (
                    "PASS"
                    if check_result
                    else "FAIL"
                )

                symbol = (
                    "✓"
                    if check_result
                    else "✗"
                )

                print(
                    f"{symbol} "
                    f"{check_name:<35} "
                    f": {status}"
                )


            print_pipeline(result)


            if passed:

                passed_count += 1

                print(
                    "\nSTATUS TEST: PASS"
                )

            else:

                failed_cases.append(
                    test_case["name"]
                )

                print(
                    "\nSTATUS TEST: FAIL"
                )


        except Exception as error:

            failed_cases.append(
                test_case["name"]
            )

            print(
                "\nSTATUS TEST: ERROR"
            )

            print(
                f"ERROR: {error}"
            )


    # ========================================================
    # SUMMARY
    # ========================================================

    print("\n")
    print("=" * 70)

    print(
        "RINGKASAN PENGUJIAN"
    )

    print("=" * 70)

    print(
        f"TOTAL TEST : {total}"
    )

    print(
        f"PASS       : {passed_count}"
    )

    print(
        f"FAIL/ERROR : "
        f"{total - passed_count}"
    )


    success_rate = (
        passed_count / total * 100
        if total > 0
        else 0
    )


    print(
        f"KEBERHASILAN: "
        f"{success_rate:.2f}%"
    )


    if failed_cases:

        print(
            "\nTEST YANG GAGAL:"
        )

        for case_name in failed_cases:

            print(
                f"- {case_name}"
            )

    else:

        print(
            "\nSEMUA TEST BERHASIL."
        )


    print("=" * 70)


if __name__ == "__main__":
    main()