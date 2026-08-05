import streamlit as st
import os
import json
import google.generativeai as genai

st.title("Transkript Assistent")

# ---------------------------------------------------------
# 1. Setup
# ---------------------------------------------------------
api_key = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=api_key)

ORDNER = "transkripte"
INDEX_PATH = "index.json"
MODELL_NAME = "models/gemini-3.5-flash"  # dein Original-Modell


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
# ---------------------------------------------------------
if "chat_session" not in st.session_state:
    st.session_state.chat_session = model.start_chat(history=[])

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Stell mir eine Frage zu den Transkripten..."):

    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        # Hauptantwort: GENAU wie im Original, die Frage geht 1:1 durch,
        # das Modell sieht die Transkripte bereits ueber system_instruction.
        response = st.session_state.chat_session.send_message(prompt, stream=True)

        def stream_text():
            for chunk in response:
                yield chunk.text

        antwort_text = st.write_stream(stream_text())

        # Links unten: separat ermittelt, beeinflusst die Hauptantwort nicht.
        gefundene_dateien = finde_relevante_dateien(prompt, index)
        links = baue_video_links(gefundene_dateien, index)
        if links:
            st.markdown(links)

        full_response = antwort_text + links

    st.session_state.messages.append({"role": "assistant", "content": full_response})
