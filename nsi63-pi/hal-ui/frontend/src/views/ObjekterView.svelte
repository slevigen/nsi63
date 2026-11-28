<script lang="ts">
  import {
    AlertTriangle,
    Layers,
    Plus,
    Search,
    X,
  } from "@lucide/svelte";
  import ObjektInspektor from "$components/ObjektInspektor.svelte";
  import Badge from "$components/ui/Badge.svelte";
  import Button from "$components/ui/Button.svelte";
  import Card from "$components/ui/Card.svelte";
  import Dialog from "$components/ui/Dialog.svelte";
  import {
    GRUPPER,
    MAX_FUNKSJONER,
    aliasFor,
    erHoved,
    gruppeIdx,
    hovedsignalManglerRolle,
    litraNs,
    litraUgyldig,
    macForNode,
    portNokkel,
  } from "$lib/domain/regler";
  import { draft, type DraftFunction } from "$lib/stores/draft.svelte";

  interface Props {
    focusRid?: number | null;
    onclearfocus?: () => void;
  }

  let { focusRid = null, onclearfocus }: Props = $props();

  let sok = $state("");
  let valgtGruppe = $state<number | "alle">("alle");
  let kunBundne = $state(false);
  let kunFeil = $state(false);
  let valgtRid = $state<number | null>(null);
  let mobilInspektorApen = $state(false);
  let visNyMeny = $state(false);

  $effect(() => {
    if (focusRid != null) {
      valgtRid = focusRid;
      if (typeof window !== "undefined" && window.innerWidth < 1024) {
        mobilInspektorApen = true;
      }
      onclearfocus?.();
    }
  });

  // Duplikat-litra innen samme navnerom
  let duplikatRids = $derived.by(() => {
    const sett = new Map<string, number[]>();
    for (const f of draft.functions) {
      const id = (f.id || "").trim();
      if (!id) continue;
      const k = `${litraNs(f.type, draft.signaltyper)}|${id}`;
      const arr = sett.get(k) || [];
      arr.push(f._rid);
      sett.set(k, arr);
    }
    const dup = new Set<number>();
    for (const arr of sett.values()) {
      if (arr.length > 1) arr.forEach((r) => dup.add(r));
    }
    return dup;
  });

  function harObjektFeil(f: DraftFunction): string | null {
    const id = (f.id || "").trim();
    if (!id) return "Mangler litra";
    const u = litraUgyldig(id);
    if (u) return `Ugyldig tegn «${u}»`;
    if (duplikatRids.has(f._rid)) return "Duplikat litra";
    if (hovedsignalManglerRolle(f, draft.signaltyper)) return "Mangler rolle";
    for (const b of f.bindinger || []) {
      if (!b.node) continue;
      const mac = macForNode(b.node, draft.noder);
      const st = draft.signaltyper[f.type];
      const n =
        st && (b.sted === "anlegg" || b.sted === "panel") ? st.lamper || 1 : 1;
      for (let k = 0; k < n; k++) {
        if (draft.portKart.feilNokler.has(portNokkel(mac, b.i2c, (b.port || 0) + k))) {
          return "Portkonflikt";
        }
      }
    }
    return null;
  }

  function matchSok(f: DraftFunction, needle: string): boolean {
    if (!needle) return true;
    if ((f.id || "").toLowerCase().includes(needle)) return true;
    if ((f.type || "").toLowerCase().includes(needle)) return true;
    if ((f.navn || "").toLowerCase().includes(needle)) return true;
    if ((f.rolle || "").toLowerCase().includes(needle)) return true;
    for (const b of f.bindinger || []) {
      if (!b.node) continue;
      if (b.node.toLowerCase().includes(needle)) return true;
      const mac = macForNode(b.node, draft.noder);
      if (mac.includes(needle)) return true;
      const alias = aliasFor(mac, draft.noder);
      if (alias && alias.toLowerCase().includes(needle)) return true;
    }
    return false;
  }

  let needle = $derived(sok.trim().toLowerCase());

  let gruppeAntall = $derived.by(() => {
    const counts = GRUPPER.map(() => 0);
    for (const f of draft.functions) {
      counts[gruppeIdx(f.type)]++;
    }
    return counts;
  });

  let feilAntall = $derived(
    draft.functions.filter((f) => harObjektFeil(f) !== null).length
  );

  let filtrerte = $derived.by(() => {
    return draft.functions.filter((f) => {
      if (valgtGruppe !== "alle" && gruppeIdx(f.type) !== valgtGruppe) {
        return false;
      }
      if (kunBundne && !(f.bindinger || []).some((b) => b.node)) {
        return false;
      }
      if (kunFeil && harObjektFeil(f) === null) {
        return false;
      }
      return matchSok(f, needle);
    });
  });

  let grupperte = $derived.by(() => {
    const grupper: { idx: number; navn: string; rader: DraftFunction[] }[] = [];
    for (let i = 0; i < GRUPPER.length; i++) {
      const rader = filtrerte.filter((f) => gruppeIdx(f.type) === i);
      if (rader.length) {
        grupper.push({ idx: i, navn: GRUPPER[i].navn, rader });
      }
    }
    return grupper;
  });

  let valgtObj = $derived(
    draft.functions.find((f) => f._rid === valgtRid) || null
  );

  function velgRad(rid: number) {
    valgtRid = rid;
    if (typeof window !== "undefined" && window.innerWidth < 1024) {
      mobilInspektorApen = true;
    }
  }

  function leggTil(gi: number) {
    visNyMeny = false;
    const ny = draft.leggTilObjekt(gi);
    valgtGruppe = "alle";
    kunBundne = false;
    kunFeil = false;
    sok = "";
    velgRad(ny._rid);
  }

  function kortOppsummering(f: DraftFunction): string {
    const deler: string[] = [];
    if (f.rolle) {
      if (f.type === "sporfelt" && f.rolle === "linjefelt") {
        deler.push(f.linjeblokk === false ? "linjefelt" : "blokksporfelt");
      } else {
        deler.push(f.rolle);
      }
    }
    if (f.side === "v") deler.push("venstre");
    if (f.side === "h") deler.push("høyre");
    if (erHoved(f.type, draft.signaltyper) && f.linjefelt) {
      deler.push(`linje ${f.linjefelt}`);
    }
    if (f.montert_med) deler.push(`på ${f.montert_med}`);
    if (f.varsler_om) deler.push(`varsler ${f.varsler_om}`);
    if (f.navn) deler.push(f.navn);
    if (f.omfatter?.length) deler.push(`${f.omfatter.length} obj.`);
    return deler.join(" · ");
  }

  function bundneNoder(f: DraftFunction): string[] {
    const sett = new Set<string>();
    for (const b of f.bindinger || []) {
      if (!b.node) continue;
      const mac = macForNode(b.node, draft.noder);
      sett.add(aliasFor(mac, draft.noder) || b.node);
    }
    return [...sett];
  }
