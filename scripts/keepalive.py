"""
Weckt die Streamlit Community Cloud App auf, falls sie im Schlafmodus ist.

Warum kein einfaches requests.get(URL)?
Ein reines HTTP-GET liefert von Streamlit Community Cloud nur eine statische
HTML-Huelle mit Status 200 zurueck - die eigentliche Python-App startet dabei
NICHT. Nur ein echter Browser (der JavaScript ausfuehrt und die WebSocket-
Verbindung aufbaut) weckt die App tatsaechlich auf. Deshalb Playwright
(Headless Chromium) statt requests/urllib.

Ablauf:
1. Seite mit echtem Browser aufrufen
2. Pruefen, ob der "Yes, get this app back up!"-Button da ist (= App schlaeft)
3. Falls ja: klicken und kurz warten, bis die App tatsaechlich hochfaehrt
4. Falls kein Button da ist: App war schon wach, nichts zu tun
"""

import sys
from playwright.sync_api import sync_playwright

APP_URL = "https://be-partner.streamlit.app/"

# Der exakte Button-Text kann sich bei Streamlit-Updates leicht aendern -
# deshalb mehrere plausible Varianten probieren, statt nur eine.
WAKE_BUTTON_TEXTS = [
    "Yes, get this app back up!",
    "Get this app back up",
    "Wake up",
]


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        print(f"Rufe {APP_URL} auf ...")
        try:
            page.goto(APP_URL, timeout=60_000, wait_until="domcontentloaded")
        except Exception as e:
            print(f"FEHLER beim Aufrufen der Seite: {e}")
            browser.close()
            sys.exit(1)

        # Kurz warten, damit die Sleeping-Seite (falls vorhanden) sich aufbaut
        page.wait_for_timeout(3000)

        button_geklickt = False
        for text in WAKE_BUTTON_TEXTS:
            button = page.get_by_text(text, exact=False)
            try:
                if button.count() > 0:
                    print(f"App schlaeft - klicke Button: '{text}'")
                    button.first.click()
                    button_geklickt = True
                    break
            except Exception:
                continue

        if button_geklickt:
            # Nach dem Klick dauert das Hochfahren der App einen Moment.
            # Wir warten hier bewusst, damit der naechste echte Besucher
            # nicht selbst noch auf das Hochfahren warten muss.
            print("Warte, bis die App hochgefahren ist ...")
            page.wait_for_timeout(15_000)
            print("App aufgeweckt.")
        else:
            print("Kein Wecken-Button gefunden - App war bereits wach.")

        browser.close()


if __name__ == "__main__":
    main()
