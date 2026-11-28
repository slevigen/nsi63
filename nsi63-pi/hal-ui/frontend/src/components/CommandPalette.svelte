<script lang="ts">
  import { Dialog as BitsDialog } from "bits-ui";
  import {
    Cpu,
    Download,
    ExternalLink,
    GitBranch,
    Layers,
    Lightbulb,
    Search,
    Sparkles,
  } from "@lucide/svelte";
  import { aliasFor } from "$lib/domain/regler";
  import { draft } from "$lib/stores/draft.svelte";
  import { live } from "$lib/stores/live.svelte";
  import type { ViewId } from "$lib/types";

  interface Props {
    open?: boolean;
    onnavigate: (view: ViewId, focus?: { rid?: number; node?: string; togveiId?: string }) => void;
    onlamptest: () => void;
    onledguide: () => void;
  }

  let {
    open = $bindable(false),
    onnavigate,
    onlamptest,
    onledguide,
  }: Props = $props();

  let q = $state("");
  let inputEl = $state<HTMLInputElement | null>(null);

  $effect(() => {
    if (open) {
      q = "";
      setTimeout(() => inputEl?.focus(), 20);
    }
  });

  let needle = $derived(q.trim().toLowerCase());

  let objektTreff = $derived(
    draft.functions
      .filter((f) => {
        if (!needle) return true;
        return (
          (f.id || "").toLowerCase().includes(needle) ||
          (f.type || "").toLowerCase().includes(needle) ||
          (f.navn || "").toLowerCase().includes(needle)
        );
      })
      .slice(0, 8)
  );

  let nodeTreff = $derived.by(() => {
    const sett = new Map<string, { label: string; mac: string }>();
    for (const n of live.nodes.nodes || []) {
      const a = aliasFor(n.mac, draft.noder);
      sett.set(n.mac, { label: a || n.mac, mac: n.mac });
    }
    for (const [k, v] of Object.entries(draft.noder)) {
      if (v?.mac && !sett.has(v.mac)) {
        sett.set(v.mac, {
          label: k === v.mac ? v.mac : k,
          mac: v.mac,
        });
      }
    }
    return [...sett.values()]
      .filter(
        (x) =>
          !needle ||
          x.label.toLowerCase().includes(needle) ||
          x.mac.toLowerCase().includes(needle)
      )
      .slice(0, 5);
  });

  let togveiTreff = $derived(
    draft.togveier
      .filter(
        (t) =>
          !needle ||
          (t.id || "").toLowerCase().includes(needle) ||
          (t.start || "").toLowerCase().includes(needle)
      )
      .slice(0, 5)
  );

  function velg(fn: () => void) {
    open = false;
    fn();
  }
</script>

