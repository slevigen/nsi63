<script lang="ts">
  import { AlertTriangle, CheckCircle2, Plus } from "@lucide/svelte";
  import Button from "$components/ui/Button.svelte";
  import {
    erHoved,
    frEnder,
    sigKlasse,
    validerSporplan,
  } from "$lib/domain/regler";
  import { draft } from "$lib/stores/draft.svelte";

  interface Props {
    aktivTogveiId?: string | null;
    onopprett: (spec: {
      linje: string;
      spor: string;
      retning: "innkjor" | "utkjor";
    }) => void;
  }

  let { aktivTogveiId = null, onopprett }: Props = $props();

  const cmp = (a: string, b: string) =>
    a.localeCompare(b, "no", { numeric: true });

  // Bygg sporplan-modell fra togveiene og objektrollene (speiler frSkisse)
  let modell = $derived.by(() => {
    const fns = draft.functions;
    const st = draft.signaltyper;
    const sigAv = (id: string) =>
      fns.find((f) => f.id === id && erHoved(f.type, st));
    const feltAv = (id: string) =>
      fns.find((f) => f.id === id && f.type === "sporfelt");

    const ruter: {
      id: string;
      retning: "innkjor" | "utkjor";
      linje: string;
      spor: string;
      start: string;
      veksler: { id: string; stilling: "normal" | "avvik" }[];
    }[] = [];

    for (const tv of draft.togveier) {
      if (!tv.start) continue;
      const rolle = sigAv(tv.start)?.rolle || "";
      if (rolle !== "innkjor" && rolle !== "utkjor") continue;
      const linje =
        (tv.frie || []).find((f) => feltAv(f)?.rolle === "linjefelt") || "";
      ruter.push({
        id: tv.id || "",
        retning: rolle,
        linje,
        spor: tv.spor || "",
        start: tv.start,
        veksler: (tv.sporveksler || [])
          .filter((v) => v.sporveksel)
          .map((v) => ({ id: v.sporveksel, stilling: v.stilling })),
      });
    }

    const ender = fns
      .filter((f) => f.type === "sporfelt" && f.rolle === "linjefelt")
      .map((f) => f.id);
    for (const r of ruter) {
      if (r.linje && !ender.includes(r.linje)) ender.push(r.linje);
    }
    ender.sort(cmp);

    const sporIds = fns
      .filter((f) => f.type === "sporfelt" && f.rolle === "togspor")
      .map((f) => f.id);
    for (const r of ruter) {
      if (r.spor && !sporIds.includes(r.spor)) sporIds.push(r.spor);
    }
    sporIds.sort(cmp);

    let vEnde = ender.find((e) => feltAv(e)?.side === "v") || null;
    let hEnde =
      ender.find((e) => e !== vEnde && feltAv(e)?.side === "h") || null;
    if (!vEnde) vEnde = ender.find((e) => e !== hEnde) || null;
    if (!hEnde) hEnde = ender.find((e) => e !== vEnde) || null;

    // Hovedspor = færrest avvik i togveiene
    const avvikTall = (sp: string) =>
      ruter
        .filter((r) => r.spor === sp)
        .reduce(
          (n, r) => n + r.veksler.filter((v) => v.stilling === "avvik").length,
          0
        );
    const sporSortert = sporIds
      .slice()
      .sort((a, b) => avvikTall(a) - avvikTall(b) || cmp(a, b));

    // Signaler ved endene vs på enkeltspor
    const sigEnde: Record<string, { inn: string[]; ut: string[] }> = {};
    for (const e of [vEnde, hEnde]) {
      if (e) sigEnde[e] = { inn: [], ut: [] };
    }
    const sigSpor: Record<string, { v: string[]; h: string[] }> = {};
    const utPerSig: Record<string, { spor: Set<string>; linje: string }> = {};

    for (const r of ruter) {
      if (!r.linje) continue;
      if (r.retning === "innkjor" && sigEnde[r.linje]) {
        if (!sigEnde[r.linje].inn.includes(r.start)) {
          sigEnde[r.linje].inn.push(r.start);
        }
      }
      if (r.retning === "utkjor") {
        (utPerSig[r.start] ??= { spor: new Set(), linje: r.linje }).spor.add(
          r.spor
        );
      }
    }
    for (const [sig, o] of Object.entries(utPerSig)) {
      if (o.spor.size > 1) {
        if (sigEnde[o.linje] && !sigEnde[o.linje].ut.includes(sig)) {
          sigEnde[o.linje].ut.push(sig);
        }
      } else if (o.linje === vEnde || o.linje === hEnde) {
        const side = o.linje === vEnde ? "v" : "h";
        const sp = [...o.spor][0];
        if (sp) {
          (sigSpor[sp] ??= { v: [], h: [] })[side].push(sig);
        }
      }
    }

    // Veksler per togspor og side (kun veksler som faktisk tilhører togveiene!)
    const vxSpor: Record<string, { v: string[]; h: string[] }> = {};
    for (const r of ruter) {
      if (!r.spor || !r.linje) continue;
      const side = r.linje === vEnde ? "v" : r.linje === hEnde ? "h" : null;
      if (!side) continue;
      const bucket = (vxSpor[r.spor] ??= { v: [], h: [] })[side];
      for (const vx of r.veksler) {
        const lbl = `${vx.id}${vx.stilling === "avvik" ? "−" : "+"}`;
        if (!bucket.includes(lbl)) bucket.push(lbl);
      }
    }
    for (const o of Object.values(vxSpor)) {
      o.v.sort(cmp);
      o.h.sort(cmp);
    }

    // Forsignaler: påmonterte og frittstående
    const montertPaa: Record<string, string[]> = {};
    const frittFor: Record<string, string[]> = {};
    for (const fs of fns) {
      if (sigKlasse(fs.type, st) !== "forsignal") continue;
      if (fs.montert_med && sigAv(fs.montert_med)) {
        (montertPaa[fs.montert_med] ??= []).push(fs.id);
      } else if (!fs.montert_med && fs.varsler_om && sigAv(fs.varsler_om)) {
        (frittFor[fs.varsler_om] ??= []).push(fs.id);
      }
    }

    // Varselfelt per linjefelt
    const varselPerEnde: Record<string, string[]> = {};
    for (const m of fns) {
      if (m.type === "sporfelt" && m.rolle === "varselfelt" && m.linjefelt) {
        (varselPerEnde[m.linjefelt] ??= []).push(m.id);
      }
    }

    return {
      vEnde,
      hEnde,
      sporSortert,
      sigEnde,
      sigSpor,
      vxSpor,
      montertPaa,
      frittFor,
      varselPerEnde,
    };
  });

  let aktivTv = $derived(
    aktivTogveiId
      ? draft.togveier.find((t) => t.id === aktivTogveiId) || null
      : null
  );

  let aktivDeler = $derived.by(() => {
    if (!aktivTv)
      return { felt: new Set<string>(), veksler: new Set<string>(), start: "" };
    const { fra, til } = frEnder(aktivTv, draft.functions, draft.signaltyper);
    const felt = new Set<string>([
      ...(aktivTv.frie || []),
      fra,
      til,
      aktivTv.spor || "",
    ]);
    const vx = new Set<string>(
      (aktivTv.sporveksler || []).map((v) => v.sporveksel)
    );
    return { felt, veksler: vx, start: aktivTv.start || "" };
  });

  let advarsler = $derived(
    validerSporplan(draft.functions, draft.togveier, draft.signaltyper)
  );

  const HOVED_Y = 66;
  const SPOR_STEG = 52;
  let svgHoyde = $derived(
    Math.max(145, 80 + Math.max(1, modell.sporSortert.length) * SPOR_STEG)
  );

  function sporY(idx: number): number {
    return HOVED_Y + idx * SPOR_STEG;
  }

  function sigMedFs(sig: string, retning: "h" | "v"): string {
    const fs = modell.montertPaa[sig] || [];
    const base = retning === "h" ? `${sig}▶` : `◀${sig}`;
    if (!fs.length) return base;
    return (
      base +
      " " +
      fs.map((f) => (retning === "h" ? `${f}▷` : `◁${f}`)).join(" ")
    );
  }
