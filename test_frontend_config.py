from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_frontend_formats_costs_as_inr():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "currency: 'INR'" in js
    assert "Unit cost (INR ₹)" in html
    assert 'id="metricExposure">₹0.00' in html


def test_github_pages_root_entrypoint_exists():
    for name in ("index.html", "style.css", "app.js"):
        assert (ROOT / name).is_file()
