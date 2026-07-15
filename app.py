import streamlit as st
import os
import glob
import google.generativeai as genai

# Chat-UI aufbauen
st.title("Transkript Assistent")

def calculate_ts_url(timestamp_str):
    h, m, s = timestamp_str.split(':')
    s, ms = s.split('.')
    total_seconds = int(h)*3600 + int(m)*60 + int(s)
    result = max(0, total_seconds - 4)
    m_res = result // 60
    s_res = result % 60
    if m_res == 0:
        return f"{s_res}s"
    return f"{m_res}m{s_res}s"

# 1. API-Key sicher aus den Streamlit Secrets laden
api_key = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=api_key)

# 2. Transkripte laden
@st.cache_data
def load_transcripts():
    text = ""
    for file in glob.glob("**/*.txt", recursive=True):
        if "requirements.txt" not in file: 
            with open(file, "r", encoding="utf-8") as f:
                text += f"\n--- Datei: {os.path.basename(file)} ---\n"
                text += f.read()
    return text

transcripts_text = load_transcripts()
# Zum Testen anlassen, wenn du fertig bist, einfach mit # auskommentieren
st.info(f"System-Diagnose: Es wurden {len(transcripts_text)} Zeichen geladen.")

# 3. Gemini konfigurieren
system_prompt = f"""Du bist ein Extraktions-Assistent. 
Suche in den Transkripten nach relevanten Stellen.
Wenn du eine Stelle findest, gib mir NUR dieses Format aus:
[SLUG] | [ORIGINAL_TIMESTAMP] | [ERKLÄRUNG]

Beispiel:
video-6_1 | 00:01:20.000 | Hier wird erklärt, wie das Teammeeting ablief.

Wenn nichts gefunden wurde, antworte exakt: "Keine relevante Stelle in der Wissensbasis gefunden."
Keine anderen Texte oder Erklärungen.

HIER SIND DIE TRANSKRIPTE:
{transcripts_text}
"""

if "chat_session" not in st.session_state:
    model = genai.GenerativeModel(
        model_name="models/gemini-3.5-flash",
        system_instruction=system_prompt
    )
    st.session_state.chat_session = model.start_chat(history=[])

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 4. Neue Frage verarbeiten
if prompt := st.chat_input("Stell mir eine Frage zu den Transkripten..."):
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        response = st.session_state.chat_session.send_message(prompt, stream=True)
        
        def process_and_stream():
            for chunk in response:
                if chunk.text:
                    text = chunk.text
                    if "|" in text:
                        parts = text.split(" | ")
                        if len(parts) == 3:
                            slug, ts, erklärung = parts
                            ts_url = calculate_ts_url(ts.strip())
                            url = f"https://bepartner-test.kopfhandundfuss.net/s/course/{slug.strip()}?lang=de&ts={ts_url}"
                            yield f"{slug.strip()} @ {ts.strip()} – {erklärung.strip()}\n{url}\n\n"
                        else:
                            yield text
                    else:
                        yield text
                
        full_response = st.write_stream(process_and_stream())
    
    st.session_state.messages.append({"role": "assistant", "content": full_response})
