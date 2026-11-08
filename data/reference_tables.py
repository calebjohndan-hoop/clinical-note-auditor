"""
Reference tables for the rule engine.

Scope deliberately small and well-known for a defensible demo (5-10 classic
conflicts, not a drug database). EVERY entry carries a source comment. Before
adding an entry: find the source first, then add it. If you can't cite it,
don't add it — a judge who finds one wrong entry discounts all of them.

Sources referenced below (all free / public):
  [DM]  DailyMed (NIH/NLM) FDA-approved prescribing information for the drug
        named in the comment: Contraindications + Dosage & Administration.
  [ACR] American College of Radiology, ACR Manual on Contrast Media.
  [AHA] Wilson W. et al., "Prevention of Viridans Group Streptococcal Infective
        Endocarditis", AHA Scientific Statement, Circulation 2021.
  [AAAAI] AAAAI/ACAAI Drug Allergy Practice Parameter Update, 2022.

NOT clinical guidance. Bounds are sanity checks to catch transcription errors
(500 mg written as 5000 mg, mg vs g), not individualized dosing.
"""

# allergy (lowercase) -> drugs that conflict with it.
ALLERGY_DRUG_CONFLICTS = {
    # Same beta-lactam class; labels contraindicate in penicillin hypersensitivity. [DM: amoxicillin,
    # ampicillin, piperacillin-tazobactam]. Cephalosporins deliberately NOT listed: cross-reactivity
    # is low (~1-2%) and current guidance does not treat it as a contraindication. [AAAAI]
    "penicillin": ["amoxicillin", "ampicillin", "penicillin", "piperacillin"],
    # Contraindicated in sulfonamide hypersensitivity. [DM: sulfamethoxazole-trimethoprim (Bactrim),
    # sulfasalazine]
    "sulfa": ["sulfamethoxazole", "sulfasalazine", "trimethoprim-sulfamethoxazole", "bactrim"],
    # NSAID labels contraindicate in patients with asthma/urticaria/allergic-type reactions after
    # aspirin or other NSAIDs. [DM: ibuprofen, naproxen, ketorolac — Contraindications]
    "nsaid": ["ibuprofen", "naproxen", "aspirin", "ketorolac"],
    # Aspirin-sensitive patients: NSAID labels contraindicate them (and the aspirin label
    # contraindicates NSAID allergy). [DM: aspirin; ibuprofen, naproxen, ketorolac — Contraindications]
    "aspirin": ["aspirin", "acetylsalicylic acid", "ibuprofen", "naproxen", "ketorolac"],
    # Codeine "allergy" is usually intolerance; true opioid cross-reactivity is uncommon. Kept as a
    # REVIEW-level flag (see CONFLICT_SEVERITY), not a hard stop. [AAAAI]
    "codeine": ["codeine", "hydrocodone"],
    # Not a drug conflict; kept so "latex" parses as a documented allergy (procedure supplies).
    "latex": [],
    # "Iodine allergy" is NOT a contraindication to iodinated contrast — iodine isn't an allergen.
    # Recognized as an allergy term, never flags contrast. Flagging it would repeat a myth. [ACR]
    "iodine": [],
}

# Allergies whose conflicts should be "review", not "high". Default is "high".
CONFLICT_SEVERITY = {
    "codeine": "medium",
}

# drug -> (min, max, unit) for a SINGLE adult dose unless noted. [DM = that drug's label, D&A section]
DOSAGE_SAFE_RANGES = {
    "acetaminophen": (325, 1000, "mg"),    # [DM] max 1000 mg/dose, 4000 mg/day (OTC labeling 3000)
    "ibuprofen": (200, 800, "mg"),         # [DM] Rx 400-800 mg/dose, max 3200 mg/day; OTC 200-400
    "amoxicillin": (250, 2000, "mg"),      # [DM] 250-875 mg/dose; 2 g single dose = prophylaxis [AHA]
    "metformin": (500, 2000, "mg"),        # [DM] IR 500-1000/dose; ER up to 2000 mg once daily
    "lisinopril": (2.5, 80, "mg"),         # [DM] daily; usual 20-40 mg, up to 80 mg used
    "warfarin": (1, 10, "mg"),             # [DM] daily; maintenance typically 2-10 mg, INR-guided
    "atorvastatin": (10, 80, "mg"),        # [DM] daily; 10-80 mg
}

