<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { toast } from "svelte-sonner";
  import AppShell from "$components/layout/AppShell.svelte";
  import CommandPalette from "$components/CommandPalette.svelte";
  import LedGuideDialog from "$components/LedGuideDialog.svelte";
  import { betjenLampeprove } from "$lib/api/klient";
  import { draft } from "$lib/stores/draft.svelte";
  import { live } from "$lib/stores/live.svelte";
  import type { ViewId } from "$lib/types";
  import ForriglingView from "$views/ForriglingView.svelte";
  import HendelsesloggView from "$views/HendelsesloggView.svelte";
  import InnstillingerView from "$views/InnstillingerView.svelte";
  import KablingView from "$views/KablingView.svelte";
  import ObjekterView from "$views/ObjekterView.svelte";
  import OversiktView from "$views/OversiktView.svelte";

  const GYLDIGE: ViewId[] = [
    "oversikt",
    "objekter",
    "kabling",
    "forrigling",
    "logg",
    "innstillinger",
  ];

  function lesHash(): ViewId {
    const raw = (location.hash || "").replace(/^#/, "").trim().toLowerCase();
    // Bakoverkompatible bokmerker fra tidligere UI
    if (raw === "noder") return "oversikt";
    if (raw === "hal") return "objekter";
    if (GYLDIGE.includes(raw as ViewId)) return raw as ViewId;
    return "oversikt";
  }

  let activeView = $state<ViewId>(lesHash());
  let cmdOpen = $state(false);
  let ledGuideOpen = $state(false);

  // Fokus-overføring mellom visninger (fra ⌘K eller Oversikt → Kabling/Objekter/Forrigling)
  let focusRid = $state<number | null>(null);
  let focusNode = $state<string | null>(null);
  let focusTogveiId = $state<string | null>(null);

  function naviger(
    view: ViewId,
    focus?: { rid?: number; node?: string; togveiId?: string }
  ) {
    activeView = view;
    if (location.hash !== `#${view}`) {
      location.hash = `#${view}`;
    }
    if (focus?.rid != null) focusRid = focus.rid;
    if (focus?.node) focusNode = focus.node;
    if (focus?.togveiId) focusTogveiId = focus.togveiId;
  }

  async function toggleLampeprove() {
    const action = live.lamptest.running ? "stop" : "start";
    try {
      await betjenLampeprove(action);
      toast.info(
        action === "start" ? "Lampeprøve startet" : "Avslutter lampeprøve…"
      );
    } catch (e: any) {
      toast.error(e?.message || "Klarte ikke å styre lampeprøven");
    }
  }

  onMount(() => {
    live.start();
    draft.lastAlt(false);

    const onHash = () => {
      activeView = lesHash();
    };
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        cmdOpen = !cmdOpen;
      }
    };
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (draft.harUlagredeEndringer) {
        e.preventDefault();
        e.returnValue = "";
      }
    };

    window.addEventListener("hashchange", onHash);
    window.addEventListener("keydown", onKey);
    window.addEventListener("beforeunload", onBeforeUnload);

    return () => {
      window.removeEventListener("hashchange", onHash);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("beforeunload", onBeforeUnload);
    };
  });

  onDestroy(() => {
    live.stopp();
  });

  // Sjekk streng master-ACK når SSE oppdaterer live.ack
  $effect(() => {
    void live.ack.hal?.version;
    void live.ack.forrigling?.version;
    void live.ack.anlegg?.id;
    void live.anleggAckTeller;
    draft.sjekkAck();
  });

  // Oppdater sidetittel etter anleggs-ID
  $effect(() => {
    const id = draft.anlegg?.id || "";
    document.title = id ? `NSI63${id} — sikringsanlegg` : "NSI63 — sikringsanlegg";
  });

  // Hent ny konfig ved SSE konfig_endret eller gjenoppkobling (snapshotTeller > 1)
  // Oppdaterer alltid server-grunnlaget mens ulagrede utkast bevares (punkt 4 / U4).
  let sistKonfigTeller = 0;
  let sistSnapshotTeller = 0;
  $effect(() => {
    const kTeller = live.konfigVersjonTeller;
    const sTeller = live.snapshotTeller;
    const nyKonfig = kTeller > sistKonfigTeller;
    const nyGjenoppkobling = sTeller > 1 && sTeller > sistSnapshotTeller;
    if (kTeller > sistKonfigTeller) sistKonfigTeller = kTeller;
    if (sTeller > sistSnapshotTeller) sistSnapshotTeller = sTeller;
    if (nyKonfig || nyGjenoppkobling) {
      draft.lastAlt(true);
    }
  });
</script>

<AppShell
  {activeView}
  onnavigate={(v) => naviger(v)}
  onopencmd={() => (cmdOpen = true)}
>
  {#if activeView === "oversikt"}
    <OversiktView
      onnavigate={(v, f) => naviger(v, f)}
      onledguide={() => (ledGuideOpen = true)}
    />
  {:else if activeView === "objekter"}
    <ObjekterView
      {focusRid}
      onclearfocus={() => (focusRid = null)}
    />
  {:else if activeView === "kabling"}
    <KablingView
      {focusNode}
      onclearfocus={() => (focusNode = null)}
    />
  {:else if activeView === "forrigling"}
    <ForriglingView
      {focusTogveiId}
      onclearfocus={() => (focusTogveiId = null)}
    />
  {:else if activeView === "logg"}
    <HendelsesloggView />
  {:else if activeView === "innstillinger"}
    <InnstillingerView />
  {/if}
</AppShell>

<CommandPalette
  bind:open={cmdOpen}
  onnavigate={(v, f) => naviger(v, f)}
  onlamptest={toggleLampeprove}
  onledguide={() => (ledGuideOpen = true)}
/>

<LedGuideDialog bind:open={ledGuideOpen} />
