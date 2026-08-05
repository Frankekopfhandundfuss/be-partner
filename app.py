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


def generiere_schnell(aufruf_funktion, prompt, stream=False, thinking_level="low"):
    """Versucht, mit reduziertem Thinking-Level zu generieren (schneller).
    aufruf_funktion ist z. B. model.generate_content oder chat_session.send_message.
    Faellt automatisch auf den normalen Aufruf zurueck, falls der Parameter
    fuer dieses Modell/diese SDK-Version nicht unterstuetzt wird."""
    try:
        return aufruf_funktion(
            prompt,
            stream=stream,
            generation_config={"thinking_config": {"thinking_level": thinking_level}},
        )
    except Exception:
        return aufruf_funktion(prompt, stream=stream)


# ---------------------------------------------------------
# 4. Schritt A: Welche Datei(en) passen zur Frage?
#    -> eigener, GEDAECHTNISLOSER Aufruf (bewusst ohne Chat-Historie),
#       damit das Routing nicht mit jeder neuen Frage langsamer/teurer wird.
#       Die eigentliche Antwort (Schritt B) hat das Gedaechtnis.
#    -> Rueckgabe sind jetzt die vollen Index-Eintraege (nicht nur Dateinamen),
#       weil wir gleich sowohl ID als auch Dateiname/Link brauchen.
# ---------------------------------------------------------
def finde_relevante_eintraege(frage, index):
    prompt = f"""Hier ist eine Liste von Videos mit ID, Titel und Themen:

{index_uebersicht(index)}

Frage des Nutzers: "{frage}"

Antworte AUSSCHLIESSLICH mit den passenden IDs (z. B. V03), kommagetrennt.
Kein Fliesstext, keine Erklaerung, keine Dateinamen.
Wenn keine ID passt, schreibe genau: KEINE
"""
    response = generiere_schnell(model.generate_content, prompt, thinking_level="low")
    text = response.text.strip()

    if text.upper() == "KEINE":
        return []

    kandidaten = [d.strip().upper() for d in text.split(",")]
    index_by_id = {e["id"]: e for e in index}
    # Nur IDs akzeptieren, die WIRKLICH im Index existieren
    # -> verhindert, dass eine "erfundene" ID durchrutscht
    return [index_by_id[k] for k in kandidaten if k in index_by_id]


# ---------------------------------------------------------
# 5. Quellen-Marker im Antworttext durch echte Links ersetzen
#    -> das Modell schreibt nur [V07] an die richtige Stelle im Fliesstext,
#       der Code loest das erst danach in einen echten Link auf.
#       Unbekannte/erfundene IDs werden stillschweigend entfernt statt
#       einen falschen Link zu zeigen.
# ---------------------------------------------------------
def ersetze_quellenmarker(text, eintraege):
    index_by_id = {e["id"]: e for e in eintraege}

    def ersetzung(match):
        vid = match.group(1).upper()
        eintrag = index_by_id.get(vid)
        if not eintrag:
            return ""  # unbekannte/erfundene ID -> einfach entfernen
        return f" [🎥 {eintrag['titel']}]({eintrag['link']})"

    return re.sub(r"\[(V\d{2})\]", ersetzung, text)


def baue_video_links(eintraege):
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
        gefundene_eintraege = finde_relevante_eintraege(prompt, index)

        if not gefundene_eintraege:
            # Kein passendes Video -> trotzdem an die Chat-Session schicken,
            # damit der Gespraechsverlauf konsistent bleibt (z. B. Folgefragen).
            hinweis_prompt = (
                f"Der Nutzer fragt: \"{prompt}\"\n\n"
                "Zu dieser Frage liegt kein passendes Transkript vor. "
                "Antworte kurz und ehrlich, dass dir dazu keine Informationen vorliegen."
            )
            response = generiere_schnell(
                st.session_state.chat_session.send_message, hinweis_prompt, stream=True, thinking_level="low"
            )

            def stream_text():
                for chunk in response:
                    yield chunk.text

            full_response = st.write_stream(stream_text())
        else:
            volltext = ""
            for e in gefundene_eintraege:
                volltext += f"\n--- Quelle {e['id']} (Thema: {e['titel']}) ---\n"
                volltext += load_transcript(e["datei"])

            gueltige_ids = ", ".join(e["id"] for e in gefundene_eintraege)
            erweiterter_prompt = f"""Beantworte die folgende Frage AUSSCHLIESSLICH basierend auf den
Transkript-Ausschnitten unten. Wenn die Antwort darin nicht zu finden ist, sag ehrlich,
dass dir dazu keine Informationen vorliegen.

Kennzeichne die Quelle NICHT nach jedem einzelnen Aufzaehlungspunkt, sondern nur EINMAL
am Ende jedes zusammenhaengenden Absatzes bzw. thematischen Abschnitts. Setze dazu den
kurzen Marker der Quelle in eckigen Klammern an das Ende des Absatzes, z. B. [{gefundene_eintraege[0]['id']}].
Wenn ein Absatz Informationen aus mehreren Quellen zusammenfasst, nenne alle passenden
IDs direkt hintereinander, z. B. [{gefundene_eintraege[0]['id']}][{gefundene_eintraege[0]['id']}].
Nutze dafuer AUSSCHLIESSLICH diese Quell-IDs: {gueltige_ids}
Erfinde KEINE eigenen IDs, nenne KEINE Dateinamen oder Links - das erledigt die Anwendung
automatisch anhand deiner Marker.

TRANSKRIPTE:
{volltext}

FRAGE: {prompt}
"""
            response = generiere_schnell(
                st.session_state.chat_session.send_message, erweiterter_prompt, stream=True, thinking_level="low"
            )

            platzhalter = st.empty()

            def stream_text():
                for chunk in response:
                    yield chunk.text

            with platzhalter.container():
                antwort_roh = st.write_stream(stream_text())

            antwort_final = ersetze_quellenmarker(antwort_roh, gefundene_eintraege)

            # Fallback: falls das Modell doch keinen einzigen Marker gesetzt hat,
            # haengen wir die Links sicherheitshalber trotzdem unten an,
            # damit nie ganz ohne Quellenangabe geantwortet wird.
            if antwort_final == antwort_roh:
                antwort_final += baue_video_links(gefundene_eintraege)

            platzhalter.markdown(antwort_final)
            full_response = antwort_final

    st.session_state.messages.append({"role": "assistant", "content": full_response})
