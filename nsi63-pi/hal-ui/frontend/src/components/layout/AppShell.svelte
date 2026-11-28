<script lang="ts">
  import type { Snippet } from "svelte";
  import { Toaster } from "svelte-sonner";
  import {
    Activity,
    AlertTriangle,
    Cpu,
    Download,
    ExternalLink,
    GitBranch,
    Layers,
    Menu,
    RefreshCw,
    Save,
    Search,
    Settings,
    Terminal,
    WifiOff,
  } from "@lucide/svelte";
  import Button from "$components/ui/Button.svelte";
  import Badge from "$components/ui/Badge.svelte";
  import Dialog from "$components/ui/Dialog.svelte";
  import { betjenLampeprove, stoppOtaKo } from "$lib/api/klient";
  import { fmtKlokkeNed } from "$lib/domain/regler";
  import { draft } from "$lib/stores/draft.svelte";
  import { live } from "$lib/stores/live.svelte";
  import type { ViewId } from "$lib/types";
  import { toast } from "svelte-sonner";

  interface Props {
    activeView: ViewId;
    onnavigate: (view: ViewId) => void;
    onopencmd: () => void;
    children?: Snippet;
  }

  let { activeView, onnavigate, onopencmd, children }: Props = $props();

  let mobilMeny = $state(false);

  const TITLER: Record<ViewId, string> = {
    oversikt: "Oversikt",
    objekter: "Objekter",
    kabling: "Kabling",
    forrigling: "Forrigling & Togveier",
    logg: "Hendelseslogg (Svart boks)",
    innstillinger: "Innstillinger",
  };

  let anleggId = $derived(draft.anlegg?.id || "");
  let stasjonNavn = $derived(draft.anlegg?.navn || anleggId || "NSI63");

  let testmodusPaa = $derived(
    live.master.testmodus === "paa" ||
      (live.master.testmodus == null && !!draft.anleggLagret?.testmodus)
  );

  // Hvilken lagringslinje gjelder aktiv fane?
  let visHalBar = $derived(
    (activeView === "objekter" || activeView === "kabling") &&
      (draft.halDirty ||
        draft.halAck.status === "venter" ||
        draft.halAck.status === "kvittert")
  );
  let visFrBar = $derived(
    activeView === "forrigling" &&
      (draft.forriglingDirty ||
        draft.frAck.status === "venter" ||
        draft.frAck.status === "kvittert")
  );
  let visAnleggBar = $derived(
    activeView === "innstillinger" &&
      (draft.anleggDirty ||
        draft.anleggAck.status === "venter" ||
        draft.anleggAck.status === "kvittert")
  );

  let masterStatusTekst = $derived.by(() => {
    if (live.masterErOnline) return "Master online";
    if (live.sistHortSek != null) return `Master stille (${live.sistHortSek}s)`;
    if (live.master.status === "offline") return "Master offline";
    if (live.master.status === "online") return "Master ikke hørt";
    return `Master ${live.master.status || "ukjent"}`;
  });

  async function stoppLampeprove() {
    try {
      await betjenLampeprove("stop");
    } catch (e: any) {
      toast.error(e?.message || "Klarte ikke å avslutte lampeprøve");
    }
  }

  async function stoppOta() {
    try {
      await stoppOtaKo();
      toast.info("OTA-køen stopper etter pågående node");
    } catch (e: any) {
      toast.error(e?.message || "Klarte ikke å stoppe OTA-køen");
    }
  }

  function velgFane(v: ViewId) {
    mobilMeny = false;
    onnavigate(v);
  }
</script>

<Toaster theme="dark" position="bottom-right" richColors />

