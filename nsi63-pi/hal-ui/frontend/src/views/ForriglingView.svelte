<script lang="ts">
  import {
    AlertTriangle,
    GitBranch,
    Pencil,
    Play,
    Plus,
    Sparkles,
    Square,
    Trash2,
    Unlock,
  } from "@lucide/svelte";
  import { toast } from "svelte-sonner";
  import FiendtligMatrise from "$components/FiendtligMatrise.svelte";
  import SporplanSvg from "$components/SporplanSvg.svelte";
  import Badge from "$components/ui/Badge.svelte";
  import Button from "$components/ui/Button.svelte";
  import Card from "$components/ui/Card.svelte";
  import ConfirmDialog from "$components/ui/ConfirmDialog.svelte";
  import Dialog from "$components/ui/Dialog.svelte";
  import { betjenTogvei } from "$lib/api/klient";
  import {
    MAX_TOGVEIER,
    MAX_TV_FELT,
    MAX_TV_LAASER,
    MAX_TV_VEKSLER,
    fmtSek,
    frAutoFelt,
    frBilde,
    frEnder,
    frKrav,
    frRetning,
    frStartKandidater,
    isLaas,
    isVeksel,
    normaliserTogvei,
  } from "$lib/domain/regler";
  import { draft } from "$lib/stores/draft.svelte";
  import { live } from "$lib/stores/live.svelte";
  import type { Togvei } from "$lib/types";

  interface Props {
    focusTogveiId?: string | null;
    onclearfocus?: () => void;
  }

  let { focusTogveiId = null, onclearfocus }: Props = $props();

  let valgtIdx = $state<number | null>(null);
  let hoverId = $state<string | null>(null);
  let skuffApen = $state(false);
  let bekreftSlettIdx = $state<number | null>(null);
  let betjener = $state<string | null>(null);

  $effect(() => {
    if (focusTogveiId) {
      const i = draft.togveier.findIndex((t) => t.id === focusTogveiId);
      if (i >= 0) {
        valgtIdx = i;
        skuffApen = true;
      }
      onclearfocus?.();
    }
  });

  const cmp = (a: string, b: string) =>
    a.localeCompare(b, "no", { numeric: true });

  let manglerKrav = $derived(frKrav(draft.functions));

  let endeFelt = $derived(
    draft.functions
      .filter(
        (f) =>
          f.type === "sporfelt" &&
          (f.rolle === "linjefelt" || f.rolle === "togspor")
      )
      .sort((a, b) => cmp(a.id, b.id))
  );

  let alleSporfelt = $derived(
    draft.functions
      .filter((f) => f.type === "sporfelt")
      .sort((a, b) => cmp(a.id, b.id))
  );

  let alleVeksler = $derived(
    draft.functions
      .filter((f) => isVeksel(f.type))
      .sort((a, b) => cmp(a.id, b.id))
  );

  let alleLaaser = $derived(
    draft.functions
      .filter((f) => isLaas(f.type))
      .sort((a, b) => cmp(a.id, b.id))
  );

  let aktivTv = $derived(
    valgtIdx !== null ? draft.togveier[valgtIdx] || null : null
  );

  let aktivRetning = $derived(
    aktivTv ? frRetning(aktivTv, draft.functions, draft.signaltyper) : ""
  );

  let aktivKandidater = $derived(
    aktivTv ? frStartKandidater(aktivTv, draft.functions, draft.signaltyper) : []
  );

  function oppdaterTv(idx: number, neste: Togvei) {
    draft.togveier = draft.togveier.map((t, i) => (i === idx ? neste : t));
  }

  function settFraTil(idx: number, felt: "fra" | "til", val: string) {
    const cur = draft.togveier[idx];
    if (!cur) return;
    const oppdatert = normaliserTogvei(
      { ...cur, [felt]: val },
      draft.functions,
      draft.signaltyper
    );
    oppdaterTv(idx, oppdatert);
  }

  function leggTilTogvei() {
    const linje =
      endeFelt.find((f) => f.rolle === "linjefelt")?.id || "";
    const spor =
      endeFelt.find((f) => f.rolle === "togspor")?.id || "";
    const forsteVeksel = alleVeksler[0]?.id || "";
    let basis: Togvei = normaliserTogvei(
      {
        id: "",
        fra: linje,
        til: spor,
        start: "",
        spor,
        sporveksler: forsteVeksel
          ? [{ sporveksel: forsteVeksel, stilling: "normal" }]
          : [],
        frie: [],
        laaser: [],
        utlosningsfelt: "",
        notes: "",
      },
      draft.functions,
      draft.signaltyper
    );
    const auto = frAutoFelt(basis, draft.functions, draft.signaltyper);
    if (auto) {
      basis = { ...basis, frie: auto.frie, utlosningsfelt: auto.utlos };
    } else if (linje && spor) {
      basis = { ...basis, frie: [linje, spor] };
    }
    draft.togveier = [...draft.togveier, basis];
    valgtIdx = draft.togveier.length - 1;
    skuffApen = true;
  }

  function opprettManglende(spec: {
    linje: string;
    spor: string;
    retning: "innkjor" | "utkjor";
  }) {
    if (draft.togveier.length >= MAX_TOGVEIER) {
      toast.error(`Maks ${MAX_TOGVEIER} togveier nådd`);
      return;
    }
    const fra = spec.retning === "innkjor" ? spec.linje : spec.spor;
    const til = spec.retning === "innkjor" ? spec.spor : spec.linje;

    // Arv vekselstillinger fra motsatt togvei mellom samme linjefelt og spor
    const motsatt = draft.togveier.find((t) => {
      const e = frEnder(t, draft.functions, draft.signaltyper);
      return e.fra === til && e.til === fra;
    });
    const veksler = motsatt
      ? motsatt.sporveksler.map((v) => ({ ...v }))
      : [];

    let ny: Togvei = normaliserTogvei(
      {
        id: "",
        fra,
        til,
        start: "",
        spor: spec.spor,
        sporveksler: veksler,
        frie: [],
        laaser: motsatt?.laaser ? [...motsatt.laaser] : [],
        utlosningsfelt: "",
        notes: "",
      },
      draft.functions,
      draft.signaltyper
    );

    const auto = frAutoFelt(ny, draft.functions, draft.signaltyper);
    if (auto) {
      ny = { ...ny, frie: auto.frie, utlosningsfelt: auto.utlos };
    }

    draft.togveier = [...draft.togveier, ny];
    valgtIdx = draft.togveier.length - 1;
    skuffApen = true;
    toast.success(`Opprettet togvei ${ny.id || `${fra}→${til}`}`);
  }

  function kjorAutoFelt(idx: number) {
    const cur = draft.togveier[idx];
    if (!cur) return;
    const auto = frAutoFelt(cur, draft.functions, draft.signaltyper);
    if (!auto) {
      toast.error(
        "Legg først til gyldig fra/til og minst én sporveksel som også har et sporfelt med samme litra"
      );
      return;
    }
    oppdaterTv(idx, {
      ...cur,
      frie: auto.frie,
      utlosningsfelt: auto.utlos || cur.utlosningsfelt,
    });
    toast.success(`Avledet ${auto.frie.length} sporfelt og utløsningsfelt`);
  }

  function toggleFrie(idx: number, feltId: string) {
    const cur = draft.togveier[idx];
    if (!cur) return;
    const finnes = (cur.frie || []).includes(feltId);
    if (finnes) {
      oppdaterTv(idx, {
        ...cur,
        frie: cur.frie.filter((x) => x !== feltId),
      });
    } else {
      if ((cur.frie || []).length >= MAX_TV_FELT) {
        toast.error(`Maks ${MAX_TV_FELT} frie sporfelt per togvei`);
        return;
      }
      oppdaterTv(idx, { ...cur, frie: [...(cur.frie || []), feltId] });
    }
  }

  function toggleLaas(idx: number, laasId: string) {
    const cur = draft.togveier[idx];
    if (!cur) return;
    const curL = cur.laaser || [];
    if (curL.includes(laasId)) {
      oppdaterTv(idx, { ...cur, laaser: curL.filter((x) => x !== laasId) });
    } else {
      if (curL.length >= MAX_TV_LAASER) {
        toast.error(`Maks ${MAX_TV_LAASER} låser per togvei`);
        return;
      }
      oppdaterTv(idx, { ...cur, laaser: [...curL, laasId] });
    }
  }

  function slettTogvei(idx: number) {
    draft.togveier = draft.togveier.filter((_, i) => i !== idx);
    if (valgtIdx === idx) {
      valgtIdx = null;
      skuffApen = false;
    }
    bekreftSlettIdx = null;
  }

  async function sendBetjen(
    id: string,
    hva: "sikre" | "stopp" | "hjelpeutlos"
  ) {
    if (!id) return;
    betjener = `${id}:${hva}`;
    try {
      const res = await betjenTogvei(id, hva);
      if (res.svar) {
        toast.info(`${id}: ${res.svar}`);
      } else {
        toast.success(`Sendte «${hva}» til togvei ${id}`);
      }
    } catch (e: any) {
      toast.error(e?.message || `Klarte ikke å sende ${hva} til ${id}`);
    } finally {
      betjener = null;
    }
  }

  let lysTogveiId = $derived(
    hoverId || (skuffApen && aktivTv ? aktivTv.id : null)
  );
