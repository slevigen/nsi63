"""Backend-herding: /api/hendelser?n=, /api/togvei-betjen, OTA-skriving og hevd_konfig."""

import io
import pytest


def test_hendelser_ugyldig_n_gir_ikke_500(fersk):
    for q in ("abc", "-5", "0", "999999"):
        r = fersk.klient.get(f"/api/hendelser?n={q}")
        assert r.status_code == 200, q
        assert isinstance(r.get_json()["hendelser"], list)


@pytest.mark.parametrize("tid", ["A/B", "A+", "A#1", "../master"])
def test_togvei_betjen_avviser_mqtt_tegn(fersk, tid):
    r = fersk.klient.post("/api/togvei-betjen",
                          json={"id": tid, "hva": "sikre"})
    assert r.status_code == 400
    assert not fersk.mq.publisert


def test_togvei_betjen_avviser_ikke_dict(fersk):
    r = fersk.klient.post("/api/togvei-betjen", json=["A01"])
    assert r.status_code == 400
    assert not fersk.mq.publisert


def test_ota_firmware_skriver_atomisk_uten_tmp_rester(fersk):
    data = b"\xe9" + bytes(250_000)
    r = fersk.klient.post(
        "/api/ota/firmware",
        data={"file": (io.BytesIO(data), "nsi63-atoms3-202611280930.bin")},
        content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    filer = {p.name for p in fersk.app.OTA_DIR.iterdir()}
    assert not any(n.endswith(".tmp") for n in filer)
    assert {"nsi63-atoms3.bin", "nsi63-atoms3.bin.md5",
            "nsi63-atoms3.bin.stempel"} <= filer


def test_hevd_konfig_tar_laasen(sokna, monkeypatch):
    a = sokna.app
    holdt = []
    ekte = a.lock

    class SporLaas:
        def __enter__(self):
            holdt.append(True)
            return ekte.__enter__()

        def __exit__(self, *args):
            return ekte.__exit__(*args)

    monkeypatch.setattr(a, "lock", SporLaas())
    a.hevd_konfig()
    assert holdt == [True]
    assert "nsi63/config/hal" in sokna.mq.retained
