"""
Henter Byggekostnadsindeks for veganlegg (SSB tabell 08658) live fra
SSBs PxWebApi v2, og gir funksjoner for å prisjustere en pris fra ett
år til et annet ved hjelp av indeksen.

SSBs metadata-endepunkt returnerer et fullt json-stat2-datasett (samme
struktur som selve dataendepunktet, bare med tom "value"-liste). Det
har en "role"-blokk som forteller hvilken dimensjon som er tid
("role.time") og hvilken som er statistikkvariabel ("role.metric"),
og en "dimension"-blokk med kategori-koder og -tekster per dimensjon.
Vi leser disse dynamisk i stedet for å hardkode dimensjonsnavn, slik
at koden tåler at SSB endrer navn/koder internt, så lenge selve
tabellstrukturen (tid, statistikkvariabel, anleggstype) forblir lik.
"""

import requests
import streamlit as st

SSB_TABLE_ID = "08658"
BASE_URL = f"https://data.ssb.no/api/pxwebapi/v2/tables/{SSB_TABLE_ID}"


@st.cache_data(ttl=3600)
def hent_metadata():
    """Henter variabelstrukturen for tabell 08658 (koder + tekster)."""
    resp = requests.get(f"{BASE_URL}/metadata", params={"lang": "no"}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _finn_variabler(metadata):
    """
    Identifiserer, ut fra "role"-blokken i json-stat2-strukturen:
    - tid_id: dimensjons-id-en for år
    - innhold_id: dimensjons-id-en for statistikkvariabel
    - indeks_kode: kategorikoden for selve indekstallet (ikke "endring i %")
    - type_id: den gjenværende dimensjonen (anleggstype)
    """
    role = metadata.get("role", {})
    tid_liste = role.get("time", [])
    innhold_liste = role.get("metric", [])

    if not tid_liste or not innhold_liste:
        raise ValueError(
            "Klarte ikke å tolke strukturen på SSB-tabell 08658 "
            "(fant ikke 'role.time' eller 'role.metric' i metadata)."
        )

    tid_id = tid_liste[0]
    innhold_id = innhold_liste[0]

    innhold_labels = metadata["dimension"][innhold_id]["category"]["label"]
    indeks_kode = None
    for kode, tekst in innhold_labels.items():
        if "indeks" in tekst.lower() and "endring" not in tekst.lower():
            indeks_kode = kode
            break
    if indeks_kode is None:
        indeks_kode = next(iter(innhold_labels))

    alle_dim_ider = metadata.get("id", list(metadata.get("dimension", {}).keys()))
    type_id = next((d for d in alle_dim_ider if d not in (tid_id, innhold_id)), None)

    return tid_id, innhold_id, indeks_kode, type_id


def _kategorier_i_rekkefolge(dimensjon):
    """Returnerer [(kode, tekst), ...] for en dimensjon, sortert på posisjon."""
    kategori = dimensjon["category"]
    index_map = kategori["index"]
    labels = kategori.get("label", {})
    koder = sorted(index_map, key=lambda k: index_map[k])
    return [(kode, labels.get(kode, kode)) for kode in koder]


@st.cache_data(ttl=3600)
def hent_anleggstyper():
    """
    Returnerer liste av (kode, tekst) for anleggstype-dimensjonen,
    samt hvilken kode som virker å være "totalen" (brukes som forvalg).
    """
    metadata = hent_metadata()
    _, _, _, type_id = _finn_variabler(metadata)

    if type_id is None:
        return [], None

    par = _kategorier_i_rekkefolge(metadata["dimension"][type_id])
    forvalg = next((kode for kode, tekst in par if "i alt" in tekst.lower()), par[0][0])
    return par, forvalg


@st.cache_data(ttl=3600)
def hent_indeks(anleggstype_kode):
    """
    Henter indeksserien (år -> indeksverdi) for valgt anleggstype,
    live fra SSBs API.
    """
    metadata = hent_metadata()
    tid_id, innhold_id, indeks_kode, type_id = _finn_variabler(metadata)

    params = {
        "lang": "no",
        "outputFormat": "json-stat2",
        f"valueCodes[{tid_id}]": "*",
        f"valueCodes[{innhold_id}]": indeks_kode,
    }
    if type_id is not None:
        params[f"valueCodes[{type_id}]"] = anleggstype_kode

    resp = requests.get(f"{BASE_URL}/data", params=params, timeout=15)
    resp.raise_for_status()
    dataset = resp.json()

    koder_i_rekkefolge = [kode for kode, _ in _kategorier_i_rekkefolge(dataset["dimension"][tid_id])]
    verdier = dataset["value"]

    indeks = {}
    for i, arskode in enumerate(koder_i_rekkefolge):
        v = verdier[i]
        if v is not None:
            indeks[int(arskode)] = v
    return indeks


def tom_cache():
    """Tømmer cachen slik at neste kall henter ferske tall fra SSB."""
    hent_metadata.clear()
    hent_anleggstyper.clear()
    hent_indeks.clear()


def juster_pris(pris, fra_ar, til_ar, indeks):
    """
    Justerer en pris fra ett år til et annet med indeksen.
    Returnerer None hvis et av årene mangler i indeksen.
    """
    if fra_ar not in indeks or til_ar not in indeks:
        return None
    return pris * (indeks[til_ar] / indeks[fra_ar])
