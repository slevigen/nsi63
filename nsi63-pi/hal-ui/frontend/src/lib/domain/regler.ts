import type {
  Binding,
  HalFunction,
  MasterInfo,
  NodeAliasMap,
  ObjektType,
  SignalKlasse,
  SignalTypeDef,
  TidslaasDef,
  Togvei,
} from "../types";

export const MAX_FUNKSJONER = 96;
export const MAX_BINDINGER = 16;
export const MAX_SKIFT_VEKSLER = 4;
export const MAX_TOGVEIER = 32;
export const MAX_TV_VEKSLER = 6;
export const MAX_TV_FELT = 8;
export const MAX_TV_LAASER = 3;
export const MAX_LITRA = 23;
export const MAX_LITRA_UI = 6;
export const MAX_ORDREPUNKTER = 40;
export const WARN_ORDREPUNKTER = 34;
export const MASTER_MQTT_BUFFER = 24576;

export const I2C_ALLE = [
  "0x40",
  "0x41",
  "0x42",
  "0x43",
  "0x20",
  "0x21",
  "0x22",
  "0x23",
] as const;

export const KB_BRIKKER = [...I2C_ALLE, "gpio"] as const;
export const PCA_ADRESSER = ["0x40", "0x41", "0x42", "0x43"] as const;
export const GPIO_PINNER = ["G5", "G6", "G7", "G8", "G38", "G39"] as const;

export interface GruppeDef {
  navn: string;
  typer: string[];
  venstre: string;
  hoyre: string;
}

export const GRUPPER: GruppeDef[] = [
  {
    navn: "Signaler",
    typer: [
      "hovedsignal3",
      "hovedsignal2",
      "forsignal2",
      "skiftesignal2",
      "skiftesignal1",
      "dvergsignal3",
    ],
    venstre: "ute på anlegget",
    hoyre: "på stillerapparatet",
  },
  {
    navn: "Veksler",
    typer: ["sporveksel", "manuellveksel"],
    venstre: "normal",
    hoyre: "avvik",
  },
  {
    navn: "Sporavsnitt",
    typer: ["sporfelt"],
    venstre: "",
    hoyre: "",
  },
  {
    navn: "Trykknapper og brytere",
    typer: ["trykknapp", "bryter"],
    venstre: "inngangen",
    hoyre: "kontrollampe",
  },
  {
    navn: "Sporsperrer",
    typer: ["sporsperre"],
    venstre: "pålagt",
    hoyre: "avlagt",
  },
  {
    navn: "Låser",
    typer: ["samlelaas", "rigel"],
    venstre: "",
    hoyre: "",
  },
  {
    navn: "Annet",
    typer: ["utgang", "inngang", "klokke", "amperemeter"],
    venstre: "",
    hoyre: "",
  },
];

// Fallback kun for Node/Vitest når /ui/signalfarger.js ikke er lastet i window.
// I nettleseren er window.SIGNAL_LAMPEFARGE fra /ui/signalfarger.js fasiten.
const FALLBACK_LAMPEFARGE: Record<string, string[]> = {
  hovedsignal3: ["#1fe04e", "#ff2a1e", "#1fe04e"],
  hovedsignal2: ["#1fe04e", "#ff2a1e"],
  forsignal2: ["#ffb400", "#1fe04e"],
  skiftesignal2: ["#ffb400", "#ffb400"],
  skiftesignal1: ["#ffb400"],
  dvergsignal3: ["#d7d9dc", "#d7d9dc", "#d7d9dc"],
};

function lampeFargeKart(): Record<string, string[]> {
  if (typeof globalThis !== "undefined") {
    const w = globalThis as unknown as {
      SIGNAL_LAMPEFARGE?: Record<string, string[]>;
    };
    if (w.SIGNAL_LAMPEFARGE) return w.SIGNAL_LAMPEFARGE;
  }
  return FALLBACK_LAMPEFARGE;
}

/**
 * Fargen på én kanal for lyssignaler. Gjelder KUN «anlegg» og «panel»
 * (ikke stiller eller middelkontrollampe på skiftesignaler).
 */
export function signalLampeFarge(
  type: string,
  kanal: number,
  sted = "anlegg"
): string | null {
  if (sted !== "anlegg" && sted !== "panel") return null;
  const f = lampeFargeKart()[type];
  return f && f[kanal] ? f[kanal] : null;
}

export function sigKlasse(
  t: string | undefined,
  signaltyper?: Record<string, SignalTypeDef>
): SignalKlasse | null {
  if (!t) return null;
  const st = signaltyper?.[t];
  if (st?.klasse) return st.klasse;
  for (const k of [
    "forsignal",
    "skiftesignal",
    "dvergsignal",
    "hovedsignal",
  ] as const) {
    if (t.startsWith(k)) return k;
  }
  return null;
}

export const erHoved = (
  t: string,
  st?: Record<string, SignalTypeDef>
): boolean => sigKlasse(t, st) === "hovedsignal";

export const isSkift = (
  t: string,
  st?: Record<string, SignalTypeDef>
): boolean => sigKlasse(t, st) === "skiftesignal";

export const isDverg = (
  t: string,
  st?: Record<string, SignalTypeDef>
): boolean => sigKlasse(t, st) === "dvergsignal";

