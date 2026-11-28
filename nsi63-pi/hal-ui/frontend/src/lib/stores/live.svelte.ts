import { sendKlokkeSjekk } from "../api/klient";
import type {
  AckState,
  BackupStatus,
  HendelseRad,
  LamptestState,
  MasterState,
  NodesState,
  OtaFilInfo,
  OtaKoState,
  PiStatus,
  SseSnapshot,
  TogveiInfoEntry,
} from "../types";

export type SseStatus = "kobler-til" | "tilkoblet" | "frakoblet";

const VAKTHUND_MS = 30_000;
const BACKOFF_MS = [2000, 5000, 10000];

export class LiveStore {
  status = $state<SseStatus>("kobler-til");
  harSnapshot = $state(false);
  master = $state<MasterState>({
    mac: null,
    status: null,
    sist_hort_s: null,
    info: null,
    conflict: null,
    meldinger: [],
    jord: null,
    signalstopp: null,
    gjennomgang: null,
    testmodus: null,
    frigivning: null,
  });
  nodes = $state<NodesState>({});
  inputs = $state<Record<string, number>>({});
  ack = $state<AckState>({ hal: null, forrigling: null, anlegg: null });
  togveiInfo = $state<Record<string, TogveiInfoEntry>>({});
  lamptest = $state<LamptestState>({
    running: false,
    traad: false,
    progress: "",
    i: 0,
    total: 0,
    igjen_s: null,
  });
  ota = $state<Record<string, OtaFilInfo | null>>({});
  otaKo = $state<OtaKoState>({
    kjorer: false,
    stopp: false,
    stempel: "",
    aktiv: null,
    venter: [],
    ferdig: [],
    feilet: [],
    avbrutt: [],
    antall: 0,
    varighet_s: null,
    kandidater: [],
    hindring: null,
    fw_finnes: false,
    fw_stempel: "",
  });
  backup = $state<BackupStatus>({
    sist: null,
    endret: false,
    hva: [],
    auto: [],
  });
  pi = $state<PiStatus | null>(null);
  hendelserAktiv = $state(false);
  /** Live innkommende hendelser fra SSE (lyttes av HendelsesloggView) */
  sisteHendelser = $state<HendelseRad[]>([]);
  /** Øker hver gang server melder konfig_endret fra en lagring/gjenoppretting */
  konfigVersjonTeller = $state(0);
  sisteKonfigEndret = $state<{ hva: string; version?: string } | null>(null);
  /** Øker ved hver SSE-snapshot (brukes til å synke konfig etter gjenoppkobling) */
  snapshotTeller = $state(0);
  /** Øker ved fersk SSE `ack` med type === "anlegg" (ikke ved snapshot) */
  anleggAckTeller = $state(0);

  /** Lokal 1 s-teller for jevn fremdrift av monotonisk alder mellom 10 s-tick */
  nowPerf = $state(typeof performance !== "undefined" ? performance.now() : 0);
  private masterRefPerf = 0;
  private lamptestRefPerf = 0;

  private es: EventSource | null = null;
  private sistMottattPerf = 0;
  private backoffIdx = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private vakthundTimer: ReturnType<typeof setInterval> | null = null;
  private klokkeTimer: ReturnType<typeof setInterval> | null = null;
  private sekTimer: ReturnType<typeof setInterval> | null = null;
  private pendingInputs: Record<string, number> = {};
  private inputRaf: number | null = null;

  /** Sekunder siden siste livstegn fra master (monotonisk, uavhengig av RTC) */
  sistHortSek = $derived.by(() => {
    if (this.master.sist_hort_s == null) return null;
    const diff = Math.max(
      0,
      Math.floor((this.nowPerf - this.masterRefPerf) / 1000)
    );
    return this.master.sist_hort_s + diff;
  });

  masterErOnline = $derived(
    this.master.status === "online" &&
      this.sistHortSek !== null &&
      this.sistHortSek < 35
  );

  lamptestIgjenSek = $derived.by(() => {
    if (!this.lamptest.running || this.lamptest.igjen_s == null) return null;
    const diff = Math.max(
      0,
      Math.floor((this.nowPerf - this.lamptestRefPerf) / 1000)
    );
    return Math.max(0, this.lamptest.igjen_s - diff);
  });

  onlineNodeAntall = $derived(
    (this.nodes.nodes || []).filter((n) => !!n.online).length
  );

  start() {
    this.kobleTil();
    sendKlokkeSjekk();
    this.klokkeTimer = setInterval(() => sendKlokkeSjekk(), 300_000);
    this.sekTimer = setInterval(() => {
      this.nowPerf = performance.now();
    }, 1000);
    this.vakthundTimer = setInterval(() => {
      if (this.status === "tilkoblet" || this.status === "kobler-til") {
        if (performance.now() - this.sistMottattPerf > VAKTHUND_MS) {
          this.markerFrakobletOgPlanlegg();
        }
      }
    }, 5000);
  }

