<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import {
    Download,
    Pause,
    Play,
    RefreshCw,
    Search,
    Terminal,
    X,
  } from "@lucide/svelte";
  import { toast } from "svelte-sonner";
  import Badge from "$components/ui/Badge.svelte";
  import Button from "$components/ui/Button.svelte";
  import Card from "$components/ui/Card.svelte";
  import Switch from "$components/ui/Switch.svelte";
  import { hentHendelser, settHendelserAktiv } from "$lib/api/klient";
  import { live } from "$lib/stores/live.svelte";
  import type { HendelseRad } from "$lib/types";

  const HURTIGFILTRE = [
    { id: "", label: "Alle" },
    { id: "togvei", label: "togvei" },
    { id: "avvist", label: "avvist" },
    { id: "sporveksel", label: "sporveksel" },
    { id: "sporfelt", label: "sporfelt" },
    { id: "master", label: "master" },
  ] as const;

  let historikk = $state<HendelseRad[]>([]);
  let kuttet = $state(false);
  let laster = $state(false);
  let hurtig = $state("");
  let sok = $state("");
  let pauset = $state(false);
  let pausetSnapshot = $state<HendelseRad[] | null>(null);
  let bytterLogging = $state(false);
  let loggBoks = $state<HTMLDivElement | null>(null);
  let sokTimer: ReturnType<typeof setTimeout> | null = null;
  let henteSekvens = 0;

  // Serveren tar én filterstreng; bruk sok hvis satt, ellers hurtigfilter
  let serverFilter = $derived((sok.trim() || hurtig).trim());

  function radNokkel(r: HendelseRad): string {
    return `${r.ts}|${r.tema}|${r.data}`;
  }

  async function lastHistorikk(filterStr = serverFilter) {
    const seq = ++henteSekvens;
    laster = true;
    try {
      const res = await hentHendelser(300, filterStr);
      if (seq !== henteSekvens) return;
      historikk = res.hendelser || [];
      kuttet = !!res.kuttet;
    } catch (e: any) {
      if (seq === henteSekvens) {
        toast.error(e?.message || "Klarte ikke å hente hendelseslogg");
      }
    } finally {
      if (seq === henteSekvens) laster = false;
    }
  }

  onMount(() => {
    lastHistorikk("");
  });

  onDestroy(() => {
    if (sokTimer) clearTimeout(sokTimer);
  });

  function velgHurtig(id: string) {
    hurtig = id;
    if (sokTimer) clearTimeout(sokTimer);
    lastHistorikk((sok.trim() || id).trim());
  }

  function onSokInput(val: string) {
    sok = val;
    if (sokTimer) clearTimeout(sokTimer);
    sokTimer = setTimeout(() => {
      lastHistorikk((val.trim() || hurtig).trim());
    }, 250);
  }

  // Slå sammen serverfiltrert historikk + nye SSE-hendelser uten duplikater
  let alleRader = $derived.by(() => {
    const sett = new Set<string>();
    const ut: HendelseRad[] = [];
    for (const r of [...historikk, ...live.sisteHendelser]) {
      const k = radNokkel(r);
      if (sett.has(k)) continue;
      sett.add(k);
      ut.push(r);
    }
    return ut.slice(-500);
  });

  let synligeKilde = $derived(pauset && pausetSnapshot ? pausetSnapshot : alleRader);

  let nyeMensPauset = $derived(
    pauset && pausetSnapshot
      ? Math.max(0, alleRader.length - pausetSnapshot.length)
      : 0
  );

  let filtrerte = $derived.by(() => {
    const f1 = hurtig.toLowerCase();
    const f2 = sok.trim().toLowerCase();
    return synligeKilde.filter((r) => {
      const hay = `${r.tema} ${r.data}`.toLowerCase();
      if (f1 && !hay.includes(f1)) return false;
      if (f2 && !hay.includes(f2)) return false;
      return true;
    });
  });

  $effect(() => {
    const _len = filtrerte.length;
    if (!pauset && loggBoks && _len > 0) {
      queueMicrotask(() => {
        if (loggBoks) loggBoks.scrollTop = loggBoks.scrollHeight;
      });
    }
  });

  function togglePause() {
    if (!pauset) {
      pausetSnapshot = [...alleRader];
      pauset = true;
    } else {
      pauset = false;
      pausetSnapshot = null;
    }
  }

  async function toggleSdLogging(ny: boolean) {
    bytterLogging = true;
    try {
      await settHendelserAktiv(ny);
      toast.success(
        ny ? "Hendelseslogging skrudd på" : "Hendelseslogging skrudd av"
      );
    } catch (e: any) {
      toast.error(e?.message || "Klarte ikke å endre logging");
    } finally {
      bytterLogging = false;
    }
  }

  function fmtTid(ts: number): string {
    const d = new Date(ts * 1000);
    const pad = (n: number, w = 2) => String(n).padStart(w, "0");
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`;
  }

  function temaFarge(r: HendelseRad): string {
    const t = `${r.tema} ${r.data}`.toLowerCase();
    if (
      t.includes("avvist") ||
      t.includes("feil") ||
      t.includes("conflict") ||
      t.includes("offline")
    ) {
      return "text-warn";
    }
    if (t.includes("sikret") || t.includes("online") || t.includes("ok")) {
      return "text-ok";
    }
    if (t.includes("utlos") || t.includes("varsel") || t.includes("stopp")) {
      return "text-amber";
    }
    return "text-inn";
  }
</script>

<div class="flex flex-col gap-3 h-[calc(100vh-112px)] min-h-[420px]">
  <!-- Kontrollinje -->
  <Card class="p-3 flex flex-wrap items-center justify-between gap-3 shrink-0">
    <div class="flex flex-wrap items-center gap-3">
      <label class="flex items-center gap-2 text-xs cursor-pointer">
        <Switch
          checked={live.hendelserAktiv}
          disabled={bytterLogging}
          onchange={toggleSdLogging}
        />
        <span class="font-medium">Lagre til SD-kort (svart boks)</span>
      </label>
      {#if live.hendelserAktiv}
        <Badge variant="ok">Skriver til hendelser.jsonl og strømmer live</Badge>
      {:else}
        <Badge variant="muted">Logging av — slå på for å registrere og strømme hendelser</Badge>
      {/if}
    </div>

    <div class="flex flex-wrap items-center gap-1.5">
      <Button size="xs" variant={pauset ? "primary" : "outline"} onclick={togglePause}>
        {#if pauset}
          <Play class="w-3 h-3" />
          Følg{#if nyeMensPauset > 0} (+{nyeMensPauset}){/if}
        {:else}
          <Pause class="w-3 h-3" />
          Pause
        {/if}
      </Button>
      <Button size="xs" variant="outline" disabled={laster} onclick={() => lastHistorikk()}>
        <RefreshCw class="w-3 h-3 {laster ? 'animate-spin' : ''}" />
        Oppdater
      </Button>
      <a
        href="/api/hendelser/fil"
        class="inline-flex items-center gap-1.5 h-6 px-2 text-xs rounded-md border border-border-strong bg-transparent hover:bg-secondary text-foreground no-underline"
      >
        <Download class="w-3 h-3" />
        Last ned .jsonl
      </a>
    </div>
  </Card>

  <!-- Filterlinje (søker i hele loggen på serveren) -->
  <div class="flex flex-wrap items-center gap-2 shrink-0">
    <div class="flex flex-wrap items-center gap-1">
      {#each HURTIGFILTRE as f}
        <button
          type="button"
          class="px-2.5 py-1 rounded-full text-[11.5px] border cursor-pointer transition-colors {hurtig === f.id
            ? 'border-primary bg-primary/15 text-primary font-semibold'
            : 'border-border bg-card text-muted-foreground hover:text-foreground'}"
          onclick={() => velgHurtig(f.id)}
        >
          {f.label}
        </button>
      {/each}
    </div>

    <div class="relative flex-1 min-w-[180px]">
      <Search class="w-3.5 h-3.5 text-muted-foreground absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
      <input
        type="text"
        value={sok}
        oninput={(e) => onSokInput(e.currentTarget.value)}
        placeholder="Søk i hele loggen (tema eller melding)…"
        class="w-full pl-8 pr-7 py-1 text-xs rounded-md bg-card border border-border"
      />
      {#if sok}
        <button
          type="button"
          class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground cursor-pointer"
          onclick={() => onSokInput("")}
          aria-label="Tøm filter"
        >
          <X class="w-3.5 h-3.5" />
        </button>
      {/if}
    </div>

    <span class="text-[11px] font-mono text-muted-foreground tabular">
      {filtrerte.length} linjer{kuttet ? " (siste 300 treff)" : ""}
    </span>
  </div>

  <!-- Mørk loggkonsoll -->
  <div
    bind:this={loggBoks}
    class="flex-1 min-h-0 overflow-y-auto rounded-lg border border-border bg-[#0b0d11] p-3 font-mono text-[11.5px] leading-relaxed"
  >
    {#if !filtrerte.length}
      <div class="h-full flex flex-col items-center justify-center text-muted-foreground gap-2 py-12 font-sans text-xs">
        <Terminal class="w-6 h-6 opacity-50" />
        <div>
          {alleRader.length === 0
            ? "Ingen hendelser funnet. Slå på SD-kort-logging for å registrere hendelser."
            : "Ingen hendelser matcher filteret."}
        </div>
      </div>
    {:else}
      <div class="space-y-0.5">
        {#each filtrerte as rad, i (`${rad.ts}-${i}`)}
          <div class="flex items-baseline gap-2.5 px-1.5 py-0.5 rounded hover:bg-white/[0.04]">
            <span class="text-muted-foreground/70 shrink-0 tabular">
              {fmtTid(rad.ts)}
            </span>
            <span class="shrink-0 font-semibold {temaFarge(rad)}">
              {rad.tema}
            </span>
            <span class="text-foreground/90 break-all">
              {rad.data}
            </span>
            {#if rad.r}
              <span class="text-[10px] text-muted-foreground/50 shrink-0">retained</span>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
  </div>
</div>
