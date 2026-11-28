import { toast } from "svelte-sonner";
import {
  hentAnlegg,
  hentForrigling,
  hentHal,
  lagreAnlegg,
  lagreForrigling,
  lagreHal,
} from "../api/klient";
import {
  GRUPPER,
  beregnPortKart,
  estimertKonfigBytes,
  frGenId,
  frRetning,
  gruppeIdx,
  masterBufferGrense,
  normaliserTogvei,
  validerTidslas,
} from "../domain/regler";
import {
  type DraftFunction,
  halGrunnlagJson,
  klon,
  normaliserForLagring,
  oppdaterOrgIdFraSendt,
  tilDraftFns,
} from "../domain/utkast";
import type {
  AnleggConfig,
  Binding,
  HalFunction,
  NodeAliasMap,
  SignalTypeDef,
  Togvei,
} from "../types";
import { live } from "./live.svelte";

export type { DraftFunction };

let ridTeller = 1;
const nesteRid = () => ridTeller++;

export type AckTilstand =
  | { status: "ingen" }
  | { status: "lagrer" }
  | { status: "venter"; version: string; tidsutlopt: boolean }
  | { status: "kvittert"; version: string; antall?: number };

function anleggLikt(a: AnleggConfig | null, b: AnleggConfig | null): boolean {
  if (!a || !b) return a === b;
  if (
    a.id !== b.id ||
    a.navn !== b.navn ||
    a.nabo_venstre !== b.nabo_venstre ||
    a.nabo_hoyre !== b.nabo_hoyre ||
    a.adopter !== b.adopter ||
    a.testmodus !== b.testmodus ||
    a.fjernstyrt !== b.fjernstyrt ||
    a.dekningsstilling !== b.dekningsstilling ||
    a.vis_sim !== b.vis_sim
  ) {
    return false;
  }
  for (const def of b.tider_def || a.tider_def || []) {
    const va = a.tider?.[def.navn] ?? def.standard;
    const vb = b.tider?.[def.navn] ?? def.standard;
    if (va !== vb) return false;
  }
  return true;
}

export class DraftStore {
  lastet = $state(false);
  laster = $state(false);

  // Lagrede fasiter fra server
  halVersjon = $state<string | number>("");
  signaltyper = $state<Record<string, SignalTypeDef>>({});
  noder = $state<NodeAliasMap>({});
  private lagretHalJson = $state("");

  forriglingVersjon = $state<string | number>("");
  private lagretForriglingJson = $state("");

  anleggLagret = $state<AnleggConfig | null>(null);

  // Konfliktflagg når serverens grunnlag endret seg mens lokalt utkast var skittent
  halKonflikt = $state(false);
  forriglingKonflikt = $state(false);
  anleggKonflikt = $state(false);

  // Redigerbare utkast
  functions = $state<DraftFunction[]>([]);
  togveier = $state<Togvei[]>([]);
  anlegg = $state<AnleggConfig | null>(null);
  /** Rå strenger for tidslåsfelt så tomme felt aldri blir stille 0 (U7) */
  tiderTekst = $state<Record<string, string>>({});

  // Master-ACK-sporing med STRENG versjonsmatch (aldri gammel snapshot-ack)
  halAck = $state<AckTilstand>({ status: "ingen" });
  frAck = $state<AckTilstand>({ status: "ingen" });
  anleggAck = $state<AckTilstand>({ status: "ingen" });
  private halAckTimer: ReturnType<typeof setTimeout> | null = null;
  private frAckTimer: ReturnType<typeof setTimeout> | null = null;
  private anleggAckTimer: ReturnType<typeof setTimeout> | null = null;
  private anleggAckBaseTeller = 0;

  // Avledet tilstand delt mellom Objekter, Kabling og Forrigling
  halDirty = $derived.by(() => {
    if (!this.lastet) return false;
    return (
      halGrunnlagJson(normaliserForLagring(this.functions)) !==
      this.lagretHalJson
    );
  });

