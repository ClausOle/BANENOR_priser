import io
import os
import sqlite3
from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

import ssb_index

# Absolutt sti: databasen ligger alltid ved siden av denne filen,
# uansett hvilken mappe du står i når du kjører "streamlit run" fra.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prices.db")

# Kolonner i limt Excel-data: år og prosjekt id skrives inn manuelt én gang
# (se "Legg til data"-fanen) og gjelder for alle limte rader, så de er IKKE
# med i selve den limte teksten.
EXPECTED_COLUMNS = ["kostkode", "kostkode_tekst", "enhet", "enh_pris"]


def get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_conn()
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
    conn.commit()
    conn.close()


init_db()

st.set_page_config(page_title="Price Tracker", layout="wide")
st.title("Price Tracker")

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
            conn = get_conn()
            try:
                conn.execute(
                    """
                    INSERT INTO prices (kostkode, kostkode_tekst, enhet, enh_pris, aar, prosjekt_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (kostkode.strip(), kostkode_tekst.strip(), enhet.strip(), enh_pris, int(aar), prosjekt_id.strip()),
                )
                conn.commit()
                st.success(f"La til {kostkode} (prosjekt {prosjekt_id}, {int(aar)}).")
            except sqlite3.IntegrityError:
                st.error(
                    f"Denne kombinasjonen finnes allerede: kostkode '{kostkode}', "
                    f"prosjekt '{prosjekt_id}', år {int(aar)}. Ikke lagt til på nytt."
                )
            finally:
                conn.close()

    st.divider()

    # --- Paste rows copied from Excel ---
    st.subheader("Lim inn rader fra Excel")
    st.caption(
        "År og Prosjekt id gjelder for ALLE radene du limer inn under. "
        "Kolonnerekkefølge i selve den limte teksten: "
        "Kostkode, Kostkode tekst, Enhet, Enh.pris (ingen header-rad)."
    )

    col_year, col_project = st.columns(2)
    with col_year:
        paste_aar = st.number_input(
            "År (gjelder alle limte rader)",
            min_value=1990, max_value=2100, value=date.today().year, step=1,
            key="paste_aar",
        )
    with col_project:
        paste_prosjekt_id = st.text_input("Prosjekt id (gjelder alle limte rader)", key="paste_prosjekt_id")

    pasted_text = st.text_area("Limt inn data", height=140)
    paste_submitted = st.button("Legg til limte rader")

    if paste_submitted:
        if not pasted_text.strip():
            st.error("Ingenting limt inn.")
        elif not paste_prosjekt_id.strip():
            st.error("Prosjekt id må fylles ut før du legger til limte rader.")
        else:
            try:
                lines = [line for line in pasted_text.splitlines() if line.strip()]
                n_expected = len(EXPECTED_COLUMNS)
                bad_lines = [
                    (i + 1, line) for i, line in enumerate(lines)
                    if len(line.split("\t")) != n_expected
                ]
                if bad_lines:
                    examples = "; ".join(f"linje {n}: {len(l.split(chr(9)))} felt" for n, l in bad_lines[:3])
                    st.error(
                        f"Forventet nøyaktig {n_expected} kolonner "
                        f"(Kostkode, Kostkode tekst, Enhet, Enh.pris) per rad. "
                        f"Fant rader med annet antall felt ({examples})."
                    )
                    st.stop()

                pasted_df = pd.read_csv(
                    io.StringIO(pasted_text),
                    sep="\t",
                    header=None,
                    names=EXPECTED_COLUMNS,
                    index_col=False,
                    skip_blank_lines=True,
                )

                for col in ["kostkode", "kostkode_tekst", "enhet"]:
                    pasted_df[col] = pasted_df[col].astype(str).str.strip()

                pasted_df["enh_pris"] = pd.to_numeric(
                    pasted_df["enh_pris"].astype(str).str.replace(",", ".").str.strip(),
                    errors="coerce",
                )

                # Aar og prosjekt_id kommer fra feltene over, samme for alle rader
                pasted_df["aar"] = int(paste_aar)
                pasted_df["prosjekt_id"] = paste_prosjekt_id.strip()

                before_count = len(pasted_df)
                pasted_df = pasted_df.replace("", pd.NA)
                pasted_df = pasted_df.dropna(subset=["kostkode", "enh_pris"], how="any")
                skipped_invalid = before_count - len(pasted_df)

                if pasted_df.empty:
                    st.error("Ingen gyldige rader funnet etter fjerning av tomme/ugyldige rader.")
                    st.stop()

                pasted_df["aar"] = pasted_df["aar"].astype(int)

                conn = get_conn()
                cur = conn.cursor()
                inserted = 0
                duplicates = 0
                for row in pasted_df.itertuples(index=False):
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO prices
                        (kostkode, kostkode_tekst, enhet, enh_pris, aar, prosjekt_id)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (row.kostkode, row.kostkode_tekst, row.enhet, row.enh_pris, row.aar, row.prosjekt_id),
                    )
                    if cur.rowcount:
                        inserted += 1
                    else:
                        duplicates += 1
                conn.commit()
                conn.close()

                msg = f"La til {inserted} rader."
                if duplicates:
                    msg += f" Hoppet over {duplicates} duplikat(er) (kostkode+prosjekt+år finnes allerede)."
                if skipped_invalid:
                    msg += f" Hoppet over {skipped_invalid} rad(er) med ugyldige/tomme felt."
                st.success(msg)
            except Exception as e:
                st.error(f"Klarte ikke å tolke innlimt tekst: {e}")

# ============================================================
# TAB: Alle oppføringer
# ============================================================
with tab_data:
    st.subheader("Alle oppføringer")

    conn = get_conn()
    df_all = pd.read_sql_query(
        """
        SELECT id, kostkode, kostkode_tekst, enhet, enh_pris, aar, prosjekt_id
        FROM prices
        ORDER BY kostkode, aar DESC
        """,
        conn,
    )
    conn.close()

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
                conn = get_conn()
                conn.executemany("DELETE FROM prices WHERE id = ?", [(i,) for i in valgte_ider])
                conn.commit()
                conn.close()
                st.success(f"Slettet {len(valgte_ider)} rad(er).")
                st.rerun()

# ============================================================
# TAB: Analyse
# ============================================================
with tab_analysis:
    st.subheader("Prisutvikling per kostkode")

    conn = get_conn()
    kostkoder = pd.read_sql_query(
        "SELECT DISTINCT kostkode FROM prices ORDER BY kostkode", conn
    )["kostkode"].tolist()

    if not kostkoder:
        st.info("Ingen data registrert ennå.")
    else:
        selected_kode = st.selectbox("Velg kostkode", kostkoder)

        df_kode = pd.read_sql_query(
            """
            SELECT kostkode_tekst, enhet, enh_pris, aar, prosjekt_id
            FROM prices
            WHERE kostkode = ?
            ORDER BY aar
            """,
            conn,
            params=(selected_kode,),
        )
        conn.close()

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