</script>

<div class="space-y-3">
  {#if modell.sporSortert.length > 0 && (modell.vEnde || modell.hEnde)}
    <div class="rounded-lg border border-border bg-[#0c0e13] p-3 overflow-x-auto">
      <svg
        viewBox="0 0 920 {svgHoyde}"
        class="w-full min-w-[660px] h-auto block select-none"
        role="img"
        aria-label="Skjematisk sporplan"
      >
        <!-- Nabostasjoner -->
        {#if draft.anlegg?.nabo_venstre}
          <text
            x="14"
            y="18"
            fill="#8b949e"
            font-size="11"
            font-family="ui-monospace, monospace"
          >
            ← {draft.anlegg.nabo_venstre}
          </text>
        {/if}
        {#if draft.anlegg?.nabo_hoyre}
          <text
            x="906"
            y="18"
            text-anchor="end"
            fill="#8b949e"
            font-size="11"
            font-family="ui-monospace, monospace"
          >
            {draft.anlegg.nabo_hoyre} →
          </text>
        {/if}

        <!-- Venstre ende: varselfelt → frittstående forsignal → innkjørsignal → linjefelt → felles utkjør -->
        {#if modell.vEnde}
          {@const ende = modell.vEnde}
          {@const lys = aktivDeler.felt.has(ende)}
          {@const sv = modell.sigEnde[ende] || { inn: [], ut: [] }}
          {@const fritt = sv.inn.flatMap((s) => modell.frittFor[s] || [])}
          {@const mf = modell.varselPerEnde[ende] || []}

          <line
            x1="14"
            y1={HOVED_Y}
            x2="235"
            y2={HOVED_Y}
            stroke={lys ? "#d4a72c" : "#3b4452"}
            stroke-width={lys ? 5 : 3.5}
            stroke-linecap="round"
          />

          {#if mf.length}
            <text
              x="36"
              y={HOVED_Y - 12}
              text-anchor="middle"
              fill="#64748b"
              font-size="9.5"
              font-family="ui-monospace, monospace"
            >
              {mf.join(",")}
            </text>
          {/if}

          {#if fritt.length}
            <text
              x="76"
              y={HOVED_Y - 22}
              text-anchor="middle"
              fill="#eab308"
              font-size="10"
              font-family="ui-monospace, monospace"
            >
              {fritt.map((f) => `${f}▷`).join(" ")}
            </text>
          {/if}

          {#if sv.inn.length}
            {@const aktivInn = sv.inn.some((s) => aktivDeler.start === s)}
            <circle
              cx="118"
              cy={HOVED_Y - 14}
              r="4.5"
              fill={aktivInn ? "#d4a72c" : "#2ea043"}
            />
            <text
              x="118"
              y={HOVED_Y - 24}
              text-anchor="middle"
              fill={aktivInn ? "#ffd866" : "#cbd5e1"}
              font-size="10.5"
              font-weight="600"
              font-family="ui-monospace, monospace"
            >
              {sv.inn.map((s) => sigMedFs(s, "h")).join(" ")}
            </text>
          {/if}

          <!-- Linjefelt-merke -->
          <rect
            x="144"
            y={HOVED_Y - 11}
            width="44"
            height="22"
            rx="4"
            fill="#141820"
            stroke={lys ? "#d4a72c" : "#353c48"}
          />
          <text
            x="166"
            y={HOVED_Y + 4}
            text-anchor="middle"
            fill={lys ? "#ffd866" : "#e6ebf0"}
            font-size="11"
            font-weight="700"
            font-family="ui-monospace, monospace"
          >
            {ende}
          </text>

          {#if sv.ut.length}
            {@const aktivUt = sv.ut.some((s) => aktivDeler.start === s)}
            <circle
              cx="210"
              cy={HOVED_Y + 14}
              r="4.5"
              fill={aktivUt ? "#d4a72c" : "#2ea043"}
            />
            <text
              x="210"
              y={HOVED_Y + 29}
              text-anchor="middle"
              fill={aktivUt ? "#ffd866" : "#cbd5e1"}
              font-size="10.5"
              font-weight="600"
              font-family="ui-monospace, monospace"
            >
              {sv.ut.map((s) => sigMedFs(s, "v")).join(" ")}
            </text>
          {/if}
        {/if}

        <!-- Høyre ende: felles utkjør → linjefelt → innkjørsignal → frittstående forsignal → varselfelt -->
        {#if modell.hEnde}
          {@const ende = modell.hEnde}
          {@const lys = aktivDeler.felt.has(ende)}
          {@const sv = modell.sigEnde[ende] || { inn: [], ut: [] }}
          {@const fritt = sv.inn.flatMap((s) => modell.frittFor[s] || [])}
          {@const mf = modell.varselPerEnde[ende] || []}

          <line
            x1="685"
            y1={HOVED_Y}
            x2="906"
            y2={HOVED_Y}
            stroke={lys ? "#d4a72c" : "#3b4452"}
            stroke-width={lys ? 5 : 3.5}
            stroke-linecap="round"
          />

          {#if sv.ut.length}
            {@const aktivUt = sv.ut.some((s) => aktivDeler.start === s)}
            <circle
              cx="710"
              cy={HOVED_Y - 14}
              r="4.5"
              fill={aktivUt ? "#d4a72c" : "#2ea043"}
            />
            <text
              x="710"
              y={HOVED_Y - 24}
              text-anchor="middle"
              fill={aktivUt ? "#ffd866" : "#cbd5e1"}
              font-size="10.5"
              font-weight="600"
              font-family="ui-monospace, monospace"
            >
              {sv.ut.map((s) => sigMedFs(s, "h")).join(" ")}
            </text>
          {/if}

          <rect
            x="732"
            y={HOVED_Y - 11}
            width="44"
            height="22"
            rx="4"
            fill="#141820"
            stroke={lys ? "#d4a72c" : "#353c48"}
          />
          <text
            x="754"
            y={HOVED_Y + 4}
            text-anchor="middle"
            fill={lys ? "#ffd866" : "#e6ebf0"}
            font-size="11"
            font-weight="700"
            font-family="ui-monospace, monospace"
          >
            {ende}
          </text>

          {#if sv.inn.length}
            {@const aktivInn = sv.inn.some((s) => aktivDeler.start === s)}
            <circle
              cx="802"
              cy={HOVED_Y + 14}
              r="4.5"
              fill={aktivInn ? "#d4a72c" : "#2ea043"}
            />
            <text
              x="802"
              y={HOVED_Y + 29}
              text-anchor="middle"
              fill={aktivInn ? "#ffd866" : "#cbd5e1"}
              font-size="10.5"
              font-weight="600"
              font-family="ui-monospace, monospace"
            >
              {sv.inn.map((s) => sigMedFs(s, "v")).join(" ")}
            </text>
          {/if}

          {#if fritt.length}
            <text
              x="846"
              y={HOVED_Y + 28}
              text-anchor="middle"
              fill="#eab308"
              font-size="10"
              font-family="ui-monospace, monospace"
            >
              {fritt.map((f) => `◁${f}`).join(" ")}
            </text>
          {/if}

          {#if mf.length}
            <text
              x="886"
              y={HOVED_Y - 12}
              text-anchor="middle"
              fill="#64748b"
              font-size="9.5"
              font-family="ui-monospace, monospace"
            >
              {mf.join(",")}
            </text>
          {/if}
        {/if}

        <!-- Togspor med grener, togvei-veksler og evt. enkeltspor-utkjørsignaler -->
        {#each modell.sporSortert as sp, idx (sp)}
          {@const y = sporY(idx)}
          {@const lys = aktivDeler.felt.has(sp)}
          {@const lysV = lys && !!modell.vEnde && aktivDeler.felt.has(modell.vEnde)}
          {@const lysH = lys && !!modell.hEnde && aktivDeler.felt.has(modell.hEnde)}
          {@const vx = modell.vxSpor[sp] || { v: [], h: [] }}
          {@const sg = modell.sigSpor[sp] || { v: [], h: [] }}

          {#if modell.vEnde}
            <path
              d="M 235 {HOVED_Y} L 305 {y} L 345 {y}"
              fill="none"
              stroke={lysV ? "#d4a72c" : "#323a46"}
              stroke-width={lysV ? 4.5 : 3}
            />
            {#if vx.v.length}
              <text
                x="325"
                y={y - 10}
                text-anchor="middle"
                fill={lysV ? "#ffd866" : "#94a3b8"}
                font-size="10"
                font-weight="600"
                font-family="ui-monospace, monospace"
              >
                {vx.v.join(", ")}
              </text>
            {/if}
          {/if}

          {#if modell.hEnde}
            <path
              d="M 575 {y} L 615 {y} L 685 {HOVED_Y}"
              fill="none"
              stroke={lysH ? "#d4a72c" : "#323a46"}
              stroke-width={lysH ? 4.5 : 3}
            />
            {#if vx.h.length}
              <text
                x="595"
                y={y - 10}
                text-anchor="middle"
                fill={lysH ? "#ffd866" : "#94a3b8"}
                font-size="10"
                font-weight="600"
                font-family="ui-monospace, monospace"
              >
                {vx.h.join(", ")}
              </text>
            {/if}
          {/if}

          <line
            x1="345"
            y1={y}
            x2="575"
            y2={y}
            stroke={lys ? "#d4a72c" : "#4b5563"}
            stroke-width={lys ? 5 : 3.5}
            stroke-linecap="round"
          />

          <!-- Enkeltspor utkjørsignal mot venstre -->
          {#if sg.v.length}
            {@const aktivSig = sg.v.some((s) => aktivDeler.start === s)}
            <text
              x="382"
              y={y - 10}
              text-anchor="middle"
              fill={aktivSig ? "#ffd866" : "#cbd5e1"}
              font-size="10"
              font-weight="600"
              font-family="ui-monospace, monospace"
            >
              {sg.v.map((s) => sigMedFs(s, "v")).join(" ")}
            </text>
          {/if}

          <!-- Togspor-etikett -->
          <rect
            x="428"
            y={y - 11}
            width="64"
            height="22"
            rx="4"
            fill="#141820"
            stroke={lys ? "#d4a72c" : "#353c48"}
          />
          <text
            x="460"
            y={y + 4}
            text-anchor="middle"
            fill={lys ? "#ffd866" : "#e6ebf0"}
            font-size="11.5"
            font-weight="700"
            font-family="ui-monospace, monospace"
          >
            Spor {sp}
          </text>

          <!-- Enkeltspor utkjørsignal mot høyre -->
          {#if sg.h.length}
            {@const aktivSig = sg.h.some((s) => aktivDeler.start === s)}
            <text
              x="538"
              y={y - 10}
              text-anchor="middle"
              fill={aktivSig ? "#ffd866" : "#cbd5e1"}
              font-size="10"
              font-weight="600"
              font-family="ui-monospace, monospace"
            >
              {sg.h.map((s) => sigMedFs(s, "h")).join(" ")}
            </text>
          {/if}
        {/each}
      </svg>
    </div>
  {/if}

  <!-- Kompletthets-sjekkliste -->
  {#if advarsler.length === 0 && draft.togveier.length > 0}
    <div class="flex items-center gap-2 rounded-md border border-ok/35 bg-ok/10 px-3 py-2 text-xs text-ok">
      <CheckCircle2 class="w-4 h-4 shrink-0" />
      <span>Alle togspor har fullstendige inn- og utkjørtogveier uten sporplankonflikter.</span>
    </div>
  {:else if advarsler.length > 0}
    <div class="rounded-md border border-amber/35 bg-amber/10 p-3 space-y-2 text-xs">
      <div class="flex items-center gap-1.5 font-semibold text-amber">
        <AlertTriangle class="w-4 h-4 shrink-0" />
        <span>Sporplansjekk ({advarsler.length} {advarsler.length === 1 ? "punkt" : "punkter"})</span>
      </div>
      <div class="space-y-1.5">
        {#each advarsler as a, idx (idx)}
          <div class="flex flex-wrap items-center justify-between gap-2 text-[11.5px] text-foreground/90">
            <span>• {a.tekst}</span>
            {#if a.opprett}
              <Button
                size="xs"
                variant="outline"
                onclick={() => onopprett(a.opprett!)}
              >
                <Plus class="w-3 h-3" />
                Opprett
              </Button>
            {/if}
          </div>
        {/each}
      </div>
    </div>
  {/if}
</div>
