"""
Plassholder for AI-assistenten i Price Tracker.

Denne modulen er bevisst UTEN modellkall ennå. Den definerer grensesnittet
appen snakker med (svar() og FORSLAG), slik at chat-siden i full_app.py er
ferdig bygd og bare denne fila må endres når agenten skal kobles på.

Tenkt arkitektur når den kobles på:

  - Modell: Anthropic Messages API. Nøkkel i st.secrets["anthropic"]["api_key"],
    aldri i koden. Legg "anthropic" til i requirements.txt.
  - Verktøy agenten får (tool use):
      * sporr_priser(sql):  kjører KUN SELECT mot prices via turso_db.query_df.
                            Valider at setningen starter med SELECT og ikke
                            inneholder ';' før den sendes — agenten skal
                            aldri kunne skrive/slette.
      * hent_indeks(anleggstype_kode): ssb_index.hent_indeks
      * juster_pris(pris, fra_ar, til_ar, anleggstype_kode): ssb_index.juster_pris
  - Systemprompt: beskriv tabellen prices (kolonner, at unik nøkkel er
    kostkode+prosjekt_id+aar, at mengde kan mangle), enheter, og krev at
    svar oppgir hvilke rader/år/prosjekter tallet bygger på.
  - Samtalehistorikk holdes i st.session_state (se full_app.py) og sendes
    med i hvert kall; agenten husker ingenting selv.
  - Alt av skriving til databasen holdes utenfor agenten.
"""

# Sett til True (og implementer svar()) når agenten er koblet på.
AGENT_AKTIV = False

# Eksempler på spørsmål som vises som snarveier på chat-siden. Byttes ut med
# det som faktisk er nyttig for brukerne når agenten er i drift.
FORSLAG = [
    "Hvilke kostkoder har steget mest i pris de siste tre årene?",
    "Hva er snittprisen for kostkode 71.1 justert til 2026-nivå?",
    "Hvilke prosjekter har registrert priser for asfaltering?",
    "Er det kostkoder der prisen varierer mye mellom prosjekter samme år?",
]


def svar(sporsmal: str, historikk: list[dict]) -> str:
    """
    Tar brukerens spørsmål og samtalehistorikken (liste av
    {"role": "user"|"assistant", "content": str}, uten det nye spørsmålet)
    og returnerer assistentens svar som tekst.

    Plassholder: returnerer en fast melding. Når agenten kobles på, skal
    denne funksjonen bygge meldingslisten, kalle modellen med verktøyene
    beskrevet i modulens docstring, kjøre verktøykall i en løkke til
    modellen er ferdig, og returnere sluttsvaret.
    """
    return (
        "AI-assistenten er ikke koblet på ennå — dette er en plassholder.\n\n"
        f"Jeg mottok spørsmålet «{sporsmal.strip()}» "
        f"(samtalen har {len(historikk)} tidligere meldinger). "
        "Når agenten er i drift vil den kunne slå opp i prisdatabasen, "
        "hente SSB-indeksen og svare med tall og hvilke oppføringer de bygger på."
    )
