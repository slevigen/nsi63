<script lang="ts">
  import {
    AlertTriangle,
    Download,
    Eye,
    FileArchive,
    Lightbulb,
    Play,
    RefreshCw,
    Sparkles,
    Square,
    Trash2,
    Upload,
  } from "@lucide/svelte";
  import { toast } from "svelte-sonner";
  import Badge from "$components/ui/Badge.svelte";
  import Button from "$components/ui/Button.svelte";
  import Card from "$components/ui/Card.svelte";
  import ConfirmDialog from "$components/ui/ConfirmDialog.svelte";
  import Progress from "$components/ui/Progress.svelte";
  import {
    betjenLampeprove,
    finnNode,
    glemNode,
    lagreAlias,
    lastOppFirmware,
    settDriver,
    startOta,
    startOtaKo,
    stoppOtaKo,
  } from "$lib/api/klient";
  import {
    MAX_ORDREPUNKTER,
    PCA_ADRESSER,
    WARN_ORDREPUNKTER,
    aliasFor,
    driverBrikkerForMac,
    fmtKlokkeNed,
    fmtSek,
  } from "$lib/domain/regler";
  import { draft } from "$lib/stores/draft.svelte";
  import { live } from "$lib/stores/live.svelte";
  import type { ViewId } from "$lib/types";

  interface Props {
    onnavigate: (view: ViewId, focus?: { node?: string }) => void;
    onledguide: () => void;
  }

  let { onnavigate, onledguide }: Props = $props();

  const FW_FIL = "nsi63-atoms3.bin";

  let aliasUtkast = $state<Record<string, string>>({});
  let bekreft = $state<{
    open: boolean;
    title: string;
    desc: string;
    destructive?: boolean;
    fn: () => Promise<void>;
  }>({ open: false, title: "", desc: "", fn: async () => {} });
  let otaInput = $state<HTMLInputElement | null>(null);

  let fwInfo = $derived(live.ota[FW_FIL] || null);
  let fwStempel = $derived(fwInfo?.stempel || "");
  let rosterFersk = $derived(live.sistHortSek !== null && live.sistHortSek < 35);
  let alleNoder = $derived(live.nodes.nodes || []);
  let safeAntall = $derived(alleNoder.filter((n) => !!n.safe).length);
  let bufferPct = $derived(
    Math.round((draft.halBytesAnslag / Math.max(1, draft.masterBufferMaks)) * 100)
  );

  // Foreldreløse kallenavn (uten å vise driver-only MAC-nøkler som foreldreløse)
  let foreldrelose = $derived.by(() => {
    const kjente = new Set(alleNoder.map((n) => n.mac.toLowerCase()));
    return Object.entries(draft.noder).filter(
      ([k, v]) =>
        v?.mac &&
        k.toLowerCase() !== v.mac.toLowerCase() &&
        !kjente.has(v.mac.toLowerCase())
    );
  });

  function fwErEldre(bygget?: string): boolean {
    return Boolean(fwStempel && bygget && bygget < fwStempel);
  }

  async function onLagreAlias(mac: string) {
    const val = (aliasUtkast[mac] ?? aliasFor(mac, draft.noder) ?? "")
      .trim()
      .toUpperCase();
    try {
      await lagreAlias(mac, val);
      delete aliasUtkast[mac];
      await draft.friskNoder();
      toast.success(val ? `Kallenavn satt til ${val}` : "Kallenavn fjernet");
    } catch (e: any) {
      toast.error(e?.message || "Klarte ikke å lagre kallenavn");
    }
  }

  async function onToggleDriver(mac: string, i2c: string, paa: boolean) {
    try {
      await settDriver(mac, i2c, paa);
      await draft.friskNoder();
      toast.success(`Driver ${i2c} ${paa ? "slått på" : "slått av"}`);
    } catch (e: any) {
      toast.error(e?.message || "Klarte ikke å endre driver");
    }
  }

  async function onBlink(mac: string) {
    try {
      await finnNode(mac);
      toast.info(`Blinker gult på ${aliasFor(mac, draft.noder) || mac} i 10 s`);
    } catch (e: any) {
      toast.error(e?.message || "Klarte ikke å sende blink-kommando");
    }
  }

  function sporGlemNode(mac: string) {
    const navn = aliasFor(mac, draft.noder) || mac;
    bekreft = {
      open: true,
      title: `Fjerne node ${navn}?`,
      desc: "Retained-temaer slettes og noden forsvinner fra oversikten. En node som fortsatt er i drift melder seg inn igjen av seg selv.",
      destructive: true,
      fn: async () => {
        try {
          await glemNode(mac);
          toast.success(`Ba master glemme ${navn}`);
        } catch (e: any) {
          toast.error(e?.message || "Klarte ikke å fjerne node");
        }
      },
    };
  }

  function sporSlettAlias(alias: string, mac: string) {
    bekreft = {
      open: true,
      title: `Slette kallenavnet ${alias}?`,
      desc: "Bindinger på noden skrives tilbake til MAC-adressen.",
      destructive: true,
      fn: async () => {
        try {
          await lagreAlias(mac, "");
          await draft.friskNoder();
          toast.success(`Kallenavn ${alias} slettet`);
        } catch (e: any) {
          toast.error(e?.message || "Klarte ikke å slette kallenavn");
        }
      },
    };
  }

  async function onOtaFil(e: Event) {
    const inp = e.currentTarget as HTMLInputElement;
    const fil = inp.files?.[0];
    inp.value = "";
    if (!fil) return;
    try {
      const r = await lastOppFirmware(fil);
      toast.success(
        `Firmware mottatt: ${r.fil}${r.stempel ? ` (${r.stempel})` : ""}`
      );
    } catch (err: any) {
      toast.error(err?.message || "Opplasting av firmware feilet");
    }
  }

  function sporOtaEnhet(maal: string) {
    const hvem =
      maal === "master"
        ? "master? Hele anlegget går i sikker tilstand i ~1 min og henter seg inn selv."
        : `noden ${aliasFor(maal, draft.noder) || maal}? Den er mørk (= stopp) i ~1 min.`;
    bekreft = {
      open: true,
      title: "Start trådløs firmwareoppdatering?",
      desc: `Oppdatere ${hvem}`,
      fn: async () => {
        try {
          await startOta(maal);
          toast.success("OTA startet");
        } catch (err: any) {
          toast.error(err?.message || "Klarte ikke å starte OTA");
        }
      },
    };
  }

  function sporOtaKo(antall: number) {
    bekreft = {
      open: true,
      title: `Oppdatere ${antall} utdaterte noder?`,
      desc: "Nodene oppdateres én om gangen. Hver node er mørk (= stopp) i ~1 min mens den henter firmware. Master oppdateres ikke av køen.",
      fn: async () => {
        try {
          const r = await startOtaKo();
          toast.success(`OTA-kø startet (${r.antall} noder)`);
        } catch (err: any) {
          toast.error(err?.message || "Klarte ikke å starte OTA-kø");
        }
      },
    };
  }

  async function onLamptest(action: "start" | "stop") {
    try {
      await betjenLampeprove(action);
    } catch (err: any) {
      toast.error(err?.message || "Lampeprøve feilet");
    }
  }

  async function onStoppOtaKo() {
    try {
      await stoppOtaKo();
      toast.info("OTA-køen stopper etter pågående node");
    } catch (err: any) {
      toast.error(err?.message || "Klarte ikke å stoppe OTA-køen");
    }
  }

  let masterBadgeTekst = $derived.by(() => {
    if (live.masterErOnline) return "ONLINE";
    if (live.sistHortSek != null) return "STILLE";
    if (live.master.status === "offline") return "OFFLINE";
    if (live.master.status === "online") return "IKKE HØRT";
    return (live.master.status || "UKJENT").toUpperCase();
  });
