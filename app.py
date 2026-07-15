import streamlit as st
import google.generativeai as genai

st.title("Verfügbare Gemini Modelle für deinen Key:")

api_key = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=api_key)

# Fragt die Google API direkt nach allen aktuell gültigen Modellen ab
for m in genai.list_models():
    if 'generateContent' in m.supported_generation_methods:
        st.write(m.name)
