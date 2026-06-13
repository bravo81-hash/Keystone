"""Desktop launcher: start the Keystone Flask app and open it in the browser.

Run via run_keystone.bat (which uses the project's .venv). Opens
http://127.0.0.1:5000/ a moment after the server starts. Close the console
window (or Ctrl+C) to stop the app.
"""

from __future__ import annotations

import threading
import webbrowser

from ui.app import create_app

HOST = "127.0.0.1"
PORT = 5000
URL = f"http://{HOST}:{PORT}/"


def _open_browser() -> None:
    webbrowser.open(URL)


if __name__ == "__main__":
    print(f"Starting Keystone — opening {URL}")
    print("Close this window (or press Ctrl+C) to stop the app.")
    threading.Timer(1.5, _open_browser).start()
    # debug/reloader off so the launcher runs a single, clean process.
    create_app().run(host=HOST, port=PORT, debug=False)
