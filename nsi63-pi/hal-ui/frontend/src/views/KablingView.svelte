<script lang="ts">
  import { AlertTriangle, Cpu, Plus } from "@lucide/svelte";
  import { toast } from "svelte-sonner";
  import ObjektInspektor from "$components/ObjektInspektor.svelte";
  import Badge from "$components/ui/Badge.svelte";
  import Button from "$components/ui/Button.svelte";
  import Card from "$components/ui/Card.svelte";
  import Dialog from "$components/ui/Dialog.svelte";
  import Progress from "$components/ui/Progress.svelte";
  import Switch from "$components/ui/Switch.svelte";
  import {
    GPIO_PINNER,
    KB_BRIKKER,
    MAX_ORDREPUNKTER,
    WARN_ORDREPUNKTER,
    aliasFor,
    bindErInngang,
    bindingsrader,
    brikkeKapasitet,
    brikkeNavn,
    driverBrikkerForMac,
    i2cNorm,
    inputNokkel,
    macForNode,
    portNokkel,
    portSymbol,
    signalLampeFarge,
  } from "$lib/domain/regler";
  import { draft, type DraftFunction } from "$lib/stores/draft.svelte";
  import { live } from "$lib/stores/live.svelte";

  interface Props {
    focusNode?: string | null;
    onclearfocus?: () => void;
  }

  let { focusNode = null, onclearfocus }: Props = $props();

  let visAlleBrikker = $state(false);
  let valgtNodeMac = $state<string | null>(null);
  let valgtObjRid = $state<number | null>(null);
  let inspektorApen = $state(false);

  // Tilordningsdialog ved klikk på ledig port
  let ledigPort = $state<{
    mac: string;
    nodeRef: string;
    i2c: string;
    port: number;
  } | null>(null);
  let sokSlot = $state("");

  $effect(() => {
    if (focusNode) {
      valgtNodeMac = focusNode.toLowerCase();
      onclearfocus?.();
    }
  });

  interface NodeKortData {
    mac: string;
    alias: string | null;
    nodeRef: string;
    online: boolean | null;
    skannet: string[];
    drivere: string[];
    ordrer: number;
  }

  let alleNoder = $derived.by(() => {
    const map = new Map<string, NodeKortData>();
    for (const ln of live.nodes.nodes || []) {
      const mac = ln.mac.toLowerCase();
      const alias = aliasFor(mac, draft.noder);
      map.set(mac, {
        mac,
        alias,
        nodeRef: alias || mac,
        online: !!ln.online,
        skannet: (ln.i2c || []).map((a) => i2cNorm(a)),
        drivere: driverBrikkerForMac(mac, draft.noder),
        ordrer: draft.portKart.ordrer[mac] || 0,
      });
    }
    for (const [k, v] of Object.entries(draft.noder)) {
      if (!v?.mac) continue;
      const mac = v.mac.toLowerCase();
      if (!map.has(mac)) {
        const alias = aliasFor(mac, draft.noder);
        map.set(mac, {
          mac,
          alias,
          nodeRef: alias || (k.toLowerCase() === mac ? mac : k),
          online: null,
          skannet: [],
          drivere: driverBrikkerForMac(mac, draft.noder),
          ordrer: draft.portKart.ordrer[mac] || 0,
        });
      }
    }
    for (const mac of Object.keys(draft.portKart.kart)) {
      if (!map.has(mac)) {
        const alias = aliasFor(mac, draft.noder);
        map.set(mac, {
          mac,
          alias,
          nodeRef: alias || mac,
          online: null,
          skannet: [],
          drivere: driverBrikkerForMac(mac, draft.noder),
          ordrer: draft.portKart.ordrer[mac] || 0,
        });
      }
    }
    return [...map.values()].sort((a, b) =>
      (a.alias || a.mac).localeCompare(b.alias || b.mac, "no", { numeric: true })
    );
  });

  function brikkerForNode(nd: NodeKortData): string[] {
    if (visAlleBrikker) return [...KB_BRIKKER];
    const brukt = Object.keys(draft.portKart.kart[nd.mac] || {});
    const sett = new Set<string>([...nd.skannet, ...brukt]);
    if (sett.size === 0) return ["0x40", "0x20", "gpio"];
    return KB_BRIKKER.filter((b) => sett.has(b));
  }

  function inngangAktiv(mac: string, i2c: string, port: number): boolean | null {
    const key = inputNokkel(mac, i2c);
    const byte = live.inputs[key];
    if (byte === undefined) return null;
    // Aktiv lav på PCF8574 og GPIO
    return ((byte >> port) & 1) === 0;
  }

  function ledigeAntall(mac: string, i2c: string): { brukt: number; fri: number; kap: number } {
    const kap = brikkeKapasitet(i2c) || 8;
    const porter = draft.portKart.kart[mac]?.[i2c] || {};
    let brukt = 0;
    for (let p = 0; p < kap; p++) {
      if ((porter[p] || []).length > 0) brukt++;
    }
    return { brukt, fri: Math.max(0, kap - brukt), kap };
  }

  function apneObjekt(objIdx: number) {
    const f = draft.functions[objIdx];
    if (!f) return;
    valgtObjRid = f._rid;
    inspektorApen = true;
  }

  function apneLedig(nd: NodeKortData, i2c: string, port: number) {
    ledigPort = { mac: nd.mac, nodeRef: nd.nodeRef, i2c, port };
    sokSlot = "";
  }

  // Ubundne kompatible plasser for tilordningsdialogen
  interface LedigKandidat {
    obj: DraftFunction;
    sted: string;
    navn: string;
    inn: boolean;
    lamper: number;
    passer: boolean;
  }

  let kandidater = $derived.by((): LedigKandidat[] => {
    if (!ledigPort) return [];
    const { mac, i2c, port } = ledigPort;
    const erPca = i2c.startsWith("0x4");
    const erPcf = i2c.startsWith("0x2");
    const kap = brikkeKapasitet(i2c) || 8;
    const needle = sokSlot.trim().toLowerCase();
    const out: LedigKandidat[] = [];

    for (const obj of draft.functions) {
      const rader = bindingsrader(obj.type, obj.rolle || "", draft.signaltyper);
      const st = draft.signaltyper[obj.type];
      for (const rad of rader) {
        for (const sted of [rad.a, rad.b].filter(Boolean) as string[]) {
          const alleredeBundet = (obj.bindinger || []).some(
            (b) => b.sted === sted && b.node
          );
          if (alleredeBundet) continue;
          const inn = bindErInngang(obj.type, sted);
          if (erPca && inn) continue;
          if (erPcf && !inn) continue;

          if (needle) {
            const hay = `${obj.id} ${obj.type} ${sted} ${rad.navn}`.toLowerCase();
            if (!hay.includes(needle)) continue;
          }

          const lamper =
            st && (sted === "anlegg" || sted === "panel") ? st.lamper || 1 : 1;
          let passer = port + lamper <= kap;
          if (passer && !inn) {
            for (let k = 0; k < lamper; k++) {
              const eks = draft.portKart.kart[mac]?.[i2c]?.[port + k] || [];
              if (eks.length > 0) {
                passer = false;
                break;
              }
            }
          }
          out.push({ obj, sted, navn: rad.navn, inn, lamper, passer });
        }
      }
    }
    return out;
  });

  function bindTilPort(k: LedigKandidat) {
    if (!ledigPort) return;
    if (!k.passer) {
      toast.error(
        `${k.obj.id || "(uten litra)"} trenger ${k.lamper} ledige sammenhengende porter her`
      );
      return;
    }
    draft.settBinding(k.obj._rid, k.sted, {
      sted: k.sted,
      node: ledigPort.nodeRef,
      i2c: ledigPort.i2c,
      port: ledigPort.port,
    });
    toast.success(
      `Bandt ${k.obj.id || "(uten litra)"} (${k.sted}) til ${ledigPort.nodeRef} ${ledigPort.i2c} port ${ledigPort.port}`
    );
    ledigPort = null;
  }

  let valgtObj = $derived(
    draft.functions.find((f) => f._rid === valgtObjRid) || null
  );
