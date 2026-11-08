"""
Synthetic notes with deliberately planted errors, plus clean controls.
Used by tests/test_rules.py to prove the pipeline catches real problems.
"""

NOTES = {
    "drug_allergy_conflict": """
        Patient presents with sinus infection. Allergies: penicillin.
        BP: 118/76. HR: 72. Temp: 98.6. RR: 16.
        Plan: Start amoxicillin 500mg three times daily for 10 days.
    """,

    "dosage_out_of_range": """
        Patient here for hypertension follow-up. Allergies: none known.
        BP: 142/90. HR: 80. Temp: 98.4. RR: 14.
        Plan: Increase lisinopril 120mg daily.
    """,

    "missing_vitals": """
        Patient reports mild headache for two days. Allergies: NKDA.
        Plan: Recommend acetaminophen 500mg as needed, follow up in one week.
    """,

    "missing_allergy_section": """
        Patient here for routine diabetes check.
        BP: 130/85. HR: 76. Temp: 98.7. RR: 15.
        Plan: Continue metformin 500mg twice daily.
    """,

    "clean_note": """
        Patient here for routine follow-up. Allergies: no known drug allergies.
        BP: 122/78. HR: 70. Temp: 98.6. RR: 16.
        Plan: Continue atorvastatin 20mg daily.
    """,

    "clean_note_2": """
        Patient presents with mild cough. Allergies: none known.
        BP: 118/74. HR: 68. Temp: 98.5. RR: 14.
        Plan: Amoxicillin 500mg twice daily for 7 days.
    """,

    # Regression case: found 2026-09-10 during a live smoke test. Same conflict
    # as "drug_allergy_conflict" above, but phrased as prose instead of an
    # "Allergies: <list>" line — this previously went unflagged because the
    # old extractor captured "to penicillin noted in chart" as one allergy
    # string instead of "penicillin".
    "messy_phrasing_conflict": """
        Pt has an allergy to Penicillin noted in chart.
        Rx: Amoxicillin 500 mg PO TID.
        Vitals: BP 120/80 HR 70 Temp 98.6 RR 16.
    """,

    # Same regression, different prose order ("<drug> allergy" instead of
    # "allergy to <drug>").
    "prose_allergy_conflict": """
        Penicillin allergy noted on intake.
        Plan: Start amoxicillin 500mg three times daily.
        BP: 118/76. HR: 72. Temp: 98.6. RR: 16.
    """,
}
