import streamlit as st
import os
import json
import re
import google.generativeai as genai

st.title("Transkript Assistent")

# ---------------------------------------------------------
# 1. Setup
# ---------------------------------------------------------
api_key = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=api_key)

ORDNER = "transkripte"
INDEX_PATH = "index.json"
MODELL_NAME = "models/gemini-3.1-flash-lite"  # deutlich hoeheres Freemium-Kontingent (500 RPD statt 20 RPD)


# ---------------------------------------------------------
# 2. Index laden (fuer die Link-Zuordnung unten, NICHT fuer den Modell-Kontext)
# ---------------------------------------------------------
@st.cache_data
def load_index():
    if not os.path.exists(INDEX_PATH):
        st.error(f"Fehler: '{INDEX_PATH}' wurde nicht gefunden.")
        return []
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def index_uebersicht(index):
    """Kompakte Textdarstellung des Index fuer den Router-Prompt.
    Bewusst nur die kurze ID statt des vollen Dateinamens, damit das Modell
    keinen komplizierten String (Leerzeichen/Umlaute/Endungen) reproduzieren muss."""
    zeilen = []
    for e in index:
        themen = ", ".join(e.get("themen", []))
        zeilen.append(f"- ID: {e['id']} | Titel: {e['titel']} | Themen: {themen}")
    return "\n".join(zeilen)


# ---------------------------------------------------------
# 3. ALLE Transkripte EINMAL laden -> landen im system_instruction
#    -> genau wie im Original, damit Google das grosse, stabile
#       Textstueck cachen kann (implizites Caching bei Gemini 2.5+).
#       Das ist der eigentliche Geschwindigkeits-Hebel.
# ---------------------------------------------------------
@st.cache_data
def load_all_transcripts(index):
    text = ""
    gesamt_zeichen = 0
    fehlende_dateien = []
    for e in index:
        pfad = os.path.join(ORDNER, e["datei"])
        if not os.path.exists(pfad):
            fehlende_dateien.append(e["datei"])
            continue
        with open(pfad, "r", encoding="utf-8") as f:
            inhalt = f.read()
        text += f"\n--- Datei: {e['datei']} (ID: {e['id']}) ---\n"
        text += inhalt
        gesamt_zeichen += len(inhalt)
    return text, gesamt_zeichen, fehlende_dateien


index = load_index()
transcripts_text, gesamt_zeichen, fehlende_dateien = load_all_transcripts(index)

st.info(
    f"System-Diagnose: {len(index)} Videos im Index, "
    f"insgesamt {gesamt_zeichen} Zeichen in den Transkripten geladen."
)
if fehlende_dateien:
    st.warning(f"Achtung, nicht gefunden: {', '.join(fehlende_dateien)}")


# ---------------------------------------------------------
# 4. Modell mit dem GESAMTEN Transkript-Text als system_instruction
#    -> genau wie im Original-Code
# ---------------------------------------------------------
system_prompt = (
    "Du bist ein hilfsbereiter Assistent für eine Website. "
    "Beantworte die Fragen der Nutzer AUSSCHLIESSLICH basierend auf den folgenden Transkripten. "
    "Wenn die Antwort in den Texten nicht zu finden ist, antworte "
    "höflich, dass dir dazu keine Informationen vorliegen.\n\n"
    "Nutze wo sinnvoll knappe Stichpunkte statt langer Fließtext-Absätze, gruppiert unter "
    "kurzen Zwischenüberschriften je Thema.\n\n"
    "Jede Transkript-Datei unten hat eine ID (z. B. V05). Kennzeichne am Ende jedes "
    "Themenblocks kurz, aus welcher/welchen ID(s) die Informationen stammen, im Format "
    "[V05] bzw. bei mehreren Quellen [V05][V11] (eckige Klammern, keine runden Klammern, "
    "keine Kommas). Wiederhole am Ende der Antwort NICHT nochmal alle IDs/Marker in einer "
    "zusammenfassenden Liste - die Marker gehören ausschliesslich an das Ende des jeweiligen "
    "Themenblocks, sonst nirgends.\n\n"
    f"HIER SIND DIE TRANSKRIPTE:\n{transcripts_text}"
)

model = genai.GenerativeModel(
    model_name=MODELL_NAME,
    system_instruction=system_prompt,
)


