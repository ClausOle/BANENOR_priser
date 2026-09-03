"""
Databasetilkobling mot Turso (libSQL), for delt bruk mellom flere personer.

Bruker libsql_client sin synkrone klient direkte mot Turso i skyen (INGEN
lokal "embedded replica"-fil). Det betyr at hver spørring går over nett og
alltid gir ferske, delte data — ingen synk-håndtering eller risiko for at
noen ser utdaterte tall fra en lokal kopi. Prisen er at hver spørring har
litt nettverks-latency. Derfor:

  - init_db() kjøres én gang per økt (styres fra appen), ikke hver rerun.
  - Innsetting og sletting gjøres i BATCH (client.batch), så en Excel-fil
    med 300 rader koster noen få nettverksrunder, ikke 600.

Skjemaendringer håndteres med en enkel migrering i init_db(): CREATE TABLE
IF NOT EXISTS oppretter tabellen for nye databaser, og en PRAGMA-sjekk
legger til kolonner som mangler i eksisterende databaser (f.eks. "mengde",
som kom til etter at tabellen først ble laget).

Turso-URL og auth-token leses fra Streamlit sine secrets
(.streamlit/secrets.toml), ALDRI hardkodet eller committet til git.
"""

import math
from collections import namedtuple

import pandas as pd
import streamlit as st
import libsql_client
from libsql_client import Statement

TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kostkode TEXT NOT NULL,
    kostkode_tekst TEXT,
    enhet TEXT,
    enh_pris REAL NOT NULL,
    mengde REAL,
    aar INTEGER NOT NULL,
    prosjekt_id TEXT NOT NULL,
    UNIQUE(kostkode, prosjekt_id, aar)
)
"""

# Kolonner som skal finnes i eksisterende tabeller. Legges til med
# ALTER TABLE hvis de mangler (SQLite/libSQL støtter kun ADD COLUMN, som
# er alt vi trenger). Nye kolonner i fremtiden: legg dem til her OG i
# TABLE_SCHEMA over.
MIGRERINGER = {
    "mengde": "ALTER TABLE prices ADD COLUMN mengde REAL",
}

INSERT_SQL = """
INSERT INTO prices (kostkode, kostkode_tekst, enhet, enh_pris, mengde, aar, prosjekt_id)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""

ImportResultat = namedtuple("ImportResultat", ["inserted", "duplicates", "conflicts", "mengde_oppdatert"])


def _get_client():
    # libsql:// bruker som standard WebSocket (wss://) mot Turso. Mange
    # bedriftsnettverk (brannmur/proxy) blokkerer eller bryter WebSocket-
    # handshaket, noe som gir en kryptisk "400 Invalid response status".
    # https:// bruker ren HTTP i stedet — samme database, mer robust
    # transport gjennom brannmurer. Vi bytter derfor ut skjemaet her,
    # så URL-en fra "turso db show" kan limes inn uendret i secrets.toml.
    url = st.secrets["turso"]["url"]
    if url.startswith("libsql://"):
        url = "https://" + url[len("libsql://"):]
    return libsql_client.create_client_sync(
        url=url,
        auth_token=st.secrets["turso"]["auth_token"],
    )


def _til_db(verdi):
    """NaN/None -> None (SQL NULL), ellers float. Brukes for valgfrie tallfelt."""
    if verdi is None:
        return None
    try:
        f = float(verdi)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def init_db():
    """Oppretter tabellen hvis den ikke finnes, og legger til manglende kolonner."""
    client = _get_client()
    try:
        client.execute(TABLE_SCHEMA)
        rs = client.execute("PRAGMA table_info(prices)")
        eksisterende_kolonner = {row[1] for row in rs.rows}
        for kolonne, sql in MIGRERINGER.items():
            if kolonne not in eksisterende_kolonner:
                client.execute(sql)
    finally:
        client.close()


def query_df(sql, args=()):
    """Kjører en SELECT og returnerer resultatet som en pandas DataFrame."""
    client = _get_client()
    try:
        rs = client.execute(sql, args)
        return pd.DataFrame([tuple(row) for row in rs.rows], columns=list(rs.columns))
    finally:
        client.close()