  forriglingDirty = $derived.by(() => {
    if (!this.lastet) return false;
    return JSON.stringify(this.togveier) !== this.lagretForriglingJson;
  });

  anleggDirty = $derived.by(() => {
    if (!this.lastet || !this.anlegg || !this.anleggLagret) return false;
    const base = this.anleggLagret;
    const cur = this.anlegg;
    if (
      cur.id !== base.id ||
      cur.navn !== base.navn ||
      cur.nabo_venstre !== base.nabo_venstre ||
      cur.nabo_hoyre !== base.nabo_hoyre ||
      cur.adopter !== base.adopter ||
      cur.testmodus !== base.testmodus ||
      cur.fjernstyrt !== base.fjernstyrt ||
      cur.dekningsstilling !== base.dekningsstilling ||
      cur.vis_sim !== base.vis_sim
    ) {
      return true;
    }
    for (const def of base.tider_def || []) {
      const lagret = String(base.tider?.[def.navn] ?? def.standard);
      if ((this.tiderTekst[def.navn] ?? lagret) !== lagret) return true;
    }
    return false;
  });

  harUlagredeEndringer = $derived(
    this.halDirty || this.forriglingDirty || this.anleggDirty
  );

  portKart = $derived(
    beregnPortKart(this.functions, this.signaltyper, this.noder)
  );

  masterBufferMaks = $derived(masterBufferGrense(live.master?.info));

  halBytesAnslag = $derived.by(() => {
    if (!this.lastet) return 0;
    return estimertKonfigBytes({
      version: this.halVersjon || "2026-01-01 00:00:00",
      updated: "2026-01-01T00:00:00+00:00",
      signaltyper: this.signaltyper,
      noder: this.noder,
      functions: normaliserForLagring(this.functions),
    });
  });

  forriglingBytesAnslag = $derived.by(() => {
    if (!this.lastet) return 0;
    return estimertKonfigBytes({
      version: this.forriglingVersjon || "2026-01-01 00:00:00",
      updated: "2026-01-01T00:00:00+00:00",
      togveier: this.togveier,
    });
  });

  async lastAlt(bevarUlagret = false) {
    this.laster = true;
    try {
      const [hal, fr, an] = await Promise.all([
        hentHal(),
        hentForrigling(),
        hentAnlegg(),
      ]);

      const st = hal.signaltyper || {};
      this.signaltyper = st;
      this.noder = hal.noder || {};
      this.halVersjon = hal.version || "";

      const ferskHalDraft = tilDraftFns(
        hal.functions || [],
        this.functions,
        nesteRid,
        st
      );
      const ferskHalJson = halGrunnlagJson(normaliserForLagring(ferskHalDraft));
      const varHalDirty = this.lastet && this.halDirty;
      const gammelHalJson = this.lagretHalJson;
      // Oppdater ALLTID server-grunnlaget så Forkast gjenoppretter fersk server-tilstand
      this.lagretHalJson = ferskHalJson;
      if (!bevarUlagret || !varHalDirty) {
        this.functions = ferskHalDraft;
        this.halKonflikt = false;
      } else if (gammelHalJson && gammelHalJson !== ferskHalJson) {
        this.halKonflikt = true;
        toast.warning(
          "Objekter ble endret på serveren mens du har ulagrede endringer — bruk Forkast for å hente fersk versjon, eller Lagre for å overskrive."
        );
      }

      this.forriglingVersjon = fr.version || "";
      const ferskFr = klon(fr.togveier || []);
      const ferskFrJson = JSON.stringify(ferskFr);
      const varFrDirty = this.lastet && this.forriglingDirty;
      const gammelFrJson = this.lagretForriglingJson;
      this.lagretForriglingJson = ferskFrJson;
      if (!bevarUlagret || !varFrDirty) {
        this.togveier = ferskFr;
        this.forriglingKonflikt = false;
      } else if (gammelFrJson && gammelFrJson !== ferskFrJson) {
        this.forriglingKonflikt = true;
        toast.warning(
          "Forrigling ble endret på serveren mens du har ulagrede endringer — bruk Forkast for å hente fersk versjon, eller Lagre for å overskrive."
        );
      }

      const varAnleggDirty = this.lastet && this.anleggDirty;
      const gammelAnlegg = this.anleggLagret;
      this.anleggLagret = klon(an);
      if (!bevarUlagret || !varAnleggDirty) {
        this.anlegg = klon(an);
        const tt: Record<string, string> = {};
        for (const def of an.tider_def || []) {
          tt[def.navn] = String(an.tider?.[def.navn] ?? def.standard);
        }
        this.tiderTekst = tt;
        this.anleggKonflikt = false;
      } else if (gammelAnlegg && !anleggLikt(gammelAnlegg, an)) {
        this.anleggKonflikt = true;
        toast.warning(
          "Anleggsinnstillinger ble endret på serveren mens du har ulagrede endringer — bruk Forkast for å hente fersk versjon, eller Lagre for å overskrive."
        );
      }

      this.lastet = true;
    } catch (e: any) {
      toast.error(e?.message || "Klarte ikke å laste konfigurasjonen");
    } finally {
      this.laster = false;
    }
  }

