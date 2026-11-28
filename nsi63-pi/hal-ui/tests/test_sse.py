"""Sanntidsstrømmen (GET /api/events) og monotonisk aldersberegning."""

import json
import threading
import time


class _Msg:
    def __init__(self, topic, payload, retain=False):
        self.topic = topic
        self.payload = payload if isinstance(payload, bytes) else payload.encode()
        self.retain = retain


def _parse_ramme(chunk):
    tekst = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
    hendelse, data = None, None
    for linje in tekst.strip().splitlines():
        if linje.startswith("event:"):
            hendelse = linje.split(":", 1)[1].strip()
        elif linje.startswith("data:"):
            data = json.loads(linje.split(":", 1)[1].strip())
    return hendelse, data


def test_snapshot_inneholder_alle_felt_og_rydder_i_finally(fersk):
    a = fersk.app
    assert a.sse.antall() == 0
    r = fersk.klient.get("/api/events")
    assert r.status_code == 200
    assert r.mimetype == "text/event-stream"
    it = iter(r.response)
    try:
        ev, snap = _parse_ramme(next(it))
        assert ev == "snapshot"
        assert a.sse.antall() == 1
        assert "server_ts" not in snap
        for felt in ("master", "nodes", "inputs", "ack", "togvei_info",
                     "lamptest", "ota", "ota_ko", "backup", "pi",
                     "hendelser_aktiv"):
            assert felt in snap, f"mangler {felt} i snapshot"
        assert "igjen_s" in snap["lamptest"]
        assert "start_mono" not in snap["lamptest"]
    finally:
        r.close()
    assert a.sse.antall() == 0


def test_abonnering_fanger_hendelse_under_snapshot(fersk, monkeypatch):
    """Klienten meldes på navet FØR _snapshot_payload() kjører, så en
    hendelse som kommer mens snapshotet bygges ikke går tapt."""
    a = fersk.app
    ekte = a._snapshot_payload

    def snap_med_samtidig_input():
        res = ekte()
        a.on_message(None, None, _Msg(
            "nsi63/espnow/aa0000000001/in/20", '{"i2c":"0x20","value":254}'))
        return res

    monkeypatch.setattr(a, "_snapshot_payload", snap_med_samtidig_input)
    r = fersk.klient.get("/api/events")
    it = iter(r.response)
    try:
        ev1, _ = _parse_ramme(next(it))
        ev2, data2 = _parse_ramme(next(it))
        assert ev1 == "snapshot"
        assert ev2 == "input"
        assert data2 == {"k": "aa0000000001/0x20", "v": 254}
    finally:
        r.close()
    assert a.sse.antall() == 0


def test_mqtt_meldinger_sender_delta_eventer(fersk):
    a = fersk.app
    r = fersk.klient.get("/api/events")
    it = iter(r.response)
    try:
        assert _parse_ramme(next(it))[0] == "snapshot"

        a.on_message(None, None, _Msg(
            "nsi63/espnow/aa0000000001/in/20", '{"i2c":"0x20","value":253}'))
        ev, d = _parse_ramme(next(it))
        assert ev == "input" and d == {"k": "aa0000000001/0x20", "v": 253}

        a.on_message(None, None, _Msg(
            "nsi63/master/hal", '{"version":"2026-11-28 10:00:00","functions":4}'))
        ev, d = _parse_ramme(next(it))
        assert ev == "ack" and d["type"] == "hal"
        assert d["data"]["version"] == "2026-11-28 10:00:00"

        a.on_message(None, None, _Msg(
            "nsi63/togvei/A01/info", "sikret: kjorsignal satt"))
        ev, d = _parse_ramme(next(it))
        assert ev == "togvei_info"
        assert d == {"id": "A01", "tekst": "sikret: kjorsignal satt",
                     "alder_s": 0}

        a.on_message(None, None, _Msg("nsi63/master/melding", "testvarsel"))
        ev, d = _parse_ramme(next(it))
        assert ev == "master"
        assert d["meldinger"][-1]["tekst"] == "testvarsel"
        assert d["meldinger"][-1]["alder_s"] == 0
    finally:
        r.close()


