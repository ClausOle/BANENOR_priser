"""
Genererer syntetisk testdata for Price Tracker-appen, og skriver den til
Turso-databasen (samme sted som selve appen bruker).

Krever at .streamlit/secrets.toml er satt opp med [turso] url og auth_token,
samme som for selve appen.
"""

import random

import turso_db as db

random.seed(42)

KOSTKODER = [
    ("10.1", "Rydding av vegetasjon", "m2"),
    ("12.3", "Graving, løsmasser", "m3"),
    ("14.2", "Sprengning av fjell", "m3"),
    ("22.1", "Forsterkningslag", "m2"),
    ("22.4", "Bærelag, knust grus", "m3"),
    ("23.5", "Asfaltering, bindlag", "m2"),
    ("23.6", "Asfaltering, slitelag", "m2"),
    ("30.1", "Rørlegging, overvann", "lm"),
    ("30.2", "Kummer, komplett", "stk"),
    ("40.1", "Rekkverk, montering", "lm"),
    ("50.3", "Skilting, komplett", "stk"),
    ("60.1", "Grøntanlegg, såing", "m2"),
    ("70.2", "Trafikkregulering, drift", "uke"),
    ("80.1", "Brulager, montering", "stk"),
    ("90.5", "Belysning, mast komplett", "stk"),
]

PROSJEKTER = ["P-1001", "P-1002", "P-1003", "P-1004", "P-1005", "P-1006"]

BASE_PRICES = {
    "10.1": 45, "12.3": 180, "14.2": 320, "22.1": 210, "22.4": 260,
    "23.5": 140, "23.6": 155, "30.1": 950, "30.2": 18500, "40.1": 1200,
    "50.3": 3400, "60.1": 65, "70.2": 22000, "80.1": 145000, "90.5": 32000,
}

db.init_db()

rows = []
for kostkode, tekst, enhet in KOSTKODER:
    base = BASE_PRICES[kostkode]
    aktive_prosjekter = random.sample(PROSJEKTER, k=random.randint(2, len(PROSJEKTER)))

    for prosjekt in aktive_prosjekter:
        if random.random() < 0.1:
            aar_liste = [2025]
        else:
            n_aar = random.randint(2, 5)
            slutt_aar = 2025
            aar_liste = list(range(slutt_aar - n_aar + 1, slutt_aar + 1))

        pris = base * random.uniform(0.9, 1.1)
        for aar in aar_liste:
            vekst = random.uniform(1.02, 1.07)
            pris *= vekst
            rows.append((kostkode, tekst, enhet, round(pris, 2), aar, prosjekt))

inserted, duplicates = db.insert_many_ignore_duplicates(
    """
    INSERT OR IGNORE INTO prices
    (kostkode, kostkode_tekst, enhet, enh_pris, aar, prosjekt_id)
    VALUES (?, ?, ?, ?, ?, ?)
    """,
    rows,
)

print(f"Satte inn {inserted} rader i Turso-databasen ({duplicates} duplikat(er) hoppet over).")