  /** Oppdaterer kun noder-kartet fra server uten å kaste ulagrede utkast */
  async friskNoder() {
    try {
      const hal = await hentHal();
      this.noder = hal.noder || {};
      const fersk = tilDraftFns(
        hal.functions || [],
        this.functions,
        nesteRid,
        this.signaltyper
      );
      const ferskJson = halGrunnlagJson(normaliserForLagring(fersk));
      const varDirty = this.halDirty;
      this.lagretHalJson = ferskJson;
      if (!varDirty) {
        this.functions = fersk;
        this.halKonflikt = false;
      }
    } catch (e: any) {
      toast.error(e?.message || "Klarte ikke å oppdatere nodelisten");
    }
  }

  /** Sjekk streng versjonsmatch når live.ack endrer seg */
  sjekkAck() {
    if (
      this.halAck.status === "venter" &&
      live.ack.hal?.version === this.halAck.version
    ) {
      if (this.halAckTimer) clearTimeout(this.halAckTimer);
      this.halAck = {
        status: "kvittert",
        version: this.halAck.version,
        antall: live.ack.hal.functions,
      };
    }
    if (
      this.frAck.status === "venter" &&
      live.ack.forrigling?.version === this.frAck.version
    ) {
      if (this.frAckTimer) clearTimeout(this.frAckTimer);
      this.frAck = {
        status: "kvittert",
        version: this.frAck.version,
        antall: live.ack.forrigling.togveier,
      };
    }
    if (
      this.anleggAck.status === "venter" &&
      live.anleggAckTeller > this.anleggAckBaseTeller &&
      live.ack.anlegg?.id === this.anleggAck.version
    ) {
      if (this.anleggAckTimer) clearTimeout(this.anleggAckTimer);
      this.anleggAck = {
        status: "kvittert",
        version: this.anleggAck.version,
      };
    }
  }

  leggTilObjekt(gi: number): DraftFunction {
    const type = GRUPPER[gi]?.typer[0] || "utgang";
    const ny: DraftFunction = {
      id: "",
      type,
      bindinger: [],
      _rid: nesteRid(),
      _orgId: "",
    };
    if (type === "hovedsignal3" || type === "hovedsignal2") {
      ny.rolle = "utkjor";
    }
    this.functions = [...this.functions, ny];
    return ny;
  }

  oppdaterObjekt(rid: number, fn: DraftFunction) {
    this.functions = this.functions.map((x) => (x._rid === rid ? fn : x));
  }

  slettObjekt(rid: number) {
    this.functions = this.functions.filter((x) => x._rid !== rid);
  }