</script>

<div class="space-y-4">
  <!-- Topplinje: søk, filtre, + Nytt objekt -->
  <div class="flex flex-wrap items-center gap-2.5">
    <div class="relative flex-1 min-w-[220px]">
      <Search class="w-3.5 h-3.5 text-muted-foreground absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
      <input
        type="text"
        bind:value={sok}
        placeholder="Søk litra, type, navn eller node…"
        class="w-full pl-8 pr-7 py-1.5 text-xs rounded-md bg-card border border-border"
      />
      {#if sok}
        <button
          type="button"
          class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground cursor-pointer"
          onclick={() => (sok = "")}
          aria-label="Tøm søk"
        >
          <X class="w-3.5 h-3.5" />
        </button>
      {/if}
    </div>

    <div class="flex flex-wrap items-center gap-1.5">
      <button
        type="button"
        class="px-2.5 py-1 rounded-md text-xs border cursor-pointer transition-colors {kunBundne
          ? 'border-primary bg-primary/15 text-primary font-medium'
          : 'border-border bg-card text-muted-foreground hover:text-foreground'}"
        onclick={() => (kunBundne = !kunBundne)}
      >
        Kun bundne
      </button>
      <button
        type="button"
        class="px-2.5 py-1 rounded-md text-xs border cursor-pointer transition-colors {kunFeil
          ? 'border-warn bg-warn/15 text-warn font-medium'
          : 'border-border bg-card text-muted-foreground hover:text-foreground'}"
        onclick={() => (kunFeil = !kunFeil)}
      >
        Kun med feil
        {#if feilAntall > 0}
          <span class="ml-1 font-mono text-[10.5px]">({feilAntall})</span>
        {/if}
      </button>

      <div class="relative">
        <Button
          size="sm"
          variant="primary"
          disabled={draft.functions.length >= MAX_FUNKSJONER}
          onclick={() => (visNyMeny = !visNyMeny)}
        >
          <Plus class="w-3.5 h-3.5" />
          Nytt objekt
        </Button>

        {#if visNyMeny}
          <div
            class="fixed inset-0 z-20"
            onclick={() => (visNyMeny = false)}
            role="presentation"
          ></div>
          <div
            class="absolute right-0 mt-1.5 z-30 w-52 rounded-lg border border-border-strong bg-card shadow-2xl p-1 space-y-0.5"
          >
            <div class="px-2 py-1 text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
              Velg kategori
            </div>
            {#each GRUPPER as g, gi}
              <button
                type="button"
                class="w-full text-left px-2.5 py-1.5 rounded text-xs hover:bg-secondary cursor-pointer flex items-center justify-between"
                onclick={() => leggTil(gi)}
              >
                <span>{g.navn}</span>
                <span class="text-[10.5px] font-mono text-muted-foreground">{g.typer[0]}</span>
              </button>
            {/each}
          </div>
        {/if}
      </div>
    </div>
  </div>

  <!-- Gruppefilter-chips -->
  <div class="flex flex-wrap items-center gap-1.5">
    <button
      type="button"
      class="px-2.5 py-1 rounded-full text-[11.5px] border cursor-pointer transition-colors {valgtGruppe === 'alle'
        ? 'border-primary bg-primary/15 text-primary font-semibold'
        : 'border-border bg-card text-muted-foreground hover:text-foreground'}"
      onclick={() => (valgtGruppe = "alle")}
    >
      Alle <span class="font-mono text-[10.5px] opacity-80">{draft.functions.length}</span>
    </button>
    {#each GRUPPER as g, gi}
      <button
        type="button"
        class="px-2.5 py-1 rounded-full text-[11.5px] border cursor-pointer transition-colors {valgtGruppe === gi
          ? 'border-primary bg-primary/15 text-primary font-semibold'
          : 'border-border bg-card text-muted-foreground hover:text-foreground'}"
        onclick={() => (valgtGruppe = gi)}
      >
        {g.navn} <span class="font-mono text-[10.5px] opacity-80">{gruppeAntall[gi]}</span>
      </button>
    {/each}
  </div>

  <!-- Portfeil-oppsummering hvis det finnes konflikter -->
  {#if draft.portKart.feil.length > 0}
    <div class="rounded-lg border border-warn/40 bg-warn/10 px-3.5 py-2.5 text-xs text-warn space-y-1">
      <div class="font-semibold flex items-center gap-1.5">
        <AlertTriangle class="w-4 h-4 shrink-0" />
        {draft.portKart.feil.length} portfeil hindrer lagring:
      </div>
      <ul class="list-disc pl-5 space-y-0.5 text-[11.5px]">
        {#each draft.portKart.feil.slice(0, 6) as feil}
          <li>{feil}</li>
        {/each}
        {#if draft.portKart.feil.length > 6}
          <li>… og {draft.portKart.feil.length - 6} til</li>
        {/if}
      </ul>
    </div>
  {/if}

  <!-- Master-Detail hovedoppsett -->
  <div class="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_400px] xl:grid-cols-[minmax(0,1fr)_440px] gap-4 items-start">
    <!-- Venstre: gruppert objekttabell -->
    <div class="space-y-4 min-w-0">
      {#if !grupperte.length}
        <Card class="p-8 text-center space-y-2">
          <Layers class="w-7 h-7 text-muted-foreground mx-auto opacity-60" />
          <div class="text-sm font-medium">
            {draft.functions.length === 0 ? "Ingen objekter i anlegget ennå" : "Ingen objekter matcher filteret"}
          </div>
          <p class="text-xs text-muted-foreground">
            {draft.functions.length === 0
              ? "Klikk «+ Nytt objekt» for å legge til signaler, veksler eller sporfelt."
              : "Prøv et annet søkeord eller nullstill filtrene."}
          </p>
        </Card>
      {:else}
        {#each grupperte as grp (grp.idx)}
          <Card class="overflow-hidden">
            <div class="px-3.5 py-2 border-b border-border bg-secondary/40 flex items-center justify-between">
              <div class="text-xs font-semibold">{grp.navn}</div>
              <div class="flex items-center gap-2">
                <span class="text-[11px] font-mono text-muted-foreground">{grp.rader.length}</span>
                <button
                  type="button"
                  class="text-[11px] text-primary hover:underline cursor-pointer"
                  onclick={() => leggTil(grp.idx)}
                >
                  + Legg til
                </button>
              </div>
            </div>

            <div class="divide-y divide-border/60">
              {#each grp.rader as f (f._rid)}
                {@const feil = harObjektFeil(f)}
                {@const noder = bundneNoder(f)}
                {@const oppsum = kortOppsummering(f)}
                {@const aktiv = valgtRid === f._rid}
                <button
                  type="button"
                  class="w-full text-left px-3.5 py-2.5 flex items-center gap-3 text-xs transition-colors cursor-pointer {aktiv
                    ? 'bg-primary/15 border-l-2 border-l-primary'
                    : 'hover:bg-secondary/50 border-l-2 border-l-transparent'}"
                  onclick={() => velgRad(f._rid)}
                >
                  <div class="w-16 shrink-0 font-mono font-bold text-sm truncate {f.id ? 'text-foreground' : 'text-amber'}">
                    {f.id || "(tom)"}
                  </div>

                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 flex-wrap">
                      <span class="font-mono text-[11px] text-muted-foreground">{f.type}</span>
                      {#if oppsum}
                        <span class="text-muted-foreground truncate">· {oppsum}</span>
                      {/if}
                    </div>
                  </div>

                  <div class="hidden sm:flex items-center gap-1.5 shrink-0">
                    {#if noder.length}
                      {#each noder.slice(0, 2) as nd}
                        <span class="font-mono text-[10.5px] px-1.5 py-0.5 rounded bg-secondary text-muted-foreground">
                          {nd}
                        </span>
                      {/each}
                      {#if noder.length > 2}
                        <span class="text-[10.5px] text-muted-foreground">+{noder.length - 2}</span>
                      {/if}
                    {:else}
                      <span class="text-[11px] text-muted-foreground/60">ubundet</span>
                    {/if}
                  </div>

                  <div class="shrink-0 flex items-center gap-1.5">
                    <span class="font-mono text-[11px] text-muted-foreground tabular">
                      {f.bindinger.length}p
                    </span>
                    {#if feil}
                      <Badge variant="warn" class="text-[10px]">{feil}</Badge>
                    {/if}
                  </div>
                </button>
              {/each}
            </div>
          </Card>
        {/each}
      {/if}
    </div>

    <!-- Høyre: fast ObjektInspektor på desktop -->
    <div class="hidden lg:block sticky top-16 max-h-[calc(100vh-110px)] overflow-y-auto">
      {#if valgtObj}
        <Card class="p-4">
          <ObjektInspektor
            obj={valgtObj}
            ondeleted={() => {
              valgtRid = null;
            }}
          />
        </Card>
      {:else}
        <Card class="p-8 text-center text-xs text-muted-foreground space-y-2">
          <Layers class="w-6 h-6 mx-auto opacity-50" />
          <div>Velg et objekt i listen til venstre for å redigere litra, rolle og portbindinger.</div>
        </Card>
      {/if}
    </div>
  </div>
</div>

<!-- Mobil/nettbrett: ObjektInspektor i høyreskuff -->
<Dialog
  bind:open={mobilInspektorApen}
  side="right"
  title={valgtObj ? `Objekt ${valgtObj.id || "(uten litra)"}` : "Objekt"}
>
  {#if valgtObj}
    <ObjektInspektor
      obj={valgtObj}
      ondeleted={() => {
        valgtRid = null;
        mobilInspektorApen = false;
      }}
    />
  {/if}
</Dialog>
