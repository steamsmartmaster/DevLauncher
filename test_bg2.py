"""Test with actual bg.png"""
import sys, base64, os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QUrl, QTimer

bg_path = r"D:\sss-data\workplace\DevLauncher\ui\bg.png"
with open(bg_path, 'rb') as f:
    raw = f.read()
print(f"File size: {len(raw)} bytes")
data_uri = f"data:image/png;base64,{base64.b64encode(raw).decode()}"
print(f"Data URI length: {len(data_uri)}")

HTML = """<!DOCTYPE html>
<html><body style="margin:0; background:#222;">
<div id="bg" style="position:fixed;top:0;left:0;width:100%;height:100%;z-index:-1;background-size:cover;"></div>
<h1 style="color:white;padding:20px;">Background Test with bg.png</h1>
</body></html>"""

app = QApplication(sys.argv)
view = QWebEngineView()
view.setHtml(HTML)
view.resize(800, 600)
view.show()

def set_bg():
    js = f"document.getElementById('bg').style.backgroundImage = 'url({data_uri})';"
    print(f"JS command length: {len(js)}")
    view.page().runJavaScript(js, lambda r: print("runJavaScript OK"), lambda e: print("runJavaScript ERR:", e))

QTimer.singleShot(1000, set_bg)
sys.exit(app.exec())