  settBinding(rid: number, sted: string, binding: Binding | null, idx = 0) {
    const obj = this.functions.find((x) => x._rid === rid);
    if (!obj) return;
    const binds = klon(obj.bindinger || []);
    let sett = 0;
    let funnet = -1;
    for (let i = 0; i < binds.length; i++) {
      if (binds[i].sted === sted) {
        if (sett === idx) {
          funnet = i;
          break;
        }
        sett++;
      }
    }
    if (binding === null || !binding.node) {
      if (funnet >= 0) binds.splice(funnet, 1);
    } else if (funnet >= 0) {
      binds[funnet] = binding;
    } else {
      binds.push(binding);
    }
    this.oppdaterObjekt(rid, { ...obj, bindinger: binds });
  }

  forkastHal() {
    if (!this.lagretHalJson) return;
    const fns = JSON.parse(this.lagretHalJson) as HalFunction[];
    this.functions = tilDraftFns(fns, this.functions, nesteRid, this.signaltyper);
    this.halKonflikt = false;
  }

  forkastForrigling() {
    if (!this.lagretForriglingJson) return;
    this.togveier = JSON.parse(this.lagretForriglingJson) as Togvei[];
    this.forriglingKonflikt = false;
  }

  forkastAnlegg() {
    if (!this.anleggLagret) return;
    this.anlegg = klon(this.anleggLagret);
    const tt: Record<string, string> = {};
    for (const def of this.anleggLagret.tider_def || []) {
      tt[def.navn] = String(
        this.anleggLagret.tider?.[def.navn] ?? def.standard
      );
    }
    this.tiderTekst = tt;
    this.anleggKonflikt = false;
  }

  async lagreHalDraft(): Promise<boolean> {
    if (this.portKart.feil.length > 0) {
      toast.error(`Portkonflikt: ${this.portKart.feil[0]}`);
      return false;
    }
    // Frys nøyaktig det som sendes FØR await (punkt 3)
    const sendtDraft = klon(this.functions);
    const payload = normaliserForLagring(sendtDraft);
    const sendtJson = halGrunnlagJson(payload);
    const sendtRidTilId = new Map<number, string>(
      sendtDraft.map((f) => [f._rid, (f.id || "").trim()])
    );

    this.halAck = { status: "lagrer" };
    try {
      const res = await lagreHal(payload);
      this.halVersjon = res.version;
      this.halKonflikt = false;

      // U3 + punkt 3: oppdater _orgId KUN til det som faktisk ble sendt,
      // og sett grunnlaget til det som faktisk ble lagret — endringer gjort
      // mens kallet pågikk forblir dermed merket som ulagrede!
      this.functions = oppdaterOrgIdFraSendt(this.functions, sendtRidTilId);
      this.lagretHalJson = sendtJson;

      if (res.omdopt > 0) {
        // Punkt 2: ved omdøping henter vi bare HAL + Forrigling, og overskriver
        // ALDRI brukerens ulagrede anleggs- eller togveiendringer!
        const [hal, fr] = await Promise.all([hentHal(), hentForrigling()]);
        const st = hal.signaltyper || this.signaltyper;
        this.signaltyper = st;
        this.noder = hal.noder || this.noder;
        this.halVersjon = hal.version || res.version;

        const ferskHal = tilDraftFns(
          hal.functions || [],
          this.functions,
          nesteRid,
          st
        );
        const ferskHalJson = halGrunnlagJson(normaliserForLagring(ferskHal));
        const haddeEndringerUnderveis =
          halGrunnlagJson(normaliserForLagring(this.functions)) !== sendtJson;
        this.lagretHalJson = ferskHalJson;
        if (!haddeEndringerUnderveis) {
          this.functions = ferskHal;
        }

        this.forriglingVersjon = fr.version || this.forriglingVersjon;
        const ferskFr = klon(fr.togveier || []);
        const ferskFrJson = JSON.stringify(ferskFr);
        const varFrDirty = this.forriglingDirty;
        const gammelFrJson = this.lagretForriglingJson;
        this.lagretForriglingJson = ferskFrJson;
        if (!varFrDirty) {
          this.togveier = ferskFr;
          this.forriglingKonflikt = false;
        } else if (gammelFrJson !== ferskFrJson) {
          this.forriglingKonflikt = true;
          toast.warning(
            "Serveren oppdaterte togveiene etter omdøping, men du har ulagrede togveier — se Forrigling-fanen."
          );
        }
      }

      if (this.halAckTimer) clearTimeout(this.halAckTimer);
      this.halAck = { status: "venter", version: res.version, tidsutlopt: false };
      this.sjekkAck();
      if (this.halAck.status === "venter") {
        this.halAckTimer = setTimeout(() => {
          if (this.halAck.status === "venter") {
            this.halAck = { ...this.halAck, tidsutlopt: true };
          }
        }, 10_000);
      }
      toast.success(
        `Objekter lagret og publisert (${res.version})` +
          (res.omdopt
            ? ` · ${res.omdopt} litra omdøpt (${res.referanser} referanser)`
            : "")
      );
      return true;
    } catch (e: any) {
      this.halAck = { status: "ingen" };
      toast.error(e?.message || "Klarte ikke å lagre objekter");
      return false;
    }
  }

