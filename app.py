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
system_prompt = f"""Task: 

Search the provided context (VTT transcript excerpts) for ALL passages relevant to the user's query. 

Step 1 – Merge nearby excerpts: 
If two excerpts about the same subtopic are within 30 seconds of each other, treat them as ONE entry using the EARLIEST timestamp. Only start a new entry if a later mention is more than 30 seconds after the previous one. 

Example: mentions at 00:01:10 and 00:01:25 -> ONE entry at 00:01:10. Mentions at 00:01:10 and 00:02:20 -> TWO separate entries. 

Step 2 – Calculate the timestamp for each entry. Show your math briefly inside <calc> ... </calc> tags before writing the final output line. 
a) Take the original timestamp (HH:MM:SS.mmm), convert to total seconds. b) Subtract 4. If below 0, use 0. c) Convert to URL format: 
result < 60 -> "{{seconds}}s" 
result >= 60 -> "{{minutes}}m{{seconds}}s" 

Worked examples: 
00:00:02.360 -> 2s total, minus 4 = -2 -> use 0 -> "0s" 
00:00:16.000 -> 16s total, minus 4 = 12 -> "12s" 
00:01:40.000 -> 100s total, minus 4 = 96 -> 96s = 1m36s -> "1m36s" 
00:03:15.880 -> 195s total, minus 4 = 191 -> 191s = 3m11s -> "3m11s" 

Step 3 – Extract slug and lang: 
Both appear as a tag directly in the text, format [slug|lang], e.g. [video-6_1|de]. Use exactly these values, never guess. 

Step 4 – Build the URL: 
https://bepartner-test.kopfhandundfuss.net/s/course/{{slug}}?lang={{lang}}&ts={{calculated_timestamp}} 

Output format (one line per merged entry, no exceptions, no placeholders, no unresolved {{{{}}}}): 
{{slug}} @ {{original_timestamp}} – Ein Satz, der erklärt, warum diese Stelle relevant zur Frage ist. 
https://bepartner-test.kopfhandundfuss.net/s/course/{{slug}}?lang={{lang}}&ts={{calculated_timestamp}}

Rules: 
Never output a literal "{{{{url}}}}" or similar placeholder — always compute the real value. 
If no relevant excerpt exists, respond exactly: "Keine relevante Stelle in der Wissensbasis gefunden." 
Respond in German.

HIER SIND DIE TRANSKRIPTE:
{transcripts_text}
"""

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
        
        # HIER IST DIE LÖSUNG: Wir packen die Google-Datenpakete aus
        def stream_text():
            for chunk in response:
                # Wir geben nur den reinen Text an Streamlit weiter
                yield chunk.text
                
        full_response = st.write_stream(stream_text())
    
    # Antwort in der Historie speichern
    st.session_state.messages.append({"role": "assistant", "content": full_response})
