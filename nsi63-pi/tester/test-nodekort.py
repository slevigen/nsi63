#!/usr/bin/env python3
"""Benktest-skript for NSI63 nodekort (v1: 2x PCA9685 + 4x PCF8574 + 6 GPIO).

Kjøres mot anleggets MQTT-broker — enten direkte på Pi-en (127.0.0.1) eller
fra en arbeidsmaskin (--host 10.206.0.1 / benk-IP).

Hva skriptet tester:
  roster  Noden er online, ikke i sikker tilstand, og melder eksakt de seks
          I2C-brikkene på nodekortet (0x40, 0x41, 0x20, 0x21, 0x22, 0x23).
  ut      Pauser masterens bildemotor (master/lampeprove) og kjører løpelys
          over alle 32 PCA9685-utganger (J11–J14), + fade/blink per bank.
  inn     Verifiserer 0xFF i hvile på alle 4 PCF8574-banker (J21–J24) og
          kjører interaktivt jord-sveip over alle 32 innganger. Varsler
          straks hvis flere porter går lavt samtidig (mulig loddebro).
  gpio    Kjører utgangs-løpelys over J7 (G5, G6, G7, G8, G38, G39 = logisk
          port 0–5 på adresse 0x00). Hvis noden også sender in/00 (portene
          er bundet som inngang i HAL), kjøres inngangssveip på dem også.
  last    Slår på alle 32 PCA9685-utganger og overvåker ESP-NOW-pulsen for
          termisk/last-test av bucken (U1/L1) på kort nr. 1.

Eksempler:
  python3 nsi63-pi/tester/test-nodekort.py
  python3 nsi63-pi/tester/test-nodekort.py --host 10.206.0.1 aa11bb22cc33
  python3 nsi63-pi/tester/test-nodekort.py --deler ut --steg
  python3 nsi63-pi/tester/test-nodekort.py --deler inn
  python3 nsi63-pi/tester/test-nodekort.py --deler last
"""

import argparse
import json
import os
import sys
import threading
import time

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

ROT = "nsi63/"
FORVENTET_I2C = ["0x40", "0x41", "0x20", "0x21", "0x22", "0x23"]

UT_BANKER = [
    ("J11", "JP1/U7",  "0x40", range(0, 8)),
    ("J12", "JP2/U8",  "0x40", range(8, 16)),
    ("J13", "JP3/U9",  "0x41", range(0, 8)),
    ("J14", "JP4/U10", "0x41", range(8, 16)),
]
INN_BANKER = [
    ("J21", "U11", 0x20),
    ("J22", "U12", 0x21),
    ("J23", "U13", 0x22),
    ("J24", "U14", 0x23),
]
GPIO_PINNER = ["G5", "G6", "G7", "G8", "G38", "G39"]


def _lag_klient():
    if mqtt is None:
        sys.exit("Mangler paho-mqtt. Kjør skriptet på Pi-en (eller installer paho-mqtt).")
    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                           client_id=f"nodekort-test-{os.getpid()}")
    except AttributeError:  # paho-mqtt 1.x
        return mqtt.Client(client_id=f"nodekort-test-{os.getpid()}")


