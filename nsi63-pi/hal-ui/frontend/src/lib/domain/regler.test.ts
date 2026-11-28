import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  MAX_LITRA,
  aliasFor,
  beregnPortKart,
  fmtSek,
  frAutoFelt,
  frBilde,
  frFiendtlig,
  frGenId,
  frKrav,
  hovedsignalManglerRolle,
  inputNokkel,
  litraNs,
  litraUgyldig,
  normaliserTogvei,
  portSymbol,
  rensObjektVedTypeBytte,
  rensSporfeltVedRolleBytte,
  signalLampeFarge,
  utledetEnde,
  validerSporplan,
  validerTidslas,
} from "./regler";
import {
  type DraftFunction,
  halGrunnlagJson,
  normaliserForLagring,
  oppdaterOrgIdFraSendt,
  tilDraftFns,
} from "./utkast";
import type { HalConfig, ForriglingConfig, SignalTypeDef } from "../types";

const TESTS_DIR = resolve(__dirname, "../../../../tests");
const EKSEMPLER_DIR = resolve(__dirname, "../../../../eksempler");
const FASIT = JSON.parse(
  readFileSync(resolve(TESTS_DIR, "fasit_regler.json"), "utf8")
);

const DEFAULT_ST: Record<string, SignalTypeDef> = {
  hovedsignal3: { klasse: "hovedsignal", lamper: 3, bilder: {} },
  hovedsignal2: { klasse: "hovedsignal", lamper: 2, bilder: {} },
  forsignal2: { klasse: "forsignal", lamper: 2, bilder: {} },
  skiftesignal2: { klasse: "skiftesignal", lamper: 2, bilder: {} },
  skiftesignal1: { klasse: "skiftesignal", lamper: 1, bilder: {} },
  dvergsignal3: { klasse: "dvergsignal", lamper: 3, bilder: {} },
};

describe("Felles fasitdata (server_og_klient)", () => {
  const sok = FASIT.server_og_klient;

  it("MAX_LITRA matcher fasit", () => {
    expect(MAX_LITRA).toBe(sok.maks_litra);
  });

  it.each(sok.litra_tegn as Record<string, any>[])(
    "litraUgyldig($litra) === $ulovlig",
    (r) => {
      expect(litraUgyldig(r.litra)).toBe(r.ulovlig);
    }
  );

  it.each(sok.navnerom as Record<string, any>[])(
    "litraNs($type) === $ns",
    (r) => {
      expect(litraNs(r.type, DEFAULT_ST)).toBe(r.ns);
    }
  );

  it.each(sok.port_konflikter as Record<string, any>[])(
    "port_konflikter: $navn",
    (c) => {
      const res = beregnPortKart(c.functions, DEFAULT_ST, c.noder);
      if (c.forvent_feil) {
        expect(res.feil.length).toBeGreaterThan(0);
        if (c.hint) {
          expect(res.feil.some((f) => f.includes(c.hint))).toBe(true);
        }
      } else {
        expect(res.feil).toEqual([]);
      }
    }
  );

  it.each(sok.togvei_id as Record<string, any>[])(
    "frGenId -> $forventet",
    (c) => {
      expect(frGenId(c.tv, sok.togvei_id_objekter, DEFAULT_ST)).toBe(
        c.forventet
      );
    }
  );
});

describe("Felles fasitdata (klient_og_master)", () => {
  const km = FASIT.klient_og_master;

  it.each(km.fiendtlige as Record<string, any>[])(
    "frFiendtlig: $navn",
    (c) => {
      const g = frFiendtlig(c.a, c.b);
      expect(g.length > 0).toBe(c.fiendtlig);
    }
  );

  it.each(km.signalbilde as Record<string, any>[])(
    "frBilde: $navn",
    (c) => {
      const fns = [{ id: "S", type: c.start_type, bindinger: [] }];
      expect(
        frBilde({ start: "S", sporveksler: c.sporveksler }, fns, DEFAULT_ST)
      ).toBe(c.bilde);
    }
  );

  it.each(km.auto_felt as Record<string, any>[])(
    "frAutoFelt: $navn",
    (c) => {
      const res = frAutoFelt(c.tv, km.auto_felt_objekter, DEFAULT_ST);
      expect(res).toEqual({ frie: c.frie, utlos: c.utlos });
    }
  );
});

