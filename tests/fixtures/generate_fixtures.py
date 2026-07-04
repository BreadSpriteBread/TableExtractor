"""Generate fixture PDFs for every case in the extraction scope.

Deterministic output — run once and commit the PDFs alongside the
hand-verified expected JSON in tests/fixtures/expected/.

    python3 -m tests.fixtures.generate_fixtures
"""
import io
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

FIXTURE_DIR = Path(__file__).parent
PDF_DIR = FIXTURE_DIR / "pdfs"

GRID_STYLE = TableStyle([
    ("GRID", (0, 0), (-1, -1), 0.8, colors.black),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE", (0, 0), (-1, -1), 10),
])

SIMPLE_DATA = [
    ["Item", "Q1", "Q2", "Total"],
    ["Revenue", "1000", "1200", "2200"],
    ["Expenses", "400", "500", "900"],
    ["Profit", "600", "700", "1300"],
]


def _doc(path, pagesize=letter):
    return SimpleDocTemplate(str(path), pagesize=pagesize,
                             leftMargin=72, rightMargin=72,
                             topMargin=72, bottomMargin=72)


def make_simple():
    _doc(PDF_DIR / "simple.pdf").build([Table(SIMPLE_DATA, style=GRID_STYLE)])


def make_landscape():
    _doc(PDF_DIR / "landscape_table.pdf", pagesize=landscape(letter)).build(
        [Table(SIMPLE_DATA, style=GRID_STYLE)])


def make_borderless():
    """Columns aligned by position only — no ruling lines at all."""
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(PDF_DIR / "borderless.pdf"), pagesize=letter)
    xs = [72, 220, 320, 420]
    y = 700
    for row in SIMPLE_DATA:
        font = "Helvetica-Bold" if y == 700 else "Helvetica"
        for x, cell in zip(xs, row):
            c.setFont(font, 11)
            c.drawString(x, y, cell)
        y -= 24
    c.save()


def make_rotated():
    """Same table but the page carries /Rotate 90."""
    from pypdf import PdfReader, PdfWriter
    make_simple()
    reader = PdfReader(str(PDF_DIR / "simple.pdf"))
    writer = PdfWriter()
    page = reader.pages[0]
    page.rotate(90)
    writer.add_page(page)
    with open(PDF_DIR / "rotated.pdf", "wb") as f:
        writer.write(f)


def make_multipage():
    """One logical table that flows over two pages with a repeated header."""
    data = [["Month", "Sales", "Cost"]]
    for i in range(1, 45):
        data.append([f"Month {i}", str(1000 + i), str(500 + i)])
    t = Table(data, style=GRID_STYLE, repeatRows=1)
    _doc(PDF_DIR / "multipage.pdf").build([t])


def make_nested():
    """Outer table with an inner table flattened into one cell."""
    inner = Table([["a", "b"], ["c", "d"]], style=GRID_STYLE)
    outer = Table(
        [["Region", "Breakdown"],
         ["North", inner],
         ["South", "42"]],
        style=GRID_STYLE, colWidths=[120, 160])
    _doc(PDF_DIR / "nested.pdf").build([outer])


def make_scanned():
    """Image-only PDF: render simple.pdf to a bitmap and re-embed it."""
    import fitz
    make_simple()
    with fitz.open(PDF_DIR / "simple.pdf") as src:
        pix = src[0].get_pixmap(dpi=150)
        img_bytes = pix.tobytes("jpg", jpg_quality=85)
    out = fitz.open()
    page = out.new_page(width=612, height=792)
    page.insert_image(fitz.Rect(0, 0, 612, 792), stream=img_bytes)
    out.save(PDF_DIR / "scanned.pdf")
    out.close()


def make_no_tables():
    styles = getSampleStyleSheet()
    story = [Paragraph("This report contains narrative text only. " * 20,
                       styles["Normal"])]
    _doc(PDF_DIR / "no_tables.pdf").build(story)


def make_password_protected():
    from pypdf import PdfReader, PdfWriter
    make_simple()
    reader = PdfReader(str(PDF_DIR / "simple.pdf"))
    writer = PdfWriter()
    writer.append(reader)
    writer.encrypt("secret")
    with open(PDF_DIR / "password.pdf", "wb") as f:
        writer.write(f)


def make_corrupted():
    (PDF_DIR / "corrupted.pdf").write_bytes(
        b"%PDF-1.7\nthis is not a real pdf body" + b"\x00" * 64)


def make_zero_byte():
    (PDF_DIR / "zero_byte.pdf").write_bytes(b"")


def main():
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    make_simple()
    make_landscape()
    make_borderless()
    make_rotated()
    make_multipage()
    make_nested()
    make_scanned()
    make_no_tables()
    make_password_protected()
    make_corrupted()
    make_zero_byte()
    print(f"fixtures written to {PDF_DIR}")
    for p in sorted(PDF_DIR.iterdir()):
        print(f"  {p.name} ({p.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
