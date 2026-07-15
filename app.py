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

# 2. Transkripte laden (WICHTIG: Text "eindampfen")
@st.cache_data
def load_transcripts():
    text = ""
    for file in glob.glob("**/*.txt", recursive=True):
        if "requirements.txt" not in file: 
            with open(file, "r", encoding="utf-8") as f:
                # Wir entfernen überflüssige Zeilenumbrüche, um Token zu sparen
                content = f.read().replace("\n", " ").strip()
                text += f"[{os.path.basename(file)}] {content} "
    return text

transcripts_text = load_transcripts()

# 3. Gemini konfigurieren (Blitzschnell ohne Dateianhang)
system_prompt = f"""Du bist ein Extraktions-Assistent. Suche in den Kontextdaten.
Format: [SLUG] | [ORIGINAL_TIMESTAMP] | [ERKLÄRUNG]
Wenn nichts gefunden: "Keine relevante Stelle in der Wissensbasis gefunden."

KONTEXT:
{transcripts_text}
"""

if "chat_session" not in st.session_state:
    model = genai.GenerativeModel(model_name="models/gemini-3.5-flash", system_instruction=system_prompt)
    st.session_state.chat_session = model.start_chat(history=[])

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