# Common clinical abbreviations for allergy entries -> ALLERGY_DRUG_CONFLICTS key.
# PCN, ASA are standard prescriber abbreviations for penicillin and aspirin (ASA = acetylsalicylic
# acid); sulfonamide is the class name behind "sulfa".
ALLERGY_ALIASES = {
    "pcn": "penicillin",
    "asa": "aspirin",
    "sulfonamide": "sulfa",
    "sulfonamides": "sulfa",
    "nsaid": "nsaid",
    # descriptive forms LLMs and clinicians use for the penicillin class
    "pen": "penicillin",
    "pen vk": "penicillin",
    "penicillins": "penicillin",
    "penicillin g": "penicillin",
    "penicillin v": "penicillin",
    "pen class": "penicillin",
    "pen-class": "penicillin",
    "penicillin class": "penicillin",
    "penicillin-class": "penicillin",
    "penicillin type": "penicillin",
    "penicillin-type": "penicillin",
    "penicillin family": "penicillin",
    "imuran": "azathioprine",
    # opioid brands seen in real allergy lists (allergy side only: the meds table never maps
    # combination products to a single dose)
    "duragesic": "fentanyl",
    "percocet": "oxycodone",
    "percodan": "oxycodone",
    # An allergy to an aminopenicillin is managed as a penicillin allergy until a
    # penicillin allergy evaluation says otherwise [AAAAI]. Conservative on purpose:
    # the output is a "review" flag, never an automatic order change.
    "amoxicillin": "penicillin",
    "ampicillin": "penicillin",
    "augmentin": "penicillin",
    "amoxil": "penicillin",
}

# US brand name -> generic, so brand-name orders hit the same rules.
# Source: each brand's DailyMed label (active ingredient). Verified pairs only.
DRUG_ALIASES = {
    "tylenol": "acetaminophen",
    "paracetamol": "acetaminophen",   # INN name used outside the US (incl. India)
    "augmentin": "amoxicillin",       # amoxicillin/clavulanate; dose listed = amoxicillin component
    "amoxil": "amoxicillin",
    "advil": "ibuprofen",
    "motrin": "ibuprofen",
    "aleve": "naproxen",
    "glucophage": "metformin",
    "lipitor": "atorvastatin",
    "coumadin": "warfarin",
    "zestril": "lisinopril",
    "prinivil": "lisinopril",
    # Added after the first real-note run (MTSamples): brand names the notes actually used.
    # Source: each brand's DailyMed label, active ingredient. Single-ingredient products only.
    "inderal": "propranolol",
    "lexapro": "escitalopram",
    "colace": "docusate",
    "dilantin": "phenytoin",
    "norvasc": "amlodipine",
    "renagel": "sevelamer",
    "sensipar": "cinacalcet",
    "zocor": "simvastatin",
    "levaquin": "levofloxacin",
    "lovenox": "enoxaparin",
    "protonix": "pantoprazole",
    "levoxyl": "levothyroxine",
    "synthroid": "levothyroxine",
    "unithroid": "levothyroxine",
    "diovan": "valsartan",
    "imuran": "azathioprine",
    "zoloft": "sertraline",
    "prozac": "fluoxetine",
    "xanax": "alprazolam",
    "ativan": "lorazepam",
    "valium": "diazepam",
    "klonopin": "clonazepam",
    "lasix": "furosemide",
    "plavix": "clopidogrel",
    "crestor": "rosuvastatin",
    "nexium": "esomeprazole",
    "prilosec": "omeprazole",
    "zofran": "ondansetron",
    "neurontin": "gabapentin",
    "flexeril": "cyclobenzaprine",
    "ultram": "tramadol",
    "singulair": "montelukast",
    "zyrtec": "cetirizine",
    "claritin": "loratadine",
    "benadryl": "diphenhydramine",
    "cipro": "ciprofloxacin",
    "zithromax": "azithromycin",
    "keflex": "cephalexin",
    "lopressor": "metoprolol",
    "dolophine": "methadone",
}

# Fields the rule engine expects to see in a well-formed structured note.
REQUIRED_VITALS = ["blood_pressure", "heart_rate", "temperature", "respiratory_rate"]