  async lagreForriglingDraft(): Promise<boolean> {
    // Normaliser og valider alle togveier før sending
    const renset = this.togveier.map((tv) =>
      normaliserTogvei(tv, this.functions, this.signaltyper)
    );
    const sett = new Set<string>();
    for (const tv of renset) {
      const r = frRetning(tv, this.functions, this.signaltyper);
      if ((tv.fra || tv.til) && !r) {
        toast.error(
          `Togvei ${tv.id || `${tv.fra}→${tv.til}`}: endene må være linjefelt→togspor, togspor→linjefelt eller togspor→togspor`
        );
        return false;
      }
      if (r && !tv.start) {
        toast.error(
          `Togvei ${frGenId(tv, this.functions, this.signaltyper)}: mangler hovedsignal — sett rolle/linjefelt på signalet under Objekter`
        );
        return false;
      }
      if (tv.id) {
        if (sett.has(tv.id)) {
          toast.error(`Duplikat togvei-ID: ${tv.id}`);
          return false;
        }
        sett.add(tv.id);
      }
    }
    this.togveier = renset;
    const sendtJson = JSON.stringify(renset);
    this.frAck = { status: "lagrer" };
    try {
      const res = await lagreForrigling(renset);
      this.forriglingVersjon = res.version;
      // Punkt 3: grunnlaget er det som ble sendt, ikke evt. endringer underveis
      this.lagretForriglingJson = sendtJson;
      this.forriglingKonflikt = false;
      if (this.frAckTimer) clearTimeout(this.frAckTimer);
      this.frAck = { status: "venter", version: res.version, tidsutlopt: false };
      this.sjekkAck();
      if (this.frAck.status === "venter") {
        this.frAckTimer = setTimeout(() => {
          if (this.frAck.status === "venter") {
            this.frAck = { ...this.frAck, tidsutlopt: true };
          }
        }, 10_000);
      }
      toast.success(`Forrigling lagret og publisert (${res.version})`);
      return true;
    } catch (e: any) {
      this.frAck = { status: "ingen" };
      toast.error(e?.message || "Klarte ikke å lagre forrigling");
      return false;
    }
  }

