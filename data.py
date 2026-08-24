"""
Genererer syntetisk testdata for Price Tracker-appen.

Kjør denne i samme mappe som full_app.py, så fylles prices.db opp med
realistiske (fiktive) rader dere kan teste appen på.
"""

import os
import random
import sqlite3

# Absolutt sti: databasen ligger alltid ved siden av denne filen,
# uansett hvilken mappe du står i når du kjører scriptet fra.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prices.db")

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

conn = sqlite3.connect(DB_PATH)
conn.execute(
    """
    CREATE TABLE IF NOT EXISTS prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kostkode TEXT NOT NULL,
        kostkode_tekst TEXT,
        enhet TEXT,
        enh_pris REAL NOT NULL,
        aar INTEGER NOT NULL,
        prosjekt_id TEXT NOT NULL,
        UNIQUE(kostkode, prosjekt_id, aar)
    )
    """
)

rows = []
for kostkode, tekst, enhet in KOSTKODER:
    base = BASE_PRICES[kostkode]
    aktive_prosjekter = random.sample(PROSJEKTER, k=random.randint(2, len(PROSJEKTER)))

    for prosjekt in aktive_prosjekter:
        # De fleste kostkoder har 2-5 år med data; noen faa har bare 1 aar
        # for aa teste "ikke nok data"-varselen i appen.
        if random.random() < 0.1:
            aar_liste = [2025]
        else:
            n_aar = random.randint(2, 5)
            slutt_aar = 2025
            aar_liste = list(range(slutt_aar - n_aar + 1, slutt_aar + 1))

        pris = base * random.uniform(0.9, 1.1)  # litt variasjon mellom prosjekter
        for aar in aar_liste:
            vekst = random.uniform(1.02, 1.07)  # 2-7% aarlig vekst
            pris *= vekst
            rows.append((
                kostkode,
                tekst,
                enhet,
                round(pris, 2),
                aar,
                prosjekt,
            ))

cur = conn.cursor()
inserted = 0
for row in rows:
    cur.execute(
        """
        INSERT OR IGNORE INTO prices
        (kostkode, kostkode_tekst, enhet, enh_pris, aar, prosjekt_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        row,
    )
    if cur.rowcount:
        inserted += 1

conn.commit()
conn.close()

print(f"Satte inn {inserted} rader i {DB_PATH}.")