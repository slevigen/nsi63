export type SignalKlasse =
  | "hovedsignal"
  | "forsignal"
  | "skiftesignal"
  | "dvergsignal";

export type ObjektType =
  | "hovedsignal3"
  | "hovedsignal2"
  | "forsignal2"
  | "skiftesignal2"
  | "skiftesignal1"
  | "dvergsignal3"
  | "sporveksel"
  | "manuellveksel"
  | "sporsperre"
  | "utgang"
  | "klokke"
  | "sporfelt"
  | "bryter"
  | "trykknapp"
  | "inngang"
  | "amperemeter"
  | "samlelaas"
  | "rigel"
  | string;

export interface SignalTypeDef {
  klasse?: SignalKlasse;
  lamper: number;
  normalbilde?: string;
  bilder: Record<string, string[]>;
  signalnr?: Record<string, string>;
  folger?: Record<string, string>;
}

export interface Binding {
  sted: string;
  node: string;
  i2c: string | number;
  port: number;
}

export interface HalFunction {
  id: string;
  type: ObjektType;
  bindinger: Binding[];
  gammel_id?: string;
  montert_med?: string;
  varsler_om?: string;
  rolle?: string;
  side?: "" | "v" | "h";
  linjeblokk?: boolean;
  linjefelt?: string;
  utslag?: number;
  hakk_hz?: number;
  hakk_duty?: number;
  skift_sporveksler?: string[];
  omfatter?: string[];
  navn?: string;
  // Sporplan-topologi (kun /panel-tegning)
  spiss?: "" | "v" | "h";
  pluss_til?: string;
  minus_til?: string;
  spiss_til?: string;
  avvik_ben?: "" | "spiss" | "pluss";
  ligger_i?: string;
}

export interface NodeAliasEntry {
  mac: string;
  driver?: string[];
}

export type NodeAliasMap = Record<string, NodeAliasEntry>;

export interface HalConfig {
  version: string | number;
  updated: string | null;
  signaltyper: Record<string, SignalTypeDef>;
  functions: HalFunction[];
  noder: NodeAliasMap;
}

export interface TogveiVeksel {
  sporveksel: string;
  stilling: "normal" | "avvik";
}

export interface Togvei {
  id: string;
  fra?: string;
  til?: string;
  start: string;
  spor: string;
  sporveksler: TogveiVeksel[];
  frie: string[];
  laaser?: string[];
  utlosningsfelt: string;
  notes?: string;
}

export interface ForriglingConfig {
  version: string | number;
  updated: string | null;
  togveier: Togvei[];
}

export interface TidslaasDef {
  navn: string;
  enhet: string;
  min: number;
  maks: number;
  av: boolean;
  standard: number;
  forbilde: string;
  tittel: string;
  hva: string;
  kilde: string;
}

export interface AnleggConfig {
  id: string;
  navn: string;
  nabo_venstre: string;
  nabo_hoyre: string;
  adopter: boolean;
  testmodus: boolean;
  fjernstyrt: boolean;
  dekningsstilling: boolean;
  vis_sim: boolean;
  tider: Record<string, number>;
  hjelpeutlosning_s?: number;
  ack?: { id?: string; [k: string]: unknown } | null;
  tider_def?: TidslaasDef[];
}

export interface LiveNode {
  mac: string;
  online: number | boolean;
  safe?: number | boolean;
  fw?: number;
  bygget?: string;
  i2c?: string[];
}

export interface NodesState {
  master?: string;
  nodes?: LiveNode[];
}

export interface MasterInfo {
  fw?: number;
  bygget?: string;
  uptime?: number;
  pulse?: number;
  rssi?: number;
  nodes?: number;
  buf?: number;
}

export interface MasterMelding {
  tekst: string;
  ts?: number;
  alder_s: number;
}

export interface MasterConflict {
  self: string;
  other: string;
}

export interface MasterState {
  mac: string | null;
  status: string | null;
  sist_hort_s: number | null;
  info: MasterInfo | null;
  conflict: MasterConflict | null;
  meldinger: MasterMelding[];
  jord: string | null;
  signalstopp: string | null;
  gjennomgang: string | null;
  testmodus: string | null;
  frigivning: Record<string, unknown> | null;
}

export interface LamptestState {
  running: boolean;
  traad?: boolean;
  progress: string;
  i: number;
  total: number;
  igjen_s: number | null;
  start_ts?: number;
}

export interface OtaFilInfo {
  bytes: number;
  md5: string;
  stempel: string;
  tid: number;
}

export interface OtaKoNode {
  mac: string;
  alias: string;
  fra?: string;
  sekunder?: number;
  grunn?: string;
  varighet_s?: number;
}

export interface OtaKoState {
  kjorer: boolean;
  stopp: boolean;
  stempel: string;
  aktiv: OtaKoNode | null;
  venter: OtaKoNode[];
  ferdig: OtaKoNode[];
  feilet: OtaKoNode[];
  avbrutt: OtaKoNode[];
  antall: number;
  varighet_s: number | null;
  kandidater: OtaKoNode[];
  hindring: string | null;
  fw_finnes: boolean;
  fw_stempel: string;
}

export interface BackupStatus {
  sist: string | null;
  endret: boolean;
  hva: string[];
  auto: string[];
}

export interface PiApKlient {
  mac: string;
  ip: string;
  navn: string;
  signal: number | null;
  tid_s: number | null;
}

export interface PiStatus {
  temp: number | null;
  throttled: { raw: string; naa: string[]; historikk: string[] } | null;
  ips: { ifname: string; addrs: string[]; oper: string }[];
  klienter: PiApKlient[];
  tjenester: Record<string, string>;
  ntp: boolean;
  klokke: string;
  klokke_stilt: { naar: string; diff_s: number; fra: string } | null;
  oppetid_s: number | null;
  last: number[] | null;
  mem: { total_mb: number; ledig_mb: number } | null;
  disk: { total_gb: number; ledig_gb: number } | null;
  modell: string | null;
  hal_ui: {
    commit?: string;
    kort?: string;
    gren?: string;
    ukommittert?: boolean;
    tid?: string;
  } | null;
}

export interface HendelseRad {
  ts: number;
  tema: string;
  data: string;
  r?: number;
}

export interface TogveiInfoEntry {
  tekst: string;
  alder_s: number;
}

export interface AckState {
  hal: { version?: string; functions?: number } | null;
  forrigling: { version?: string; togveier?: number } | null;
  anlegg: { id?: string } | null;
}

export interface SseSnapshot {
  master: MasterState;
  nodes: NodesState;
  inputs: Record<string, number>;
  ack: AckState;
  togvei_info: Record<string, TogveiInfoEntry>;
  lamptest: LamptestState;
  ota: Record<string, OtaFilInfo | null>;
  ota_ko: OtaKoState;
  backup: BackupStatus;
  pi: PiStatus | null;
  hendelser_aktiv: boolean;
}

export type ViewId =
  | "oversikt"
  | "objekter"
  | "kabling"
  | "forrigling"
  | "logg"
  | "innstillinger";