# ---------------------------------------------------------
# 5. Schritt A: Welche Video(s) passen zur Frage?
#    -> NUR fuer die Link-Anzeige unten, beeinflusst NICHT die Hauptantwort.
#    -> eigener, gedaechtnisloser Aufruf; profitiert vom gecachten system_instruction.
# ---------------------------------------------------------
def finde_relevante_dateien(frage, index):
    routing_prompt = f"""Hier ist eine Liste von Videos mit ID, Titel und Themen:

{index_uebersicht(index)}

Frage des Nutzers: "{frage}"

Antworte AUSSCHLIESSLICH mit den passenden IDs (z. B. V03), kommagetrennt.
Kein Fliesstext, keine Erklaerung, keine Dateinamen.
Wenn keine ID passt, schreibe genau: KEINE
"""
    response = model.generate_content(routing_prompt)
    text = response.text.strip()

    if text.upper() == "KEINE":
        return []

    kandidaten = [d.strip().upper() for d in text.split(",")]
    index_by_id = {e["id"]: e for e in index}
    # Nur IDs akzeptieren, die WIRKLICH im Index existieren
    # -> verhindert, dass eine "erfundene" ID durchrutscht
    gefundene_eintraege = [index_by_id[k] for k in kandidaten if k in index_by_id]
    return [e["datei"] for e in gefundene_eintraege]


def ersetze_quellenmarker(text, index):
    index_by_id = {e["id"]: e for e in index}

    def ein_marker(vid):
        eintrag = index_by_id.get(vid.upper())
        if not eintrag:
            return ""  # unbekannte/erfundene ID -> einfach entfernen
        return f" [🎥 {eintrag['titel']}]({eintrag['link']})"

    # Fall 1: unser gewuenschtes Format, mehrere Marker direkt hintereinander: [V05][V11]
    def ersetze_eckige_klammern(match):
        ids = re.findall(r"V\d{2}", match.group(0))
        return "".join(ein_marker(v) for v in ids)

    text = re.sub(r"(?:\[V\d{2}\])+", ersetze_eckige_klammern, text)

    # Fall 2: falls das Modell doch mal in sein altes Format zurueckfaellt: (V05, V11)
    def ersetze_runde_klammern(match):
        ids = re.findall(r"V\d{2}", match.group(0))
        return "".join(ein_marker(v) for v in ids)

    text = re.sub(r"\((?:\s*V\d{2}\s*,?)+\)", ersetze_runde_klammern, text)

    return text


# ---------------------------------------------------------
# 6. Video-Links deterministisch aus dem Index bauen
#    -> das Modell hat damit NICHTS zu tun, also keine Halluzinationsgefahr
# ---------------------------------------------------------
def baue_video_links(dateien, index):
    eintraege = [e for e in index if e["datei"] in dateien]
    if not eintraege:
        return ""
    links = [f"🎥 [{e['titel']}]({e['link']})" for e in eintraege]
    return "\n\n**Passendes Video:**\n" + "\n".join(links)


# ---------------------------------------------------------
# 7. Chat-Session im Hintergrund am Leben halten (Gedaechtnis!)
#    -> genau wie im Original: start_chat + history in session_state
#
#    ERWEITERT (siehe PROJEKT_STAND.md fuer den Hintergrund):
#    Google's stream=True-Antworten sind "lazy" - erst wenn die Chunk-
#    Iteration KOMPLETT durchlaufen ist, ist die Antwort intern fertig
#    aufgeloest. Wenn Streamlit einen laufenden Skriptdurchlauf mitten in
#    dieser Iteration abbricht (z. B. weil der Nutzer schon die naechste
#    Frage abschickt, waehrend die vorherige noch streamt), bleibt die
#    kaputte Antwort in chat_session.history stehen. JEDE folgende
#    send_message()-Anfrage crasht dann mit IncompleteIterationError, weil
#    sie beim Aufbau der Anfrage die History liest.
#
#    Ebene 1 (Eingabesperre): Eingabefeld wird gesperrt, waehrend eine
#    Antwort verarbeitet wird - verhindert den Abbruch von vornherein.
#    WICHTIG: disabled=... an st.chat_input wird erst im naechsten
#    Durchlauf sichtbar, nicht im selben, in dem man die Anfrage startet -
#    deshalb der Zwischenschritt ueber "pending_prompt" + rerun().
#
#    Ebene 2 (Fehlerbehandlung): Falls es trotzdem zu einem Fehler kommt
#    (dieser oder ein anderer), faengt try/except ihn ab, zeigt eine
#    freundliche Meldung statt Traceback und setzt die chat_session neu
#    auf - das kostet dem Modell den bisherigen Gespraechskontext, haelt
#    die App aber stabil statt komplett abzustuerzen.
# ---------------------------------------------------------
if "chat_session" not in st.session_state:
    st.session_state.chat_session = model.start_chat(history=[])

