"""청약홈 미계약 세대 스캐너 진입점."""

import threading
import webbrowser

import server

PORT = 8765

if __name__ == "__main__":
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    server.serve(PORT)