export const isSignal = (
  t: string,
  st?: Record<string, SignalTypeDef>
): boolean => (st ? t in st : sigKlasse(t) !== null);

export const isVeksel = (t: string): boolean => t === "sporveksel";
export const isManuell = (t: string): boolean => t === "manuellveksel";
export const isNoenVeksel = (t: string): boolean =>
  isVeksel(t) || isManuell(t);
export const isSperre = (t: string): boolean => t === "sporsperre";
export const isLaas = (t: string): boolean =>
  t === "samlelaas" || t === "rigel";

export function gruppeIdx(type: string): number {
  const i = GRUPPER.findIndex((g) => g.typer.includes(type));
  return i < 0 ? GRUPPER.length - 1 : i;
}

export function litraUgyldig(s: string): string | null {
  for (const c of "/+#") {
    if (s.includes(c)) return c;
  }
  return null;
}

/**
 * Sant hvis et hovedsignal mangler gyldig lagret `rolle`.
 * - hovedsignal3 krever "innkjor" | "utkjor" | "indre"
 * - hovedsignal2 krever "utkjor"
 */
export function hovedsignalManglerRolle(
  f: Pick<HalFunction, "type" | "rolle">,
  st?: Record<string, SignalTypeDef>
): boolean {
  if (!erHoved(f.type, st)) return false;
  if (f.type === "hovedsignal2") return f.rolle !== "utkjor";
  return f.rolle !== "innkjor" && f.rolle !== "utkjor" && f.rolle !== "indre";
}

export function litraNs(
  t: string,
  signaltyper?: Record<string, SignalTypeDef>
): string {
  const k = sigKlasse(t, signaltyper);
  if (k) return k;
  if (t === "sporveksel" || t === "manuellveksel") return "sporveksel";
  if (t === "sporfelt") return "sporfelt";
  if (t === "trykknapp" || t === "bryter") return "knapp";
  if (t === "samlelaas" || t === "rigel" || t === "sporsperre") return t;
  return "annet";
}

export function i2cNorm(v: string | number | null | undefined): string {
  if (typeof v === "number" && Number.isFinite(v)) {
    const s = `0x${Math.trunc(v).toString(16).padStart(2, "0")}`;
    return s === "0x00" ? "gpio" : s;
  }
  const s = String(v ?? "")
    .trim()
    .toLowerCase();
  if (s === "gpio" || s === "0x0" || s === "0x00") return "gpio";
  return s;
}

export function i2cLabel(a: string): string {
  const n = i2cNorm(a);
  if (n === "gpio") return "GPIO";
  return n + (n.startsWith("0x4") ? " PCA" : " PCF");
}

export function brikkeKapasitet(a: string | number): number | null {
  const n = i2cNorm(a);
  if (n === "gpio") return 6;
  if (n.startsWith("0x4")) return 16;
  if (n.startsWith("0x2")) return 8;
  return null;
}

export function brikkeNavn(a: string): string {
  const n = i2cNorm(a);
  if (n === "gpio") return "GPIO på noden · 6 porter";
  return n.startsWith("0x4")
    ? `${n} PCA9685 · 16 utganger`
    : `${n} PCF8574 · 8 innganger`;
}

export function erInngang(sted: string): boolean {
  return (
    sted.startsWith("sensor") ||
    sted.startsWith("stiller") ||
    sted.startsWith("lokal-") ||
    sted === "kvittering"
  );
}

export function bindErInngang(t: string, sted: string): boolean {
  if (
    sted === "anlegg" &&
    (t === "trykknapp" || t === "bryter" || t === "inngang")
  ) {
    return true;
  }
  return erInngang(sted);
}

export function defaultI2c(t: string, sted: string): string {
  if (bindErInngang(t, sted)) return "0x20";
  if (sted.startsWith("ut-")) return "0x41";
  return "0x40";
}

export interface BindingSlotRad {
  navn: string;
  par?: string;
  a: string;
  b?: string;
}

