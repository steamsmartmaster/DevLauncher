"""Minimal test: can runJavaScript set a CSS background-image with a data URI?"""
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QUrl, QTimer
import base64

# 1x1 red pixel PNG
TINY_PNG = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
    b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00'
    b'\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00'
    b'\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
)
DATA_URI = f'data:image/png;base64,{base64.b64encode(TINY_PNG).decode()}'

HTML = """<!DOCTYPE html>
<html><body style="margin:0; background:#222;">
<div id="bg" style="position:fixed;top:0;left:0;width:100%;height:100%;z-index:-1;"></div>
<h1 style="color:white;padding:20px;">Background Test</h1>
</body></html>"""

app = QApplication(sys.argv)
view = QWebEngineView()
view.setHtml(HTML)
view.resize(800, 600)
view.show()

def set_bg():
    js = f"document.getElementById('bg').style.backgroundImage = 'url({DATA_URI})';"
    print(f"JS length: {len(js)}")
    view.page().runJavaScript(js, lambda r: print("OK:", r), lambda e: print("ERR:", e))

QTimer.singleShot(1000, set_bg)
sys.exit(app.exec())