</script>

<div class="space-y-4">
  <!-- 4 KPI-kort -->
  <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
    <div class="rounded-lg border border-border bg-card p-3.5">
      <div class="flex items-center justify-between text-xs text-muted-foreground">
        <span>Master (AtomS3)</span>
        <Badge variant={live.masterErOnline ? "ok" : "warn"}>
          {masterBadgeTekst}
        </Badge>
      </div>
      <div class="mt-1.5 text-lg font-bold tabular flex items-baseline gap-2">
        <span>
          {live.master.info?.fw != null ? `fw v${live.master.info.fw}` : "—"}
        </span>
        {#if draft.anlegg?.id}
          <span class="text-xs font-mono text-primary">{draft.anlegg.id}</span>
        {/if}
      </div>
      <div class="mt-1 text-[11px] font-mono text-muted-foreground tabular">
        {#if live.master.info?.uptime != null}
          puls {live.master.info.pulse} · {live.master.info.rssi} dBm · {live.sistHortSek ?? "?"}s siden
        {:else}
          ingen livstegn mottatt
        {/if}
      </div>
    </div>

    <div class="rounded-lg border border-border bg-card p-3.5">
      <div class="flex items-center justify-between text-xs text-muted-foreground">
        <span>Noder (ESP-NOW)</span>
        <Badge variant={safeAntall > 0 ? "warn" : "ok"}>
          {live.onlineNodeAntall} / {alleNoder.length}
        </Badge>
      </div>
      <div class="mt-1.5 text-lg font-bold tabular">
        {alleNoder.length
          ? `${Math.round((live.onlineNodeAntall / alleNoder.length) * 100)}%`
          : "0"}
      </div>
      <div class="mt-1 text-[11px] font-mono text-muted-foreground">
        {safeAntall > 0
          ? `${safeAntall} i sikker tilstand`
          : live.otaKo.kandidater.length
            ? `${live.otaKo.kandidater.length} utdaterte fw`
            : "0 i sikker tilstand"}
      </div>
    </div>

    <div class="rounded-lg border border-border bg-card p-3.5">
      <div class="flex items-center justify-between text-xs text-muted-foreground">
        <span>Raspberry Pi</span>
        {#if live.pi?.temp != null}
          <Badge variant={live.pi.temp >= 70 ? "warn" : "ok"} class="tabular">
            {String(live.pi.temp).replace(".", ",")}°C
          </Badge>
        {:else}
          <Badge variant="muted">Pi</Badge>
        {/if}
      </div>
      <div class="mt-1.5 text-lg font-bold font-mono tabular">
        {live.pi?.ips?.[0]?.addrs?.[0] || "10.206.0.1"}
      </div>
      <div class="mt-1 text-[11px] font-mono text-muted-foreground truncate">
        {#if live.pi?.throttled?.naa?.length}
          <span class="text-warn">⚠ {live.pi.throttled.naa.join(", ")}</span>
        {:else if live.pi?.oppetid_s != null}
          oppetid {fmtSek(live.pi.oppetid_s)} · {live.pi.klienter?.length || 0} AP-klienter
        {:else}
          {live.pi?.modell || "lokal server"}
        {/if}
      </div>
    </div>

    <div class="rounded-lg border border-border bg-card p-3.5">
      <div class="flex items-center justify-between text-xs text-muted-foreground">
        <span>Konfigbuffer (anslag)</span>
        <Badge variant={bufferPct > 85 ? "warn" : bufferPct > 65 ? "amber" : "ok"} class="tabular">
          {bufferPct}%
        </Badge>
      </div>
      <div class="mt-1.5 text-lg font-bold tabular">
        ~{(draft.halBytesAnslag / 1024).toFixed(1)} kB
      </div>
      <div class="mt-1.5">
        <Progress
          value={draft.halBytesAnslag}
          max={draft.masterBufferMaks}
          warnAt={draft.masterBufferMaks * 0.7}
          dangerAt={draft.masterBufferMaks * 0.9}
        />
      </div>
    </div>
  </div>

  <!-- To kolonner: Noder/Master + Drift/OTA -->
  <div class="grid grid-cols-1 lg:grid-cols-[1.45fr_1fr] gap-4 items-start">
    <div class="space-y-4">
      <!-- Master-kort -->
      <Card title="Master" subtitle={live.master.mac || "Ikke registrert ennå"}>
        {#snippet actions()}
          {#if fwInfo && live.masterErOnline && !live.otaKo.kjorer}
            <Button size="xs" onclick={() => sporOtaEnhet("master")}>
              Oppdater master fw
            </Button>
          {/if}
        {/snippet}
        <div class="space-y-2.5 text-xs">
          <div class="flex flex-wrap gap-1.5">
            <Badge variant={live.master.jord === "av" ? "ok" : "amber"}>
              Jord: {live.master.jord || "—"}
            </Badge>
            <Badge variant={live.master.signalstopp === "paa" ? "warn" : "muted"}>
              Signalstopp: {live.master.signalstopp || "—"}
            </Badge>
            <Badge variant={live.master.gjennomgang === "aktiv" ? "ok" : "muted"}>
              Gjennomgang: {live.master.gjennomgang || "—"}
            </Badge>
            {#if live.master.info?.uptime != null}
              <Badge variant="muted" class="font-mono tabular">
                oppetid {fmtSek(live.master.info.uptime)}
              </Badge>
            {/if}
            {#if live.master.info?.bygget}
              <Badge variant={fwErEldre(live.master.info.bygget) ? "warn" : "muted"} class="font-mono">
                bygget {live.master.info.bygget}
                {fwErEldre(live.master.info.bygget) ? " · utdatert" : ""}
              </Badge>
            {/if}
          </div>

          {#if live.master.meldinger?.length}
            <div class="space-y-1 rounded-md border border-warn/40 bg-warn/10 p-2.5">
              {#each live.master.meldinger as m}
                <div class="flex items-baseline justify-between gap-2 text-xs">
                  <span class="text-warn font-medium">⚠ {m.tekst}</span>
                  <span class="text-[11px] text-muted-foreground font-mono shrink-0 tabular">
                    {fmtSek(m.alder_s)} siden
                  </span>
                </div>
              {/each}
            </div>
          {/if}
        </div>
      </Card>

      <!-- Noder -->
      <Card
        title="Noder"
        subtitle="Sett kallenavn, slå på lampedriver per PCA9685, eller hopp direkte til Kabling."
      >
        {#if !alleNoder.length}
          <p class="text-xs text-muted-foreground">Ingen noder meldt fra master ennå.</p>
        {:else}
          <div class="space-y-2.5">
            {#each alleNoder as n (n.mac)}
              {@const alias = aliasFor(n.mac, draft.noder)}
              {@const ordrer = draft.portKart.ordrer[n.mac.toLowerCase()] || 0}
              {@const pcas = (n.i2c || []).filter((a) => (PCA_ADRESSER as readonly string[]).includes(a))}
              {@const drivere = driverBrikkerForMac(n.mac, draft.noder)}
              <div class="rounded-md border border-border bg-background/60 p-3 space-y-2.5">
                <div class="flex flex-wrap items-center justify-between gap-2">
                  <div class="flex flex-wrap items-center gap-2">
                    <strong class="font-mono text-sm">
                      {alias || n.mac}
                    </strong>
                    {#if alias}
                      <span class="font-mono text-[11px] text-muted-foreground">{n.mac}</span>
                    {/if}
                    {#if !rosterFersk}
                      <Badge variant="warn">ukjent (master stille)</Badge>
                    {:else}
                      <Badge variant={n.online ? "ok" : "warn"}>
                        {n.online ? "online" : "offline"}
                      </Badge>
                    {/if}
                    {#if n.safe}
                      <Badge variant="warn">SIKKER TILSTAND</Badge>
                    {/if}
                    {#if n.fw}
                      <Badge variant={fwErEldre(n.bygget) ? "amber" : "muted"} class="font-mono">
                        v{n.fw}{n.bygget ? ` · ${n.bygget}` : ""}
                      </Badge>
                    {/if}
                  </div>
                  <div class="flex items-center gap-1.5">
                    <Button size="xs" variant="ghost" onclick={() => onnavigate("kabling", { node: n.mac })}>
                      Kabling →
                    </Button>
                    <Button size="xs" onclick={() => onBlink(n.mac)}>
                      <Eye class="w-3 h-3" /> Blink
                    </Button>
                    {#if fwInfo && n.online && !n.bygget && !live.otaKo.kjorer}
                      <Button size="xs" onclick={() => sporOtaEnhet(n.mac)}>
                        OTA
                      </Button>
                    {/if}
                    <Button size="xs" variant="ghost" onclick={() => sporGlemNode(n.mac)} title="Fjern node">
                      <Trash2 class="w-3 h-3 text-warn" />
                    </Button>
                  </div>
                </div>

                <div class="flex flex-wrap items-center gap-2">
                  <input
                    class="w-44 rounded border border-border bg-card px-2 py-1 font-mono text-xs uppercase focus:outline-none focus:border-primary"
                    placeholder="KALLENAVN"
                    value={aliasUtkast[n.mac] ?? alias ?? ""}
                    oninput={(e) => (aliasUtkast[n.mac] = e.currentTarget.value)}
                    onkeydown={(e) => e.key === "Enter" && onLagreAlias(n.mac)}
                  />
                  <Button size="xs" onclick={() => onLagreAlias(n.mac)}>
                    Lagre navn
                  </Button>
                  <span class="text-[11px] font-mono text-muted-foreground ml-auto tabular">
                    Brikker: {(n.i2c || []).join(", ") || "ingen"} ·
                    <span class={ordrer > MAX_ORDREPUNKTER ? "text-warn font-bold" : ordrer > WARN_ORDREPUNKTER ? "text-amber" : ""}>
                      {ordrer}/{MAX_ORDREPUNKTER} ordrepkt
                    </span>
                  </span>
                </div>

                {#if pcas.length}
                  <div class="flex flex-wrap items-center gap-3 text-[11.5px] text-muted-foreground pt-1 border-t border-border/60">
                    <span>Utganger via lampedriver:</span>
                    {#each pcas as addr}
                      <label class="inline-flex items-center gap-1.5 cursor-pointer font-mono text-foreground">
                        <input
                          type="checkbox"
                          checked={drivere.includes(addr)}
                          disabled={!alias}
                          onchange={(e) => onToggleDriver(n.mac, addr, e.currentTarget.checked)}
                        />
                        {addr}
                      </label>
                    {/each}
                    {#if !alias}
                      <span class="text-[11px] text-muted-foreground">(gi noden et kallenavn først)</span>
                    {/if}
                  </div>
                {/if}
              </div>
            {/each}
          </div>
        {/if}

        {#if foreldrelose.length}
          <div class="mt-3 pt-3 border-t border-border space-y-2">
            <div class="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Foreldreløse kallenavn (aldri sett)
            </div>
            {#each foreldrelose as [al, v]}
              <div class="flex items-center justify-between rounded border border-border bg-background/50 px-3 py-2 text-xs">
                <span>
                  <strong class="font-mono">{al}</strong>
                  <span class="font-mono text-muted-foreground ml-2">{v.mac}</span>
                </span>
                <Button size="xs" variant="destructive" onclick={() => sporSlettAlias(al, v.mac)}>
                  Slett kallenavn
                </Button>
              </div>
            {/each}
          </div>
        {/if}
      </Card>
    </div>

    <!-- Høyre kolonne: Hurtighandlinger, Lampeprøve, OTA, Pi -->
    <div class="space-y-4">
      <!-- Hurtighandlinger & Lampeprøve -->
      <Card title="Drift & Lampeprøve">
        <div class="space-y-3 text-xs">
          <div class="grid grid-cols-2 gap-2">
            <Button
              variant={live.lamptest.running ? "destructive" : "default"}
              disabled={!live.lamptest.running && !!live.lamptest.traad}
              onclick={() => onLamptest(live.lamptest.running ? "stop" : "start")}
            >
              {#if live.lamptest.running}
                <Square class="w-3.5 h-3.5" /> Stopp prøve
              {:else}
                <Lightbulb class="w-3.5 h-3.5 text-amber" /> Lampeprøve
              {/if}
            </Button>
            <Button onclick={onledguide}>
              <Sparkles class="w-3.5 h-3.5 text-ok" /> LED-språk
            </Button>
            <a
              href="/api/backup"
              class="inline-flex items-center justify-center gap-1.5 rounded-md border border-border-strong bg-secondary px-3 py-1.5 text-xs font-medium text-foreground hover:border-primary no-underline"
            >
              <Download class="w-3.5 h-3.5" /> Backup
            </a>
            <a
              href="/api/diagnostikk"
              class="inline-flex items-center justify-center gap-1.5 rounded-md border border-border-strong bg-secondary px-3 py-1.5 text-xs font-medium text-foreground hover:border-primary no-underline"
            >
              <FileArchive class="w-3.5 h-3.5" /> Diagnostikk-zip
            </a>
          </div>

          {#if live.lamptest.progress}
            <div class="rounded border border-border bg-background/60 px-2.5 py-2 text-[11.5px] font-mono tabular">
              <div class="text-muted-foreground">
                Lampeprøve ({live.lamptest.i}/{live.lamptest.total}):
                <span class={live.lamptest.progress.startsWith("AVBRUTT") ? "text-warn font-semibold" : "text-foreground"}>
                  {live.lamptest.progress}
                </span>
              </div>
              {#if live.lamptestIgjenSek != null}
                <div class="text-[11px] text-amber mt-0.5">
                  Sikkerhetsstopp om {fmtKlokkeNed(live.lamptestIgjenSek)}
                </div>
              {/if}
            </div>
          {/if}
        </div>
      </Card>

      <!-- Firmware OTA -->
      <Card
        title="Firmware (OTA)"
        subtitle="Felles binær for master og noder (bygg med bygg-ota.sh)."
      >
        {#snippet actions()}
          <input
            bind:this={otaInput}
            type="file"
            accept=".bin"
            class="hidden"
            onchange={onOtaFil}
          />
          <Button size="xs" disabled={live.otaKo.kjorer} onclick={() => otaInput?.click()}>
            <Upload class="w-3 h-3" /> Last opp .bin
          </Button>
        {/snippet}

        <div class="space-y-3 text-xs">
          <div class="flex items-center justify-between rounded border border-border bg-background/60 px-2.5 py-2 font-mono text-[11.5px]">
            <span class="text-muted-foreground">Klar på Pi:</span>
            <span>
              {fwInfo
                ? `${fwInfo.stempel || "uten stempel"} (${Math.round(fwInfo.bytes / 1024)} kB)`
                : "ingen firmware"}
            </span>
          </div>

          {#if live.otaKo.kjorer}
            {@const nr = live.otaKo.ferdig.length + live.otaKo.feilet.length + (live.otaKo.aktiv ? 1 : 0)}
            <div class="space-y-2">
              <div class="flex items-center justify-between">
                <strong>Oppdaterer {nr} av {live.otaKo.antall}</strong>
                {#if !live.otaKo.stopp}
                  <Button size="xs" variant="destructive" onclick={onStoppOtaKo}>
                    Stopp etter denne
                  </Button>
                {/if}
              </div>
              <Progress value={nr} max={Math.max(1, live.otaKo.antall)} />
            </div>
          {:else if live.otaKo.kandidater.length}
            {#if live.otaKo.hindring}
              <p class="text-amber">
                {live.otaKo.kandidater.length} utdaterte noder — kan ikke starte kø: {live.otaKo.hindring}
              </p>
            {:else}
              <Button
                variant="primary"
                size="sm"
                class="w-full"
                onclick={() => sporOtaKo(live.otaKo.kandidater.length)}
              >
                <Play class="w-3.5 h-3.5" />
                Oppdater alle utdaterte noder ({live.otaKo.kandidater.length})
              </Button>
            {/if}
          {:else}
            <p class="text-[11.5px] text-muted-foreground">
              {!live.otaKo.fw_finnes
                ? "Last opp en firmware-binær først."
                : !live.otaKo.fw_stempel
                  ? "Firmwaren mangler byggestempel (kan ikke auto-køes)."
                  : `Alle online noder kjører ${live.otaKo.fw_stempel}.`}
            </p>
          {/if}

          {#if live.otaKo.ferdig.length || live.otaKo.feilet.length || live.otaKo.aktiv || live.otaKo.avbrutt.length}
            <ul class="space-y-1 font-mono text-[11px] border-t border-border pt-2">
              {#each live.otaKo.ferdig as n}
                <li class="text-ok">✓ {n.alias || n.mac} ({n.sekunder}s)</li>
              {/each}
              {#each live.otaKo.feilet as n}
                <li class="text-warn">✕ {n.alias || n.mac} — {n.grunn}</li>
              {/each}
              {#if live.otaKo.aktiv}
                <li class="text-amber">⟳ {live.otaKo.aktiv.alias || live.otaKo.aktiv.mac} henter firmware…</li>
              {/if}
              {#each live.otaKo.venter as n}
                <li class="text-muted-foreground">· {n.alias || n.mac} venter</li>
              {/each}
              {#each live.otaKo.avbrutt as n}
                <li class="text-muted-foreground">– {n.alias || n.mac} avbrutt</li>
              {/each}
            </ul>
          {/if}
        </div>
      </Card>

      <!-- Pi-detaljer -->
      {#if live.pi}
        <Card title="Raspberry Pi" subtitle={live.pi.modell || "Systemstatus"}>
          <div class="space-y-2.5 text-xs">
            {#if live.pi.throttled?.naa?.length}
              <div class="rounded border border-warn/50 bg-warn/15 px-2.5 py-1.5 text-warn font-semibold">
                ⚠ {live.pi.throttled.naa.join(", ").toUpperCase()} — sjekk strømforsyningen!
              </div>
            {/if}
            {#if live.pi.throttled?.historikk?.length}
              <div class="rounded border border-amber/40 bg-amber/10 px-2.5 py-1.5 text-amber text-[11.5px]">
                Tidligere struping siden oppstart: {live.pi.throttled.historikk.join(", ")}
              </div>
            {/if}

            <div class="grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-[11.5px] tabular">
              {#if live.pi.oppetid_s != null}
                <span class="text-muted-foreground">Oppetid</span>
                <span>{fmtSek(live.pi.oppetid_s)}</span>
              {/if}
              {#if live.pi.last?.length}
                <span class="text-muted-foreground">Last (1/5/15m)</span>
                <span>{live.pi.last.map((x) => Number(x).toFixed(2)).join(" · ")}</span>
              {/if}
              {#if live.pi.mem}
                <span class="text-muted-foreground">Minne ledig</span>
                <span>{live.pi.mem.ledig_mb} / {live.pi.mem.total_mb} MB</span>
              {/if}
              {#if live.pi.disk}
                <span class="text-muted-foreground">Disk ledig</span>
                <span>{live.pi.disk.ledig_gb} / {live.pi.disk.total_gb} GB</span>
              {/if}
              {#if live.pi.ips?.length}
                <span class="text-muted-foreground">Nettverk</span>
                <span class="break-all">
                  {live.pi.ips
                    .map((i) => `${i.ifname}: ${i.addrs.join(", ")}`)
                    .join(" · ")}
                </span>
              {/if}
              <span class="text-muted-foreground">Klokke</span>
              <span>
                {live.pi.klokke}
                {live.pi.ntp
                  ? "(NTP)"
                  : live.pi.klokke_stilt
                    ? `(stilt ${live.pi.klokke_stilt.naar})`
                    : ""}
              </span>
              {#if live.pi.hal_ui}
                <span class="text-muted-foreground">HAL-UI</span>
                <span>
                  {live.pi.hal_ui.kort} ({live.pi.hal_ui.gren})
                  {#if live.pi.hal_ui.ukommittert}
                    <span class="text-warn">+ukom.</span>
                  {/if}
                </span>
              {/if}
            </div>

            {#if live.pi.tjenester}
              <div class="flex flex-wrap gap-1.5 pt-1">
                {#each Object.entries(live.pi.tjenester) as [tj, st]}
                  <Badge variant={st === "active" ? "ok" : "warn"} class="font-mono">
                    {tj}: {st === "active" ? "ok" : st}
                  </Badge>
                {/each}
              </div>
            {/if}

            {#if live.pi.klienter?.length}
              <div class="pt-2 border-t border-border overflow-x-auto">
                <div class="text-[11px] font-semibold text-muted-foreground mb-1">
                  AP-klienter ({live.pi.klienter.length})
                </div>
                <table class="w-full text-[11px] font-mono tabular">
                  <thead>
                    <tr class="text-left text-muted-foreground border-b border-border">
                      <th class="py-1 pr-2">Navn</th>
                      <th class="py-1 pr-2">IP</th>
                      <th class="py-1 pr-2">Signal</th>
                      <th class="py-1">Tid</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each live.pi.klienter as c}
                      {@const erM = live.master.mac && c.mac.replace(/:/g, "") === live.master.mac}
                      <tr class="border-b border-border/50 last:border-0">
                        <td class="py-1 pr-2">
                          {c.navn || "?"}
                          {#if erM}<span class="text-ok ml-1">master</span>{/if}
                        </td>
                        <td class="py-1 pr-2">{c.ip || "–"}</td>
                        <td class="py-1 pr-2">{c.signal != null ? `${c.signal} dBm` : "–"}</td>
                        <td class="py-1">{fmtSek(c.tid_s)}</td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {/if}
          </div>
        </Card>
      {/if}
    </div>
  </div>
</div>

<ConfirmDialog
  bind:open={bekreft.open}
  title={bekreft.title}
  description={bekreft.desc}
  destructive={bekreft.destructive}
  onconfirm={bekreft.fn}
/>
