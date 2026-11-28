import type {
  AnleggConfig,
  ForriglingConfig,
  HalConfig,
  HalFunction,
  HendelseRad,
  Togvei,
} from "../types";

export class ApiFeil extends Error {
  status: number;
  constructor(melding: string, status: number) {
    super(melding);
    this.status = status;
  }
}

async function apiJson<T = any>(r: Response): Promise<T> {
  let j: any;
  try {
    j = await r.json();
  } catch {
    throw new ApiFeil(
      `Serverfeil ${r.status} — sjekk «journalctl -u nsi63-hal» på Pi-en`,
      r.status
    );
  }
  if (!r.ok) {
    throw new ApiFeil(j?.error || `Feil ${r.status}`, r.status);
  }
  return j as T;
}

export async function hentHal(): Promise<HalConfig> {
  return apiJson(await fetch("/api/hal"));
}

export async function lagreHal(functions: HalFunction[]): Promise<{
  ok: true;
  version: string;
  omdopt: number;
  referanser: number;
}> {
  return apiJson(
    await fetch("/api/hal", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ functions }),
    })
  );
}

export async function hentForrigling(): Promise<ForriglingConfig> {
  return apiJson(await fetch("/api/forrigling"));
}

export async function lagreForrigling(
  togveier: Togvei[]
): Promise<{ ok: true; version: string }> {
  return apiJson(
    await fetch("/api/forrigling", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ togveier }),
    })
  );
}

export async function hentAnlegg(): Promise<AnleggConfig> {
  return apiJson(await fetch("/api/anlegg"));
}

export async function lagreAnlegg(
  payload: Partial<AnleggConfig>
): Promise<
  AnleggConfig & { ok: true; ssid: string; hostname: string; ap_omdopt: boolean }
> {
  return apiJson(
    await fetch("/api/anlegg", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}

export async function lagreAlias(
  mac: string,
  alias: string
): Promise<{ ok: true; version: string }> {
  return apiJson(
    await fetch("/api/node-alias", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mac, alias }),
    })
  );
}

export async function settDriver(
  mac: string,
  i2c: string,
  driver: boolean
): Promise<{ ok: true; version: string }> {
  return apiJson(
    await fetch("/api/node-driver", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mac, i2c, driver }),
    })
  );
}

export async function finnNode(mac: string): Promise<{ ok: true }> {
  return apiJson(
    await fetch("/api/find", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mac }),
    })
  );
}

export async function glemNode(mac: string): Promise<{ ok: true }> {
  return apiJson(
    await fetch("/api/forget", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mac }),
    })
  );
}

export async function betjenLampeprove(
  action: "start" | "stop"
): Promise<{ ok: true }> {
  return apiJson(
    await fetch("/api/lamptest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    })
  );
}

export async function lastOppFirmware(
  file: File
): Promise<{ ok: true; fil: string; stempel: string }> {
  const fd = new FormData();
  fd.append("file", file);
  return apiJson(await fetch("/api/ota/firmware", { method: "POST", body: fd }));
}

export async function startOta(
  maal: string
): Promise<{ ok: true; maal: string }> {
  return apiJson(
    await fetch("/api/ota/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ maal }),
    })
  );
}

export async function startOtaKo(): Promise<{ ok: true; antall: number }> {
  return apiJson(await fetch("/api/ota/ko", { method: "POST" }));
}

export async function stoppOtaKo(): Promise<{ ok: true }> {
  return apiJson(await fetch("/api/ota/ko/stopp", { method: "POST" }));
}

export async function betjenTogvei(
  id: string,
  hva: "sikre" | "stopp" | "hjelpeutlos"
): Promise<{ ok: true; svar: string | null }> {
  return apiJson(
    await fetch("/api/togvei-betjen", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, hva }),
    })
  );
}

export async function hentHendelser(
  n = 300,
  filter = ""
): Promise<{ hendelser: HendelseRad[]; kuttet: boolean; aktiv: boolean }> {
  return apiJson(
    await fetch(
      `/api/hendelser?n=${n}&filter=${encodeURIComponent(filter)}`
    )
  );
}

export async function settHendelserAktiv(
  aktiv: boolean
): Promise<{ ok: true; aktiv: boolean }> {
  return apiJson(
    await fetch("/api/hendelser/aktiv", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ aktiv }),
    })
  );
}

export async function gjenopprettBackup(file: File): Promise<{
  ok: true;
  version: string;
  functions: number;
  togveier: number | null;
  anlegg_i_backup: string | null;
}> {
  const fd = new FormData();
  fd.append("file", file);
  return apiJson(await fetch("/api/restore", { method: "POST", body: fd }));
}

export async function sendKlokkeSjekk(): Promise<void> {
  try {
    await fetch("/api/klokke", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ epoch_ms: Date.now() }),
    });
  } catch {
    // stille — Pi kan være opptatt eller offline
  }
}