if "messages" not in st.session_state:
    st.session_state.messages = []

if "is_streaming" not in st.session_state:
    st.session_state.is_streaming = False

if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt = None

with st.sidebar:
    st.caption(
        "Falls die App mal haengen bleibt (Eingabefeld dauerhaft "
        "gesperrt, z. B. nach einem Browser-Refresh mitten in einer "
        "Antwort), hilft ein Klick hier:"
    )
    if st.button("Sitzung zurücksetzen"):
        st.session_state.chat_session = model.start_chat(history=[])
        st.session_state.messages = []
        st.session_state.is_streaming = False
        st.session_state.pending_prompt = None
        st.rerun()

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

neue_eingabe = st.chat_input(
    "Stell mir eine Frage zu den Transkripten...",
    disabled=st.session_state.is_streaming,
)

# Schritt 1: neue Eingabe kommt an, und wir sind noch nicht beschaeftigt
# -> Prompt merken, Feld sperren, rerun. Erst danach (im naechsten
# Durchlauf) starten wir die eigentliche, langsamere Modellanfrage - so
# sieht der Nutzer das gesperrte Feld auch tatsaechlich waehrenddessen.
if neue_eingabe and not st.session_state.is_streaming:
    st.session_state.pending_prompt = neue_eingabe
    st.session_state.is_streaming = True
    st.rerun()

# Schritt 2: es liegt eine zu verarbeitende Frage vor -> jetzt an das
# Modell schicken, mit Fehlerbehandlung (Ebene 2).
if st.session_state.is_streaming and st.session_state.pending_prompt:
    prompt = st.session_state.pending_prompt

    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        platzhalter = st.empty()

        try:
            # Hauptantwort: die Frage geht 1:1 durch, das Modell sieht die
            # Transkripte bereits ueber system_instruction und setzt selbst
            # Zitier-Marker.
            response = st.session_state.chat_session.send_message(prompt, stream=True)

            def stream_text():
                for chunk in response:
                    yield chunk.text

            with platzhalter.container():
                antwort_roh = st.write_stream(stream_text())

            antwort_final = ersetze_quellenmarker(antwort_roh, index)

            # Fallback: falls das Modell mal gar keinen Marker gesetzt hat,
            # ermitteln wir sicherheitshalber trotzdem die passenden Videos
            # ueber den Router und haengen sie unten an - damit nie ganz
            # ohne Quellenangabe geantwortet wird.
            if antwort_final == antwort_roh:
                gefundene_dateien = finde_relevante_dateien(prompt, index)
                antwort_final += baue_video_links(gefundene_dateien, index)

            platzhalter.markdown(antwort_final)
            full_response = antwort_final

        except Exception:
            # Bekannter Fall: die chat_session ist in einem kaputten
            # Zustand (z. B. IncompleteIterationError nach einer
            # abgebrochenen vorherigen Antwort). Session neu aufsetzen,
            # damit die naechste Frage wieder funktioniert, statt dass die
            # App bei JEDER weiteren Anfrage abstuerzt.
            st.session_state.chat_session = model.start_chat(history=[])
            full_response = (
                "⚠️ Die letzte Antwort wurde unterbrochen, daher musste "
                "die Sitzung neu gestartet werden. Bitte stelle deine "
                "Frage einfach nochmal - der bisherige Gesprächsverlauf "
                "ist dem Modell dabei leider nicht mehr bekannt."
            )
            platzhalter.markdown(full_response)

    st.session_state.messages.append({"role": "assistant", "content": full_response})
    st.session_state.is_streaming = False
    st.session_state.pending_prompt = None
