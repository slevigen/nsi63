"""Lampeprøven: avbruddsgrunnen skal vises, og to tråder skal aldri gå."""


def test_avbrutt_uten_lamper_vises(fersk):
    # Uten konfig finnes ingen lamper. Før ble «AVBRUTT»-grunnen
    # overskrevet av finally med «stoppet etter 0 runder».
    app = fersk.app
    app.lamptest.update(running=True, traad=True)
    app.run_lamptest()
    assert app.lamptest["progress"].startswith("AVBRUTT")
    assert not app.lamptest["running"] and not app.lamptest["traad"]


def test_avbrutt_naar_master_ikke_bekrefter_pausen(fersk, monkeypatch):
    # Ingen master svarer på håndtrykket: grunnen skal stå igjen.
    # Eksempelkonfigene har ingen bindinger, så én lampe legges inn.
    app = fersk.app
    monkeypatch.setattr(app, "lamp_list", lambda hal: [
        ("aa0000000001", "0x40", 0, "test", False)])
    klokke = [0.0]
    monkeypatch.setattr(app.time, "time", lambda: klokke[0])
    monkeypatch.setattr(app.time, "sleep",
                        lambda s: klokke.__setitem__(0, klokke[0] + s))
    app.lamptest.update(running=True, traad=True)
    app.run_lamptest()
    assert "bekrefter ikke pausen" in app.lamptest["progress"]


def test_ny_start_avvises_mens_traaden_avslutter(fersk):
    # Stopp setter running=False, men tråden kan henge i håndtrykket i
    # opptil 3 s. En ny Start i det vinduet ga to parallelle tråder.
    app = fersk.app
    app.lamptest.update(running=False, traad=True)
    try:
        r = fersk.klient.post("/api/lamptest", json={"action": "start"})
        assert r.status_code == 400
        assert "pågår" in r.get_json()["error"]
    finally:
        app.lamptest.update(running=False, traad=False)