export function bindingsrader(
  t: string,
  rolle = "",
  st?: Record<string, SignalTypeDef>
): BindingSlotRad[] {
  if (isSkift(t, st)) {
    return [
      { navn: "signallamper", par: "ute · apparat", a: "anlegg", b: "panel" },
      { navn: "stiller", a: "stiller" },
      { navn: "middelkontrollampe", a: "middelkontrollampe" },
    ];
  }
  if (isSignal(t, st)) {
    return [
      { navn: "signallamper", par: "ute · apparat", a: "anlegg", b: "panel" },
    ];
  }
  if (isVeksel(t)) {
    return [
      { navn: "drivutgang", par: "normal · avvik", a: "ut-normal", b: "ut-avvik" },
      {
        navn: "stillingssensor",
        par: "normal · avvik",
        a: "sensor-normal",
        b: "sensor-avvik",
      },
      {
        navn: "kontrollampe",
        par: "normal · avvik",
        a: "panel-normal",
        b: "panel-avvik",
      },
      {
        navn: "apparatstiller",
        par: "normal · avvik",
        a: "stiller-normal",
        b: "stiller-avvik",
      },
      {
        navn: "lokalbetjening",
        par: "normal · avvik",
        a: "lokal-normal",
        b: "lokal-avvik",
      },
      { navn: "lokalstillerlampe", a: "lokalstillerlampe" },
    ];
  }
  if (isManuell(t)) {
    return [
      { navn: "drivutgang", par: "normal · avvik", a: "ut-normal", b: "ut-avvik" },
      {
        navn: "stillingssensor",
        par: "normal · avvik",
        a: "sensor-normal",
        b: "sensor-avvik",
      },
      {
        navn: "kontrollampe",
        par: "normal · avvik",
        a: "panel-normal",
        b: "panel-avvik",
      },
      {
        navn: "betjening",
        par: "normal · avvik",
        a: "lokal-normal",
        b: "lokal-avvik",
      },
    ];
  }
  if (isSperre(t)) {
    return [
      {
        navn: "drivutgang",
        par: "pålagt · avlagt",
        a: "ut-paalagt",
        b: "ut-avlagt",
      },
      { navn: "kontroll pålagt", a: "sensor-paalagt" },
      {
        navn: "betjening",
        par: "pålagt · avlagt",
        a: "lokal-paalagt",
        b: "lokal-avlagt",
      },
    ];
  }
  if (t === "sporfelt") {
    if (rolle === "varselfelt") {
      return [
        {
          navn: "sporfelt",
          par: "ytre · indre",
          a: "sensor-ytre",
          b: "sensor-indre",
        },
        { navn: "kvitteringsknapp", a: "kvittering" },
      ];
    }
    const r: BindingSlotRad[] = [
      { navn: "sporfelt", par: "ute · på apparatet", a: "sensor", b: "panel" },
    ];
    if (rolle === "togspor" || rolle === "linjefelt") {
      r.push({
        navn: "togveistiller",
        par: "venstre · høyre",
        a: "stiller-v",
        b: "stiller-h",
      });
    }
    if (rolle === "linjefelt") {
      r.push({ navn: "togveislampe", a: "togveislampe" });
    }
    return r;
  }
  if (t === "samlelaas") {
    return [
      {
        navn: "frigittlampe",
        par: "ved låsen · apparat",
        a: "anlegg",
        b: "panel",
      },
      { navn: "frigivningsstiller", a: "stiller" },
      { navn: "kvitteringsknapp", a: "kvittering" },
    ];
  }
  if (t === "rigel") {
    return [
      {
        navn: "frigittlampe",
        par: "ved objektene · apparat",
        a: "anlegg",
        b: "panel",
      },
      { navn: "frigivningsstiller", a: "stiller" },
    ];
  }
  if (t === "trykknapp" || t === "bryter") {
    return [{ navn: t, par: "inngang · lampe", a: "anlegg", b: "panel" }];
  }
  if (t === "klokke") return [{ navn: "klokke", a: "anlegg" }];
  if (t === "amperemeter") return [{ navn: "instrument", a: "anlegg" }];
  if (t === "inngang") return [{ navn: "reservert inngang", a: "anlegg" }];
  return [{ navn: "reservert utgang", a: "anlegg" }];
}

export function portSymbol(sted: string, type: string): string {
  if (sted === "anlegg" && lampeFargeKart()[type]) return "●";
  if (sted === "anlegg" && (type === "samlelaas" || type === "rigel"))
    return "○";
  if (
    sted.startsWith("panel") ||
    sted === "lokalstillerlampe" ||
    sted === "togveislampe" ||
    sted === "middelkontrollampe"
  ) {
    return "○";
  }
  if (sted.startsWith("ut-")) return "⇄";
  if (sted.startsWith("sensor")) return "◎";
  if (
    sted.startsWith("stiller") ||
    sted.startsWith("lokal-") ||
    sted === "kvittering"
  ) {
    return "▣";
  }
  if (type === "klokke") return "♪";
  if (type === "amperemeter") return "△";
  if (type === "trykknapp" || type === "bryter") return "▣";
  if (type === "inngang") return "◎";
  return "▪";
}

/**
 * Kallenavn for en MAC. Kontrakt fra 87ddb69: når kallenavn fjernes blir
 * en evt. driver-liste liggende under hal["noder"][mac] = {mac, driver}.
 * En nøkkel som er lik MAC-en selv skal ALDRI returneres som kallenavn.
 */
export function aliasFor(mac: string, noder: NodeAliasMap): string | null {
  const m = (mac || "").toLowerCase();
  for (const [alias, v] of Object.entries(noder || {})) {
    if (!v || !v.mac) continue;
    if (alias.toLowerCase() === v.mac.toLowerCase()) continue;
    if (v.mac.toLowerCase() === m) return alias;
  }
  return null;
}

export function macForNode(nodeRef: string, noder: NodeAliasMap): string {
  const nd = (nodeRef || "").trim();
  const entry = noder?.[nd];
  return (entry?.mac || nd).toLowerCase();
}

export function driverBrikkerForMac(mac: string, noder: NodeAliasMap): string[] {
  const m = (mac || "").toLowerCase();
  for (const v of Object.values(noder || {})) {
    if (v?.mac?.toLowerCase() === m && Array.isArray(v.driver)) {
      return v.driver.map((a) => i2cNorm(a));
    }
  }
  return [];
}

// ---------- Portkart, kollisjoner & ordrepunkter ----------

