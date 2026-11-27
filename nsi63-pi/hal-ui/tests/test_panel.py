"""Stillerapparatets filer: manifest, ikoner og stasjonsinstruksen."""

import pytest


def test_manifest_navngis_etter_anlegget(fersk):
    r = fersk.klient.post("/api/anlegg", json={"id": "grv", "navn": "GRINDVOLL"})
    assert r.status_code == 200
    m = fersk.klient.get("/panel/manifest.json")
    assert m.status_code == 200
    assert m.mimetype == "application/manifest+json"
    d = m.get_json(force=True)
    assert d["name"].startswith("GRINDVOLL")
    assert d["start_url"] == "/panel" and d["display"] == "standalone"
    for ikon in d["icons"]:
        assert fersk.klient.get(ikon["src"]).status_code == 200


def test_manifest_uten_anlegg(fersk):
    d = fersk.klient.get("/panel/manifest.json").get_json(force=True)
    assert d["short_name"] == "NSI63"


@pytest.mark.parametrize("fil, type_", [("icon.svg", "image/svg+xml"),
                                        ("icon-192.png", "image/png")])
def test_ikonene_serveres(fersk, fil, type_):
    r = fersk.klient.get(f"/panel/{fil}")
    assert r.status_code == 200 and r.mimetype == type_


def test_andre_filer_i_mappen_serveres_ikke(fersk):
    for fil in ("app.py", "hal.json", "instruks.md", "..%2Fapp.py"):
        assert fersk.klient.get(f"/panel/{fil}").status_code == 404


def test_uten_instruks_svarer_404(fersk):
    """Panelet viser bare Instruks-knappen når denne svarer 200."""
    assert fersk.klient.get("/panel/instruks").status_code == 404
    assert fersk.klient.head("/panel/instruks").status_code == 404


def test_instruksen_vises(sokna):
    if not (sokna.mappe / "instruks.md").exists():
        pytest.skip("ingen instruks i dette treet")
    r = sokna.klient.get("/panel/instruks")
    assert r.status_code == 200 and r.mimetype == "text/html"
    html = r.get_data(as_text=True)
    assert "<h1>" in html and "<ol>" in html
    assert sokna.klient.head("/panel/instruks").status_code == 200


def test_instruksen_escaper_html(fersk):
    (fersk.mappe / "instruks.md").write_text(
        "# Tittel <script>alert(1)</script>\n\ntekst & <b>mer</b>\n",
        encoding="utf-8")
    html = fersk.klient.get("/panel/instruks").get_data(as_text=True)
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html and "&amp;" in html


@pytest.mark.parametrize("md, forventet", [
    ("# A\n## B", "<h1>A</h1>\n<h2>B</h2>"),
    ("**fet** og *kursiv* og `kode`",
     "<p><b>fet</b> og <i>kursiv</i> og <code>kode</code></p>"),
    ("1. en\n   fortsatt\n\n2. to", "<ol>\n<li>en fortsatt</li>\n<li>to</li>\n</ol>"),
    ("3. tre", '<ol start="3">\n<li>tre</li>\n</ol>'),
    ("- a\n- b\n\netter", "<ul>\n<li>a</li>\n<li>b</li>\n</ul>\n<p>etter</p>"),
    ("over\n\n---\n\nunder", "<p>over</p>\n<hr>\n<p>under</p>"),
    ("2 * 3 * 4", "<p>2 * 3 * 4</p>"),
])
def test_markdown(fersk, md, forventet):
    assert fersk.app.md_til_html(md) == forventet
