#!/usr/bin/env python3
"""Serve the site locally and capture the standard screenshots."""
import contextlib, functools, http.server, os, shutil, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = [(1280, 900, 1, "#tw", "screenshot-desktop.png"),
         (390, 844, 2, "#tw", "screenshot-mobile.png"),
         (1280, 900, 1, "#intl", "screenshot-intl.png"),
         (1280, 900, 1, "archive.html", "screenshot-archive.png"),
         (1280, 900, 1, "corrections.html", "screenshot-corrections.png")]

def chrome_path():
    for p in ("/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"):
        if os.path.exists(p):
            return p
    return None  # fall back to playwright's bundled chromium

def main():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    handler = functools.partial(Quiet, directory=ROOT)
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as srv:
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        with sync_playwright() as p:
            kw = {"args": ["--no-sandbox"]}
            if chrome_path(): kw["executable_path"] = chrome_path()
            b = p.chromium.launch(**kw)
            for w, h, scale, hash_, out in SHOTS:
                pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=scale)
                pg.goto(f"http://127.0.0.1:{port}/{hash_}")
                pg.wait_for_selector(".arch-item" if hash_.startswith("archive") else ".empty, .correction" if hash_.startswith("corrections") else ".item")
                pg.screenshot(path=os.path.join(ROOT, out), full_page=True)
                pg.close()
                print("saved", out)
            b.close()
        srv.shutdown()

if __name__ == "__main__":
    main()