export interface PortBruk {
  litra: string;
  type: string;
  sted: string;
  del: number;
  av: number;
  inn: boolean;
  objIdx: number;
}

export interface PortKartResult {
  /** mac -> i2cNorm -> port -> PortBruk[] */
  kart: Record<string, Record<string, Record<number, PortBruk[]>>>;
  /** mac -> antall ordrepunkter */
  ordrer: Record<string, number>;
  /** Nøkler "mac|i2cNorm|port" som har konflikt eller er utenfor brikken */
  feilNokler: Set<string>;
  /** Lesbare feilmeldinger (speiler _port_konflikter i app.py) */
  feil: string[];
}

export function portNokkel(mac: string, i2c: string | number, port: number): string {
  return `${mac.toLowerCase()}|${i2cNorm(i2c)}|${port}`;
}

/**
 * Nøkkel for sanntids inngangsbyte fra app.py (`cache["inputs"]`).
 * Serveren nøkler `espnow/<mac>/in/<hex>` som `<mac>/0xNN`, der GPIO er `0x00`.
 */
export function inputNokkel(mac: string, i2c: string | number): string {
  const n = i2cNorm(i2c);
  return `${mac.toLowerCase()}/${n === "gpio" ? "0x00" : n}`;
}

export function beregnPortKart(
  functions: HalFunction[],
  signaltyper: Record<string, SignalTypeDef>,
  noder: NodeAliasMap
): PortKartResult {
  const kart: Record<string, Record<string, Record<number, PortBruk[]>>> = {};
  const ordrer: Record<string, number> = {};
  const feilNokler = new Set<string>();
  const feil: string[] = [];

  for (let objIdx = 0; objIdx < functions.length; objIdx++) {
    const f = functions[objIdx];
    const st = signaltyper?.[f.type];
    for (const b of f.bindinger || []) {
      const node = (b.node || "").trim();
      if (!node) continue;
      const mac = macForNode(node, noder);
      const sted = b.sted || "";
      const n =
        st && (sted === "anlegg" || sted === "panel") ? st.lamper || 1 : 1;
      const i2c = i2cNorm(b.i2c);
      const inn = bindErInngang(f.type, sted);

      if (!inn) {
        ordrer[mac] = (ordrer[mac] || 0) + n;
      } else if (i2c === "gpio") {
        ordrer[mac] = (ordrer[mac] || 0) + 1;
      }

      const kap = brikkeKapasitet(i2c);
      const port0 = Number.isFinite(Number(b.port))
        ? Math.trunc(Number(b.port))
        : 0;
      if (port0 < 0) {
        feil.push(`${f.id || "(uten litra)"} (${sted}): negativ port ${port0}`);
        feilNokler.add(portNokkel(mac, i2c, port0));
      } else if (kap !== null && port0 + n > kap) {
        const spenn = n > 1 ? `–${port0 + n - 1} (${n} lamper)` : "";
        feil.push(
          `${f.id || "(uten litra)"} (${sted}): port ${port0}${spenn} går utenfor ${b.i2c} (porter 0–${kap - 1})`
        );
        for (let k = 0; k < n; k++) {
          feilNokler.add(portNokkel(mac, i2c, port0 + k));
        }
      }

      for (let k = 0; k < n; k++) {
        const p = port0 + k;
        kart[mac] ??= {};
        kart[mac][i2c] ??= {};
        kart[mac][i2c][p] ??= [];
        kart[mac][i2c][p].push({
          litra: f.id,
          type: f.type,
          sted,
          del: k,
          av: n,
          inn,
          objIdx,
        });
      }
    }
  }

  for (const [mac, brikker] of Object.entries(kart)) {
    for (const [i2c, porter] of Object.entries(brikker)) {
      for (const [pStr, brukere] of Object.entries(porter)) {
        if (brukere.length < 2) continue;
        const p = Number(pStr);
        const inn = brukere.filter((x) => x.inn);
        const ut = brukere.filter((x) => !x.inn);
        const hvem = brukere
          .map((x) => `${x.litra || "?"} (${x.sted})`)
          .join(" og ");
        const stedTxt = `${i2c} port ${p}`;
        if (inn.length && ut.length) {
          feilNokler.add(portNokkel(mac, i2c, p));
          feil.push(`${hvem} deler ${stedTxt} som både inngang og utgang`);
        } else if (ut.length >= 2) {
          feilNokler.add(portNokkel(mac, i2c, p));
          feil.push(`${hvem} deler utgangen ${stedTxt}`);
        }
      }
    }
  }

  for (const [mac, antall] of Object.entries(ordrer)) {
    if (antall > MAX_ORDREPUNKTER) {
      const navn = aliasFor(mac, noder) || mac;
      feil.push(
        `${navn} har ${antall} ordrepunkter (utganger + GPIO-innganger) — maks ${MAX_ORDREPUNKTER} per node`
      );
    }
  }

  return { kart, ordrer, feilNokler, feil };
}

// ---------- Buffer-anslag ----------

export function masterBufferGrense(info: MasterInfo | null | undefined): number {
  const buf = Number(info?.buf || 0);
  const raw = buf > 0 ? Math.min(MASTER_MQTT_BUFFER, buf) : MASTER_MQTT_BUFFER;
  return Math.max(0, raw - 512);
}