<BitsDialog.Root bind:open>
  <BitsDialog.Portal>
    <BitsDialog.Overlay class="fixed inset-0 z-50 bg-black/65 backdrop-blur-[1px]" />
    <BitsDialog.Content
      class="fixed left-1/2 top-[15vh] z-50 w-[calc(100%-24px)] max-w-lg -translate-x-1/2 rounded-lg border border-border-strong bg-card shadow-2xl overflow-hidden"
    >
      <div class="flex items-center gap-2 border-b border-border px-3 py-2.5">
        <Search class="w-4 h-4 text-muted-foreground shrink-0" />
        <input
          bind:this={inputEl}
          bind:value={q}
          placeholder="Søk objekter, noder, togveier eller handlinger…"
          class="w-full bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
        />
        <kbd class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-secondary border border-border text-muted-foreground">
          ESC
        </kbd>
      </div>

      <div class="max-h-[60vh] overflow-y-auto p-2 space-y-3 text-xs">
        {#if !needle}
          <div>
            <div class="px-2 py-1 text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
              Hurtighandlinger
            </div>
            <button
              type="button"
              class="w-full flex items-center gap-2 rounded-md px-2.5 py-2 hover:bg-secondary text-left cursor-pointer"
              onclick={() => velg(onlamptest)}
            >
              <Lightbulb class="w-3.5 h-3.5 text-amber" />
              <span>{live.lamptest.running ? "Avslutt lampeprøve" : "Start lampeprøve"}</span>
            </button>
            <button
              type="button"
              class="w-full flex items-center gap-2 rounded-md px-2.5 py-2 hover:bg-secondary text-left cursor-pointer"
              onclick={() => velg(() => { location.href = "/api/backup"; })}
            >
              <Download class="w-3.5 h-3.5 text-inn" />
              <span>Last ned komplett backup</span>
            </button>
            <button
              type="button"
              class="w-full flex items-center gap-2 rounded-md px-2.5 py-2 hover:bg-secondary text-left cursor-pointer"
              onclick={() => velg(onledguide)}
            >
              <Sparkles class="w-3.5 h-3.5 text-ok" />
              <span>Vis LED-språk (M5 AtomS3)</span>
            </button>
            <a
              href="/panel"
              target="_blank"
              class="w-full flex items-center gap-2 rounded-md px-2.5 py-2 hover:bg-secondary text-foreground no-underline"
              onclick={() => (open = false)}
            >
              <ExternalLink class="w-3.5 h-3.5 text-muted-foreground" />
              <span>Åpne digitalt stillerapparat (/panel)</span>
            </a>
          </div>
        {/if}

        {#if objektTreff.length}
          <div>
            <div class="px-2 py-1 text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
              Objekter
            </div>
            {#each objektTreff as obj (obj._rid)}
              <button
                type="button"
                class="w-full flex items-center justify-between gap-2 rounded-md px-2.5 py-1.5 hover:bg-secondary text-left cursor-pointer"
                onclick={() => velg(() => onnavigate("objekter", { rid: obj._rid }))}
              >
                <span class="flex items-center gap-2">
                  <Layers class="w-3.5 h-3.5 text-muted-foreground" />
                  <strong class="font-mono text-foreground">{obj.id || "(uten litra)"}</strong>
                  <span class="text-muted-foreground">{obj.type}</span>
                </span>
                <span class="text-[11px] text-muted-foreground font-mono">
                  {obj.bindinger.length} bind.
                </span>
              </button>
            {/each}
          </div>
        {/if}

        {#if nodeTreff.length}
          <div>
            <div class="px-2 py-1 text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
              Noder (Kabling)
            </div>
            {#each nodeTreff as nd (nd.mac)}
              <button
                type="button"
                class="w-full flex items-center justify-between gap-2 rounded-md px-2.5 py-1.5 hover:bg-secondary text-left cursor-pointer"
                onclick={() => velg(() => onnavigate("kabling", { node: nd.mac }))}
              >
                <span class="flex items-center gap-2">
                  <Cpu class="w-3.5 h-3.5 text-muted-foreground" />
                  <strong class="font-mono">{nd.label}</strong>
                </span>
                <span class="text-[11px] text-muted-foreground font-mono">{nd.mac}</span>
              </button>
            {/each}
          </div>
        {/if}

        {#if togveiTreff.length}
          <div>
            <div class="px-2 py-1 text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
              Togveier (Forrigling)
            </div>
            {#each togveiTreff as tv (tv.id || `${tv.fra}-${tv.til}`)}
              <button
                type="button"
                class="w-full flex items-center justify-between gap-2 rounded-md px-2.5 py-1.5 hover:bg-secondary text-left cursor-pointer"
                onclick={() => velg(() => onnavigate("forrigling", { togveiId: tv.id }))}
              >
                <span class="flex items-center gap-2">
                  <GitBranch class="w-3.5 h-3.5 text-muted-foreground" />
                  <strong class="font-mono">{tv.id || "—"}</strong>
                  <span class="text-muted-foreground">{tv.fra || "?"} → {tv.til || "?"}</span>
                </span>
                <span class="text-[11px] text-muted-foreground font-mono">sig {tv.start || "—"}</span>
              </button>
            {/each}
          </div>
        {/if}

        {#if needle && !objektTreff.length && !nodeTreff.length && !togveiTreff.length}
          <div class="px-3 py-6 text-center text-muted-foreground">
            Ingen treff for «{q}»
          </div>
        {/if}
      </div>
    </BitsDialog.Content>
  </BitsDialog.Portal>
</BitsDialog.Root>