def test_hendelseslogg_strommer_live(fersk):
    a = fersk.app
    assert fersk.klient.post("/api/hendelser/aktiv",
                             json={"aktiv": True}).status_code == 200
    r = fersk.klient.get("/api/events")
    it = iter(r.response)
    try:
        assert _parse_ramme(next(it))[0] == "snapshot"
        a.on_message(None, None, _Msg("nsi63/togvei/A01/cmd", "sikre"))
        ev, d = _parse_ramme(next(it))
        assert ev == "hendelse"
        assert d["tema"] == "togvei/A01/cmd" and d["data"] == "sikre"
    finally:
        r.close()


def test_full_ko_lukker_klientstrom_umiddelbart(fersk):
    """En treg klient hvis kø fylles opp skal meldes av OG få lukkesignal
    så generatoren avslutter i stedet for å bli stående på evige pings."""
    a = fersk.app
    a.sse = a._SseHub(maks_ko=3)
    r = fersk.klient.get("/api/events")
    it = iter(r.response)
    try:
        assert _parse_ramme(next(it))[0] == "snapshot"
        assert a.sse.antall() == 1
        # Overfyll køen (kapasitet 3) -> 4. melding skal droppe og lukke klienten
        for i in range(5):
            a.sse.send("input", {"k": "aa0000000001/0x20", "v": i})
        assert a.sse.antall() == 0
        # Generatoren skal avslutte rent (StopIteration) umiddelbart
        rester = list(it)
        assert rester == []
    finally:
        r.close()


def test_tick_fyrer_paa_fast_frist_selv_under_trafikk(fersk, monkeypatch):
    """Tick skal sendes på fast frist uansett hvor mange hendelser som
    kommer på køen, og skal oppdatere sist_hort_s og utløpt konflikt."""
    a = fersk.app
    monkeypatch.setattr(a, "SSE_TICK_S", 0.06)
    a.cache["master_hort_ts"] = time.monotonic() - 40
    a.cache["conflict"] = {"data": {"self": "a", "other": "b"},
                           "mono": time.monotonic() - 65}
    r = fersk.klient.get("/api/events")
    it = iter(r.response)
    try:
        assert _parse_ramme(next(it))[0] == "snapshot"
        # Pump jevnlige hendelser hvert 15 ms — uten fast frist ville
        # timeouten blitt nullstilt for alltid
        stopp = threading.Event()

        def pumpe():
            i = 0
            while not stopp.is_set():
                a.sse.send("input", {"k": "aa0000000001/0x20", "v": i})
                i += 1
                time.sleep(0.015)

        t = threading.Thread(target=pumpe, daemon=True)
        t.start()
        try:
            tick_data = None
            frist = time.monotonic() + 1.0
            while time.monotonic() < frist:
                ev, d = _parse_ramme(next(it))
                if ev == "tick":
                    tick_data = d
                    break
            assert tick_data is not None, "tick fyrte aldri under trafikk"
            assert "server_ts" not in tick_data
            assert tick_data["master"]["sist_hort_s"] >= 40
            assert tick_data["master"]["conflict"] is None
            assert "pi" in tick_data and "lamptest" in tick_data
        finally:
            stopp.set()
            t.join(1.0)
    finally:
        r.close()
    assert a.sse.antall() == 0


def test_lamptest_payload_har_monotonisk_igjen_s(fersk, monkeypatch):
    a = fersk.app
    klokke = [100.0]
    monkeypatch.setattr(a.time, "monotonic", lambda: klokke[0])
    a.lamptest.update(running=True, traad=True, start_mono=100.0)
    try:
        klokke[0] = 142.0
        p = fersk.klient.get("/api/lamptest").get_json()
        assert p["igjen_s"] == a.LAMPTEST_MAKS_S - 42
        assert "start_mono" not in p
    finally:
        a.lamptest.update(running=False, traad=False)
        a.lamptest.pop("start_mono", None)


