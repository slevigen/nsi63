"""Diagnostikk-eksporten: én zip til feilsøking på avstand."""

import io
import json
import zipfile

FILER = {"oppsummering.json", "konfig-backup.json", "hendelser.jsonl",
         "journal.txt"}


def _hent(h):
    r = h.klient.get("/api/diagnostikk")
    assert r.status_code == 200
    assert r.mimetype == "application/zip"
    return r, zipfile.ZipFile(io.BytesIO(r.data))


def test_zip_med_alle_filene(anlegg):
    r, z = _hent(anlegg)
    assert set(z.namelist()) == FILER
    assert z.testzip() is None
    o = json.loads(z.read("oppsummering.json"))
    for nokkel in ("laget", "anlegg", "pi", "master", "noder", "ota",
                   "backup"):
        assert nokkel in o
    navn = r.headers["Content-Disposition"]
    assert "nsi63-diagnostikk-" in navn and navn.endswith(".zip")


def test_filnavn_bruker_anleggs_id(fersk):
    fersk.klient.post("/api/anlegg", json={"id": "grv"})
    r, _ = _hent(fersk)
    assert "nsi63-diagnostikk-GRV-" in r.headers["Content-Disposition"]


def test_uten_id(fersk):
    r, _ = _hent(fersk)
    assert "nsi63-diagnostikk-uten-id-" in r.headers["Content-Disposition"]


def test_konfigen_kan_gjenopprettes(fersk, sokna):
    _, z = _hent(sokna)
    r = fersk.klient.post(
        "/api/restore",
        data={"file": (io.BytesIO(z.read("konfig-backup.json")), "k.json")},
        content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    assert fersk.fil("hal.json")["functions"] == \
        sokna.fil("hal.json")["functions"]


def test_er_ikke_en_backup(anlegg):
    """Påminnelsen skal stå: brukeren har ikke tatt backup."""
    for_ = anlegg.klient.get("/api/backup-status").get_json()
    _hent(anlegg)
    etter = anlegg.klient.get("/api/backup-status").get_json()
    assert etter == for_
    assert not (anlegg.mappe / "backup-status.json").exists()


def test_hendelsesloggen_kuttes_paa_hel_linje(fersk, monkeypatch):
    linjer = [json.dumps({"n": i, "fyll": "x" * 90}) for i in range(10000)]
    (fersk.mappe / "hendelser.jsonl").write_text("\n".join(linjer) + "\n")
    monkeypatch.setattr(fersk.app, "DIAG_HENDELSER_BYTE", 50_000)
    _, z = _hent(fersk)
    data = z.read("hendelser.jsonl").decode()
    assert 0 < len(data) <= 50_000
    for linje in data.strip().splitlines():
        json.loads(linje)                       # ingen halve linjer
    assert json.loads(data.strip().splitlines()[-1])["n"] == 9999


def test_uten_hendelseslogg(fersk):
    _, z = _hent(fersk)
    assert z.read("hendelser.jsonl") == b""


def test_journal_ber_om_tjenestene(fersk):
    _, z = _hent(fersk)
    kall = [k for k in fersk.subprocess_kall if k and k[0] == "journalctl"]
    assert kall
    for t in fersk.app.DIAG_TJENESTER:
        assert t in kall[-1]
    assert z.read("journal.txt")