class Benk:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.lock = threading.Lock()
        self.roster = None
        self.roster_ev = threading.Event()
        self.lp_ack = None
        self.lp_ev = threading.Event()
        self.inputs = {}          # (mac, addr_int) -> value_int
        self.in_ev = threading.Event()
        self.in_historikk = []    # [(ts, mac, addr_int, value_int)]
        self.mq = _lag_klient()
        self.mq.on_message = self._on_msg

    def koble(self):
        try:
            self.mq.connect(self.host, self.port, keepalive=15)
        except OSError as e:
            sys.exit(f"Klarte ikke koble til MQTT på {self.host}:{self.port}: {e}")
        self.mq.subscribe(ROT + "master/nodes")
        self.mq.subscribe(ROT + "master/lampeprove/ack")
        self.mq.subscribe(ROT + "espnow/+/in/+")
        self.mq.loop_start()

    def lukk(self):
        self.mq.loop_stop()
        self.mq.disconnect()

    def _on_msg(self, _client, _ud, msg):
        topic = msg.topic
        pl = msg.payload.decode("utf-8", errors="replace").strip()
        if not pl:
            return
        if topic == ROT + "master/nodes":
            try:
                data = json.loads(pl)
            except json.JSONDecodeError:
                return
            with self.lock:
                self.roster = data
            self.roster_ev.set()
            return
        if topic == ROT + "master/lampeprove/ack":
            with self.lock:
                self.lp_ack = pl
            self.lp_ev.set()
            return
        if topic.startswith(ROT + "espnow/") and "/in/" in topic:
            deler = topic[len(ROT):].split("/")
            if len(deler) == 4 and deler[0] == "espnow" and deler[2] == "in":
                mac = deler[1].lower()
                try:
                    addr = int(deler[3], 16)
                    val = int(json.loads(pl)["value"])
                except (ValueError, KeyError, json.JSONDecodeError, TypeError):
                    return
                with self.lock:
                    self.inputs[(mac, addr)] = val
                    self.in_historikk.append((time.monotonic(), mac, addr, val))
                self.in_ev.set()

    def vent_roster(self, timeout=5.0):
        if not self.roster_ev.wait(timeout):
            sys.exit("Fikk ikke nsi63/master/nodes innen 5 s — er master på nett?")
        with self.lock:
            return dict(self.roster)

    def pause_motor(self, pause: bool, timeout=3.0) -> bool:
        self.lp_ev.clear()
        with self.lock:
            self.lp_ack = None
        onsket = "pauset" if pause else "aktiv"
        self.mq.publish(ROT + "master/lampeprove", "start" if pause else "stopp")
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if self.lp_ev.wait(0.2):
                with self.lock:
                    if self.lp_ack == onsket:
                        return True
                self.lp_ev.clear()
        return False

    def send_ut(self, mac: str, i2c: str, port: int, mode: str,
                fade: bool = False, invert: bool = False):
        pl = json.dumps({
            "i2c": i2c,
            "port": port,
            "mode": mode,
            "fade": fade,
            "invert": invert,
        })
        self.mq.publish(f"{ROT}espnow/{mac}/out", pl)

    def slukk_alle_pca(self, mac: str, invert: bool = False):
        for _, _, addr, porter in UT_BANKER:
            for p in porter:
                self.send_ut(mac, addr, p, "av", fade=False, invert=invert)
                time.sleep(0.015)

    def slukk_alle_gpio(self, mac: str, invert: bool = False):
        for p in range(len(GPIO_PINNER)):
            self.send_ut(mac, "0x00", p, "av", fade=False, invert=invert)
            time.sleep(0.015)


def velg_node(roster: dict, mac_arg: str | None) -> dict:
    noder = roster.get("nodes", [])
    if not noder:
        sys.exit("Master melder ingen noder i nsi63/master/nodes.")
    if mac_arg:
        maal = mac_arg.lower().replace(":", "").replace("-", "")
        for n in noder:
            if n.get("mac", "").lower() == maal:
                return n
        sys.exit(f"Fant ikke noden {maal}. Kjente noder: "
                 + ", ".join(n.get("mac", "?") for n in noder))

    kandidater = [n for n in noder
                  if set(FORVENTET_I2C).issubset(set(n.get("i2c", [])))]
    if len(kandidater) == 1:
        n = kandidater[0]
        print(f"Valgte automatisk nodekort {n['mac']} (eneste node med 6× I2C).")
        return n

    print("\nTilgjengelige noder:")
    for idx, n in enumerate(noder, 1):
        status = "online" if n.get("online") else "OFFLINE"
        i2c = ", ".join(n.get("i2c", [])) or "(ingen)"
        print(f"  [{idx}] {n['mac']}  {status:7s}  fw={n.get('fw')}  "
              f"bygget={n.get('bygget','?')}  i2c=[{i2c}]")
    while True:
        svar = input("Velg node (nummer eller MAC): ").strip().lower()
        if svar.isdigit() and 1 <= int(svar) <= len(noder):
            return noder[int(svar) - 1]
        svar_ren = svar.replace(":", "").replace("-", "")
        for n in noder:
            if n.get("mac", "").lower() == svar_ren:
                return n
        print("Ugyldig valg, prøv igjen.")