def klassifiser_rader(rows, eksisterende):
    """
    Ren funksjon (ingen DB) som deler rader inn i nye / duplikater /
    konflikter, gitt et oppslag over hva som allerede finnes.

    rows: liste av dict med nøklene kostkode, kostkode_tekst, enhet,
          enh_pris, mengde, aar, prosjekt_id.
    eksisterende: {(kostkode, prosjekt_id, aar): (enh_pris, mengde)}.
                  Oppdateres underveis, slik at to rader i samme opplasting
                  (f.eks. samme kostkode i to faner) også sjekkes mot
                  hverandre, ikke bare mot databasen.

    Returnerer (nye, duplikater, konflikter, mengde_oppdateringer):
      - nye: rader som kan settes inn
      - duplikater: antall rader som finnes fra før med samme pris
      - konflikter: liste av dict med gammel og ny pris
      - mengde_oppdateringer: [(kostkode, prosjekt_id, aar, mengde)] for
        duplikater der databasen mangler mengde men den nye raden har det —
        så eldre oppføringer kan få mengde i etterkant ved re-opplasting.
    """
    nye = []
    duplikater = 0
    konflikter = []
    mengde_oppdateringer = []

    for r in rows:
        kostkode = str(r["kostkode"]).strip()
        prosjekt_id = str(r["prosjekt_id"]).strip()
        aar = int(r["aar"])
        enh_pris = float(r["enh_pris"])
        mengde = _til_db(r.get("mengde"))
        nokkel = (kostkode, prosjekt_id, aar)

        if nokkel not in eksisterende:
            nye.append((kostkode, r.get("kostkode_tekst", "") or "", r.get("enhet", "") or "",
                        enh_pris, mengde, aar, prosjekt_id))
            eksisterende[nokkel] = (enh_pris, mengde)
            continue

        gammel_pris, gammel_mengde = eksisterende[nokkel]
        if abs(gammel_pris - enh_pris) < 0.005:
            duplikater += 1
            if gammel_mengde is None and mengde is not None:
                mengde_oppdateringer.append((kostkode, prosjekt_id, aar, mengde))
                eksisterende[nokkel] = (gammel_pris, mengde)
        else:
            konflikter.append({
                "kostkode": kostkode,
                "prosjekt_id": prosjekt_id,
                "aar": aar,
                "eksisterende_pris": gammel_pris,
                "ny_pris": enh_pris,
            })

    return nye, duplikater, konflikter, mengde_oppdateringer


def insert_many_check_conflicts(rows):
    """
    Setter inn rader med konflikt-sjekk. rows: liste av dict med nøklene
    kostkode, kostkode_tekst, enhet, enh_pris, mengde (valgfri/None), aar,
    prosjekt_id.

    For hver rad sjekkes det om kostkode+prosjekt_id+aar finnes fra før:
      - Finnes ikke -> settes inn ("inserted").
      - Finnes med SAMME enh_pris (innenfor øre-toleranse) -> ekte
        duplikat, hoppes over ("duplicates"). Mangler databasen mengde
        for raden, men den nye har det, fylles mengde inn
        ("mengde_oppdatert").
      - Finnes med ANNEN enh_pris -> settes IKKE inn (ville uansett
        brutt unik-constraint), og legges i "conflicts" med både gammel
        og ny pris, slik at det vises tydelig i stedet for å forsvinne.

    Nettverksbruk: én SELECT per distinkt (prosjekt_id, aar) i opplastingen
    (normalt 1), deretter én batch for alle INSERT/UPDATE.

    Returnerer ImportResultat(inserted, duplicates, conflicts, mengde_oppdatert).
    """
    if not rows:
        return ImportResultat(0, 0, [], 0)

    client = _get_client()
    try:
        eksisterende = {}
        par = {(str(r["prosjekt_id"]).strip(), int(r["aar"])) for r in rows}
        for prosjekt_id, aar in par:
            rs = client.execute(
                "SELECT kostkode, enh_pris, mengde FROM prices WHERE prosjekt_id = ? AND aar = ?",
                (prosjekt_id, aar),
            )
            for kostkode, pris, mengde in rs.rows:
                eksisterende[(kostkode, prosjekt_id, aar)] = (pris, mengde)

        nye, duplikater, konflikter, mengde_oppd = klassifiser_rader(rows, eksisterende)

        stmts = [Statement(INSERT_SQL, verdier) for verdier in nye]
        stmts += [
            Statement(
                "UPDATE prices SET mengde = ? WHERE kostkode = ? AND prosjekt_id = ? AND aar = ?",
                (mengde, kostkode, prosjekt_id, aar),
            )
            for kostkode, prosjekt_id, aar, mengde in mengde_oppd
        ]
        if stmts:
            client.batch(stmts)

        return ImportResultat(len(nye), duplikater, konflikter, len(mengde_oppd))
    finally:
        client.close()


def delete_by_ids(ids):
    """Sletter rader med gitte id-er (i én batch). Returnerer antall faktisk slettet."""
    if not ids:
        return 0
    client = _get_client()
    try:
        resultater = client.batch(
            [Statement("DELETE FROM prices WHERE id = ?", (int(i),)) for i in ids]
        )
        return sum(rs.rows_affected for rs in resultater)
    finally:
        client.close()
