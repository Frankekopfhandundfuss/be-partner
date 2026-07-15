import streamlit as st
import os
import glob
import google.generativeai as genai

# Chat-UI aufbauen
st.title("Transkript Assistent")

# 1. API-Key sicher aus den Streamlit Secrets laden
api_key = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=api_key)

# 2. Transkripte laden (angepasst auf die echten Dateiendungen)
@st.cache_data
def load_transcripts():
    text = ""
    # Sucht nach allen Textdateien (deckt deine .vtt.txt ab)
    for file in glob.glob("**/*.txt", recursive=True):
        # Die requirements.txt ignorieren wir, das ist kein Transkript
        if "requirements.txt" not in file: 
            with open(file, "r", encoding="utf-8") as f:
                text += f"\n--- Datei: {os.path.basename(file)} ---\n"
                text += f.read()
    return text

transcripts_text = load_transcripts()
st.info(f"System-Diagnose: Es wurden {len(transcripts_text)} Zeichen geladen.")

# 3. Gemini konfigurieren
system_prompt = (
    "Du bist ein hilfsbereiter Assistent für eine Website. "
    "Beantworte die Fragen der Nutzer AUSSCHLIESSLICH basierend auf den folgenden Transkripten. "
    "Wenn die Antwort in den Texten nicht zu finden ist, antworte "
    "höflich, dass dir dazu keine Informationen vorliegen.\n\n"
    f"HIER SIND DIE TRANSKRIPTE:\n{transcripts_text}"
)

# Chat-Session im Hintergrund am Leben halten
if "chat_session" not in st.session_state:
    model = genai.GenerativeModel(
        model_name="models/gemini-3.5-flash",
        system_instruction=system_prompt
    )
    st.session_state.chat_session = model.start_chat(history=[])

if "messages" not in st.session_state:
    st.session_state.messages = []

# Bisherigen Chatverlauf auf der Website anzeigen
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 4. Neue Frage verarbeiten
if prompt := st.chat_input("Stell mir eine Frage zu den Transkripten..."):
    
    # Frage des Nutzers anzeigen und speichern
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    # Antwort der KI holen und live anzeigen
    with st.chat_message("assistant"):
        response = st.session_state.chat_session.send_message(prompt, stream=True)
        full_response = st.write_stream(response)
    
    # Antwort in der Historie speichern
    st.session_state.messages.append({"role": "assistant", "content": full_response})