def test_roster(node: dict) -> bool:
    print("\n=== 1. ROSTER OG I2C-SKANN ===")
    ok = True
    mac = node["mac"]
    online = bool(node.get("online"))
    safe = bool(node.get("safe"))
    i2c = sorted(node.get("i2c", []))
    forventet = sorted(FORVENTET_I2C)
    mangler = sorted(set(forventet) - set(i2c))
    ekstra = sorted(set(i2c) - set(forventet))

    print(f"  MAC:     {mac}")
    print(f"  Status:  {'online' if online else 'OFFLINE'}  "
          f"(safe={int(safe)}, age={node.get('age')} s)")
    print(f"  FW:      v{node.get('fw')}  bygget={node.get('bygget', '?')}")
    print(f"  I2C:     {', '.join(i2c) or '(ingen)'}")

    if not online:
        print("  FEIL: Noden er ikke online!")
        ok = False
    if safe:
        print("  FEIL: Noden står i sikker tilstand (mangler puls?)")
        ok = False
    if mangler:
        print(f"  FEIL: Mangler I2C-brikker: {', '.join(mangler)}")
        ok = False
    if ekstra:
        print(f"  OBS:  Uventede I2C-adresser: {', '.join(ekstra)}")
    if ok:
        print("  OK: Alle 6 brikker funnet (2× PCA9685 + 4× PCF8574).")
    return ok


def test_utganger(benk: Benk, mac: str, steg: bool, tid: float, invert: bool):
    print("\n=== 2. UTGANGER (32× PCA9685 på J11–J14) ===")
    print(f"  Polaritet: {'invertert (felles anode rett på PCA)' if invert else 'aktiv høy (via TBD62083APG)'}")
    print("  Tips: Port 0 står til venstre på J11–J14 (pinne 8). Ctrl+C hopper videre.")

    if not benk.pause_motor(True):
        print("  ADVARSEL: Fikk ikke lampeprove-ack fra master (fortsetter likevel).")
    try:
        benk.slukk_alle_pca(mac, invert=invert)
        time.sleep(0.15)
        for kontakt, kort, addr, porter in UT_BANKER:
            print(f"\n  -- {kontakt} ({kort}, {addr} port {porter.start}–{porter.stop - 1}) --")
            if steg:
                input(f"  Klar for {kontakt}? Trykk Enter ...")
            for p in porter:
                lokal = p - porter.start
                print(f"    {kontakt} kanal {lokal}  ({addr} port {p:2d})  PÅ",
                      end="", flush=True)
                benk.send_ut(mac, addr, p, "pa", fade=False, invert=invert)
                if steg:
                    input("  [Enter]")
                else:
                    time.sleep(tid)
                    print()
                benk.send_ut(mac, addr, p, "av", fade=False, invert=invert)
                time.sleep(0.03)

        print("\n  -- Fade + blink-prøve på kanal 0 i hver bank (2 s) --")
        for kontakt, _, addr, porter in UT_BANKER:
            benk.send_ut(mac, addr, porter.start, "blink", fade=True, invert=invert)
            time.sleep(0.02)
        time.sleep(2.2)
    except KeyboardInterrupt:
        print("\n  (Avbrutt — slukker utganger)")
    finally:
        benk.slukk_alle_pca(mac, invert=invert)
        benk.pause_motor(False)
    print("  OK: Utgangstest ferdig og masterens bildemotor gjenopptatt.")


def _formater_inngang(banker, tilstand, aktiv_naa):
    linjer = []
    for navn, brikke, addr in banker:
        celler = []
        for p in range(8):
            k = (addr, p)
            if k in aktiv_naa:
                celler.append(f"\033[1;33m{p}:▼\033[0m")
            elif tilstand.get(k) == "ok":
                celler.append(f"\033[1;32m{p}:✓\033[0m")
            elif tilstand.get(k) == "lav":
                celler.append(f"\033[1;33m{p}:·\033[0m")
            else:
                celler.append(f"{p}:.")
        linjer.append(f"  {navn} ({brikke}, 0x{addr:02x}):  " + " ".join(celler))
    return "\n".join(linjer)