  async lagreAnleggDraft(): Promise<{
    ok: boolean;
    ap_omdopt?: boolean;
    ssid?: string;
    hostname?: string;
  }> {
    if (!this.anlegg) return { ok: false };
    const tider: Record<string, number> = {};
    for (const def of this.anlegg.tider_def || []) {
      const res = validerTidslas(this.tiderTekst[def.navn], def);
      if (!res.ok) {
        toast.error(res.feil);
        return { ok: false };
      }
      tider[def.navn] = res.verdi;
    }
    if (
      tider.veksel_timeout_ms !== undefined &&
      tider.veksel_omlegging_ms !== undefined &&
      tider.veksel_timeout_ms <= tider.veksel_omlegging_ms
    ) {
      toast.error(
        "Vekseltimeouten må være lenger enn omleggingstiden uten sensorer"
      );
      return { ok: false };
    }
    const sendtPayload = {
      id: this.anlegg.id.trim().toUpperCase(),
      navn: this.anlegg.navn.trim(),
      nabo_venstre: this.anlegg.nabo_venstre.trim(),
      nabo_hoyre: this.anlegg.nabo_hoyre.trim(),
      adopter: this.anlegg.adopter,
      testmodus: this.anlegg.testmodus,
      fjernstyrt: this.anlegg.fjernstyrt,
      dekningsstilling: this.anlegg.dekningsstilling,
      vis_sim: this.anlegg.vis_sim,
      tider,
    };
    const sendtTiderTekst = klon(this.tiderTekst);
    const sendtAnleggSnapshot = klon(this.anlegg);
    this.anleggAckBaseTeller = live.anleggAckTeller;
    this.anleggAck = { status: "lagrer" };
    try {
      const res = await lagreAnlegg(sendtPayload);
      const nyLagret: AnleggConfig = klon({
        ...(this.anleggLagret || sendtAnleggSnapshot),
        id: res.id,
        navn: res.navn,
        nabo_venstre: res.nabo_venstre,
        nabo_hoyre: res.nabo_hoyre,
        adopter: res.adopter,
        testmodus: res.testmodus,
        fjernstyrt: res.fjernstyrt,
        dekningsstilling: res.dekningsstilling,
        vis_sim: res.vis_sim,
        tider: res.tider,
      });
      // Bare overskriv utkastet hvis brukeren ikke redigerte videre mens lagring pågikk
      const uendretUnderveis =
        anleggLikt(this.anlegg, sendtAnleggSnapshot) &&
        JSON.stringify(this.tiderTekst) === JSON.stringify(sendtTiderTekst);
      this.anleggLagret = nyLagret;
      this.anleggKonflikt = false;
      if (uendretUnderveis) {
        this.anlegg = klon(nyLagret);
        const tt: Record<string, string> = {};
        for (const def of nyLagret.tider_def || []) {
          tt[def.navn] = String(res.tider?.[def.navn] ?? def.standard);
        }
        this.tiderTekst = tt;
      }

      if (this.anleggAckTimer) clearTimeout(this.anleggAckTimer);
      this.anleggAck = {
        status: "venter",
        version: res.id,
        tidsutlopt: false,
      };
      this.sjekkAck();
      if (this.anleggAck.status === "venter") {
        this.anleggAckTimer = setTimeout(() => {
          if (this.anleggAck.status === "venter") {
            this.anleggAck = { ...this.anleggAck, tidsutlopt: true };
          }
        }, 10_000);
      }

      toast.success("Anleggsinnstillinger lagret og publisert");
      return {
        ok: true,
        ap_omdopt: res.ap_omdopt,
        ssid: res.ssid,
        hostname: res.hostname,
      };
    } catch (e: any) {
      this.anleggAck = { status: "ingen" };
      toast.error(e?.message || "Klarte ikke å lagre anleggsinnstillinger");
      return { ok: false };
    }
  }

  async slaAvTestmodus(): Promise<void> {
    try {
      await lagreAnlegg({ testmodus: false });
      if (this.anlegg) this.anlegg = { ...this.anlegg, testmodus: false };
      if (this.anleggLagret)
        this.anleggLagret = { ...this.anleggLagret, testmodus: false };
      toast.success("Testmodus skrudd av");
    } catch (e: any) {
      toast.error(e?.message || "Klarte ikke å skru av testmodus");
    }
  }

  gruppeFor(fn: HalFunction): number {
    return gruppeIdx(fn.type);
  }
}

export const draft = new DraftStore();