def test_klokke_stilt_skiller_karantene_og_visningsklokke(fersk, monkeypatch):
    """Karantenen bruker monotonisk tid (upåvirket av klokkehopp), mens
    'naar' i /api/pi viser veggklokketid."""
    a = fersk.app
    monkeypatch.setattr(a, "_ntp_synk", lambda: False)
    mono = [500.0]
    vegg = [1_700_000_000.0]
    monkeypatch.setattr(a.time, "monotonic", lambda: mono[0])
    monkeypatch.setattr(a.time, "time", lambda: vegg[0])
    a._klokke_stilt.update(ts=None, mono=None, diff_s=None, fra=None)

    r1 = fersk.klient.post("/api/klokke", json={"epoch_ms": 1_700_001_000_000})
    assert r1.status_code == 200 and r1.get_json()["status"] == "stilt"
    assert a._klokke_stilt["mono"] == 500.0
    assert a._klokke_stilt["ts"] == 1_700_000_000.0

    # Veggklokken hopper 10 timer frem, men monotonisk tid er bare +10 s -> cooldown!
    vegg[0] += 36000
    mono[0] += 10
    r2 = fersk.klient.post("/api/klokke", json={"epoch_ms": 1_700_050_000_000})
    assert r2.status_code == 200 and r2.get_json()["status"] == "cooldown"


def test_ingen_traadlekkasje_ved_import(tmp_path, monkeypatch):
    from conftest import _lag
    for_ = threading.active_count()
    gen = _lag(tmp_path, monkeypatch, None)
    next(gen)
    try:
        assert threading.active_count() == for_
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_on_message_uten_klienter_leser_ikke_hal(fersk, monkeypatch):
    """Uten tilkoblede SSE-klienter skal master/nodes-meldinger ikke trigge
    disklesing (load_hal) via _ota_ko_payload()."""
    a = fersk.app
    kall = []
    ekte = a.load_hal
    monkeypatch.setattr(a, "load_hal", lambda: (kall.append(1), ekte())[1])
    assert a.sse.antall() == 0
    a.on_message(None, None, _Msg(
        "nsi63/master/nodes",
        '{"master":"aa","nodes":[{"mac":"bb0000000001","online":1}]}'))
    assert kall == []


def test_on_message_taaler_ugyldige_mqtt_payloads(fersk):
    """Feilformaterte MQTT-meldinger (f.eks. liste i master/nodes eller tall
    i bygget) skal aldri kaste unntak på paho-nettverkstråden, verken med
    eller uten SSE-klienter."""
    a = fersk.app
    ugyldige = [
        _Msg("nsi63/master/nodes", "[]"),
        _Msg("nsi63/master/nodes",
             '{"master":"aa","nodes":[{"mac":"bb0000000001","online":1,"bygget":12345}]}'),
        _Msg("nsi63/espnow/aa0000000001/in/20", "[1,2,3]"),
    ]
    # 1) Uten SSE-klienter
    for m in ugyldige:
        a.on_message(None, None, m)
    # 2) Med tilkoblet SSE-klient
    r = fersk.klient.get("/api/events")
    it = iter(r.response)
    try:
        assert _parse_ramme(next(it))[0] == "snapshot"
        for m in ugyldige:
            a.on_message(None, None, m)
    finally:
        r.close()


def test_lamptest_start_sender_fersk_igjen_s(fersk, monkeypatch):
    """Første lamptest-hendelse ved Start skal ha fersk start_mono (igjen_s
    nær 600), ikke restverdien fra en tidligere lampeprøve."""
    a = fersk.app
    klokke = [1000.0]
    monkeypatch.setattr(a.time, "monotonic", lambda: klokke[0])
    # Simuler gammel prøve fra 900 s siden og forhindre bakgrunnstråd
    a.lamptest.update(running=False, traad=False, start_mono=100.0)

    class StumTraad:
        def __init__(self, target=None, daemon=None, **kw):
            pass
        def start(self):
            pass

    monkeypatch.setattr(a.threading, "Thread", StumTraad)
    r_sse = fersk.klient.get("/api/events")
    it = iter(r_sse.response)
    try:
        assert _parse_ramme(next(it))[0] == "snapshot"
        r = fersk.klient.post("/api/lamptest", json={"action": "start"})
        assert r.status_code == 200
        ev, d = _parse_ramme(next(it))
        assert ev == "lamptest"
        assert d["running"] is True
        assert d["igjen_s"] == a.LAMPTEST_MAKS_S
    finally:
        r_sse.close()
        a.lamptest.update(running=False, traad=False)
        a.lamptest.pop("start_mono", None)