describe("Eksempelkonfigurasjoner (Sokna og Grindvoll)", () => {
  it.each(["sokna", "grindvoll"])(
    "%s har null portkollisjoner i beregnPortKart",
    (navn) => {
      const hal: HalConfig = JSON.parse(
        readFileSync(resolve(EKSEMPLER_DIR, navn, "hal.json"), "utf8")
      );
      const fr: ForriglingConfig = JSON.parse(
        readFileSync(resolve(EKSEMPLER_DIR, navn, "forrigling.json"), "utf8")
      );
      const res = beregnPortKart(hal.functions, hal.signaltyper, hal.noder);
      expect(res.feil).toEqual([]);
      expect(fr.togveier.length).toBeGreaterThan(0);
    }
  );
});

describe("Krav fra kodegjennomgangen (Seksjon 4 + 87ddb69)", () => {
  it("K13: normaliserTogvei tømmer startsignal når kandidater er tomme", () => {
    const fns = [
      { id: "A", type: "sporfelt", rolle: "linjefelt", side: "h" as const, bindinger: [] },
      { id: "B", type: "sporfelt", rolle: "linjefelt", side: "v" as const, bindinger: [] },
      { id: "01", type: "sporfelt", rolle: "togspor", bindinger: [] },
      { id: "A", type: "hovedsignal3", rolle: "innkjor", linjefelt: "A", bindinger: [] },
    ];
    const tv = normaliserTogvei(
      {
        id: "A01",
        fra: "B",
        til: "01",
        start: "A",
        spor: "01",
        sporveksler: [],
        frie: [],
        utlosningsfelt: "",
      },
      fns,
      DEFAULT_ST
    );
    expect(tv.start).toBe("");
  });

  it("U7: validerTidslas avviser tomt felt og sender aldri 0 stille", () => {
    const def = {
      navn: "hjelpeutlosning_s",
      enhet: "s",
      min: 5,
      maks: 300,
      av: true,
      standard: 90,
      forbilde: "ca. 90 s",
      tittel: "Hjelpeutløsning",
      hva: "",
      kilde: "",
    };
    expect(validerTidslas("", def).ok).toBe(false);
    expect(validerTidslas("   ", def).ok).toBe(false);
    expect(validerTidslas("abc", def).ok).toBe(false);
    expect(validerTidslas("0", def)).toEqual({ ok: true, verdi: 0 });
    expect(validerTidslas("90", def)).toEqual({ ok: true, verdi: 90 });
  });

  it("U2: rensObjektVedTypeBytte lekker ikke skift_sporveksler, men bevarer veksel-topologi", () => {
    const skift = rensObjektVedTypeBytte(
      {
        id: "ZM",
        type: "skiftesignal2",
        skift_sporveksler: ["1"],
        bindinger: [],
      },
      "hovedsignal3",
      DEFAULT_ST
    );
    expect(skift.skift_sporveksler).toBeUndefined();

    const vx = rensObjektVedTypeBytte(
      {
        id: "1",
        type: "sporveksel",
        spiss: "h",
        minus_til: "veksel 5",
        bindinger: [
          { sted: "ut-normal", node: "N1", i2c: "0x41", port: 0 },
          { sted: "stiller-normal", node: "N1", i2c: "0x20", port: 0 },
        ],
      },
      "manuellveksel",
      DEFAULT_ST
    );
    expect(vx.spiss).toBe("h");
    expect(vx.minus_til).toBe("veksel 5");
    expect(vx.bindinger.map((b) => b.sted)).toEqual(["ut-normal"]);
  });

  it("rensSporfeltVedRolleBytte fjerner generisk sensor ved bytte til varselfelt", () => {
    const vf = rensSporfeltVedRolleBytte(
      {
        id: "a",
        type: "sporfelt",
        rolle: "togspor",
        bindinger: [{ sted: "sensor", node: "N1", i2c: "0x20", port: 0 }],
      },
      "varselfelt"
    );
    expect(vf.bindinger).toEqual([]);
  });

  it("87ddb69: aliasFor viser aldri MAC-nøkkel som kallenavn for navnløs driver-node", () => {
    const mac = "aa0000000001";
    expect(aliasFor(mac, { [mac]: { mac, driver: ["0x40"] } })).toBeNull();
    expect(aliasFor(mac, { SEKSJON1: { mac, driver: ["0x40"] } })).toBe(
      "SEKSJON1"
    );
  });

  it("signalLampeFarge farger ikke stiller/middelkontrollampe på skiftesignal", () => {
    expect(signalLampeFarge("skiftesignal2", 0, "anlegg")).toBe("#ffb400");
    expect(signalLampeFarge("skiftesignal2", 0, "stiller")).toBeNull();
    expect(signalLampeFarge("skiftesignal2", 0, "middelkontrollampe")).toBeNull();
  });

  it("fmtSek klemmer negative verdier til 0s", () => {
    expect(fmtSek(-5)).toBe("0s");
    expect(fmtSek(125)).toBe("2m");
  });
});

