import hmac
from datetime import date

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import ai_agent
import excel_import
import ssb_index
import turso_db as db

st.set_page_config(page_title="Price Tracker", layout="wide")


def sjekk_passord():
    """
    Enkel felles passordsperre foran hele appen (ikke individuelle
    brukerkontoer — passer for en liten intern gruppe). Passordet leses
    fra st.secrets, aldri hardkodet. Returnerer True først når riktig
    passord er skrevet inn, og husker det for resten av økten.
    """
    if st.session_state.get("autentisert", False):
        return True

    st.title("Price Tracker")
    passord = st.text_input("Passord", type="password")
    if st.button("Logg inn"):
        # compare_digest i stedet for == : sammenligningen tar like lang tid
        # uansett hvor mye av passordet som stemmer.
        if hmac.compare_digest(passord, st.secrets["app"]["passord"]):
            st.session_state["autentisert"] = True
            st.rerun()
        else:
            st.error("Feil passord.")
    return False


if not sjekk_passord():
    st.stop()

# Skjema/migrering sjekkes én gang per økt, ikke ved hver rerun
# (hver rerun ville ellers kostet en nettverksrunde mot Turso).
if not st.session_state.get("db_klar", False):
    db.init_db()
    st.session_state["db_klar"] = True

st.title("Price Tracker")

with st.sidebar:
    if st.button("Logg ut"):
        st.session_state["autentisert"] = False
        st.rerun()


def vis_importresultat(res, kostkode=None, prosjekt_id=None, aar=None):
    """Felles tilbakemelding for både enkeltoppføring og Excel-import."""
    if res.inserted:
        if kostkode is not None:
            st.success(f"La til {kostkode} (prosjekt {prosjekt_id}, {aar}).")
        else:
            st.success(f"La til {res.inserted} rader.")
    if res.duplicates:
        msg = f"{res.duplicates} rad(er) fantes allerede med samme pris og ble ikke lagt til på nytt."
        if res.mengde_oppdatert:
            msg += f" {res.mengde_oppdatert} av dem manglet mengde i databasen og fikk mengde fylt inn."
        st.info(msg)
    if res.conflicts:
        st.error(
            f"{len(res.conflicts)} rad(er) ble IKKE lagt til: kostkode+prosjekt+år finnes allerede "
            "i databasen, men med en ANNEN pris. Slett den gamle raden i 'Alle oppføringer' "
            "først hvis den nye prisen er riktig."
        )
        st.dataframe(pd.DataFrame(res.conflicts), width="stretch", hide_index=True)


tab_add, tab_data, tab_analysis, tab_ai = st.tabs(
    ["Legg til data", "Alle oppføringer", "Analyse", "AI-assistent"]
)