export function estimertKonfigBytes(data: unknown): number {
  const json = JSON.stringify(data);
  return new TextEncoder().encode(json).length;
}

// ---------- Type-/rollebytte-opprydding (U2 / Seksjon 4) ----------

export function rensObjektVedTypeBytte(
  fn: HalFunction,
  nyType: ObjektType,
  st?: Record<string, SignalTypeDef>
): HalFunction {
  const erVekselBytte = isNoenVeksel(fn.type) && isNoenVeksel(nyType);
  const erHovedBytte = erHoved(fn.type, st) && erHoved(nyType, st);
  const neste: HalFunction = {
    id: fn.id,
    type: nyType,
    bindinger: [],
  };
  if (fn.gammel_id) neste.gammel_id = fn.gammel_id;

  // Hovedsignaler MÅ alltid ha en lagret rolle (inspektøren viser «utkjør»
  // som standard, og serveren avviser togveier hvis rolle mangler).
  if (nyType === "hovedsignal2") {
    neste.rolle = "utkjor";
  } else if (erHoved(nyType, st)) {
    neste.rolle =
      fn.rolle === "innkjor" || fn.rolle === "utkjor" || fn.rolle === "indre"
        ? fn.rolle
        : "utkjor";
  }

  if (erHovedBytte) {
    const lovlige = new Set<string>();
    for (const r of bindingsrader(nyType, neste.rolle || "", st)) {
      lovlige.add(r.a);
      if (r.b) lovlige.add(r.b);
    }
    neste.bindinger = (fn.bindinger || []).filter((b) => lovlige.has(b.sted));
    if (fn.linjefelt) neste.linjefelt = fn.linjefelt;
  }

  // Veksling mellom sentralstilt og manuell veksel bevarer både
  // kompatible bindinger og sporplan-tegnefelter
  if (erVekselBytte) {
    const lovlige = new Set<string>();
    for (const r of bindingsrader(nyType, "", st)) {
      lovlige.add(r.a);
      if (r.b) lovlige.add(r.b);
    }
    neste.bindinger = (fn.bindinger || []).filter((b) => lovlige.has(b.sted));
    if (nyType === "sporveksel" && fn.side) neste.side = fn.side;
    if (fn.spiss) neste.spiss = fn.spiss;
    if (fn.pluss_til) neste.pluss_til = fn.pluss_til;
    if (fn.minus_til) neste.minus_til = fn.minus_til;
    if (fn.spiss_til) neste.spiss_til = fn.spiss_til;
    if (fn.avvik_ben) neste.avvik_ben = fn.avvik_ben;
  }
  return neste;
}

export function rensSporfeltVedRolleBytte(
  fn: HalFunction,
  velgerVerdi: string
): HalFunction {
  const erBlokk = velgerVerdi === "blokksporfelt";
  const rolle = erBlokk ? "linjefelt" : velgerVerdi;
  const lovlige = new Set<string>();
  for (const r of bindingsrader("sporfelt", rolle)) {
    lovlige.add(r.a);
    if (r.b) lovlige.add(r.b);
  }
  const neste: HalFunction = {
    ...fn,
    rolle,
    bindinger: (fn.bindinger || []).filter((b) => lovlige.has(b.sted)),
  };
  if (rolle === "linjefelt") {
    if (erBlokk) delete neste.linjeblokk;
    else neste.linjeblokk = false;
    delete neste.linjefelt;
  } else {
    delete neste.linjeblokk;
    delete neste.side;
    if (rolle !== "varselfelt") delete neste.linjefelt;
  }
  return neste;
}

// ---------- Forrigling, togveier & fiendtlighet ----------

export function feltRolle(id: string | undefined, functions: HalFunction[]): string {
  if (!id) return "";
  const f = functions.find((x) => x.type === "sporfelt" && x.id === id);
  return f?.rolle || "";
}

export function frEnder(
  tv: Partial<Togvei>,
  functions: HalFunction[],
  st?: Record<string, SignalTypeDef>
): { fra: string; til: string } {
  if (tv.fra && tv.til) return { fra: tv.fra, til: tv.til };
  const sig = functions.find((f) => erHoved(f.type, st) && f.id === tv.start);
  const linje =
    (tv.frie || []).find((x) => feltRolle(x, functions) === "linjefelt") || "";
  if (sig?.rolle === "innkjor") return { fra: linje, til: tv.spor || "" };
  if (sig?.rolle === "utkjor") return { fra: tv.spor || "", til: linje };
  return { fra: tv.fra || "", til: tv.til || "" };
}

export function frRetning(
  tv: Partial<Togvei>,
  functions: HalFunction[],
  st?: Record<string, SignalTypeDef>
): "" | "innkjor" | "utkjor" | "indre" {
  const { fra, til } = frEnder(tv, functions, st);
  const fr = feltRolle(fra, functions);
  const tl = feltRolle(til, functions);
  if (fr === "linjefelt" && tl === "togspor") return "innkjor";
  if (fr === "togspor" && tl === "linjefelt") return "utkjor";
  if (fr === "togspor" && tl === "togspor" && fra && fra !== til)
    return "indre";
  return "";
}