</script>

<div class="space-y-5">
  <!-- Sporplan & sjekkliste -->
  <Card class="p-4 space-y-3">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div>
        <h2 class="text-sm font-semibold">Sporplan & kompletthet</h2>
        <p class="text-xs text-muted-foreground">
          Hold over en togvei i listen under for å fremheve kjøreveien i sporplanen.
        </p>
      </div>
      <div class="flex items-center gap-2">
        <Button
          size="sm"
          variant="primary"
          disabled={manglerKrav.length > 0 || draft.togveier.length >= MAX_TOGVEIER}
          onclick={leggTilTogvei}
          title={manglerKrav.length > 0
            ? `Mangler først under Objekter: ${manglerKrav.join(", ")}`
            : "Opprett ny togvei"}
        >
          <Plus class="w-3.5 h-3.5" />
          Ny togvei
        </Button>
      </div>
    </div>

    {#if manglerKrav.length > 0}
      <div class="rounded-md border border-amber/40 bg-amber/10 px-3 py-2 text-xs text-amber flex items-center gap-2">
        <AlertTriangle class="w-4 h-4 shrink-0" />
        <span>
          Før du oppretter togveier må anlegget ha {manglerKrav.join(", ")} under <strong>Objekter</strong>.
        </span>
      </div>
    {/if}

    <SporplanSvg aktivTogveiId={lysTogveiId} onopprett={opprettManglende} />
  </Card>

  <!-- Togvei-tabell -->
  <Card class="overflow-hidden">
    <div class="px-4 py-3 border-b border-border flex items-center justify-between gap-2">
      <div class="flex items-center gap-2">
        <GitBranch class="w-4 h-4 text-primary" />
        <h2 class="text-sm font-semibold">Togveier</h2>
        <Badge variant="muted">{draft.togveier.length} / {MAX_TOGVEIER}</Badge>
      </div>
      {#if draft.forriglingDirty}
        <Badge variant="amber">Ulagrede endringer — lagre før live-testing</Badge>
      {/if}
    </div>

    {#if !draft.togveier.length}
      <div class="p-8 text-center text-xs text-muted-foreground">
        Ingen togveier definert ennå.
      </div>
    {:else}
      <div class="overflow-x-auto">
        <table class="w-full text-xs border-collapse">
          <thead>
            <tr class="border-b border-border bg-secondary/40 text-left text-[11px] text-muted-foreground">
              <th class="px-3 py-2 font-semibold">ID</th>
              <th class="px-3 py-2 font-semibold">Rute</th>
              <th class="px-3 py-2 font-semibold">Signal</th>
              <th class="px-3 py-2 font-semibold">Veksler</th>
              <th class="px-3 py-2 font-semibold">Frie sporfelt</th>
              <th class="px-3 py-2 font-semibold">Live-status</th>
              <th class="px-3 py-2 font-semibold text-right">Betjen / Rediger</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-border/60">
            {#each draft.togveier as tv, idx (idx)}
              {@const e = frEnder(tv, draft.functions, draft.signaltyper)}
              {@const bilde = frBilde(tv, draft.functions, draft.signaltyper)}
              {@const info = tv.id ? live.togveiInfo[tv.id] : null}
              <tr
                class="hover:bg-secondary/40 transition-colors"
                onmouseenter={() => (hoverId = tv.id || null)}
                onmouseleave={() => (hoverId = null)}
              >
                <td class="px-3 py-2.5 font-mono font-bold text-foreground whitespace-nowrap">
                  {tv.id || "—"}
                </td>
                <td class="px-3 py-2.5 font-mono whitespace-nowrap">
                  {e.fra || "?"} → {e.til || "?"}
                </td>
                <td class="px-3 py-2.5 whitespace-nowrap">
                  {#if tv.start}
                    <span class="font-mono font-semibold">{tv.start}</span>
                    <span class="text-[10.5px] text-muted-foreground ml-1">
                      ({bilde === "kjor" ? "Kjør" : "Redusert"})
                    </span>
                  {:else}
                    <Badge variant="warn">mangler</Badge>
                  {/if}
                </td>
                <td class="px-3 py-2.5 font-mono text-[11px]">
                  {#if tv.sporveksler?.length}
                    {tv.sporveksler
                      .filter((v) => v.sporveksel)
                      .map((v) => `${v.sporveksel}:${v.stilling === "avvik" ? "−" : "+"}`)
                      .join(", ")}
                  {:else}
                    <span class="text-muted-foreground">—</span>
                  {/if}
                </td>
                <td class="px-3 py-2.5 font-mono text-[11px] text-muted-foreground">
                  {(tv.frie || []).join(", ") || "—"}
                  {#if tv.utlosningsfelt}
                    <span class="text-[10px] text-inn ml-1" title="Utløsningsfelt">
                      (utl. {tv.utlosningsfelt})
                    </span>
                  {/if}
                </td>
                <td class="px-3 py-2.5">
                  {#if info}
                    <span class="inline-flex items-center gap-1.5 text-[11px]">
                      <Badge
                        variant={info.tekst.toLowerCase().includes("avvist") ||
                        info.tekst.toLowerCase().includes("feil")
                          ? "warn"
                          : info.tekst.toLowerCase().includes("sikret")
                            ? "ok"
                            : "muted"}
                      >
                        {info.tekst}
                      </Badge>
                      <span class="text-[10px] font-mono text-muted-foreground tabular">
                        {fmtSek(info.alder_s)}
                      </span>
                    </span>
                  {:else}
                    <span class="text-muted-foreground/50">—</span>
                  {/if}
                </td>
                <td class="px-3 py-2.5 text-right whitespace-nowrap">
                  <div class="inline-flex items-center gap-1">
                    <Button
                      size="xs"
                      variant="outline"
                      disabled={!tv.id || betjener !== null || draft.forriglingDirty}
                      onclick={() => sendBetjen(tv.id, "sikre")}
                      title="Sikre togvei via master"
                    >
                      <Play class="w-3 h-3 text-ok" />
                      Sikre
                    </Button>
                    <Button
                      size="xs"
                      variant="outline"
                      disabled={!tv.id || betjener !== null || draft.forriglingDirty}
                      onclick={() => sendBetjen(tv.id, "stopp")}
                      title="Sett startsignal i stopp"
                    >
                      <Square class="w-3 h-3 text-warn" />
                      Stopp
                    </Button>
                    <Button
                      size="xs"
                      variant="outline"
                      disabled={!tv.id || betjener !== null || draft.forriglingDirty}
                      onclick={() => sendBetjen(tv.id, "hjelpeutlos")}
                      title="Start hjelpeutløsning"
                    >
                      <Unlock class="w-3 h-3 text-amber" />
                      Utløs
                    </Button>
                    <Button
                      size="xs"
                      variant="ghost"
                      onclick={() => {
                        valgtIdx = idx;
                        skuffApen = true;
                      }}
                      title="Rediger togvei"
                    >
                      <Pencil class="w-3.5 h-3.5" />
                    </Button>
                  </div>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </Card>

  <!-- Fiendtlighetsmatrise -->
  <Card class="p-4 space-y-3">
    <div>
      <h2 class="text-sm font-semibold">Fiendtlighetsmatrise</h2>
      <p class="text-xs text-muted-foreground">
        Avledet automatisk fra delt startsignal, felles sporfelt eller motsatt vekselstilling.
      </p>
    </div>
    <FiendtligMatrise togveier={draft.togveier} />
  </Card>
</div>

<!-- Togvei-redigeringsskuff -->
<Dialog
  bind:open={skuffApen}
  side="right"
  title={aktivTv ? `Togvei ${aktivTv.id || "(ny)"}` : "Rediger togvei"}
>
  {#if aktivTv && valgtIdx !== null}
    {@const idx = valgtIdx}
    {@const ender = frEnder(aktivTv, draft.functions, draft.signaltyper)}
    <div class="space-y-4 text-xs">
      <!-- Fra / Til -->
      <div class="grid grid-cols-2 gap-3">
        <div class="space-y-1">
          <label class="text-[11px] font-medium text-muted-foreground" for="tv-fra">
            Fra (linjefelt eller togspor)
          </label>
          <select
            id="tv-fra"
            class="w-full font-mono text-xs"
            value={ender.fra}
            onchange={(e) => settFraTil(idx, "fra", e.currentTarget.value)}
          >
            <option value="">— velg —</option>
            {#each endeFelt as f (f._rid)}
              <option value={f.id}>{f.id} ({f.rolle})</option>
            {/each}
          </select>
        </div>

        <div class="space-y-1">
          <label class="text-[11px] font-medium text-muted-foreground" for="tv-til">
            Til (togspor eller linjefelt)
          </label>
          <select
            id="tv-til"
            class="w-full font-mono text-xs"
            value={ender.til}
            onchange={(e) => settFraTil(idx, "til", e.currentTarget.value)}
          >
            <option value="">— velg —</option>
            {#each endeFelt as f (f._rid)}
              <option value={f.id}>{f.id} ({f.rolle})</option>
            {/each}
          </select>
        </div>
      </div>

      {#if (ender.fra || ender.til) && !aktivRetning}
        <div class="rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-[11.5px] text-warn">
          Endene må være linjefelt → togspor (innkjør), togspor → linjefelt (utkjør) eller to ulike togspor (indre).
        </div>
      {/if}

      <!-- Startsignal -->
      <div class="space-y-1">
        <div class="flex items-center justify-between">
          <label class="text-[11px] font-medium text-muted-foreground" for="tv-start">
            Startsignal
          </label>
          {#if aktivRetning}
            <Badge variant="muted">{aktivRetning}</Badge>
          {/if}
        </div>

        {#if aktivKandidater.length === 0}
          <div class="rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-[11.5px] text-warn">
            Ingen passende hovedsignal funnet for denne enden. Sett <strong>rolle</strong> og <strong>linjefelt</strong> på signalet under Objekter.
          </div>
        {:else if aktivKandidater.length === 1}
          <div class="rounded-md border border-border bg-secondary/50 px-3 py-1.5 font-mono text-xs">
            {aktivKandidater[0]} <span class="text-muted-foreground font-sans">(automatisk valgt)</span>
          </div>
        {:else}
          <select
            id="tv-start"
            class="w-full font-mono text-xs"
            value={aktivTv.start}
            onchange={(e) =>
              oppdaterTv(idx, { ...aktivTv, start: e.currentTarget.value })}
          >
            {#each aktivKandidater as s}
              <option value={s}>{s}</option>
            {/each}
          </select>
        {/if}
      </div>

      <!-- Sporveksler -->
      <div class="space-y-2 pt-2 border-t border-border">
        <div class="flex items-center justify-between">
          <span class="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Sporveksler ({aktivTv.sporveksler.length}/{MAX_TV_VEKSLER})
          </span>
          <Button
            size="xs"
            variant="outline"
            disabled={aktivTv.sporveksler.length >= MAX_TV_VEKSLER || !alleVeksler.length}
            onclick={() => {
              const brukt = new Set(aktivTv.sporveksler.map((x) => x.sporveksel));
              const nesteV = alleVeksler.find((v) => !brukt.has(v.id))?.id || alleVeksler[0]?.id || "";
              oppdaterTv(idx, {
                ...aktivTv,
                sporveksler: [
                  ...aktivTv.sporveksler,
                  { sporveksel: nesteV, stilling: "normal" },
                ],
              });
            }}
          >
            <Plus class="w-3 h-3" /> Veksel
          </Button>
        </div>

        {#if !aktivTv.sporveksler.length}
          <div class="text-[11px] text-muted-foreground">Ingen veksler lagt til.</div>
        {:else}
          <div class="space-y-1.5">
            {#each aktivTv.sporveksler as vx, vi (vi)}
              <div class="flex items-center gap-2">
                <select
                  class="flex-1 font-mono text-xs"
                  value={vx.sporveksel}
                  onchange={(e) => {
                    const arr = aktivTv.sporveksler.map((x, j) =>
                      j === vi ? { ...x, sporveksel: e.currentTarget.value } : x
                    );
                    oppdaterTv(idx, { ...aktivTv, sporveksler: arr });
                  }}
                >
                  <option value="">— velg —</option>
                  {#each alleVeksler as v (v._rid)}
                    <option value={v.id}>{v.id}</option>
                  {/each}
                </select>
                <select
                  class="w-28 text-xs"
                  value={vx.stilling}
                  onchange={(e) => {
                    const arr = aktivTv.sporveksler.map((x, j) =>
                      j === vi
                        ? { ...x, stilling: e.currentTarget.value as "normal" | "avvik" }
                        : x
                    );
                    oppdaterTv(idx, { ...aktivTv, sporveksler: arr });
                  }}
                >
                  <option value="normal">normal (+)</option>
                  <option value="avvik">avvik (−)</option>
                </select>
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label="Fjern veksel"
                  onclick={() => {
                    oppdaterTv(idx, {
                      ...aktivTv,
                      sporveksler: aktivTv.sporveksler.filter((_, j) => j !== vi),
                    });
                  }}
                >
                  <Trash2 class="w-3.5 h-3.5 text-muted-foreground" />
                </Button>
              </div>
            {/each}
          </div>
        {/if}
      </div>

      <!-- Frie sporfelt -->
      <div class="space-y-2 pt-2 border-t border-border">
        <div class="flex items-center justify-between gap-2">
          <span class="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Frie sporfelt ({(aktivTv.frie || []).length}/{MAX_TV_FELT})
          </span>
          <Button size="xs" variant="outline" onclick={() => kjorAutoFelt(idx)}>
            <Sparkles class="w-3 h-3 text-amber" />
            Auto-avled
          </Button>
        </div>

        <div class="flex flex-wrap gap-1.5">
          {#each alleSporfelt as sf (sf._rid)}
            {@const valgt = (aktivTv.frie || []).includes(sf.id)}
            <button
              type="button"
              onclick={() => toggleFrie(idx, sf.id)}
              class="px-2 py-1 rounded-md font-mono text-[11px] border cursor-pointer transition-colors {valgt
                ? 'border-primary bg-primary/15 text-primary font-semibold'
                : 'border-border bg-secondary/40 text-muted-foreground hover:text-foreground'}"
            >
              {sf.id}
            </button>
          {/each}
        </div>
      </div>

      <!-- Utløsningsfelt -->
      <div class="space-y-1">
        <label class="text-[11px] font-medium text-muted-foreground" for="tv-utlos">
          Utløsningsfelt (sporfelt toget løser ut togveien på)
        </label>
        <select
          id="tv-utlos"
          class="w-full font-mono text-xs"
          value={aktivTv.utlosningsfelt || ""}
          onchange={(e) =>
            oppdaterTv(idx, { ...aktivTv, utlosningsfelt: e.currentTarget.value })}
        >
          <option value="">— intet —</option>
          {#each alleSporfelt as sf (sf._rid)}
            <option value={sf.id}>{sf.id} {sf.rolle ? `(${sf.rolle})` : ""}</option>
          {/each}
        </select>
      </div>

      <!-- Krever låst (samlelås / rigel) -->
      {#if alleLaaser.length > 0}
        <div class="space-y-2 pt-2 border-t border-border">
          <span class="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Krever låst ({(aktivTv.laaser || []).length}/{MAX_TV_LAASER})
          </span>
          <div class="flex flex-wrap gap-1.5">
            {#each alleLaaser as ls (ls._rid)}
              {@const valgt = (aktivTv.laaser || []).includes(ls.id)}
              <button
                type="button"
                onclick={() => toggleLaas(idx, ls.id)}
                class="px-2 py-1 rounded-md font-mono text-[11px] border cursor-pointer transition-colors {valgt
                  ? 'border-amber bg-amber/15 text-amber font-semibold'
                  : 'border-border bg-secondary/40 text-muted-foreground hover:text-foreground'}"
              >
                {ls.id} ({ls.type})
              </button>
            {/each}
          </div>
        </div>
      {/if}

      <!-- Notat -->
      <div class="space-y-1 pt-2 border-t border-border">
        <label class="text-[11px] font-medium text-muted-foreground" for="tv-notes">
          Merknad (valgfritt)
        </label>
        <input
          id="tv-notes"
          type="text"
          class="w-full text-xs"
          value={aktivTv.notes || ""}
          oninput={(e) =>
            oppdaterTv(idx, { ...aktivTv, notes: e.currentTarget.value })}
          placeholder="F.eks. Innkjøring fra nord i hovedspor"
        />
      </div>

      <!-- Slett -->
      <div class="pt-3 border-t border-border flex justify-end">
        <Button
          size="sm"
          variant="destructive"
          onclick={() => (bekreftSlettIdx = idx)}
        >
          <Trash2 class="w-3.5 h-3.5" />
          Slett togvei
        </Button>
      </div>
    </div>
  {/if}
</Dialog>

<ConfirmDialog
  open={bekreftSlettIdx !== null}
  onOpenChange={(o) => {
    if (!o) bekreftSlettIdx = null;
  }}
  title="Slett togvei?"
  description="Togveien fjernes fra utkastet. Endringen publiseres først når du klikker «Lagre og publiser»."
  confirmLabel="Slett"
  destructive
  onconfirm={() => {
    if (bekreftSlettIdx !== null) slettTogvei(bekreftSlettIdx);
  }}
/>
