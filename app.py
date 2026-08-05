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
# 2. Index laden (klein, wird bei JEDER Frage fuers Routing mitgeschickt)
# ---------------------------------------------------------
@st.cache_data
def load_index():
    if not os.path.exists(INDEX_PATH):
        st.error(f"Fehler: '{INDEX_PATH}' wurde nicht gefunden.")
        return []
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def index_uebersicht(index):
    """Kompakte Textdarstellung des Index fuer den Router-Prompt (KEIN Volltext!).
    Bewusst nur die kurze ID statt des vollen Dateinamens, damit das Modell
    keinen komplizierten String (Leerzeichen/Umlaute/Endungen) reproduzieren muss."""
    zeilen = []
    for e in index:
        themen = ", ".join(e.get("themen", []))
        zeilen.append(f"- ID: {e['id']} | Titel: {e['titel']} | Themen: {themen}")
    return "\n".join(zeilen)


# ---------------------------------------------------------
# 3. Volltext einer einzelnen Transkript-Datei laden
#    (fuer die Antwort wird NUR die tatsaechlich passende Datei genutzt;
#     fuer die Diagnose-Zeile lesen wir zusaetzlich einmalig ALLE Dateien,
#     das kostet aber keine Modell-Tokens, nur einen lokalen Festplattenzugriff)
# ---------------------------------------------------------
@st.cache_data
def load_transcript(dateiname):
    pfad = os.path.join(ORDNER, dateiname)
    if not os.path.exists(pfad):
        return ""
    with open(pfad, "r", encoding="utf-8") as f:
        return f.read()


@st.cache_data
def berechne_diagnose(index):
    gesamt_zeichen = 0
    fehlende_dateien = []
    for e in index:
        text = load_transcript(e["datei"])
        if text:
            gesamt_zeichen += len(text)
        else:
            fehlende_dateien.append(e["datei"])
    return gesamt_zeichen, fehlende_dateien


index = load_index()

gesamt_zeichen, fehlende_dateien = berechne_diagnose(index)
st.info(
    f"System-Diagnose: {len(index)} Videos im Index, "
    f"insgesamt {gesamt_zeichen} Zeichen in den Transkripten geladen."
)
if fehlende_dateien:
    st.warning(f"Achtung, nicht gefunden: {', '.join(fehlende_dateien)}")

model = genai.GenerativeModel(MODELL_NAME)


# ---------------------------------------------------------
# 4. Schritt A: Welche Datei(en) passen zur Frage?
#    -> eigener, GEDAECHTNISLOSER Aufruf (bewusst ohne Chat-Historie),
#       damit das Routing nicht mit jeder neuen Frage langsamer/teurer wird.
#       Die eigentliche Antwort (Schritt B) hat das Gedaechtnis.
# ---------------------------------------------------------
def finde_relevante_dateien(frage, index):
    prompt = f"""Hier ist eine Liste von Videos mit ID, Titel und Themen:

{index_uebersicht(index)}

Frage des Nutzers: "{frage}"

Antworte AUSSCHLIESSLICH mit den passenden IDs (z. B. V03), kommagetrennt.
Kein Fliesstext, keine Erklaerung, keine Dateinamen.
Wenn keine ID passt, schreibe genau: KEINE
"""
    response = model.generate_content(prompt)
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
# 5. Video-Links deterministisch aus dem Index bauen
#    -> das Modell hat damit NICHTS zu tun, also keine Halluzinationsgefahr
# ---------------------------------------------------------
def baue_video_links(dateien, index):
    eintraege = [e for e in index if e["datei"] in dateien]
    if not eintraege:
        return ""
    links = [f"🎥 [{e['titel']}]({e['link']})" for e in eintraege]
    return "\n\n**Passendes Video:**\n" + "\n".join(links)


# ---------------------------------------------------------
# 6. Chat-Session im Hintergrund am Leben halten (Gedaechtnis!)
#    -> genau wie in deinem Original: start_chat + history in session_state
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
        gefundene_dateien = finde_relevante_dateien(prompt, index)

        if not gefundene_dateien:
            # Kein passendes Video -> trotzdem an die Chat-Session schicken,
            # damit der Gespraechsverlauf konsistent bleibt (z. B. Folgefragen).
            hinweis_prompt = (
                f"Der Nutzer fragt: \"{prompt}\"\n\n"
                "Zu dieser Frage liegt kein passendes Transkript vor. "
                "Antworte kurz und ehrlich, dass dir dazu keine Informationen vorliegen."
            )
            response = st.session_state.chat_session.send_message(hinweis_prompt, stream=True)

            def stream_text():
                for chunk in response:
                    yield chunk.text

            full_response = st.write_stream(stream_text())
        else:
            volltext = ""
            for datei in gefundene_dateien:
                volltext += f"\n--- {datei} ---\n"
                volltext += load_transcript(datei)

            erweiterter_prompt = f"""Beantworte die folgende Frage AUSSCHLIESSLICH basierend auf dem
Transkript-Ausschnitt unten. Wenn die Antwort darin nicht zu finden ist, sag ehrlich,
dass dir dazu keine Informationen vorliegen. Gib KEINE Links oder Dateinamen in deiner
Antwort an - das erledigt die Anwendung automatisch.

TRANSKRIPT:
{volltext}

FRAGE: {prompt}
"""
            response = st.session_state.chat_session.send_message(erweiterter_prompt, stream=True)

            def stream_text():
                for chunk in response:
                    yield chunk.text

            antwort_text = st.write_stream(stream_text())
            links = baue_video_links(gefundene_dateien, index)
            if links:
                st.markdown(links)
            full_response = antwort_text + links

    st.session_state.messages.append({"role": "assistant", "content": full_response})
