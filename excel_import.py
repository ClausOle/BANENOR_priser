"""
Leser en opplastet Excel-arbeidsbok og finner alle rader som følger det
kjente kostnadsoppsettet (Kostkode / Kostkode tekst / Enhet / Enh.pris),
uansett hvilken fane de ligger i eller hvor mange andre kolonner
(Delsum, Sum total, Merknader osv.) fanen har ved siden av.

Gjenkjenningen er strukturbasert, ikke navnebasert: en fane importeres
hvis og bare hvis den har en rad som inneholder alle fire påkrevde
kolonnenavn — sammendrag-/notat-faner uten denne strukturen hoppes
automatisk over.

"Mengde" er VALGFRI: hvis fanen har en Mengde-kolonne leses tallverdien
inn (tomt eller ikke-tall -> mangler), ellers settes mengde til mangler
for alle rader i fanen. Eldre filer uten Mengde importeres dermed
fortsatt, og fanerapporten sier fra om Mengde ble funnet.

En rad tas kun med hvis den har BÅDE en Kostkode og en tallverdi i
Enh.pris — rader som bare er mellomtitler, tomme grupper, eller uten
registrert pris ennå, droppes stille.
"""

import numpy as np
import pandas as pd

REQUIRED_LABELS = ["Kostkode", "Kostkode tekst", "Enhet", "Enh.pris"]
MENGDE_LABEL = "Mengde"
MAKS_HEADER_SOK_RADER = 10

UT_KOLONNER = ["kostkode", "kostkode_tekst", "enhet", "enh_pris", "mengde", "aar", "prosjekt_id", "fane"]


def _finn_header_og_kolonner(df_raw):
    """
    Søker i de første radene av en fane etter en rad som inneholder alle
    påkrevde kolonnenavn. Returnerer (header_rad_indeks, {label: kolonneindeks})
    for første treff, eller (None, None) hvis fanen ikke har strukturen.
    """
    for i in range(min(MAKS_HEADER_SOK_RADER, len(df_raw))):
        rad = df_raw.iloc[i]
        label_til_kol = {}
        for kol_idx, verdi in enumerate(rad):
            if isinstance(verdi, str):
                label_til_kol[verdi.strip()] = kol_idx
        if all(lbl in label_til_kol for lbl in REQUIRED_LABELS):
            return i, label_til_kol
    return None, None


def les_excel(fil, aar, prosjekt_id):
    """
    Leser hele arbeidsboken og returnerer (rader_df, fane_rapport):

    - rader_df: DataFrame med kolonnene i UT_KOLONNER — én rad per gyldig
      kostnadsrad funnet i hele fila, klar til forhåndsvisning/import.
      mengde er NaN der fanen mangler Mengde-kolonne eller cellen er tom.
    - fane_rapport: liste av (fanenavn, status_tekst, antall_rader) for
      hver fane i fila, til bruk i en oversikt over hva som ble
      gjenkjent/hoppet over.
    """
    xls = pd.ExcelFile(fil)
    alle_rader = []
    fane_rapport = []

    for sheet in xls.sheet_names:
        df_raw = pd.read_excel(xls, sheet_name=sheet, header=None)
        header_idx, kolonner = _finn_header_og_kolonner(df_raw)

        if header_idx is None:
            fane_rapport.append((sheet, "Hoppet over (struktur ikke gjenkjent)", 0))
            continue

        data = df_raw.iloc[header_idx + 1:].copy()
        kostkode = data.iloc[:, kolonner["Kostkode"]]
        kostkode_tekst = data.iloc[:, kolonner["Kostkode tekst"]]
        enhet = data.iloc[:, kolonner["Enhet"]]
        enh_pris = pd.to_numeric(data.iloc[:, kolonner["Enh.pris"]], errors="coerce")

        if MENGDE_LABEL in kolonner:
            mengde = pd.to_numeric(data.iloc[:, kolonner[MENGDE_LABEL]], errors="coerce")
            mengde_status = "med Mengde"
        else:
            mengde = pd.Series(np.nan, index=data.index, dtype="float64")
            mengde_status = "uten Mengde-kolonne"

        gyldig = kostkode.notna() & enh_pris.notna()
        n_gyldig = int(gyldig.sum())

        if n_gyldig > 0:
            uttrekk = pd.DataFrame({
                "kostkode": kostkode[gyldig].astype(str).str.strip(),
                "kostkode_tekst": kostkode_tekst[gyldig].fillna("").astype(str).str.strip(),
                "enhet": enhet[gyldig].fillna("").astype(str).str.strip(),
                "enh_pris": enh_pris[gyldig].astype(float),
                "mengde": mengde[gyldig].astype(float),
                "aar": int(aar),
                "prosjekt_id": prosjekt_id.strip(),
                "fane": sheet,
            })
            alle_rader.append(uttrekk)

        fane_rapport.append(
            (sheet, f"Gjenkjent (header i rad {header_idx + 1}, {mengde_status})", n_gyldig)
        )

    if alle_rader:
        rader_df = pd.concat(alle_rader, ignore_index=True)[UT_KOLONNER]
    else:
        rader_df = pd.DataFrame(columns=UT_KOLONNER)

    return rader_df, fane_rapport
