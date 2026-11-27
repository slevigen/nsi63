"""Masterens gjenoppkobling etter et wifi-brudd.

Pi-en kaster masteren ut av wifi (hostapd_cli deauthenticate — det
samme stasjonsvaktbikkja gjør), og masteren skal svare på kommandoer
igjen innen 15 s. Før rettingen var den borte i 120 s hver gang:
utkastingen har årsak 2 (AUTH_EXPIRE), og ved akkurat den lar Arduino-
kjernen (2.0.17) WiFi.status() stå som WL_CONNECTED. Masteren trodde
forbindelsen var oppe og prøvde aldri å koble til igjen. Nå følger den
wifi-hendelsene selv (wifiFalt i master.cpp).

Trenger SSH til Pi-en med passordfri sudo:

    NSI63_SSH=bruker@vert pytest -v test_wifi.py

Uten NSI63_SSH hoppes testen over.
"""
import json
import os
import subprocess

import pytest

SSH = os.environ.get("NSI63_SSH", "")
TILBAKE_S = 15


def _master_mac(anlegg):
    roster = json.loads(anlegg.tilstand.get("master/nodes") or "{}")
    mac = roster.get("master") or ""
    if len(mac) != 12:
        pytest.skip("fant ikke masterens MAC i nsi63/master/nodes")
    return ":".join(mac[i:i + 2] for i in range(0, 12, 2))


def _krev_hostapd_cli():
    """Hopp over pent hvis Pi-en ikke kan nås over SSH uten passord,
    eller ikke har hostapd_cli (f.eks. et anlegg uten eget AP)."""
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes",
                            "-o", "ConnectTimeout=5", SSH,
                            # via sudo: hostapd_cli ligger i /usr/sbin,
                            # som et ikke-interaktivt SSH-skall ikke har
                            # i PATH — men sudo har (secure_path)
                            "sudo -n sh -c 'command -v hostapd_cli'"],
                           capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as e:
        pytest.skip(f"får ikke SSH til {SSH}: {e}")
    if r.returncode != 0:
        pytest.skip(f"hostapd_cli/sudo ikke tilgjengelig på {SSH}: "
                    f"{(r.stderr or r.stdout).strip()[:120]}")


@pytest.mark.skipif(not SSH, reason="sett NSI63_SSH=bruker@vert for wifi-testen")
def test_master_tilbake_etter_deauth(anlegg, topo):
    _krev_hostapd_cli()
    mac = _master_mac(anlegg)
    tv = topo.togveier[0]["id"]
    r = subprocess.run(["ssh", SSH, f"sudo hostapd_cli deauthenticate {mac}"],
                       capture_output=True, text=True, timeout=20)
    assert r.returncode == 0 and "OK" in r.stdout, r.stdout + r.stderr
    t0 = anlegg.naa()
    # Kravet er at masteren SVARER igjen — ikke at den kobler til MQTT på
    # nytt: kommer wifi tilbake raskt nok, overlever TCP-forbindelsen, og
    # da sendes det heller ingen ny «online». «hjelpeutlos» på en ledig
    # togvei får alltid et svar («togveien er alt ledig») uten å endre noe.
    while anlegg.naa() - t0 < TILBAKE_S:
        t1 = anlegg.naa()
        anlegg.pub(f"togvei/{tv}/set", "hjelpeutlos")
        try:
            anlegg.vent_ny(f"togvei/{tv}/info", "ledig", t1, timeout=1)
        except pytest.fail.Exception:   # ikke svar ennå — prøv igjen
            continue
        print(f"\nmasteren svarte {anlegg.naa() - t0:.1f} s etter utkastingen")
        return
    pytest.fail(f"masteren svarte ikke innen {TILBAKE_S} s etter utkastingen")
