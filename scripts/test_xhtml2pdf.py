from xhtml2pdf import pisa

html = """<html><body><h1 style="color:#1a3a5c">Eli Hebdon</h1><p>Test resume PDF</p></body></html>"""
with open("/tmp/test_xhtml2pdf.pdf", "wb") as f:
    status = pisa.CreatePDF(html, dest=f)
print("err", status.err)
import os
print("size", os.path.getsize("/tmp/test_xhtml2pdf.pdf"))