def test_innganger(benk: Benk, mac: str) -> bool:
    print("\n=== 3. INNGANGER (32× PCF8574 på J21–J24) ===")
    time.sleep(0.4)  # la eventuelle retained in-meldinger lande

    hvile_ok = True
    for kontakt, brikke, addr in INN_BANKER:
        with benk.lock:
            val = benk.inputs.get((mac, addr))
        if val is None:
            print(f"  OBS:  Ingen melding sett ennå for {kontakt} (0x{addr:02x}) — "
                  f"berør en port for å vekke den hvis den ikke er retained.")
        elif val != 0xFF:
            lave = [p for p in range(8) if not ((val >> p) & 1)]
            print(f"  FEIL: {kontakt} ({brikke}, 0x{addr:02x}) er 0x{val:02X} i hvile "
                  f"(forventet 0xFF) — port {lave} henger LAVT!")
            hvile_ok = False
        else:
            print(f"  Hvile OK: {kontakt} ({brikke}, 0x{addr:02x}) = 0xFF")

    print("\n  Stryk en GND-ledning (fra J25–J28) over alle 32 porter på J21–J24.")
    print("  En port godkjennes når den har gått 1 → 0 → 1. Trykk Ctrl+C for å avslutte tidlig.\n")

    tilstand = {}   # (addr, port) -> "lav" | "ok"
    sist_val = {}
    for _, _, addr in INN_BANKER:
        with benk.lock:
            sist_val[addr] = benk.inputs.get((mac, addr), 0xFF)

    print(_formater_inngang(INN_BANKER, tilstand, set()))
    print()

    nabo_advarsler = 0
    try:
        while sum(1 for v in tilstand.values() if v == "ok") < 32:
            benk.in_ev.wait(0.25)
            benk.in_ev.clear()
            endret = False
            aktiv_naa = set()
            for kontakt, _, addr in INN_BANKER:
                with benk.lock:
                    val = benk.inputs.get((mac, addr), 0xFF)
                gammel = sist_val.get(addr, 0xFF)
                lave = [p for p in range(8) if not ((val >> p) & 1)]
                for p in lave:
                    aktiv_naa.add((addr, p))
                if val != gammel:
                    endret = True
                    nye_lave = [p for p in range(8)
                                if ((gammel >> p) & 1) and not ((val >> p) & 1)]
                    if len(nye_lave) >= 2:
                        nabo_advarsler += 1
                        print(f"  ADVARSEL: {kontakt} (0x{addr:02x}) port {nye_lave} "
                              f"gikk lavt SAMTIDIG (mulig loddebro?)")
                    for p in range(8):
                        er_lav = not ((val >> p) & 1)
                        k = (addr, p)
                        if er_lav and tilstand.get(k) != "ok":
                            tilstand[k] = "lav"
                        elif not er_lav and tilstand.get(k) == "lav":
                            tilstand[k] = "ok"
                    sist_val[addr] = val
            if endret:
                ferdig = sum(1 for v in tilstand.values() if v == "ok")
                print(f"\n  Status ({ferdig}/32 godkjent):")
                print(_formater_inngang(INN_BANKER, tilstand, aktiv_naa))
    except KeyboardInterrupt:
        print("\n  (Inngangstest avsluttet manuelt)")

    ferdig = sum(1 for v in tilstand.values() if v == "ok")
    if ferdig == 32 and hvile_ok and nabo_advarsler == 0:
        print("\n  OK: Alle 32 innganger bestått uten anmerkning.")
        return True
    mangler = []
    for kontakt, _, addr in INN_BANKER:
        m = [p for p in range(8) if tilstand.get((addr, p)) != "ok"]
        if m:
            mangler.append(f"{kontakt}:{m}")
    if mangler:
        print(f"\n  UFERDIG ({ferdig}/32): mangler {', '.join(mangler)}")
    if nabo_advarsler:
        print(f"  OBS: {nabo_advarsler} tilfelle(r) av flere porter lavt samtidig.")
    return False


def test_gpio(benk: Benk, mac: str, steg: bool, tid: float):
    print("\n=== 4. GPIO (J7: G5, G6, G7, G8, G38, G39 — adresse 0x00) ===")
    print("  Kjører 3,3 V utgangspuls på hver pinne (verifiserer R12–R17 og U3/U4).")
    print("  Mål mot GND på J8 med multimeter/LED. Ctrl+C hopper videre.")

    if not benk.pause_motor(True):
        print("  ADVARSEL: Fikk ikke lampeprove-ack fra master.")
    try:
        benk.slukk_alle_gpio(mac, invert=False)
        time.sleep(0.1)
        for p, navn in enumerate(GPIO_PINNER):
            print(f"    J7 port {p} ({navn:3s})  3,3 V PÅ", end="", flush=True)
            benk.send_ut(mac, "0x00", p, "pa", fade=False, invert=False)
            if steg:
                input("  [Enter]")
            else:
                time.sleep(max(tid, 0.5))
                print()
            benk.send_ut(mac, "0x00", p, "av", fade=False, invert=False)
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\n  (Avbrutt — slukker GPIO)")
    finally:
        benk.slukk_alle_gpio(mac, invert=False)
        benk.pause_motor(False)

    with benk.lock:
        gpio_in = benk.inputs.get((mac, 0x00))
    if gpio_in is not None:
        print(f"  GPIO-inngangsbyte (in/00) observert: 0x{gpio_in:02X} "
              f"(portene er bundet som innganger i HAL).")
    else:
        print("  OK: Alle 6 GPIO-utganger testet. (For inngangstest på J7, "
              "bind midlertidige «inngang»-objekter på 0x00 i HAL-UI.)")