export function frGenId(
  tv: Partial<Togvei>,
  functions: HalFunction[],
  st?: Record<string, SignalTypeDef>
): string {
  const { fra, til } = frEnder(tv, functions, st);
  return frRetning({ ...tv, fra, til }, functions, st) ? fra + til : "";
}

export function frStartKandidater(
  tv: Partial<Togvei>,
  functions: HalFunction[],
  st?: Record<string, SignalTypeDef>
): string[] {
  const { fra, til } = frEnder(tv, functions, st);
  const r = frRetning({ ...tv, fra, til }, functions, st);
  if (!r) return [];
  if (r === "indre") {
    return functions
      .filter((f) => erHoved(f.type, st) && f.rolle === "indre")
      .map((f) => f.id);
  }
  const mal = r === "innkjor" ? fra : til;
  const kand = functions.filter((f) => erHoved(f.type, st) && f.rolle === r);
  const eksakte = kand.filter((f) => f.linjefelt === mal);
  const uten = kand.filter((f) => !f.linjefelt);
  return (eksakte.length ? eksakte : uten).map((f) => f.id);
}

/**
 * Normaliserer en togvei etter endring av fra/til.
 * K13: Når retningen er gyldig men frStartKandidater er tom, MÅ tv.start
 * tømmes ("") — aldri beholde et gammelt startsignal fra en annen ende.
 * Når retningen mangler (f.eks. eldre rad uten fra/til), beholdes tv.start
 * slik at eksisterende rader fortsatt kan lagres.
 */
export function normaliserTogvei(
  tv: Togvei,
  functions: HalFunction[],
  st?: Record<string, SignalTypeDef>
): Togvei {
  const { fra, til } = frEnder(tv, functions, st);
  const neste: Togvei = { ...tv, fra, til };
  const r = frRetning(neste, functions, st);
  if (r) {
    neste.spor = r === "utkjor" ? fra : til;
    neste.id = fra + til;
    const kand = frStartKandidater(neste, functions, st);
    if (!kand.length) {
      neste.start = "";
    } else if (!kand.includes(neste.start)) {
      neste.start = kand[0];
    }
  }
  return neste;
}

export function frBilde(
  tv: Partial<Togvei>,
  functions: HalFunction[],
  st?: Record<string, SignalTypeDef>
): "kjor" | "kjor-redusert" {
  const sig = functions.find((f) => f.id === tv.start && erHoved(f.type, st));
  if (sig?.type === "hovedsignal2") return "kjor-redusert";
  return (tv.sporveksler || []).some((v) => v.stilling === "avvik")
    ? "kjor-redusert"
    : "kjor";
}

export function frAutoFelt(
  tv: Partial<Togvei>,
  functions: HalFunction[],
  st?: Record<string, SignalTypeDef>
): { frie: string[]; utlos: string } | null {
  const { fra, til } = frEnder(tv, functions, st);
  const r = frRetning({ ...tv, fra, til }, functions, st);
  if (!r) return null;
  const vfelt = (tv.sporveksler || [])
    .map((v) => v.sporveksel)
    .filter(
      (x) => x && functions.some((f) => f.type === "sporfelt" && f.id === x)
    );
  if (r !== "indre" && !vfelt.length) return null;
  if (r === "innkjor") {
    return { frie: [fra, ...vfelt, til], utlos: vfelt[0] };
  }
  return { frie: [...vfelt, til], utlos: vfelt[0] || "" };
}

export function frFiendtlig(a: Partial<Togvei>, b: Partial<Togvei>): string[] {
  const grunner: string[] = [];
  if (a.start && a.start === b.start) {
    grunner.push(`samme startsignal ${a.start}`);
  }
  const felles = (a.frie || []).filter((f) => (b.frie || []).includes(f));
  if (felles.length) {
    grunner.push(`deler sporfelt ${felles.join(", ")}`);
  }
  for (const va of a.sporveksler || []) {
    if (!va.sporveksel) continue;
    for (const vb of b.sporveksler || []) {
      if (!vb.sporveksel) continue;
      if (va.sporveksel === vb.sporveksel && va.stilling !== vb.stilling) {
        grunner.push(
          `veksel ${va.sporveksel}: ${va.stilling} mot ${vb.stilling}`
        );
      }
    }
  }
  return grunner;
}

export function frKrav(functions: HalFunction[]): string[] {
  const mangler: string[] = [];
  if (!functions.some((f) => f.type === "sporfelt" && f.rolle === "linjefelt"))
    mangler.push("et linjefelt");
  const nSpor = functions.filter(
    (f) => f.type === "sporfelt" && f.rolle === "togspor"
  ).length;
  if (nSpor < 2)
    mangler.push(nSpor ? "ett togspor til (minst to)" : "to togspor");
  if (!functions.some((f) => f.type === "sporveksel"))
    mangler.push("en sentralstilt veksel");
  return mangler;
}

export function utledetEnde(
  vLitra: string,
  functions: HalFunction[],
  togveier: Togvei[]
): "" | "v" | "h" {
  if (!vLitra) return "";
  const side: Record<string, string> = {};
  for (const f of functions) {
    if (f.type === "sporfelt" && f.rolle === "linjefelt" && f.id && f.side) {
      side[f.id] = f.side;
    }
  }
  let v = false;
  let h = false;
  for (const tv of togveier || []) {
    if (!(tv.sporveksler || []).some((x) => x.sporveksel === vLitra)) continue;
    for (const f of tv.frie || []) {
      if (side[f] === "v") v = true;
      else if (side[f] === "h") h = true;
    }
  }
  return v && !h ? "v" : h && !v ? "h" : "";
}