# ============================================================
# TAB: Legg til data
# ============================================================
with tab_add:
    st.subheader("Legg til en enkelt oppføring")

    with st.form("add_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            kostkode = st.text_input("Kostkode")
            kostkode_tekst = st.text_input("Kostkode tekst")
            enhet = st.text_input("Enhet")
            mengde = st.number_input(
                "Mengde (valgfritt)", min_value=0.0, step=1.0, value=None, placeholder="f.eks. 1200"
            )
        with col2:
            enh_pris = st.number_input("Enh.pris", min_value=0.0, step=0.01)
            aar = st.number_input("År", min_value=1990, max_value=2100, value=date.today().year, step=1)
            prosjekt_id = st.text_input("Prosjekt id")
        submitted = st.form_submit_button("Legg til")

    if submitted:
        if not kostkode.strip() or not prosjekt_id.strip():
            st.error("Kostkode og Prosjekt id må fylles ut.")
        else:
            res = db.insert_many_check_conflicts([{
                "kostkode": kostkode,
                "kostkode_tekst": kostkode_tekst.strip(),
                "enhet": enhet.strip(),
                "enh_pris": enh_pris,
                "mengde": mengde,
                "aar": int(aar),
                "prosjekt_id": prosjekt_id,
            }])
            vis_importresultat(res, kostkode.strip(), prosjekt_id.strip(), int(aar))

    st.divider()

    # --- Last opp Excel-fil ---
    st.subheader("Last opp Excel-fil")
    st.caption(
        "Appen leter gjennom ALLE faner i fila etter rader som har Kostkode, "
        "Kostkode tekst, Enhet og Enh.pris (uansett hvor i fila de ligger). "
        "Har fanen også en Mengde-kolonne, tas den med. Faner uten denne "
        "strukturen hoppes automatisk over, og rader uten Kostkode eller uten "
        "en tallverdi i Enh.pris droppes."
    )

    col_year, col_project = st.columns(2)
    with col_year:
        excel_aar = st.number_input(
            "År (gjelder alle rader fra fila)",
            min_value=1990, max_value=2100, value=date.today().year, step=1,
            key="excel_aar",
        )
    with col_project:
        excel_prosjekt_id = st.text_input("Prosjekt id (gjelder alle rader fra fila)", key="excel_prosjekt_id")

    opplastet_fil = st.file_uploader("Excel-fil (.xlsx)", type=["xlsx"], key="excel_uploader")

    if opplastet_fil is not None:
        if not excel_prosjekt_id.strip():
            st.error("Prosjekt id må fylles ut før fila kan leses.")
        else:
            try:
                rader_df, fane_rapport = excel_import.les_excel(
                    opplastet_fil, excel_aar, excel_prosjekt_id
                )
            except Exception as e:
                st.error(f"Klarte ikke å lese Excel-fila: {e}")
                rader_df, fane_rapport = None, None

            if fane_rapport is not None:
                with st.expander(f"Faner i fila ({len(fane_rapport)}) — hva ble gjenkjent"):
                    rapport_df = pd.DataFrame(fane_rapport, columns=["Fane", "Status", "Antall rader"])
                    st.dataframe(rapport_df, width="stretch", hide_index=True)

            if rader_df is not None and not rader_df.empty:
                n_med_mengde = int(rader_df["mengde"].notna().sum())
                st.success(
                    f"Fant {len(rader_df)} gyldige rader på tvers av fila "
                    f"({n_med_mengde} med mengde). Sjekk gjennom før du importerer:"
                )
                st.dataframe(
                    rader_df[["fane", "kostkode", "kostkode_tekst", "enhet", "enh_pris", "mengde"]],
                    width="stretch",
                    hide_index=True,
                )

                if st.button("✅ Importer disse radene til databasen", type="primary"):
                    res = db.insert_many_check_conflicts(rader_df.to_dict("records"))
                    vis_importresultat(res)
                    if res.conflicts:
                        st.caption(
                            "Konflikter ved Excel-import skyldes ofte at flere faner i fila "
                            "(f.eks. ulike varianter) dekker samme kostkode med ulik pris."
                        )
            elif rader_df is not None:
                st.warning("Fant ingen gyldige rader (med både Kostkode og Enh.pris) i noen av fanene.")

# Én spørring per rerun; både "Alle oppføringer" og "Analyse" bruker denne.
# Hentes ETTER "Legg til data", så rader som nettopp ble lagt til vises med en gang.
df_all = db.query_df(
    """
    SELECT id, kostkode, kostkode_tekst, enhet, enh_pris, mengde, aar, prosjekt_id
    FROM prices
    ORDER BY kostkode, aar DESC
    """
)
# NULL-kolonner kommer tilbake som object-dtype; tving tallkolonner til float
# så plotly/pandas ikke snubler når f.eks. alle mengder mangler.
for _kol in ("enh_pris", "mengde"):
    df_all[_kol] = pd.to_numeric(df_all[_kol], errors="coerce")

# ============================================================
# TAB: Alle oppføringer
# ============================================================
with tab_data:
    st.subheader("Alle oppføringer")

    if df_all.empty:
        st.info("Ingen data registrert ennå.")
    else:
        st.caption("Velg en eller flere rader (klikk i venstre marg) for å slette dem.")
        seleksjon = st.dataframe(
            df_all,
            width="stretch",
            hide_index=True,
            on_select="rerun",
            selection_mode="multi-row",
            key="alle_oppforinger_tabell",
        )
        st.caption(f"{len(df_all)} oppføringer totalt")

        valgte_rader = seleksjon.selection.rows if seleksjon and seleksjon.selection else []

        if valgte_rader:
            valgte_ider = df_all.iloc[valgte_rader]["id"].tolist()
            st.warning(f"{len(valgte_ider)} rad(er) valgt for sletting (id: {', '.join(map(str, valgte_ider))}).")
            if st.button("🗑️ Slett valgte rader", type="primary"):
                antall_slettet = db.delete_by_ids(valgte_ider)
                st.success(f"Slettet {antall_slettet} rad(er).")
                st.rerun()

# ============================================================
# TAB: Analyse
# ============================================================
with tab_analysis:
    st.subheader("Analyse per kostkode")

    if df_all.empty:
        st.info("Ingen data registrert ennå.")
    else:
        kostkoder = sorted(df_all["kostkode"].unique().tolist())
        selected_kode = st.selectbox("Velg kostkode", kostkoder)

        df_kode = (
            df_all[df_all["kostkode"] == selected_kode]
            .sort_values("aar")
            .reset_index(drop=True)
            .copy()
        )
        df_kode["aar"] = df_kode["aar"].astype(int)
        df_kode["aar_tekst"] = df_kode["aar"].astype(str)

        tekster = df_kode["kostkode_tekst"].dropna()
        tekster = tekster[tekster.str.strip() != ""]
        beskrivelse = tekster.iloc[0] if not tekster.empty else ""
        st.caption(
            f"{selected_kode} {beskrivelse} — {len(df_kode)} oppføringer fra "
            f"{df_kode['prosjekt_id'].nunique()} prosjekt(er), "
            f"{df_kode['aar'].min()}–{df_kode['aar'].max()}"
        )

        # Kun rader med registrert, positiv mengde kan brukes til størrelse/vekting.
        med_mengde = df_kode[df_kode["mengde"].notna() & (df_kode["mengde"] > 0)]

        # ---------- Enh.pris mot mengde ----------
        st.markdown("#### Enh.pris mot mengde (mengde på x-aksen, boblestørrelse = mengde)")
        if med_mengde.empty:
            st.info(
                "Ingen oppføringer for denne kostkoden har registrert mengde ennå. "
                "Mengde legges inn i skjemaet over, eller via en Mengde-kolonne i Excel-fila."
            )
        else:
            fig_m = px.scatter(
                med_mengde,
                x="mengde",
                y="enh_pris",
                size="mengde",
                size_max=45,
                color="aar_tekst",
                hover_data={"prosjekt_id": True, "enhet": True, "aar_tekst": False, "aar": True},
                labels={"mengde": "Mengde", "enh_pris": "Enh.pris", "aar_tekst": "År"},
                title=f"Enh.pris mot mengde — {selected_kode}",
            )
            st.plotly_chart(fig_m, width="stretch")
            if len(med_mengde) < len(df_kode):
                st.caption(
                    f"{len(df_kode) - len(med_mengde)} oppføring(er) uten mengde vises ikke i denne figuren."
                )

        # ---------- Utvikling over tid ----------
        st.markdown("#### Prisutvikling per år")

        yearly = (
            df_kode.groupby("aar", as_index=False)
            .agg(enh_pris=("enh_pris", "mean"), antall_prosjekter=("prosjekt_id", "nunique"))
            .sort_values("aar")
        )
        # Mengdevektet snitt: prosjekter med store mengder teller mer. Beregnes
        # bare for år der minst én oppføring har mengde; ellers NaN.
        if not med_mengde.empty:
            vektet = (
                med_mengde.assign(pris_x_mengde=med_mengde["enh_pris"] * med_mengde["mengde"])
                .groupby("aar")
                .agg(pris_x_mengde=("pris_x_mengde", "sum"), sum_mengde=("mengde", "sum"))
            )
            vektet["vektet_snitt"] = vektet["pris_x_mengde"] / vektet["sum_mengde"]
            yearly = yearly.merge(vektet[["vektet_snitt"]], left_on="aar", right_index=True, how="left")
        else:
            yearly["vektet_snitt"] = np.nan

        # Enkeltobservasjoner som bobler (størrelse = mengde; uten mengde = liten
        # fast størrelse), med snittkurven(e) lagt oppå.
        minste = med_mengde["mengde"].min() if not med_mengde.empty else 1.0
        obs = df_kode.assign(storrelse=df_kode["mengde"].where(df_kode["mengde"] > 0, minste))
        fig_t = px.scatter(
            obs,
            x="aar",
            y="enh_pris",
            size="storrelse",
            size_max=30,
            color="prosjekt_id",
            hover_data={"storrelse": False, "mengde": True, "enhet": True},
            labels={"aar": "År", "enh_pris": "Enh.pris", "prosjekt_id": "Prosjekt"},
            title=f"Enh.pris per år — {selected_kode}",
        )
        fig_t.add_trace(go.Scatter(
            x=yearly["aar"], y=yearly["enh_pris"], mode="lines+markers",
            name="Snitt per år", line=dict(color="black", width=2),
        ))
        if yearly["vektet_snitt"].notna().any():
            fig_t.add_trace(go.Scatter(
                x=yearly["aar"], y=yearly["vektet_snitt"], mode="lines+markers",
                name="Mengdevektet snitt", line=dict(color="gray", width=2, dash="dash"),
            ))
        fig_t.update_xaxes(dtick=1)
        st.plotly_chart(fig_t, width="stretch")

        st.caption(
            "Boblestørrelse = mengde (oppføringer uten mengde vises som små bobler). "
            "Snitt per år er uvektet gjennomsnitt av alle oppføringer; mengdevektet snitt "
            "vekter hver oppføring med mengden, og beregnes bare der mengde er registrert."
        )
        st.dataframe(
            yearly.rename(columns={
                "aar": "År",
                "enh_pris": "Snitt enh.pris",
                "vektet_snitt": "Mengdevektet snitt",
                "antall_prosjekter": "Antall prosjekter",
            }),
            width="stretch",
            hide_index=True,
        )

        # ---------- Prisjustering ----------
        st.subheader("Prisjustering (SSB byggekostnadsindeks for veganlegg)")

        if st.button("🔄 Oppdater indeks fra SSB"):
            ssb_index.tom_cache()
            st.rerun()

        try:
            anleggstyper, forvalgt_type = ssb_index.hent_anleggstyper()
        except Exception as e:
            anleggstyper, forvalgt_type = [], None
            st.error(
                f"Klarte ikke å hente anleggstyper fra SSB sitt API: {e}. "
                "Sjekk internettforbindelsen, eller prøv igjen senere."
            )

        if anleggstyper:
            type_tekster = [tekst for _, tekst in anleggstyper]
            forvalgt_indeks = next(
                (i for i, (kode, _) in enumerate(anleggstyper) if kode == forvalgt_type), 0
            )
            valgt_tekst = st.selectbox(
                "Anleggstype (fra SSB tabell 08658)", type_tekster, index=forvalgt_indeks
            )
            valgt_type_kode = dict((tekst, kode) for kode, tekst in anleggstyper)[valgt_tekst]

            try:
                indeks = ssb_index.hent_indeks(valgt_type_kode)
            except Exception as e:
                indeks = {}
                st.error(
                    f"Klarte ikke å hente indekstall fra SSB sitt API: {e}. "
                    "Sjekk internettforbindelsen, eller prøv igjen senere."
                )

            if indeks:
                tilgjengelige_aar = sorted(indeks.keys())
                malar = st.selectbox(
                    "Reguler prisene til år",
                    tilgjengelige_aar,
                    index=len(tilgjengelige_aar) - 1,  # forvalg: nyeste år i indeksen
                )

                justert = yearly.copy()
                for kilde, mal in [("enh_pris", "Justert snitt"), ("vektet_snitt", "Justert vektet snitt")]:
                    justert[mal] = justert.apply(
                        lambda r: (
                            ssb_index.juster_pris(r[kilde], int(r["aar"]), int(malar), indeks)
                            if pd.notna(r[kilde]) else np.nan
                        ),
                        axis=1,
                    )

                manglende_aar = justert[justert["Justert snitt"].isna()]["aar"].tolist()
                if manglende_aar:
                    st.warning(
                        f"Indeksen mangler tall for følgende år, disse radene kunne ikke justeres: "
                        f"{', '.join(str(int(a)) for a in manglende_aar)}."
                    )

                st.dataframe(
                    justert[["aar", "enh_pris", "Justert snitt", "vektet_snitt", "Justert vektet snitt"]]
                    .rename(columns={
                        "aar": "År",
                        "enh_pris": "Snitt enh.pris (opprinnelig)",
                        "vektet_snitt": "Mengdevektet snitt (opprinnelig)",
                    }),
                    width="stretch",
                    hide_index=True,
                )

                gyldige = justert.dropna(subset=["Justert snitt"])
                if not gyldige.empty:
                    col_a, col_b = st.columns(2)
                    col_a.metric(
                        f"Snitt prisnivå justert til {int(malar)}",
                        f"{gyldige['Justert snitt'].mean():,.2f}",
                    )
                    gyldige_v = justert.dropna(subset=["Justert vektet snitt"])
                    if not gyldige_v.empty:
                        col_b.metric(
                            f"Mengdevektet prisnivå justert til {int(malar)}",
                            f"{gyldige_v['Justert vektet snitt'].mean():,.2f}",
                        )

                st.caption(
                    "Prisene justeres med SSBs byggekostnadsindeks for veganlegg "
                    f"(tabell 08658, anleggstype: {valgt_tekst}), hentet direkte fra SSBs API. "
                    "Justert pris = opprinnelig pris × (indeks for målår / indeks for registreringsår)."
                )

# ============================================================
# TAB: AI-assistent (plassholder)
# ============================================================
with tab_ai:
    st.subheader("AI-assistent")

    if not ai_agent.AGENT_AKTIV:
        st.info(
            "Assistenten er ikke koblet på ennå. Chatten under er ferdig bygd; "
            "modellen og verktøyene kobles på i `ai_agent.py` (se docstring der)."
        )

    if "chat_historikk" not in st.session_state:
        st.session_state["chat_historikk"] = []

    kol_forslag, kol_reset = st.columns([4, 1])
    with kol_forslag:
        st.caption("Eksempler på spørsmål:")
        forslag_kolonner = st.columns(len(ai_agent.FORSLAG))
        valgt_forslag = None
        for kol, tekst in zip(forslag_kolonner, ai_agent.FORSLAG):
            if kol.button(tekst, key=f"forslag_{tekst}"):
                valgt_forslag = tekst
    with kol_reset:
        if st.button("Nullstill samtale"):
            st.session_state["chat_historikk"] = []
            st.rerun()

    for melding in st.session_state["chat_historikk"]:
        with st.chat_message(melding["role"]):
            st.markdown(melding["content"])

    sporsmal = st.chat_input("Spør om prisene i databasen …") or valgt_forslag

    if sporsmal:
        with st.chat_message("user"):
            st.markdown(sporsmal)
        with st.chat_message("assistant"):
            with st.spinner("Tenker …"):
                svar = ai_agent.svar(sporsmal, st.session_state["chat_historikk"])
            st.markdown(svar)
        st.session_state["chat_historikk"].append({"role": "user", "content": sporsmal})
        st.session_state["chat_historikk"].append({"role": "assistant", "content": svar})
