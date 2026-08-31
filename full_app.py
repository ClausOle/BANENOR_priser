import io
from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

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
        if passord == st.secrets["app"]["passord"]:
            st.session_state["autentisert"] = True
            st.rerun()
        else:
            st.error("Feil passord.")
    return False


if not sjekk_passord():
    st.stop()

db.init_db()

st.title("Price Tracker")

with st.sidebar:
    if st.button("Logg ut"):
        st.session_state["autentisert"] = False
        st.rerun()

tab_add, tab_data, tab_analysis = st.tabs(["Legg til data", "Alle oppføringer", "Analyse"])

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
        with col2:
            enh_pris = st.number_input("Enh.pris", min_value=0.0, step=0.01)
            aar = st.number_input("År", min_value=1990, max_value=2100, value=date.today().year, step=1)
            prosjekt_id = st.text_input("Prosjekt id")
        submitted = st.form_submit_button("Legg til")

    if submitted:
        if not kostkode.strip() or not prosjekt_id.strip():
            st.error("Kostkode og Prosjekt id må fylles ut.")
        else:
            inserted, duplicates, conflicts = db.insert_many_check_conflicts([
                (kostkode.strip(), kostkode_tekst.strip(), enhet.strip(), enh_pris, int(aar), prosjekt_id.strip())
            ])
            if inserted:
                st.success(f"La til {kostkode} (prosjekt {prosjekt_id}, {int(aar)}).")
            elif duplicates:
                st.info(
                    f"Denne raden finnes allerede med samme pris: kostkode '{kostkode}', "
                    f"prosjekt '{prosjekt_id}', år {int(aar)}. Ikke lagt til på nytt."
                )
            elif conflicts:
                c = conflicts[0]
                st.error(
                    f"Kostkode '{kostkode}' finnes allerede for prosjekt '{prosjekt_id}', år {int(aar)} — "
                    f"men med en ANNEN pris ({c['eksisterende_pris']:,.2f} i databasen, du skrev inn "
                    f"{c['ny_pris']:,.2f}). Raden er IKKE lagt til. Slett den gamle raden i "
                    f"'Alle oppføringer' først hvis den nye prisen er riktig."
                )

    st.divider()

    # --- Last opp Excel-fil ---
    st.subheader("Last opp Excel-fil")
    st.caption(
        "Appen leter gjennom ALLE faner i fila etter rader som har Kostkode, "
        "Kostkode tekst, Enhet og Enh.pris (uansett hvor i fila de ligger). "
        "Faner uten denne strukturen hoppes automatisk over, og rader uten "
        "Kostkode eller uten en tallverdi i Enh.pris droppes."
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
                st.success(f"Fant {len(rader_df)} gyldige rader på tvers av fila. Sjekk gjennom før du importerer:")
                st.dataframe(
                    rader_df[["fane", "kostkode", "kostkode_tekst", "enhet", "enh_pris"]],
                    width="stretch",
                    hide_index=True,
                )

                if st.button("✅ Importer disse radene til databasen", type="primary"):
                    args_list = [
                        (row.kostkode, row.kostkode_tekst, row.enhet, row.enh_pris, row.aar, row.prosjekt_id)
                        for row in rader_df.itertuples(index=False)
                    ]
                    inserted, duplicates, conflicts = db.insert_many_check_conflicts(args_list)

                    msg = f"La til {inserted} rader."
                    if duplicates:
                        msg += f" Hoppet over {duplicates} ekte duplikat(er) (samme kostkode+prosjekt+år+pris finnes allerede)."
                    st.success(msg)

                    if conflicts:
                        st.warning(
                            f"⚠️ {len(conflicts)} rad(er) ble IKKE importert fordi kostkode+prosjekt+år "
                            "allerede finnes i databasen, men med en ANNEN pris. Sjekk disse manuelt — "
                            "trolig fordi flere faner i fila (f.eks. ulike varianter) dekker samme "
                            "kostkode med ulik pris:"
                        )
                        st.dataframe(pd.DataFrame(conflicts), width="stretch", hide_index=True)
            elif rader_df is not None:
                st.warning("Fant ingen gyldige rader (med både Kostkode og Enh.pris) i noen av fanene.")

# ============================================================
# TAB: Alle oppføringer
# ============================================================
with tab_data:
    st.subheader("Alle oppføringer")

    df_all = db.query_df(
        """
        SELECT id, kostkode, kostkode_tekst, enhet, enh_pris, aar, prosjekt_id
        FROM prices
        ORDER BY kostkode, aar DESC
        """
    )

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
    st.subheader("Prisutvikling per kostkode")

    kostkoder = db.query_df("SELECT DISTINCT kostkode FROM prices ORDER BY kostkode")["kostkode"].tolist()

    if not kostkoder:
        st.info("Ingen data registrert ennå.")
    else:
        selected_kode = st.selectbox("Velg kostkode", kostkoder)

        df_kode = db.query_df(
            """
            SELECT kostkode_tekst, enhet, enh_pris, aar, prosjekt_id
            FROM prices
            WHERE kostkode = ?
            ORDER BY aar
            """,
            (selected_kode,),
        )

        # Årlig gjennomsnitt på tvers av prosjekter
        yearly = (
            df_kode.groupby("aar", as_index=False)
            .agg(enh_pris=("enh_pris", "mean"), antall_prosjekter=("prosjekt_id", "nunique"))
            .sort_values("aar")
        )

        # Plot: én samlende kurve med gjennomsnittlig enh.pris per år
        fig = px.line(
            yearly,
            x="aar",
            y="enh_pris",
            markers=True,
            hover_data=["antall_prosjekter"],
            title=f"Snitt Enh.pris per år — {selected_kode}",
        )
        fig.update_xaxes(dtick=1)
        fig.update_yaxes(title="Snitt enh.pris")
        st.plotly_chart(fig, width="stretch")

        st.caption("Gjennomsnittlig Enh.pris per år (grunnlag for prisjustering)")
        st.dataframe(
            yearly.rename(columns={"enh_pris": "Snitt enh.pris", "antall_prosjekter": "Antall prosjekter"}),
            width="stretch",
        )

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
                justert["Justert pris"] = justert.apply(
                    lambda r: ssb_index.juster_pris(r["enh_pris"], int(r["aar"]), int(malar), indeks),
                    axis=1,
                )
                justert = justert.rename(columns={"enh_pris": "Snitt enh.pris (opprinnelig)"})

                manglende_aar = justert[justert["Justert pris"].isna()]["aar"].tolist()
                if manglende_aar:
                    st.warning(
                        f"Indeksen mangler tall for følgende år, disse radene kunne ikke justeres: "
                        f"{', '.join(str(int(a)) for a in manglende_aar)}."
                    )

                st.dataframe(
                    justert[["aar", "Snitt enh.pris (opprinnelig)", "Justert pris"]],
                    width="stretch",
                )

                gyldige = justert.dropna(subset=["Justert pris"])
                if not gyldige.empty:
                    snitt_justert = gyldige["Justert pris"].mean()
                    st.metric(
                        f"Gjennomsnittlig prisnivå justert til {int(malar)}",
                        f"{snitt_justert:,.2f}",
                    )

                st.caption(
                    "Prisene justeres med SSBs byggekostnadsindeks for veganlegg "
                    f"(tabell 08658, anleggstype: {valgt_tekst}), hentet direkte fra SSBs API. "
                    "Justert pris = opprinnelig pris × (indeks for målår / indeks for registreringsår)."
                )