export interface SporplanAdvarsel {
  tekst: string;
  opprett?: { linje: string; spor: string; retning: "innkjor" | "utkjor" };
}

export function validerSporplan(
  functions: HalFunction[],
  togveier: Togvei[],
  st?: Record<string, SignalTypeDef>
): SporplanAdvarsel[] {
  const adv: SporplanAdvarsel[] = [];
  const sigAv = (id: string) =>
    functions.find((f) => f.id === id && erHoved(f.type, st));
  const feltAv = (id: string) =>
    functions.find((f) => f.id === id && f.type === "sporfelt");
  const cmp = (a: string, b: string) =>
    a.localeCompare(b, "no", { numeric: true });

  const ruter: {
    id: string;
    retning: "innkjor" | "utkjor";
    linje: string;
    spor: string;
    start: string;
    veksler: string[];
  }[] = [];

  for (const tv of togveier) {
    const id = tv.id || "(uten id)";
    if (!tv.start) {
      adv.push({ tekst: `${id}: mangler startsignal` });
      continue;
    }
    const rolle = sigAv(tv.start)?.rolle || "";
    if (rolle === "indre") {
      adv.push({
        tekst: `${id}: indre togvei (togspor til togspor) — vises ikke i skissen ennå`,
      });
      continue;
    }
    if (rolle !== "innkjor" && rolle !== "utkjor") {
      adv.push({
        tekst: `${id}: startsignalet ${tv.start} mangler rolle innkjør/utkjør under Objekter`,
      });
      continue;
    }
    const linje =
      (tv.frie || []).find((f) => feltAv(f)?.rolle === "linjefelt") || "";
    if (!linje) {
      adv.push({
        tekst: `${id}: ingen av sporfeltene er linjefelt (sett rolle under Objekter)`,
      });
    }
    if (!tv.spor) adv.push({ tekst: `${id}: mangler spor` });
    ruter.push({
      id,
      retning: rolle,
      linje,
      spor: tv.spor || "",
      start: tv.start,
      veksler: (tv.sporveksler || [])
        .filter((v) => v.sporveksel)
        .map((v) => v.sporveksel + (v.stilling === "avvik" ? "a" : "n")),
    });
  }

  const ender = functions
    .filter((f) => f.type === "sporfelt" && f.rolle === "linjefelt")
    .map((f) => f.id);
  for (const r of ruter) {
    if (r.linje && !ender.includes(r.linje)) ender.push(r.linje);
  }
  ender.sort(cmp);

  const spor = functions
    .filter((f) => f.type === "sporfelt" && f.rolle === "togspor")
    .map((f) => f.id);
  for (const r of ruter) {
    if (r.spor && !spor.includes(r.spor)) spor.push(r.spor);
  }
  spor.sort(cmp);

  let vEnde = ender.find((e) => feltAv(e)?.side === "v") || null;
  let hEnde =
    ender.find((e) => e !== vEnde && feltAv(e)?.side === "h") || null;
  if (!vEnde) vEnde = ender.find((e) => e !== hEnde) || null;
  if (!hEnde) hEnde = ender.find((e) => e !== vEnde) || null;

  const utenfor = ender.filter((e) => e !== vEnde && e !== hEnde);
  if (utenfor.length) {
    adv.push({
      tekst: `Flere enn to linjefelt (${utenfor.join(", ")}) — de vises ikke i skissen`,
    });
  }

  // Konfliktsjekk: samme vekselsett fra samme ende og retning til ulike spor
  const brukt: Record<string, Set<string>> = {};
  for (const r of ruter) {
    if (!r.linje || !r.spor) continue;
    const k = `${r.linje}|${r.retning}|${r.veksler.slice().sort().join("+")}`;
    (brukt[k] ??= new Set()).add(r.spor);
  }
  for (const [k, s] of Object.entries(brukt)) {
    if (s.size > 1) {
      const [linje, , vlist] = k.split("|");
      adv.push({
        tekst: `vekselstillingene [${vlist || "ingen"}] fra ${linje} fører til flere spor (${[...s].join(", ")})`,
      });
    }
  }

  // Manglende inn-/utkjørtogveier per togspor og ende
  for (const sp of spor) {
    for (const linje of [vEnde, hEnde]) {
      if (!linje) continue;
      if (!ruter.some((r) => r.linje === linje && r.spor === sp && r.retning === "innkjor")) {
        adv.push({
          tekst: `Spor ${sp}: mangler innkjørtogvei fra ${linje}`,
          opprett: { linje, spor: sp, retning: "innkjor" },
        });
      }
      if (!ruter.some((r) => r.linje === linje && r.spor === sp && r.retning === "utkjor")) {
        adv.push({
          tekst: `Spor ${sp}: mangler utkjørtogvei mot ${linje}`,
          opprett: { linje, spor: sp, retning: "utkjor" },
        });
      }
    }
  }

  // Forsignaler som peker på ukjent hovedsignal
  for (const fs of functions) {
    if (sigKlasse(fs.type, st) !== "forsignal") continue;
    if (fs.montert_med && !sigAv(fs.montert_med)) {
      adv.push({
        tekst: `Forsignal ${fs.id}: montert med «${fs.montert_med}» — finnes ikke som hovedsignal`,
      });
    } else if (!fs.montert_med && fs.varsler_om && !sigAv(fs.varsler_om)) {
      adv.push({
        tekst: `Forsignal ${fs.id}: varsler om «${fs.varsler_om}» — finnes ikke som hovedsignal`,
      });
    }
  }

  // Varselfelt uten kobling til et gyldig linjefelt
  for (const m of functions) {
    if (m.type !== "sporfelt" || m.rolle !== "varselfelt") continue;
    if (!m.linjefelt || feltAv(m.linjefelt)?.rolle !== "linjefelt") {
      adv.push({
        tekst: `Varselfelt ${m.id}: mangler kobling til linjefelt — varslet vet ikke hvilken side det gjelder`,
      });
    }
  }

  // Togspor med bare én veksel (unngå vakuøs .every() for spor uten togveier!)
  const erGjennomgang = (spId: string) => {
    const tvForSpor = togveier.filter((t) => t.spor === spId);
    return (
      tvForSpor.length > 0 &&
      tvForSpor.every((t) =>
        (t.sporveksler || []).every((v) => v.stilling === "normal")
      )
    );
  };
  for (const sp of spor) {
    if (erGjennomgang(sp)) continue;
    const vekslerTil = functions
      .filter(
        (v) =>
          isNoenVeksel(v.type) &&
          [v.pluss_til, v.minus_til, v.spiss_til].includes(sp)
      )
      .map((v) => v.id);
    if (vekslerTil.length === 1) {
      adv.push({
        tekst: `Togspor ${sp}: bare veksel ${vekslerTil[0]} peker på det («Sporplan-tegning» under Objekter) — et togspor trenger veksel i begge ender for å tegnes gjennomgående på /panel`,
      });
    }
  }

  // Veksel som ingen peker på og som ikke er rot i et togspor
  const vekslerAlle = functions.filter((f) => isNoenVeksel(f.type));
  const pektPaa = new Set<string>();
  for (const v of vekslerAlle) {
    for (const r of [v.pluss_til, v.minus_til]) {
      if (typeof r === "string" && r.startsWith("veksel ")) {
        pektPaa.add(r.slice(7));
      }
    }
  }
  const iTogvei = new Set<string>();
  for (const t of togveier) {
    for (const v of t.sporveksler || []) {
      if (v.sporveksel) iTogvei.add(v.sporveksel);
    }
  }
  const togsporLitra = new Set(
    functions
      .filter((f) => f.type === "sporfelt" && f.rolle === "togspor")
      .map((f) => f.id)
  );
  for (const v of vekslerAlle) {
    if (pektPaa.has(v.id) || iTogvei.has(v.id)) continue;
    if (
      togsporLitra.has(String(v.pluss_til || "")) &&
      (v.spiss === "v" || v.spiss === "h")
    ) {
      continue;
    }
    adv.push({
      tekst: `Veksel ${v.id}: ingen annen veksel peker på den, og den er ingen rot i et togspor — panelet finner den ikke. Sett «+→» til togsporet den ligger i, og «spiss» til stasjonsenden («Sporplan-tegning» under Objekter)`,
    });
  }

  return adv;
}