<div class="min-h-screen flex flex-col bg-background text-foreground">
  <!-- GLOBAL SIKKERHETSLINJE (utenfor header-flex!) -->
  <div class="sticky top-0 z-40 flex flex-col">
    {#if live.status === "frakoblet"}
      <div
        class="flex flex-wrap items-center justify-between gap-2 px-4 py-2 text-xs font-medium bg-[#5c1c1c] text-[#ffd6d6] border-b border-warn/40"
      >
        <span class="flex items-center gap-2">
          <WifiOff class="w-4 h-4 shrink-0" />
          <strong>MISTET KONTAKT MED PI</strong> — viste data kan være foreldet · kobler til på nytt…
        </span>
        <Button size="xs" variant="outline" onclick={() => live.kobleTilNaa()}>
          <RefreshCw class="w-3 h-3" /> Koble til nå
        </Button>
      </div>
    {/if}

    {#if live.master.conflict}
      <div
        class="flex flex-wrap items-center justify-between gap-2 px-4 py-2 text-xs font-medium bg-[#6e1a1a] text-[#ffe0e0] border-b border-warn/50"
      >
        <span class="flex items-center gap-2">
          <AlertTriangle class="w-4 h-4 shrink-0" />
          <strong>TO MASTERE AKTIVE</strong> — «{live.master.conflict.self}» og «{live.master.conflict.other}» publiserer samtidig. Skru av den ene umiddelbart!
        </span>
      </div>
    {/if}

    {#if testmodusPaa}
      <div
        class="flex flex-wrap items-center justify-between gap-2 px-4 py-2 text-xs font-medium bg-[#6b2910] text-[#ffdecb] border-b border-ut/40"
      >
        <span class="flex items-center gap-2">
          <AlertTriangle class="w-4 h-4 shrink-0" />
          <strong>TESTMODUS AKTIV</strong> — MQTT-kommandoer omgår forriglingen. Stillerapparatet og sikring av togvei er fortsatt forriglet.
        </span>
        <Button size="xs" variant="outline" onclick={() => draft.slaAvTestmodus()}>
          Skru av testmodus
        </Button>
      </div>
    {/if}

    {#if live.lamptest.running}
      <div
        class="flex flex-wrap items-center justify-between gap-2 px-4 py-2 text-xs font-medium bg-[#66450d] text-[#ffebc7] border-b border-amber/40"
      >
        <span class="flex items-center gap-2 tabular">
          <AlertTriangle class="w-4 h-4 shrink-0" />
          <strong>LAMPEPRØVE PÅGÅR</strong> — {live.lamptest.progress || `${live.lamptest.i}/${live.lamptest.total}`}
          {#if live.lamptestIgjenSek != null}
            · sikkerhetsstopp om {fmtKlokkeNed(live.lamptestIgjenSek)}
          {/if}
        </span>
        <Button size="xs" variant="outline" onclick={stoppLampeprove}>
          Avslutt lampeprøve
        </Button>
      </div>
    {/if}

    {#if live.otaKo.kjorer}
      {@const nr = live.otaKo.ferdig.length + live.otaKo.feilet.length + (live.otaKo.aktiv ? 1 : 0)}
      <div
        class="flex flex-wrap items-center justify-between gap-2 px-4 py-2 text-xs font-medium bg-[#0e4548] text-[#cdf4f4] border-b border-[#3cc8c8]/40"
      >
        <span class="flex items-center gap-2 tabular">
          <RefreshCw class="w-3.5 h-3.5 animate-spin shrink-0" />
          <strong>OTA-KØ</strong> — node {nr} av {live.otaKo.antall}
          {#if live.otaKo.aktiv}
            ({live.otaKo.aktiv.alias || live.otaKo.aktiv.mac})
          {/if}
          {#if live.otaKo.feilet.length}
            · {live.otaKo.feilet.length} feilet
          {/if}
          {#if live.otaKo.stopp}
            · stopper etter denne
          {/if}
        </span>
        {#if !live.otaKo.stopp}
          <Button size="xs" variant="outline" onclick={stoppOta}>
            Stopp etter denne
          </Button>
        {/if}
      </div>
    {/if}
  </div>

  <!-- HOVEDSKALL: SIDEBAR + INNHOLD -->
  <div class="flex flex-1 min-h-0">
    <!-- Desktop Sidebar -->
    <aside
      class="hidden md:flex w-56 shrink-0 flex-col border-r border-border bg-card p-3 gap-4"
    >
      <div class="flex items-center gap-2.5 px-1.5 pb-3 border-b border-border">
        <div
          class="w-8 h-8 rounded-md bg-primary text-primary-foreground font-extrabold text-xs grid place-items-center tracking-tight shrink-0"
        >
          {anleggId || "63"}
        </div>
        <div class="min-w-0">
          <div class="font-bold text-xs tracking-wider truncate">
            NSI63{anleggId ? ` · ${stasjonNavn}` : ""}
          </div>
          <div class="text-[11px] text-muted-foreground truncate">
            Sikringsanlegg
          </div>
        </div>
      </div>

      <nav class="flex flex-col gap-4 flex-1">
        <div class="space-y-0.5">
          <div class="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/75">
            Drift
          </div>
          <button
            type="button"
            class="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md text-xs cursor-pointer transition-colors {activeView === 'oversikt' ? 'bg-primary/15 text-primary font-semibold' : 'text-muted-foreground hover:bg-secondary hover:text-foreground'}"
            onclick={() => velgFane("oversikt")}
          >
            <Activity class="w-4 h-4 shrink-0" />
            <span>Oversikt</span>
            <span class="ml-auto font-mono text-[10.5px] px-1.5 py-0.5 rounded-full bg-secondary tabular">
              {live.onlineNodeAntall}/{(live.nodes.nodes || []).length}
            </span>
          </button>
          <button
            type="button"
            class="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md text-xs cursor-pointer transition-colors {activeView === 'logg' ? 'bg-primary/15 text-primary font-semibold' : 'text-muted-foreground hover:bg-secondary hover:text-foreground'}"
            onclick={() => velgFane("logg")}
          >
            <Terminal class="w-4 h-4 shrink-0" />
            <span>Hendelseslogg</span>
            {#if live.hendelserAktiv}
              <span class="ml-auto font-mono text-[10px] px-1.5 py-0.5 rounded-full bg-ok/15 text-ok">
                PÅ
              </span>
            {/if}
          </button>
        </div>

        <div class="space-y-0.5">
          <div class="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/75">
            Konfigurasjon
          </div>
          <button
            type="button"
            class="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md text-xs cursor-pointer transition-colors {activeView === 'objekter' ? 'bg-primary/15 text-primary font-semibold' : 'text-muted-foreground hover:bg-secondary hover:text-foreground'}"
            onclick={() => velgFane("objekter")}
          >
            <Layers class="w-4 h-4 shrink-0" />
            <span>Objekter</span>
            <span class="ml-auto flex items-center gap-1">
              {#if draft.halDirty}
                <span class="w-1.5 h-1.5 rounded-full bg-amber" title="Ulagrede endringer"></span>
              {/if}
              <span class="font-mono text-[10.5px] px-1.5 py-0.5 rounded-full bg-secondary tabular">
                {draft.functions.length}
              </span>
            </span>
          </button>
          <button
            type="button"
            class="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md text-xs cursor-pointer transition-colors {activeView === 'kabling' ? 'bg-primary/15 text-primary font-semibold' : 'text-muted-foreground hover:bg-secondary hover:text-foreground'}"
            onclick={() => velgFane("kabling")}
          >
            <Cpu class="w-4 h-4 shrink-0" />
            <span>Kabling</span>
            {#if draft.portKart.feil.length > 0}
              <span class="ml-auto font-mono text-[10px] px-1.5 py-0.5 rounded-full bg-warn/20 text-warn">
                {draft.portKart.feil.length}
              </span>
            {/if}
          </button>
          <button
            type="button"
            class="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md text-xs cursor-pointer transition-colors {activeView === 'forrigling' ? 'bg-primary/15 text-primary font-semibold' : 'text-muted-foreground hover:bg-secondary hover:text-foreground'}"
            onclick={() => velgFane("forrigling")}
          >
            <GitBranch class="w-4 h-4 shrink-0" />
            <span>Forrigling</span>
            <span class="ml-auto flex items-center gap-1">
              {#if draft.forriglingDirty}
                <span class="w-1.5 h-1.5 rounded-full bg-amber" title="Ulagrede endringer"></span>
              {/if}
              <span class="font-mono text-[10.5px] px-1.5 py-0.5 rounded-full bg-secondary tabular">
                {draft.togveier.length}
              </span>
            </span>
          </button>
        </div>

        <div class="space-y-0.5">
          <div class="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/75">
            Anlegg
          </div>
          <button
            type="button"
            class="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md text-xs cursor-pointer transition-colors {activeView === 'innstillinger' ? 'bg-primary/15 text-primary font-semibold' : 'text-muted-foreground hover:bg-secondary hover:text-foreground'}"
            onclick={() => velgFane("innstillinger")}
          >
            <Settings class="w-4 h-4 shrink-0" />
            <span>Innstillinger</span>
            {#if draft.anleggDirty}
              <span class="ml-auto w-1.5 h-1.5 rounded-full bg-amber"></span>
            {/if}
          </button>
        </div>
      </nav>

      <!-- Bunn: Backup + /panel -->
      <div class="pt-3 border-t border-border space-y-2">
        {#if live.backup.endret}
          <a
            href="/api/backup"
            class="flex items-center justify-between gap-2 rounded-md border border-inn/40 bg-inn/10 px-2.5 py-2 text-[11.5px] text-inn hover:bg-inn/20 no-underline transition-colors"
            title={live.backup.sist
              ? `Endret siden siste backup (${live.backup.hva.join(", ")})`
              : "Ingen backup lastet ned fra denne Pi-en ennå"}
          >
            <span class="flex items-center gap-1.5 font-medium truncate">
              <Download class="w-3.5 h-3.5 shrink-0" />
              Backup utdatert
            </span>
            <span class="text-[10px] underline shrink-0">Last ned</span>
          </a>
        {/if}

        <a
          href="/panel"
          target="_blank"
          class="flex items-center justify-between rounded-md border border-border bg-secondary px-2.5 py-2 text-xs font-medium text-foreground hover:border-primary hover:text-primary no-underline transition-colors"
        >
          <span>Åpne /panel</span>
          <ExternalLink class="w-3.5 h-3.5" />
        </a>
      </div>
    </aside>

    <!-- Mobil / Nettbrett navigasjonsskuff -->
    <Dialog bind:open={mobilMeny} side="left" title={`NSI63 ${anleggId}`}>
      <div class="flex flex-col gap-1">
        {#each [
          ["oversikt", "Oversikt"],
          ["objekter", "Objekter"],
          ["kabling", "Kabling"],
          ["forrigling", "Forrigling"],
          ["logg", "Hendelseslogg"],
          ["innstillinger", "Innstillinger"],
        ] as [id, lbl]}
          <button
            type="button"
            class="w-full text-left px-3 py-2 rounded-md text-xs cursor-pointer {activeView === id ? 'bg-primary/15 text-primary font-semibold' : 'text-muted-foreground hover:bg-secondary hover:text-foreground'}"
            onclick={() => velgFane(id as ViewId)}
          >
            {lbl}
          </button>
        {/each}
        <div class="pt-3 mt-3 border-t border-border space-y-2">
          {#if live.backup.endret}
            <a
              href="/api/backup"
              class="block rounded-md border border-inn/40 bg-inn/10 px-3 py-2 text-xs text-inn no-underline"
            >
              Last ned backup (utdatert)
            </a>
          {/if}
          <a
            href="/panel"
            target="_blank"
            class="block rounded-md border border-border bg-secondary px-3 py-2 text-xs text-foreground no-underline"
          >
            Åpne /panel ↗
          </a>
        </div>
      </div>
    </Dialog>

    <!-- Hovedkolonne -->
    <div class="flex-1 flex flex-col min-w-0">
      <!-- Topplinje -->
      <header
        class="h-12 shrink-0 border-b border-border bg-card/70 px-4 flex items-center justify-between gap-3"
      >
        <div class="flex items-center gap-2.5 min-w-0">
          <Button
            variant="ghost"
            size="icon"
            class="md:hidden"
            aria-label="Meny"
            onclick={() => (mobilMeny = true)}
          >
            <Menu class="w-4 h-4" />
          </Button>
          <h1 class="text-sm font-semibold truncate">{TITLER[activeView]}</h1>
        </div>

        <div class="flex items-center gap-2.5">
          {#if live.backup.endret}
            <a
              href="/api/backup"
              class="md:hidden inline-flex items-center gap-1 rounded-full border border-inn/50 bg-inn/15 px-2 py-0.5 text-[11px] font-medium text-inn no-underline"
              title="Backup er utdatert — klikk for å laste ned"
            >
              <Download class="w-3 h-3" />
              <span>Backup</span>
            </a>
          {/if}
          <button
            type="button"
            onclick={onopencmd}
            class="hidden sm:inline-flex items-center gap-2 rounded-md border border-border bg-background px-2.5 py-1 text-xs text-muted-foreground hover:border-border-strong hover:text-foreground cursor-pointer"
          >
            <Search class="w-3.5 h-3.5" />
            <span>Søk objekter, noder…</span>
            <kbd class="font-mono text-[10px] px-1 rounded bg-secondary border border-border">
              ⌘K
            </kbd>
          </button>

          <div
            class="inline-flex items-center gap-2 rounded-full border border-border bg-secondary px-2.5 py-1 text-[11.5px] tabular"
            title={live.status === "tilkoblet"
              ? "Sanntidsstrøm tilkoblet"
              : "Sanntidsstrøm frakoblet"}
          >
            <span
              class="w-2 h-2 rounded-full {live.status !== 'tilkoblet'
                ? 'bg-warn'
                : live.masterErOnline
                  ? 'bg-ok'
                  : 'bg-amber'}"
            ></span>
            <span class="text-muted-foreground">
              {masterStatusTekst}
              · {live.onlineNodeAntall}
              {live.onlineNodeAntall === 1 ? "node" : "noder"}
            </span>
          </div>
        </div>
      </header>

      <!-- Sideinnhold -->
      <main class="flex-1 p-4 md:p-5 max-w-[1440px] w-full mx-auto">
        {@render children?.()}
      </main>

      <!-- Sticky lagringslinje for Objekter / Kabling -->
      {#if visHalBar}
        {@const pct = Math.round((draft.halBytesAnslag / Math.max(1, draft.masterBufferMaks)) * 100)}
        <div
          class="sticky bottom-0 z-30 border-t border-primary/70 bg-[#1a222d] px-4 py-2.5 flex flex-wrap items-center justify-between gap-3 text-xs shadow-2xl"
        >
          <div class="flex flex-wrap items-center gap-2.5 tabular">
            {#if draft.halDirty}
              <Badge variant="amber">● Ulagrede objektendringer</Badge>
            {:else if draft.halAck.status === "venter"}
              <Badge variant="amber">
                {draft.halAck.tidsutlopt
                  ? `Lagret ${draft.halAck.version} — venter fortsatt på master-kvittering`
                  : `Lagret ${draft.halAck.version} — venter på master…`}
              </Badge>
            {:else if draft.halAck.status === "kvittert"}
              <Badge variant="ok">
                ✓ Master kvitterte {draft.halAck.version}
                {#if draft.halAck.antall != null}({draft.halAck.antall} objekter){/if}
              </Badge>
            {/if}

            {#if draft.halKonflikt}
              <Badge variant="warn">⚠ Endret på serveren — Forkast for fersk versjon</Badge>
            {/if}

            {#if draft.halVersjon}
              <span class="text-muted-foreground font-mono text-[11px]">
                v {draft.halVersjon}
              </span>
            {/if}

            <span class="text-muted-foreground font-mono text-[11px]">
              Anslag: ~{(draft.halBytesAnslag / 1024).toFixed(1)} / {(draft.masterBufferMaks / 1024).toFixed(1)} kB ({pct}%)
            </span>

            {#if draft.portKart.feil.length > 0}
              <Badge variant="warn">
                ⚠ {draft.portKart.feil.length} portfeil
              </Badge>
            {/if}
          </div>

          <div class="flex items-center gap-2">
            {#if draft.halDirty}
              <Button variant="ghost" size="sm" onclick={() => draft.forkastHal()}>
                Forkast
              </Button>
              <Button
                variant="primary"
                size="sm"
                disabled={draft.halAck.status === "lagrer" || draft.portKart.feil.length > 0}
                onclick={() => draft.lagreHalDraft()}
              >
                <Save class="w-3.5 h-3.5" />
                Lagre og publiser
              </Button>
            {:else}
              <Button
                variant="ghost"
                size="xs"
                onclick={() => (draft.halAck = { status: "ingen" })}
              >
                Lukk
              </Button>
            {/if}
          </div>
        </div>
      {/if}

      <!-- Sticky lagringslinje for Forrigling -->
      {#if visFrBar}
        <div
          class="sticky bottom-0 z-30 border-t border-primary/70 bg-[#1a222d] px-4 py-2.5 flex flex-wrap items-center justify-between gap-3 text-xs shadow-2xl"
        >
          <div class="flex flex-wrap items-center gap-2.5 tabular">
            {#if draft.forriglingDirty}
              <Badge variant="amber">● Ulagrede forriglingsendringer</Badge>
            {:else if draft.frAck.status === "venter"}
              <Badge variant="amber">
                {draft.frAck.tidsutlopt
                  ? `Lagret ${draft.frAck.version} — venter fortsatt på master-kvittering`
                  : `Lagret ${draft.frAck.version} — venter på master…`}
              </Badge>
            {:else if draft.frAck.status === "kvittert"}
              <Badge variant="ok">
                ✓ Master kvitterte {draft.frAck.version}
                {#if draft.frAck.antall != null}({draft.frAck.antall} togveier){/if}
              </Badge>
            {/if}
            {#if draft.forriglingKonflikt}
              <Badge variant="warn">⚠ Endret på serveren — Forkast for fersk versjon</Badge>
            {/if}
            {#if draft.forriglingVersjon}
              <span class="text-muted-foreground font-mono text-[11px]">
                v {draft.forriglingVersjon}
              </span>
            {/if}
            <span class="text-muted-foreground font-mono text-[11px]">
              Anslag: ~{(draft.forriglingBytesAnslag / 1024).toFixed(1)} / {(draft.masterBufferMaks / 1024).toFixed(1)} kB
            </span>
          </div>
          <div class="flex items-center gap-2">
            {#if draft.forriglingDirty}
              <Button variant="ghost" size="sm" onclick={() => draft.forkastForrigling()}>
                Forkast
              </Button>
              <Button
                variant="primary"
                size="sm"
                disabled={draft.frAck.status === "lagrer"}
                onclick={() => draft.lagreForriglingDraft()}
              >
                <Save class="w-3.5 h-3.5" />
                Lagre og publiser
              </Button>
            {:else}
              <Button
                variant="ghost"
                size="xs"
                onclick={() => (draft.frAck = { status: "ingen" })}
              >
                Lukk
              </Button>
            {/if}
          </div>
        </div>
      {/if}

      <!-- Sticky lagringslinje for Innstillinger -->
      {#if visAnleggBar}
        <div
          class="sticky bottom-0 z-30 border-t border-primary/70 bg-[#1a222d] px-4 py-2.5 flex flex-wrap items-center justify-between gap-3 text-xs shadow-2xl"
        >
          <div class="flex flex-wrap items-center gap-2.5 tabular">
            {#if draft.anleggDirty}
              <Badge variant="amber">● Ulagrede anleggs- eller tidslåsendringer</Badge>
            {:else if draft.anleggAck.status === "venter"}
              <Badge variant="amber">
                {draft.anleggAck.tidsutlopt
                  ? `Lagret (${draft.anleggAck.version}) — venter fortsatt på master-kvittering`
                  : `Lagret (${draft.anleggAck.version}) — venter på master…`}
              </Badge>
            {:else if draft.anleggAck.status === "kvittert"}
              <Badge variant="ok">
                ✓ Master kvitterte anlegg ({draft.anleggAck.version})
              </Badge>
            {/if}
            {#if draft.anleggKonflikt}
              <Badge variant="warn">⚠ Endret på serveren — Forkast for fersk versjon</Badge>
            {/if}
          </div>
          <div class="flex items-center gap-2">
            {#if draft.anleggDirty}
              <Button variant="ghost" size="sm" onclick={() => draft.forkastAnlegg()}>
                Forkast
              </Button>
              <Button
                variant="primary"
                size="sm"
                onclick={() => {
                  window.dispatchEvent(new CustomEvent("nsi63:lagre-anlegg"));
                }}
              >
                <Save class="w-3.5 h-3.5" />
                Lagre innstillinger
              </Button>
            {:else}
              <Button
                variant="ghost"
                size="xs"
                onclick={() => (draft.anleggAck = { status: "ingen" })}
              >
                Lukk
              </Button>
            {/if}
          </div>
        </div>
      {/if}
    </div>
  </div>
</div>