</script>

<div class="space-y-4">
  <!-- Topplinje: Forklaring + Filter -->
  <div class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card px-4 py-2.5 text-xs">
    <div class="flex flex-wrap items-center gap-3 text-[11.5px] text-muted-foreground">
      <span class="flex items-center gap-1.5">
        <span class="w-2.5 h-2.5 rounded-sm bg-ut/30 border border-ut"></span>
        Utgang (PCA/GPIO)
      </span>
      <span class="flex items-center gap-1.5">
        <span class="w-2.5 h-2.5 rounded-sm bg-inn/30 border border-inn"></span>
        Inngang (PCF/GPIO)
      </span>
      <span class="flex items-center gap-1.5">
        <span class="w-2 h-2 rounded-full bg-ok"></span>
        Inngang aktiv (lav)
      </span>
      <span class="flex items-center gap-1.5">
        <span class="w-2.5 h-2.5 rounded-sm bg-warn/30 border border-warn"></span>
        Konflikt / utenfor brikke
      </span>
      <span class="hidden sm:inline text-muted-foreground/40">|</span>
      <span class="font-mono text-[11px]">● signallampe</span>
      <span class="font-mono text-[11px]">○ kontrollampe</span>
      <span class="font-mono text-[11px]">⇄ drivutgang</span>
      <span class="font-mono text-[11px]">◎ sensor</span>
      <span class="font-mono text-[11px]">▣ knapp/stiller</span>
    </div>

    <div class="flex items-center gap-3">
      {#if valgtNodeMac}
        <Button size="xs" variant="ghost" onclick={() => (valgtNodeMac = null)}>
          Vis alle noder
        </Button>
      {/if}
      <label class="flex items-center gap-2 cursor-pointer text-xs">
        <Switch bind:checked={visAlleBrikker} />
        <span>Vis alle mulige brikkeadresser</span>
      </label>
    </div>
  </div>

  <!-- Portfeil-banner -->
  {#if draft.portKart.feil.length > 0}
    <div class="rounded-lg border border-warn/40 bg-warn/10 px-3.5 py-2.5 text-xs text-warn space-y-1">
      <div class="font-semibold flex items-center gap-1.5">
        <AlertTriangle class="w-4 h-4 shrink-0" />
        {draft.portKart.feil.length} portfeil i kablingen:
      </div>
      <ul class="list-disc pl-5 space-y-0.5 text-[11.5px]">
        {#each draft.portKart.feil as feil}
          <li>{feil}</li>
        {/each}
      </ul>
    </div>
  {/if}

  {#if !alleNoder.length}
    <Card class="p-8 text-center space-y-2">
      <Cpu class="w-7 h-7 text-muted-foreground mx-auto opacity-60" />
      <div class="text-sm font-medium">Ingen noder oppdaget eller konfigurert ennå</div>
      <p class="text-xs text-muted-foreground">
        Slå på en node i nettet, eller legg til bindinger under Objekter.
      </p>
    </Card>
  {:else}
    {#each alleNoder.filter((n) => !valgtNodeMac || n.mac === valgtNodeMac) as nd (nd.mac)}
      {@const brikker = brikkerForNode(nd)}
      {@const ordreTone =
        nd.ordrer > MAX_ORDREPUNKTER
          ? "warn"
          : nd.ordrer > WARN_ORDREPUNKTER
            ? "amber"
            : "ok"}
      <Card class="p-4 space-y-4">
        <!-- Node-topp -->
        <div class="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-border">
          <div class="flex items-center gap-2.5 min-w-0">
            <span
              class="w-2.5 h-2.5 rounded-full shrink-0 {nd.online === true
                ? 'bg-ok'
                : nd.online === false
                  ? 'bg-warn'
                  : 'bg-muted-foreground/40'}"
              title={nd.online === true ? "Online" : nd.online === false ? "Offline" : "Ikke sett live"}
            ></span>
            <div>
              <div class="flex items-center gap-2 flex-wrap">
                <h2 class="text-sm font-bold font-mono">{nd.alias || nd.mac}</h2>
                {#if nd.alias}
                  <span class="text-[11px] font-mono text-muted-foreground">{nd.mac}</span>
                {/if}
                {#if nd.online === false}
                  <Badge variant="warn">offline</Badge>
                {:else if nd.online === null}
                  <Badge variant="muted">ikke sett</Badge>
                {/if}
              </div>
              {#if nd.skannet.length}
                <div class="text-[11px] text-muted-foreground font-mono mt-0.5">
                  Skannet I2C: {nd.skannet.join(", ")}
                </div>
              {/if}
            </div>
          </div>

          <div class="w-48 space-y-1">
            <div class="flex items-center justify-between text-[11px] tabular">
              <span class="text-muted-foreground">Ordrepunkter</span>
              <span class="font-mono font-semibold {ordreTone === 'warn' ? 'text-warn' : ordreTone === 'amber' ? 'text-amber' : 'text-foreground'}">
                {nd.ordrer} / {MAX_ORDREPUNKTER}
              </span>
            </div>
            <Progress
              value={nd.ordrer}
              max={MAX_ORDREPUNKTER}
              warnAt={WARN_ORDREPUNKTER}
              dangerAt={MAX_ORDREPUNKTER}
            />
          </div>
        </div>

        <!-- Brikker -->
        <div class="space-y-4">
          {#each brikker as i2c (i2c)}
            {@const kap = brikkeKapasitet(i2c) || 8}
            {@const teller = ledigeAntall(nd.mac, i2c)}
            {@const erSkannet = i2c === "gpio" || nd.skannet.includes(i2c)}
            {@const erDriver = nd.drivere.includes(i2c)}
            {@const erInngangsBrikke = i2c.startsWith("0x2") || i2c === "gpio"}
            {@const porter = draft.portKart.kart[nd.mac]?.[i2c] || {}}

            <div class="space-y-1.5">
              <div class="flex flex-wrap items-center justify-between gap-2 text-xs">
                <div class="flex items-center gap-2">
                  <span class="font-mono font-semibold text-foreground">{brikkeNavn(i2c)}</span>
                  {#if !erSkannet}
                    <Badge variant="amber">ikke skannet</Badge>
                  {/if}
                  {#if erDriver}
                    <Badge variant="inn">12 V-driver</Badge>
                  {/if}
                </div>
                <span class="text-[11px] font-mono text-muted-foreground tabular">
                  {teller.brukt} i bruk · {teller.fri} ledige
                </span>
              </div>

              <div
                class="grid gap-1.5 {kap === 6
                  ? 'grid-cols-2 sm:grid-cols-3 md:grid-cols-6'
                  : 'grid-cols-2 sm:grid-cols-4 lg:grid-cols-8'}"
              >
                {#each Array.from({ length: kap }, (_, p) => p) as p (p)}
                  {@const bruk = porter[p] || []}
                  {@const harFeil = draft.portKart.feilNokler.has(portNokkel(nd.mac, i2c, p))}
                  {@const aktiv = erInngangsBrikke ? inngangAktiv(nd.mac, i2c, p) : null}
                  {@const forste = bruk[0]}
                  {@const farge = forste ? signalLampeFarge(forste.type, forste.del, forste.sted) : null}

                  {#if bruk.length > 0}
                    <button
                      type="button"
                      onclick={() => apneObjekt(forste.objIdx)}
                      class="group relative flex flex-col justify-between text-left rounded-md border px-2 py-1.5 min-h-[60px] cursor-pointer transition-colors {harFeil
                        ? 'border-warn bg-warn/15 hover:bg-warn/20'
                        : forste.inn
                          ? 'border-inn/45 bg-inn/10 hover:bg-inn/20'
                          : 'border-ut/45 bg-ut/10 hover:bg-ut/20'}"
                      style={farge && !harFeil ? `border-left-width: 3px; border-left-color: ${farge};` : undefined}
                      title={bruk
                        .map((b) => `${b.litra || "?"} · ${b.sted}${b.av > 1 ? ` (${b.del + 1}/${b.av})` : ""}`)
                        .join("\n")}
                    >
                      <div class="flex items-center justify-between gap-1 text-[10px] font-mono text-muted-foreground">
                        <span>{i2c === "gpio" ? `${p} (${GPIO_PINNER[p]})` : `P${p}`}</span>
                        <span class="flex items-center gap-1">
                          {#if farge}
                            <span
                              class="w-2 h-2 rounded-full inline-block"
                              style="background-color: {farge};"
                            ></span>
                          {/if}
                          {#if aktiv !== null}
                            <span
                              class="w-2 h-2 rounded-full inline-block {aktiv ? 'bg-ok' : 'bg-muted-foreground/35'}"
                              title={aktiv ? "Aktiv (lav)" : "Inaktiv (høy)"}
                            ></span>
                          {/if}
                        </span>
                      </div>

                      <div class="mt-0.5 space-y-0.5 min-w-0">
                        <div class="flex items-center gap-1 font-mono text-xs font-bold text-foreground truncate">
                          <span class="text-[10px] opacity-80">{portSymbol(forste.sted, forste.type)}</span>
                          <span class="truncate">{forste.litra || "(tom)"}</span>
                          {#if bruk.length > 1}
                            <span class="text-[10px] text-amber">+{bruk.length - 1}</span>
                          {/if}
                        </div>
                        <div class="text-[10px] text-muted-foreground truncate">
                          {forste.sted}{forste.av > 1 ? ` ${forste.del + 1}/${forste.av}` : ""}
                        </div>
                      </div>
                    </button>
                  {:else}
                    <button
                      type="button"
                      onclick={() => apneLedig(nd, i2c, p)}
                      class="group flex flex-col justify-between text-left rounded-md border border-dashed border-border hover:border-primary/70 hover:bg-secondary/60 px-2 py-1.5 min-h-[60px] cursor-pointer transition-colors"
                      title="Klikk for å binde et ubundet objekt til denne porten"
                    >
                      <div class="flex items-center justify-between gap-1 text-[10px] font-mono text-muted-foreground">
                        <span>{i2c === "gpio" ? `${p} (${GPIO_PINNER[p]})` : `P${p}`}</span>
                        {#if aktiv !== null}
                          <span
                            class="w-2 h-2 rounded-full inline-block {aktiv ? 'bg-ok' : 'bg-muted-foreground/30'}"
                            title={aktiv ? "Aktiv (lav)" : "Inaktiv (høy)"}
                          ></span>
                        {/if}
                      </div>
                      <div class="flex items-center gap-1 text-[10.5px] text-muted-foreground/50 group-hover:text-primary">
                        <Plus class="w-3 h-3" />
                        <span>ledig</span>
                      </div>
                    </button>
                  {/if}
                {/each}
              </div>
            </div>
          {/each}
        </div>
      </Card>
    {/each}
  {/if}
</div>

<!-- Høyreskuff: rediger opptatt objekt rett fra Kabling -->
<Dialog
  bind:open={inspektorApen}
  side="right"
  title={valgtObj ? `Objekt ${valgtObj.id || "(uten litra)"}` : "Objekt"}
>
  {#if valgtObj}
    <ObjektInspektor
      obj={valgtObj}
      ondeleted={() => {
        valgtObjRid = null;
        inspektorApen = false;
      }}
    />
  {/if}
</Dialog>

<!-- Tilordningsdialog ved klikk på ledig port -->
<Dialog
  open={ledigPort !== null}
  onOpenChange={(o) => {
    if (!o) ledigPort = null;
  }}
  title={ledigPort
    ? `Bind til ${ledigPort.nodeRef} · ${ledigPort.i2c} port ${ledigPort.port}`
    : "Bind port"}
  description="Velg en ubundet plass på et eksisterende objekt."
>
  <div class="space-y-3">
    <input
      type="text"
      bind:value={sokSlot}
      placeholder="Filtrer objekter (litra, type, sted)…"
      class="w-full text-xs"
    />

    {#if !kandidater.length}
      <div class="py-6 text-center text-xs text-muted-foreground">
        Ingen ubundne kompatible plasser funnet for denne brikken.
      </div>
    {:else}
      <div class="max-h-72 overflow-y-auto divide-y divide-border/60 rounded-md border border-border">
        {#each kandidater as k (`${k.obj._rid}-${k.sted}`)}
          <button
            type="button"
            disabled={!k.passer}
            onclick={() => bindTilPort(k)}
            class="w-full text-left px-3 py-2 flex items-center justify-between gap-2 text-xs hover:bg-secondary/60 disabled:opacity-45 disabled:cursor-not-allowed cursor-pointer"
          >
            <div class="min-w-0">
              <div class="flex items-center gap-2">
                <strong class="font-mono">{k.obj.id || "(uten litra)"}</strong>
                <span class="text-muted-foreground">{k.obj.type}</span>
              </div>
              <div class="text-[11px] text-muted-foreground">
                {k.navn} (<span class="font-mono">{k.sted}</span>)
                {#if k.lamper > 1}
                  · {k.lamper} sammenhengende porter
                {/if}
              </div>
            </div>
            <div class="shrink-0">
              {#if !k.passer}
                <Badge variant="warn">får ikke plass</Badge>
              {:else}
                <Badge variant={k.inn ? "inn" : "ut"}>{k.inn ? "inngang" : "utgang"}</Badge>
              {/if}
            </div>
          </button>
        {/each}
      </div>
    {/if}
  </div>
</Dialog>
