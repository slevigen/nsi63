"""Kallenavn som fjernes/flyttes, AP-omdøping etter svaret, og at
retained meldinger ikke regnes som livstegn fra master."""

import time

MAC_A = "aa0000000001"
MAC_B = "aa0000000002"


def _alias(h, mac, alias):
    return h.klient.post("/api/node-alias", json={"mac": mac, "alias": alias})


def _sporfelt(fid, node, port, sted="panel"):
    return {"id": fid, "type": "sporfelt", "bindinger": [
        {"node": node, "i2c": "0x40", "port": port, "sted": sted}]}


def _noder_og_bindinger(h):
    hal = h.fil("hal.json")
    return hal["noder"], {f["id"]: f["bindinger"][0]["node"]
                          for f in hal["functions"]}


# ---------- B1: kallenavn ----------

def test_fjernet_kallenavn_gir_bindinger_paa_mac(fersk):
    assert _alias(fersk, MAC_A, "SEKSJON1").status_code == 200
    r = fersk.klient.post("/api/hal", json={"functions": [
        _sporfelt("X1", "SEKSJON1", 0)]})
    assert r.status_code == 200, r.get_json()
    r = fersk.klient.post("/api/node-driver",
                          json={"mac": MAC_A, "i2c": "0x40", "driver": True})
    assert r.status_code == 200, r.get_json()

    r = _alias(fersk, MAC_A, "")
    assert r.status_code == 200, r.get_json()
    noder, bind = _noder_og_bindinger(fersk)
    assert "SEKSJON1" not in noder
    assert bind["X1"] == MAC_A
    # driver-listen overlever under MAC-en, og master får den
    assert fersk.app.driver_brikker(noder) == {(MAC_A, "0x40")}
    pub = fersk.mq.retained_json("nsi63/config/hal")
    assert pub["functions"][0]["bindinger"][0]["node"] == MAC_A
    # nytt kallenavn arver driver-lista og tar bindingen med seg
    assert _alias(fersk, MAC_A, "SEKSJON2").status_code == 200
    noder, bind = _noder_og_bindinger(fersk)
    assert set(noder) == {"SEKSJON2"} and bind["X1"] == "SEKSJON2"
    assert noder["SEKSJON2"]["driver"] == ["0x40"]


def test_kallenavn_til_annen_node_avvises_ved_portkonflikt(fersk):
    assert _alias(fersk, MAC_A, "A").status_code == 200
    assert _alias(fersk, MAC_B, "B").status_code == 200
    r = fersk.klient.post("/api/hal", json={"functions": [
        _sporfelt("X1", "A", 3), _sporfelt("X2", "B", 3)]})
    assert r.status_code == 200, r.get_json()
    fersk.mq.publisert.clear()
    # B overtar «A»: begge bindingene havner på samme port på MAC_B
    r = _alias(fersk, MAC_B, "A")
    assert r.status_code == 400
    assert "Portkonflikt" in r.get_json()["error"]
    assert not fersk.mq.publisert, "avvist endring ble publisert"
    noder, bind = _noder_og_bindinger(fersk)
    assert noder["A"]["mac"] == MAC_A and bind == {"X1": "A", "X2": "B"}


def test_kallenavn_avvises_naar_konfigen_blir_for_stor(fersk, monkeypatch):
    assert _alias(fersk, MAC_A, "A").status_code == 200
    monkeypatch.setattr(fersk.app, "_for_stor", lambda d, hva: "for stor")
    r = _alias(fersk, MAC_A, "")
    assert r.status_code == 400 and r.get_json()["error"] == "for stor"
    assert "A" in fersk.fil("hal.json")["noder"]


# ---------- B2: AP-omdøping etter svaret ----------

def test_hostapd_restartes_foerst_etter_svaret(fersk):
    conf = fersk.mappe / "hostapd.conf"
    conf.write_text("interface=wlan0\nssid=NSI63\n")
    r = fersk.klient.post("/api/anlegg", json={"id": "grv"})
    assert r.status_code == 200
    assert r.get_json()["ap_omdopt"] is True
    assert "ssid=NSI63GRV" in conf.read_text()
    # svaret er sendt, men ingenting er restartet ennå
    restart = ["systemctl", "restart", "hostapd"]
    assert restart not in fersk.subprocess_kall
    assert len(fersk.bakgrunn) == 1
    fersk.bakgrunn.pop()()
    assert restart in fersk.subprocess_kall


def test_uendret_ssid_rapporteres_ikke_som_omdopt(fersk):
    (fersk.mappe / "hostapd.conf").write_text("ssid=NSI63GRV\n")
    r = fersk.klient.post("/api/anlegg", json={"id": "grv"})
    assert r.get_json()["ap_omdopt"] is False
    assert not fersk.bakgrunn


def test_uten_hostapd_konfig_ingen_omdoping(fersk):
    r = fersk.klient.post("/api/anlegg", json={"id": "grv"})
    assert r.get_json()["ap_omdopt"] is False
    assert not fersk.bakgrunn


def test_etter_svaret_venter_og_kjoerer_i_bakgrunnen(fersk, monkeypatch):
    monkeypatch.setattr(fersk.app, "AP_OMSTART_FORSINKELSE_S", 0.05)
    kjort = []
    t = fersk.ekte_etter_svaret(lambda: kjort.append(time.monotonic()))
    start = time.monotonic()
    assert t.daemon and not kjort
    t.join(2)
    assert kjort and kjort[0] - start >= 0.04


# ---------- retain: ikke livstegn ----------

class _Msg:
    def __init__(self, topic, payload, retain):
        self.topic, self.payload, self.retain = topic, payload, retain


def test_retained_melding_regnes_ikke_som_hort(fersk):
    a = fersk.app
    a.cache["master_hort_ts"] = None
    for tema, nytt in (("nsi63/master/info", b'{"fw": 1}'),
                       ("nsi63/master/nodes", b'{"master": "x"}'),
                       ("nsi63/master/jord", b"av")):
        a.on_message(None, None, _Msg(tema, nytt, True))
    assert a.cache["master_hort_ts"] is None
    assert a.cache["master_info"] == {"fw": 1}      # innholdet brukes
    assert fersk.klient.get("/api/master").get_json()["sist_hort_s"] is None
    a.on_message(None, None, _Msg("nsi63/master/info", b'{"fw": 2}', False))
    assert a.cache["master_hort_ts"] is not None