  stopp() {
    this.lukkEs();
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.vakthundTimer) clearInterval(this.vakthundTimer);
    if (this.klokkeTimer) clearInterval(this.klokkeTimer);
    if (this.sekTimer) clearInterval(this.sekTimer);
  }

  kobleTilNaa() {
    this.backoffIdx = 0;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.kobleTil();
  }

  private lukkEs() {
    if (this.es) {
      this.es.close();
      this.es = null;
    }
  }

  private markerMottatt() {
    const p = performance.now();
    this.sistMottattPerf = p;
    this.nowPerf = p;
    this.backoffIdx = 0;
    if (this.status !== "tilkoblet") this.status = "tilkoblet";
  }

  private markerFrakobletOgPlanlegg() {
    this.lukkEs();
    this.status = "frakoblet";
    if (this.reconnectTimer) return;
    const vent = BACKOFF_MS[Math.min(this.backoffIdx, BACKOFF_MS.length - 1)];
    this.backoffIdx++;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.kobleTil();
    }, vent);
  }

  private settMaster(m: MasterState) {
    this.master = m;
    this.masterRefPerf = performance.now();
  }

  private settLamptest(lt: LamptestState) {
    this.lamptest = lt;
    this.lamptestRefPerf = performance.now();
  }

  private flushInputs() {
    this.inputRaf = null;
    const batch = this.pendingInputs;
    this.pendingInputs = {};
    this.inputs = { ...this.inputs, ...batch };
  }

  private kobleTil() {
    this.lukkEs();
    if (!this.harSnapshot) this.status = "kobler-til";
    const es = new EventSource("/api/events");
    this.es = es;
    this.sistMottattPerf = performance.now();

    es.addEventListener("snapshot", (ev) => {
      this.markerMottatt();
      const s = JSON.parse((ev as MessageEvent).data) as SseSnapshot;
      this.settMaster(s.master);
      this.nodes = s.nodes || {};
      this.inputs = s.inputs || {};
      this.ack = s.ack || { hal: null, forrigling: null, anlegg: null };
      this.togveiInfo = s.togvei_info || {};
      this.settLamptest(s.lamptest);
      this.ota = s.ota || {};
      this.otaKo = s.ota_ko;
      this.backup = s.backup;
      this.pi = s.pi;
      this.hendelserAktiv = !!s.hendelser_aktiv;
      this.harSnapshot = true;
      this.snapshotTeller++;
    });

    es.addEventListener("tick", (ev) => {
      this.markerMottatt();
      const d = JSON.parse((ev as MessageEvent).data);
      if (d.master) this.settMaster(d.master);
      if (d.lamptest) this.settLamptest(d.lamptest);
      if (d.pi) this.pi = d.pi;
    });

    es.addEventListener("master", (ev) => {
      this.markerMottatt();
      this.settMaster(JSON.parse((ev as MessageEvent).data));
    });

    es.addEventListener("nodes", (ev) => {
      this.markerMottatt();
      this.nodes = JSON.parse((ev as MessageEvent).data) || {};
    });

    es.addEventListener("input", (ev) => {
      this.markerMottatt();
      const d = JSON.parse((ev as MessageEvent).data) as {
        k: string;
        v: number;
      };
      this.pendingInputs[d.k] = d.v;
      if (this.inputRaf == null) {
        this.inputRaf = requestAnimationFrame(() => this.flushInputs());
      }
    });

    es.addEventListener("ack", (ev) => {
      this.markerMottatt();
      const d = JSON.parse((ev as MessageEvent).data) as {
        type: "hal" | "forrigling" | "anlegg";
        data: any;
      };
      this.ack = { ...this.ack, [d.type]: d.data };
      if (d.type === "anlegg") {
        this.anleggAckTeller++;
      }
    });

    es.addEventListener("togvei_info", (ev) => {
      this.markerMottatt();
      const d = JSON.parse((ev as MessageEvent).data) as {
        id: string;
        tekst: string;
        alder_s: number;
      };
      this.togveiInfo = {
        ...this.togveiInfo,
        [d.id]: { tekst: d.tekst, alder_s: d.alder_s },
      };
    });

    es.addEventListener("lamptest", (ev) => {
      this.markerMottatt();
      this.settLamptest(JSON.parse((ev as MessageEvent).data));
    });

    es.addEventListener("ota", (ev) => {
      this.markerMottatt();
      this.ota = JSON.parse((ev as MessageEvent).data) || {};
    });

    es.addEventListener("ota_ko", (ev) => {
      this.markerMottatt();
      this.otaKo = JSON.parse((ev as MessageEvent).data);
    });

    es.addEventListener("backup", (ev) => {
      this.markerMottatt();
      this.backup = JSON.parse((ev as MessageEvent).data);
    });

    es.addEventListener("hendelser_aktiv", (ev) => {
      this.markerMottatt();
      const d = JSON.parse((ev as MessageEvent).data);
      this.hendelserAktiv = !!d.aktiv;
    });

    es.addEventListener("hendelse", (ev) => {
      this.markerMottatt();
      const rad = JSON.parse((ev as MessageEvent).data) as HendelseRad;
      const neste = [...this.sisteHendelser, rad];
      this.sisteHendelser = neste.length > 500 ? neste.slice(-500) : neste;
    });

    es.addEventListener("konfig_endret", (ev) => {
      this.markerMottatt();
      this.sisteKonfigEndret = JSON.parse((ev as MessageEvent).data);
      this.konfigVersjonTeller++;
    });

    es.onerror = () => {
      this.markerFrakobletOgPlanlegg();
    };
  }
}

export const live = new LiveStore();