describe("Regresjonstester fra Fase 2-gjennomgangen", () => {
  it("Punkt 1: hovedsignal beholder/får alltid rolle ved typebytte", () => {
    // Bytte fra skiftesignal til hovedsignal3 må gi standardrolle «utkjor»
    const fraSkift = rensObjektVedTypeBytte(
      { id: "H1", type: "skiftesignal2", bindinger: [] },
      "hovedsignal3",
      DEFAULT_ST
    );
    expect(fraSkift.rolle).toBe("utkjor");

    // Bytte fra hovedsignal3 (innkjor) til hovedsignal2 må bli «utkjor» og bevare linjefelt/lampebinding
    const tilToLys = rensObjektVedTypeBytte(
      {
        id: "A",
        type: "hovedsignal3",
        rolle: "innkjor",
        linjefelt: "L1",
        bindinger: [{ sted: "anlegg", node: "N1", i2c: "0x40", port: 0 }],
      },
      "hovedsignal2",
      DEFAULT_ST
    );
    expect(tilToLys.rolle).toBe("utkjor");
    expect(tilToLys.linjefelt).toBe("L1");
    expect(tilToLys.bindinger).toHaveLength(1);

    // Bytte tilbake til hovedsignal3 bevarer gyldig rolle
    const tilTreLys = rensObjektVedTypeBytte(
      { id: "A", type: "hovedsignal2", rolle: "utkjor", bindinger: [] },
      "hovedsignal3",
      DEFAULT_ST
    );
    expect(tilTreLys.rolle).toBe("utkjor");
  });

  it("Punkt 3: endringer gjort mens lagring pågår merkes IKKE som lagret", () => {
    let rid = 1;
    const base: DraftFunction[] = [
      { id: "A", type: "utgang", bindinger: [], _rid: rid++, _orgId: "A" },
    ];

    // Brukeren endrer ID til A1 og trykker Lagre
    const vedSendStart: DraftFunction[] = [{ ...base[0], id: "A1" }];
    const payload = normaliserForLagring(vedSendStart);
    const sendtJson = halGrunnlagJson(payload);
    const sendtRidTilId = new Map<number, string>([[base[0]._rid, "A1"]]);

    // MENS fetch pågår, endrer brukeren ID videre til A2 og legger til nytt objekt B
    const underveis: DraftFunction[] = [
      { ...vedSendStart[0], id: "A2" },
      { id: "B", type: "utgang", bindinger: [], _rid: rid++, _orgId: "" },
    ];

    // Svaret fra serveren kommer tilbake:
    const etterSvar = oppdaterOrgIdFraSendt(underveis, sendtRidTilId);
    // _orgId for første rad skal nå være «A1» (det serveren faktisk lagret), ikke «A2»
    expect(etterSvar[0]._orgId).toBe("A1");
    expect(etterSvar[1]._orgId).toBe("");
    // Dirty-sjekk mot sendtJson må fortsatt være sann!
    expect(halGrunnlagJson(normaliserForLagring(etterSvar)) === sendtJson).toBe(
      false
    );
    // Neste lagring vil sende gammel_id: "A1" for A2
    const nestePayload = normaliserForLagring(etterSvar);
    expect(nestePayload[0].gammel_id).toBe("A1");
    expect(nestePayload[1].gammel_id).toBeUndefined();
  });

  it("tilDraftFns gjenbruker _rid så åpen inspektør ikke lukkes etter lagring", () => {
    let rid = 10;
    const neste = () => rid++;
    const forste = tilDraftFns(
      [
        { id: "A", type: "hovedsignal3", rolle: "innkjor", bindinger: [] },
        { id: "V1", type: "sporveksel", bindinger: [] },
      ],
      [],
      neste,
      DEFAULT_ST
    );
    const omLastet = tilDraftFns(
      [
        { id: "A", type: "hovedsignal3", rolle: "innkjor", bindinger: [] },
        { id: "V1", type: "sporveksel", bindinger: [] },
        { id: "B", type: "hovedsignal3", rolle: "utkjor", bindinger: [] },
      ],
      forste,
      neste,
      DEFAULT_ST
    );
    expect(omLastet.find((x) => x.id === "A")?._rid).toBe(
      forste.find((x) => x.id === "A")?._rid
    );
    expect(omLastet.find((x) => x.id === "V1")?._rid).toBe(
      forste.find((x) => x.id === "V1")?._rid
    );
    expect(omLastet.find((x) => x.id === "B")?._rid).toBeGreaterThanOrEqual(12);
  });

  it("Punkt 5: normaliserTogvei bevarer startsignal på eldre rad uten fra/til", () => {
    const fns = [
      { id: "A", type: "sporfelt", rolle: "linjefelt", bindinger: [] },
      { id: "01", type: "sporfelt", rolle: "togspor", bindinger: [] },
      { id: "S1", type: "hovedsignal3", rolle: "utkjor", bindinger: [] },
    ];
    // Eldre rad som mangler både fra/til og linjefelt i frie -> retning er ""
    const gammel = normaliserTogvei(
      {
        id: "X1",
        start: "S1",
        spor: "01",
        sporveksler: [],
        frie: ["01"],
        utlosningsfelt: "01",
      },
      fns,
      DEFAULT_ST
    );
    expect(gammel.start).toBe("S1");
  });

  it("Punkt 6: inputNokkel mapper GPIO til <mac>/0x00 som i app.py", () => {
    expect(inputNokkel("AA0011223344", "gpio")).toBe("aa0011223344/0x00");
    expect(inputNokkel("aa0011223344", "0x00")).toBe("aa0011223344/0x00");
    expect(inputNokkel("aa0011223344", "0X20")).toBe("aa0011223344/0x20");
    expect(inputNokkel("aa0011223344", 0x21)).toBe("aa0011223344/0x21");
  });

  it("validerSporplan fanger alle 5 ekstra kontrollene fra gamle frSkisse", () => {
    const fns = [
      { id: "L1", type: "sporfelt", rolle: "linjefelt", side: "v" as const, bindinger: [] },
      { id: "L2", type: "sporfelt", rolle: "linjefelt", side: "h" as const, bindinger: [] },
      { id: "L3", type: "sporfelt", rolle: "linjefelt", bindinger: [] },
      { id: "01", type: "sporfelt", rolle: "togspor", bindinger: [] },
      { id: "02", type: "sporfelt", rolle: "togspor", bindinger: [] },
      { id: "S_INDRE", type: "hovedsignal3", rolle: "indre", bindinger: [] },
      { id: "FA", type: "forsignal2", montert_med: "UKJENT_H", bindinger: [] },
      { id: "FB", type: "forsignal2", varsler_om: "UKJENT_H2", bindinger: [] },
      { id: "V_LOS", type: "sporfelt", rolle: "varselfelt", bindinger: [] },
      { id: "VX9", type: "manuellveksel", bindinger: [] },
    ];
    const togveier = [
      {
        id: "0102",
        fra: "01",
        til: "02",
        start: "S_INDRE",
        spor: "02",
        sporveksler: [],
        frie: ["02"],
        utlosningsfelt: "02",
      },
    ];
    const adv = validerSporplan(fns, togveier, DEFAULT_ST).map((a) => a.tekst);
    expect(adv.some((t) => t.includes("Flere enn to linjefelt") && t.includes("L3"))).toBe(true);
    expect(adv.some((t) => t.includes("indre togvei"))).toBe(true);
    expect(adv.some((t) => t.includes("Forsignal FA") && t.includes("UKJENT_H"))).toBe(true);
    expect(adv.some((t) => t.includes("Forsignal FB") && t.includes("UKJENT_H2"))).toBe(true);
    expect(adv.some((t) => t.includes("Varselfelt V_LOS"))).toBe(true);
    expect(adv.some((t) => t.includes("Veksel VX9"))).toBe(true);
  });

  it("utledetEnde, frKrav og portSymbol fungerer som forventet", () => {
    const fns = [
      { id: "A", type: "sporfelt", rolle: "linjefelt", side: "v" as const, bindinger: [] },
      { id: "01", type: "sporfelt", rolle: "togspor", bindinger: [] },
      { id: "02", type: "sporfelt", rolle: "togspor", bindinger: [] },
      { id: "V1", type: "sporveksel", bindinger: [] },
    ];
    expect(frKrav([])).toEqual([
      "et linjefelt",
      "to togspor",
      "en sentralstilt veksel",
    ]);
    expect(frKrav(fns)).toEqual([]);
    expect(
      utledetEnde("V1", fns, [
        {
          id: "A01",
          start: "S",
          spor: "01",
          sporveksler: [{ sporveksel: "V1", stilling: "normal" }],
          frie: ["A", "01"],
          utlosningsfelt: "01",
        },
      ])
    ).toBe("v");
    expect(portSymbol("anlegg", "hovedsignal3")).toBe("●");
    expect(portSymbol("panel", "hovedsignal3")).toBe("○");
    expect(portSymbol("ut-normal", "sporveksel")).toBe("⇄");
    expect(portSymbol("sensor", "sporfelt")).toBe("◎");
    expect(portSymbol("stiller-v", "sporfelt")).toBe("▣");
  });

  it("Hovedsignal uten rolle gir feil og lasting gjør ikke utkastet skittent", () => {
    const hs3Uten = { id: "A", type: "hovedsignal3", bindinger: [] };
    const hs3Tom = { id: "B", type: "hovedsignal3", rolle: "", bindinger: [] };
    const hs3Ok = { id: "C", type: "hovedsignal3", rolle: "innkjor", bindinger: [] };
    const hs2Uten = { id: "D", type: "hovedsignal2", bindinger: [] };
    const hs2Ok = { id: "E", type: "hovedsignal2", rolle: "utkjor", bindinger: [] };
    const forsig = { id: "FA", type: "forsignal2", bindinger: [] };

    expect(hovedsignalManglerRolle(hs3Uten, DEFAULT_ST)).toBe(true);
    expect(hovedsignalManglerRolle(hs3Tom, DEFAULT_ST)).toBe(true);
    expect(hovedsignalManglerRolle(hs3Ok, DEFAULT_ST)).toBe(false);
    expect(hovedsignalManglerRolle(hs2Uten, DEFAULT_ST)).toBe(true);
    expect(hovedsignalManglerRolle(hs2Ok, DEFAULT_ST)).toBe(false);
    expect(hovedsignalManglerRolle(forsig, DEFAULT_ST)).toBe(false);

    // Lasting av et hovedsignal uten rolle muterer ikke rolle og gjør ikke utkastet skittent
    let rid = 1;
    const serverFns = [hs3Uten, hs2Uten];
    const lastet = tilDraftFns(serverFns, [], () => rid++, DEFAULT_ST);
    expect(lastet.find((x) => x.id === "A")?.rolle).toBeUndefined();
    expect(lastet.find((x) => x.id === "D")?.rolle).toBeUndefined();
    const grunnlag = halGrunnlagJson(normaliserForLagring(lastet));
    expect(halGrunnlagJson(normaliserForLagring(lastet))).toBe(grunnlag);
    expect(halGrunnlagJson(serverFns)).toBe(grunnlag);
  });
});
