"""
Databasetilkobling mot Turso (libSQL), for delt bruk mellom flere personer.

Bruker libsql_client sin synkrone klient direkte mot Turso i skyen (INGEN
lokal "embedded replica"-fil). Det betyr at hver spørring går over nett og
alltid gir ferske, delte data — ingen synk-håndtering eller risiko for at
noen ser utdaterte tall fra en lokal kopi. Prisen er at hver spørring har
litt nettverks-latency, som ikke er et problem for dette bruksmønsteret
(en håndfull personer som av og til legger inn/ser på priser).

Turso-URL og auth-token leses fra Streamlit sine secrets
(.streamlit/secrets.toml), ALDRI hardkodet eller committet til git.
"""

import pandas as pd
import streamlit as st
import libsql_client

TABLE_SCHEMA = """
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


def init_db():
    """Oppretter tabellen hvis den ikke finnes fra før."""
    client = _get_client()
    try:
        client.execute(TABLE_SCHEMA)
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


def insert_many_check_conflicts(rows):
    """
    Setter inn rader med konflikt-sjekk, én om gangen over samme
    tilkobling. rows: liste av
    (kostkode, kostkode_tekst, enhet, enh_pris, aar, prosjekt_id).

    For hver rad sjekkes det først om kostkode+prosjekt_id+aar finnes
    fra før:
      - Finnes ikke -> settes inn ("inserted").
      - Finnes med SAMME enh_pris (innenfor øre-toleranse) -> ekte
        duplikat, hoppes stille over ("duplicates").
      - Finnes med ANNEN enh_pris -> settes IKKE inn (ville uansett
        brutt unik-constraint), og legges i "conflicts" med både gammel
        og ny pris, slik at det vises tydelig i stedet for å forsvinne.

    Returnerer (inserted: int, duplicates: int, conflicts: list[dict]).
    """
    client = _get_client()
    inserted = 0
    duplicates = 0
    conflicts = []
    try:
        for kostkode, kostkode_tekst, enhet, enh_pris, aar, prosjekt_id in rows:
            rs = client.execute(
                "SELECT enh_pris FROM prices WHERE kostkode = ? AND prosjekt_id = ? AND aar = ?",
                (kostkode, prosjekt_id, aar),
            )
            if not rs.rows:
                client.execute(
                    """
                    INSERT INTO prices (kostkode, kostkode_tekst, enhet, enh_pris, aar, prosjekt_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (kostkode, kostkode_tekst, enhet, enh_pris, aar, prosjekt_id),
                )
                inserted += 1
            else:
                eksisterende_pris = rs.rows[0][0]
                if abs(eksisterende_pris - enh_pris) < 0.005:
                    duplicates += 1
                else:
                    conflicts.append({
                        "kostkode": kostkode,
                        "prosjekt_id": prosjekt_id,
                        "aar": aar,
                        "eksisterende_pris": eksisterende_pris,
                        "ny_pris": enh_pris,
                    })
        return inserted, duplicates, conflicts
    finally:
        client.close()


def delete_by_ids(ids):
    """Sletter rader med gitte id-er. Returnerer antall faktisk slettet."""
    if not ids:
        return 0
    client = _get_client()
    try:
        deleted = 0
        for i in ids:
            rs = client.execute("DELETE FROM prices WHERE id = ?", (int(i),))
            deleted += rs.rows_affected
        return deleted
    finally:
        client.close()