def test_last(benk: Benk, mac: str, invert: bool):
    print("\n=== 5. LAST- OG VARMETEST (alle 32 utganger PÅ) ===")
    print("  Mål 5 V og 3,3 V under last, kjenn på U1, L1, U2, Q1, D3.")
    print("  Trykk Ctrl+C når du er ferdig (master slår uansett av pause etter 10 min).\n")
    if not benk.pause_motor(True):
        print("  ADVARSEL: Fikk ikke lampeprove-ack fra master.")
    try:
        for _, _, addr, porter in UT_BANKER:
            for p in porter:
                benk.send_ut(mac, addr, p, "pa", fade=False, invert=invert)
                time.sleep(0.015)
        start = time.monotonic()
        while True:
            time.sleep(5.0)
            sek = int(time.monotonic() - start)
            with benk.lock:
                r = benk.roster or {}
            n = next((x for x in r.get("nodes", []) if x.get("mac") == mac), {})
            print(f"  t={sek:3d} s | pulse={r.get('pulse')} | "
                  f"online={n.get('online')} safe={n.get('safe')} age={n.get('age')} s")
    except KeyboardInterrupt:
        print("\n  (Stopper lasttest og slukker alle 32 utganger)")
    finally:
        benk.slukk_alle_pca(mac, invert=invert)
        benk.pause_motor(False)
    print("  OK: Lasttest avsluttet.")


def main():
    ap = argparse.ArgumentParser(description="Benktest av NSI63 nodekort over MQTT")
    ap.add_argument("mac", nargs="?", help="Nodens MAC (12 hex-tegn, valgfri)")
    ap.add_argument("--host", default=os.environ.get("NSI63_MQTT_HOST", "127.0.0.1"),
                    help="MQTT-broker (standard: $NSI63_MQTT_HOST eller 127.0.0.1)")
    ap.add_argument("--port", type=int, default=1883, help="MQTT-port (1883)")
    ap.add_argument("--deler", default="roster,ut,inn,gpio",
                    help="Kommaseparert: roster,ut,inn,gpio,last (standard: roster,ut,inn,gpio)")
    ap.add_argument("--steg", action="store_true",
                    help="Vent på Enter for hver utgang i stedet for automatisk løpelys")
    ap.add_argument("--tid", type=float, default=0.35,
                    help="Sekunder per kanal i løpelys (standard: 0.35)")
    ap.add_argument("--invert", action="store_true",
                    help="Invertert PCA-utgang (kun for test UTEN TBD62083APG)")
    args = ap.parse_args()

    deler = [d.strip().lower() for d in args.deler.split(",") if d.strip()]
    gyldige = {"roster", "ut", "inn", "gpio", "last"}
    ukjente = set(deler) - gyldige
    if ukjente:
        sys.exit(f"Ukjent del: {', '.join(sorted(ukjente))} (velg blant {sorted(gyldige)})")

    benk = Benk(args.host, args.port)
    benk.koble()
    try:
        roster = benk.vent_roster()
        node = velg_node(roster, args.mac)
        mac = node["mac"].lower()

        if "roster" in deler:
            test_roster(node)
        if "ut" in deler:
            test_utganger(benk, mac, steg=args.steg, tid=args.tid, invert=args.invert)
        if "inn" in deler:
            test_innganger(benk, mac)
        if "gpio" in deler:
            test_gpio(benk, mac, steg=args.steg, tid=args.tid)
        if "last" in deler:
            test_last(benk, mac, invert=args.invert)
    finally:
        benk.lukk()


if __name__ == "__main__":
    main()