// ---------- Tidslås- og formateringshjelpere ----------

/**
 * Validerer råtekst for en tidslås. Tomt eller ikke-heltallig felt avvises —
 * konverteres ALDRI stille til 0 (som skrur av sikkerhetsvernet).
 */
export function validerTidslas(
  raw: string | number | null | undefined,
  def: TidslaasDef
): { ok: true; verdi: number } | { ok: false; feil: string } {
  const s = String(raw ?? "").trim();
  if (!s || !/^\d+$/.test(s)) {
    return {
      ok: false,
      feil: `${def.tittel}: oppgi et helt tall (${def.min}–${def.maks} ${def.enhet}${def.av ? ", eller 0 for av" : ""})`,
    };
  }
  const v = Number(s);
  if (!(def.av && v === 0) && (v < def.min || v > def.maks)) {
    return {
      ok: false,
      feil: `${def.tittel}: ${v} ${def.enhet} er utenfor ${def.min}–${def.maks} ${def.enhet}${def.av ? " (0 = av)" : ""}`,
    };
  }
  return { ok: true, verdi: v };
}

export function fmtSek(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s)) return "?";
  const n = Math.max(0, Math.floor(s));
  const d = Math.floor(n / 86400);
  const t = Math.floor((n % 86400) / 3600);
  const m = Math.floor((n % 3600) / 60);
  const sek = n % 60;
  if (d) return `${d}d ${t}t`;
  if (t) return `${t}t ${m}m`;
  if (m) return `${m}m`;
  return `${sek}s`;
}

export function fmtKlokkeNed(sek: number | null | undefined): string {
  if (sek == null || !Number.isFinite(sek)) return "";
  const n = Math.max(0, Math.floor(sek));
  const m = Math.floor(n / 60);
  const s = n % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}
