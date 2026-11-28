<script lang="ts">
  import { ChevronDown, ChevronRight, Plus, Trash2 } from "@lucide/svelte";
  import Badge from "$components/ui/Badge.svelte";
  import Button from "$components/ui/Button.svelte";
  import ConfirmDialog from "$components/ui/ConfirmDialog.svelte";
  import FeltEtikett from "$components/ui/FeltEtikett.svelte";
  import Switch from "$components/ui/Switch.svelte";
  import {
    GPIO_PINNER,
    GRUPPER,
    I2C_ALLE,
    MAX_LITRA_UI,
    aliasFor,
    bindErInngang,
    bindingsrader,
    brikkeKapasitet,
    defaultI2c,
    erHoved,
    gruppeIdx,
    hovedsignalManglerRolle,
    i2cLabel,
    i2cNorm,
    isDverg,
    isLaas,
    isManuell,
    isNoenVeksel,
    isSkift,
    isSperre,
    isVeksel,
    litraUgyldig,
    macForNode,
    portNokkel,
    portSymbol,
    rensObjektVedTypeBytte,
    rensSporfeltVedRolleBytte,
    utledetEnde,
  } from "$lib/domain/regler";
  import { draft, type DraftFunction } from "$lib/stores/draft.svelte";
  import { live } from "$lib/stores/live.svelte";
  import type { Binding } from "$lib/types";

  interface Props {
    obj: DraftFunction;
    ondeleted?: () => void;
  }

  let { obj, ondeleted }: Props = $props();

  let visTegning = $state(false);
  let bekreftSlett = $state(false);

  let gruppe = $derived(GRUPPER[gruppeIdx(obj.type)] || GRUPPER[GRUPPER.length - 1]);
  let erVekselGrp = $derived(isNoenVeksel(obj.type));
  let litraFeil = $derived(litraUgyldig(obj.id || ""));

  // Tilgjengelige noder i nedtrekket (kallenavn uten driver-only MAC-nøkler + live MAC-er)
  let nodeValg = $derived.by(() => {
    const out: { val: string; lbl: string }[] = [];
    const settMac = new Set<string>();
    const liveListe = live.nodes.nodes || [];
    for (const [k, v] of Object.entries(draft.noder)) {
      if (!v?.mac) continue;
      if (k.toLowerCase() === v.mac.toLowerCase()) continue;
      settMac.add(v.mac.toLowerCase());
      const ln = liveListe.find((x) => x.mac.toLowerCase() === v.mac.toLowerCase());
      const merke = ln ? (ln.online ? "" : " ⊘") : " ?";
      out.push({ val: k, lbl: `${k}${merke}` });
    }
    for (const ln of liveListe) {
      if (settMac.has(ln.mac.toLowerCase())) continue;
      out.push({ val: ln.mac, lbl: `${ln.mac}${ln.online ? "" : " ⊘"}` });
    }
    return out;
  });

  function i2cValgFor(nodeVal: string, curI2c: string): string[] {
    const mac = macForNode(nodeVal, draft.noder);
    const ln = (live.nodes.nodes || []).find((x) => x.mac.toLowerCase() === mac);
    const base: string[] =
      ln && ln.i2c && ln.i2c.length ? [...ln.i2c, "gpio"] : [...I2C_ALLE, "gpio"];
    const norm = i2cNorm(curI2c);
    if (norm && !base.includes(norm)) base.push(norm);
    return base;
  }

  let hovedsignaler = $derived(
    draft.functions
      .filter((f) => erHoved(f.type, draft.signaltyper) && f.id.trim())
      .map((f) => f.id.trim())
  );

  let linjefelter = $derived(
    draft.functions
      .filter((f) => f.type === "sporfelt" && f.rolle === "linjefelt" && f.id.trim())
      .map((f) => f.id.trim())
  );

  let topoValg = $derived.by(() => {
    const felt = draft.functions
      .filter((f) => f.type === "sporfelt" && f.id.trim())
      .map((f) => f.id.trim());
    const vx = draft.functions
      .filter((f) => isNoenVeksel(f.type) && f.id.trim())
      .map((f) => `veksel ${f.id.trim()}`);
    return [...felt, ...vx];
  });

  // For skiftesignal (kun sentralstilte veksler) og samlelås/rigel (alle veksler + sporsperrer)
  let kjenteVekslerForSkift = $derived(
    draft.functions
      .filter((f) => isVeksel(f.type) && f.id.trim())
      .map((f) => f.id.trim())
  );
  let kjenteObjForLaas = $derived(
    draft.functions
      .filter((f) => (isNoenVeksel(f.type) || isSperre(f.type)) && f.id.trim())
      .map((f) => f.id.trim())
  );

  // U1: Eksterne objekter på samlelaas/rigel vises KUN i fritekstfeltet
  let kjenteLaasSett = $derived(new Set(kjenteObjForLaas));
  let laasUtenforTekst = $derived(
    (obj.omfatter || []).filter((x) => !kjenteLaasSett.has(x)).join(", ")
  );

  // Ugyldige skift_sporveksler (f.eks. slettet eller manuellveksel) vises med advarsel så de kan fjernes
  let ugyldigeSkiftVeksler = $derived(
    (obj.skift_sporveksler || []).filter(
      (x) => !kjenteVekslerForSkift.includes(x)
    )
  );

  function oppdater(patch: Partial<DraftFunction>) {
    draft.oppdaterObjekt(obj._rid, { ...obj, ...patch });
  }

  function byttType(nyType: string) {
    const renset = rensObjektVedTypeBytte(obj, nyType, draft.signaltyper);
    draft.oppdaterObjekt(obj._rid, {
      ...renset,
      _rid: obj._rid,
      _orgId: obj._orgId,
    });
  }

  function byttSporfeltRolle(val: string) {
    const renset = rensSporfeltVedRolleBytte(obj, val);
    draft.oppdaterObjekt(obj._rid, {
      ...renset,
      _rid: obj._rid,
      _orgId: obj._orgId,
    });
  }

  function finnBinding(sted: string, idx = 0): Binding | null {
    let n = 0;
    for (const b of obj.bindinger || []) {
      if (b.sted === sted) {
        if (n === idx) return b;
        n++;
      }
    }
    return null;
  }

  function oppdaterSlot(
    sted: string,
    idx: number,
    felt: "node" | "i2c" | "port",
    verdi: string
  ) {
    const cur = finnBinding(sted, idx);
    if (felt === "node" && !verdi) {
      draft.settBinding(obj._rid, sted, null, idx);
      return;
    }
    const neste: Binding = cur
      ? { ...cur }
      : {
          sted,
          node: "",
          i2c: defaultI2c(obj.type, sted),
          port: 0,
        };
    if (felt === "node") {
      neste.node = verdi;
      const valg = i2cValgFor(verdi, String(neste.i2c));
      if (!valg.includes(i2cNorm(neste.i2c))) {
        neste.i2c = valg[0] || defaultI2c(obj.type, sted);
      }
    } else if (felt === "i2c") {
      neste.i2c = verdi;
      const kap = brikkeKapasitet(verdi) ?? 16;
      if (neste.port >= kap) neste.port = kap - 1;
    } else {
      neste.port = Math.max(0, parseInt(verdi, 10) || 0);
    }
    if (!neste.node) return;
    draft.settBinding(obj._rid, sted, neste, idx);
  }

  function slotHarKonflikt(b: Binding | null): boolean {
    if (!b || !b.node) return false;
    const mac = macForNode(b.node, draft.noder);
    const st = draft.signaltyper[obj.type];
    const n =
      st && (b.sted === "anlegg" || b.sted === "panel") ? st.lamper || 1 : 1;
    for (let k = 0; k < n; k++) {
      if (draft.portKart.feilNokler.has(portNokkel(mac, b.i2c, Number(b.port) + k))) {
        return true;
      }
    }
    return false;
  }

  function toggleSkiftVeksel(vid: string, paa: boolean) {
    const cur = new Set(obj.skift_sporveksler || []);
    if (paa) cur.add(vid);
    else cur.delete(vid);
    oppdater({ skift_sporveksler: [...cur] });
  }

  function toggleLaasObj(oid: string, paa: boolean) {
    const utenfor = (obj.omfatter || []).filter((x) => !kjenteLaasSett.has(x));
    const kjente = new Set(
      (obj.omfatter || []).filter((x) => kjenteLaasSett.has(x))
    );
    if (paa) kjente.add(oid);
    else kjente.delete(oid);
    oppdater({ omfatter: [...kjente, ...utenfor] });
  }

  function settLaasUtenfor(tekst: string) {
    const kjente = (obj.omfatter || []).filter((x) => kjenteLaasSett.has(x));
    const nye: string[] = [];
    for (const del of tekst.split(/[,\s]+/)) {
      const v = del.trim();
      if (v && !kjente.includes(v) && !nye.includes(v)) nye.push(v);
    }
    oppdater({ omfatter: [...kjente, ...nye] });
  }

  function ekstraSporfeltIndekser(): number[] {
    if (obj.type !== "sporfelt" || obj.rolle === "varselfelt") return [];
    const total = (obj.bindinger || []).filter((b) => b.sted === "sensor").length;
    const out: number[] = [];
    for (let i = 1; i < total; i++) out.push(i);
    return out;
  }

  function leggTilEkstraSporfelt() {
    const binds = [...(obj.bindinger || [])];
    // Sørg for at plass 0 har minst en tom plassholder hvis første sensor ikke er bundet ennå
    const første = binds.find((b) => b.sted === "sensor");
    const defaultNode = nodeValg[0]?.val || "";
    if (!første && !defaultNode) return;
    binds.push({
      sted: "sensor",
      node: defaultNode,
      i2c: "0x20",
      port: 0,
    });
    oppdater({ bindinger: binds });
  }

  let rader = $derived(bindingsrader(obj.type, obj.rolle || "", draft.signaltyper));
  let sporfeltRolleValg = $derived(
    obj.rolle === "linjefelt"
      ? obj.linjeblokk === false
        ? "linjefelt"
        : "blokksporfelt"
      : obj.rolle || ""
  );
  let utlEnde = $derived(
    isVeksel(obj.type)
      ? utledetEnde(obj.id.trim(), draft.functions, draft.togveier)
      : ""
  );
  let manglerRolle = $derived(hovedsignalManglerRolle(obj, draft.signaltyper));

  // Hjelpetekster hentet fra den tidligere flaten (87ddb69)
  const HJELP = {
    litra:
      "Litra — maks 6 tegn. Kort litra er forbildets egen skrivemåte (A, 01, ZM, SpIII), og det er det som får plass i portrutenettet og på panelet.",
    sporfeltRolle:
      "Hva sporavsnittet ER, og dermed hva forriglingen gjør med det. vekselfelt: de interne avsnittene i halsen, mellom vekslene — de har ingen togvei som ender i dem, men vernes mot omlegging under tog. togspor: stasjonsspor der tog står, med togveistiller. blokksporfelt: avsnittet mot nabolinjen når strekningen har LINJEBLOKK — blokka gir automatisk kontroll av at hele toget er kommet inn. linjefelt: samme avsnitt der strekningen kjøres på TOGMELDING — da blir innkjørtogveien stående låst til txp har gjort sistevognskontroll og kvittert på den sorte knappen. varselfelt: kort avsnitt ute på linjen utenfor forsignalet — varselklokken ringer for tog i anmarsj. spor: utenfor anlegget, tegnes på sporplanen men har ingen lampe og ingen forrigling.",
    sentralstilt:
      "Sentralstilt veksel: legges om fra stillerapparatet og inngår i forriglingen. Skrudd av er den håndstilt — den står utenfor togveiene og sikres med samlelås eller rigel.",
    hs3Rolle:
      "Innkjør viser 20A (blink) i stopp, utkjør viser 20B (fast). Indre hovedsignal brukes for togveier fra togspor til togspor.",
    hs3Linjefelt:
      "Linjefeltet signalet står FORAN (i signalets kjøreretning): innkjør foran linjefeltet det står ved på vei inn, utkjør foran linjefeltet toget kjører ut på. Brukes til å avlede signalet når togveier lages fra→til.",
    hs2Rolle:
      "Tolys utkjørsignal: viser bare 20B (stopp) og 21 (kjør redusert) — for spor der utkjøring alltid går over veksel i avvik. Alltid rolle utkjør.",
    hs2Linjefelt:
      "Linjefeltet signalet står foran (linjefeltet toget kjører ut på).",
    fsMontert:
      "Hovedsignal på samme mast — forsignalet slukkes når det viser stopp.",
    fsVarsler:
      "Hovedsignalet forsignalet varsler om — bildet følger det automatisk. «auto»: forriglingen avleder utkjørsignalet fra den aktive togveiens spor (krever utkjørtogveier med spor satt i tabellen). Et valgt signal brukes som reserve når avledningen ikke finner noe.",
    skiftMontert:
      "Hovedsignalet skiftesignalet er montert med (Sokna: ZL på utkjør L, ZM på utkjør M) — brukes av panelets sporplan til plasseringen. Tom = egen mast.",
    skiftVeksler:
      "Vekslene det høye skiftesignalet gjelder for — «ZM gjelder for skifting over veksel 1 forbi utkjørhovedsignalene M og O». Området er vekselen, ikke linjen: én stasjonshals kan betjene flere linjefelt. Stasjonsenden utledes av vekslene, så signalet trenger ingen egen venstre/høyre.",
    dvergMontert:
      "Utkjørhovedsignalet dvergsignalet står på eller ved. Bildet avledes: signal 45 når utkjørtogvei fra dette signalet er sikret, signal 46 når halsen er frigitt for lokal omlegging eller det høye skiftesignalet viser 42, ellers signal 43. Stasjonsenden arves fra hovedsignalets «foran»-linjefelt.",
    vekselSide:
      "Stasjonsenden utledes av forriglingstabellen: vekselen hører til den enden hvis linjefelt togveiene over den når. Sett verdi her BARE for veksler ingen togvei berører (rene skifteveksler) eller som nås fra begge sider.",
    manuellveksel:
      "Manuellvekselen står utenfor forriglingen: ingen ende, ingen togvei, ingen Lok-frigivning. Den er med for å tegne sporplanen, og kan betjenes med knapp eller bryter over nodens porter. Sikres i en togvei med samlelås eller rigel.",
    sporsperre:
      "Sporsperre: normalstillingen er PÅLAGT — det er dekningen togveiene krever. Deler vekselmaskineriet: valgfrie drivutganger for motordrevet modellsperre, valgfrie sensorer (pålagt-kontroll — uten dem antas stillingen), lokal stiller. Omlegging gates av samlelås/rigel som eier sperren. Symbol på planen: skråstrek over sporet.",
    laasOmfatterSamle:
      "Objektene nøkkelen låser (kontrollås/samlelås): så lenge låsen er SPERRET (nøkkelen står i kontroll) avvises all omlegging av disse — stiller, trykknapp og MQTT. Frigitt lås eller nøkkel ute sperrer til gjengjeld togveiene i virkeområdet (tosidig forrigling).",
    laasOmfatterRigel:
      "Objektene rigelen låser direkte (veksler og sporsperrer): sperret rigel avviser all omlegging, og togveiene i virkeområdet krever rigelen sperret. Tilbaketaking gir 10 s etterløp og fullføres først når alle objektene ligger i normal igjen (motordrevne modellobjekter rekker tilbake). Som i forbildet forholder anlegget seg bare til NØKLENES/rigelens status — stillingssensorer på låste objekter trengs ikke.",
    laasUtenfor:
      "Objekter låsen omfatter som IKKE er definert i anlegget: helt manuelle veksler/sperrer, eller slike som drives elektrisk av eget utstyr utenfor systemet. Anlegget ser da bare låsen — at objektene ligger riktig før sperring er operatørens ansvar, som med kontrollåsnøklene i forbildet. Kommaseparert liste; vises i panelet.",
    laasTogveiKrav:
      "Hvilke togveier låsen sperrer står i TOGVEITABELLEN: hver togvei lister låsegruppene den krever sperret. Én kilde — låsen sier hva den holder, togveien sier hva den trenger.",
    linjefeltSide:
      "Hvilken stasjonsende linjefeltet ligger i — togveistillerne bruker dette til å skille innkjør (dytt inn mot stasjonen) fra utkjør (dytt ut mot linjen).",
    varselfeltLinje:
      "Linjefeltet varselfeltet er koblet til — varslet gjelder den siden (siden arves fra linjefeltet).",
    trykknappRolle:
      "jord: oppstartsritual — etter master-boot er alle signaler sperret til denne knappen trykkes (som forbildets strømstans-prosedyre). Panel-bindingen er den røde kontrollampen, tent mens anlegget er sperret.",
    bryterRolle:
      "signalstopp: alle signaler i stopp og sperret mens bryteren står på. Frigivning: frigir sentralstilte veksler i enden for lokal omlegging (togveier over dem avvises, vekselfelt-vernet er ute av funksjon). Gjennomgangsdrift: låser stasjonen i normal for en ubetjent mellomstasjon; tog som melder seg på varselfeltet får signal gjennom hovedsporet (hvit stiller på /panel). Panel-bindingen er kontrollampen — tent når funksjonen er aktiv (gjennomgang: blink mens den venter på vilkårene).",
    klokkeGenerelt:
      "Én klokke gjør alle jobbene, som i forbildet: varselklokke (tog i anmarsj), vekselklokke (omlegging/ute av kontroll), togveiklokke (togveistiller holdes utslått) og signalstoppklokke — alle med 30 s spolevern per hendelse.",
    klokkeHakk:
      "Hakkfrekvensen for klokkens solenoid i Hz (standard 50). Gjelder GPIO-bindinger — solenoiden og klangbunnen har en mekanisk resonans, så prøv deg frem (f.eks. 30/40/50) til lyden bærer best. Trer i kraft ved lagring, uten ny firmware.",
    klokkeDuty:
      "Hvor stor del av hver hakkperiode spolen får strøm, i % (standard 50). Lavere = kaldere spole og lettere anslag, høyere = hardere anslag men mer varme — spolens snittvarme er direkte proporsjonal med duty. Kvantiseres til nærmeste 1/16. Trer i kraft ved lagring. Ringingen kappes uansett av masteren etter 30 s (spolevern); meldingslampen blinker videre til kvittering.",
    amperemeterUtslag:
      "Viserutslag i % av fullt PWM-pådrag mens en veksel legger om. Instrumentet (dreiespole) kobles til PCA-kanalen i anleggsbindingen.",
    tegningSeksjon:
      "Felter som KUN styrer tegningen av sporplanen — masteren leser dem ikke. Trengs ikke uten digitalt panel.",
    tegningPortmodell:
      "Sporplanens portmodell — bare for tegningen, masteren leser det ikke. Spiss: enden tungespissen peker mot. +→/−→: sporet eller vekselen pluss-/minusgreina fører til (velg «veksel 5» når den går rett i en annen veksel). st→: der stammen går videre i en kjede. Tomt = utledes av togveitabellen der det går.",
    tegningKrumt:
      "Hvilket ben som er det FYSISK krumme (tegningen kan ikke utlede det): standard er at minusgreina bøyer av og fortsetter utover; «stammen» betyr at pluss- og minusgreina ligger i linje og stammen bøyer av — som veksel 11, der 6 og 3 ligger rett gjennom og det krumme benet går ned mot veksel 4.",
    tegningLiggerI:
      "Sporplanen: sporet eller forbindelsen skråstreken tegnes på — et sporfelt-litra, eller «veksel N» når sperren ligger på forbindelsen fra den vekselens stamme. Kun tegning; masteren leser det ikke.",
  } as const;
</script>

{#key obj._rid}
<div class="space-y-4 text-xs">
  <!-- Identitet -->
  <div class="grid grid-cols-2 gap-2.5 items-start">
    <div class="space-y-1">
      <FeltEtikett label="Litra" forId="insp-litra" hjelp={HJELP.litra} />
      <input
        id="insp-litra"
        class="w-full rounded-md border bg-background px-2.5 py-1.5 font-mono text-xs text-foreground focus:outline-none focus:border-primary {litraFeil ? 'border-warn' : 'border-border'}"
        maxlength={obj._orgId ? 23 : MAX_LITRA_UI}
        value={obj.id}
        placeholder="A"
        oninput={(e) => oppdater({ id: e.currentTarget.value })}
      />
      {#if litraFeil}
        <span class="block text-[10.5px] text-warn">Tegn «{litraFeil}» er ulovlig i MQTT</span>
      {/if}
    </div>

    {#if obj.type === "sporfelt"}
      <div class="space-y-1">
        <FeltEtikett label="Rolle" forId="insp-sf-rolle" hjelp={HJELP.sporfeltRolle} />
        <select
          id="insp-sf-rolle"
          class="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground focus:outline-none focus:border-primary"
          value={sporfeltRolleValg}
          onchange={(e) => byttSporfeltRolle(e.currentTarget.value)}
        >
          <option value="">vekselfelt</option>
          <option value="togspor">togspor</option>
          <option value="blokksporfelt">blokksporfelt (linjeblokk)</option>
          <option value="linjefelt">linjefelt (togmelding)</option>
          <option value="varselfelt">varselfelt</option>
          <option value="spor">spor (kun tegning)</option>
        </select>
      </div>
    {:else if erVekselGrp}
      <div class="space-y-1">
        <FeltEtikett label="Sentralstilt" hjelp={HJELP.sentralstilt} />
        <div class="flex items-center justify-between gap-2 rounded-md border border-border bg-background px-2.5 py-1.5">
          <span class="text-xs font-medium">{isVeksel(obj.type) ? "Ja (sentralstilt)" : "Nei (håndstilt)"}</span>
          <Switch
            checked={isVeksel(obj.type)}
            onchange={(v) => byttType(v ? "sporveksel" : "manuellveksel")}
          />
        </div>
      </div>
    {:else if gruppe.typer.length > 1}
      <label class="block space-y-1">
        <span class="text-[11px] text-muted-foreground font-medium">Type</span>
        <select
          class="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground focus:outline-none focus:border-primary"
          value={obj.type}
          onchange={(e) => byttType(e.currentTarget.value)}
        >
          {#each gruppe.typer as tp}
            <option value={tp}>{tp}</option>
          {/each}
        </select>
      </label>
    {:else}
      <div class="space-y-1">
        <span class="text-[11px] text-muted-foreground font-medium">Type</span>
        <div class="rounded-md border border-border bg-muted/40 px-2.5 py-1.5 font-mono text-muted-foreground">
          {obj.type}
        </div>
      </div>
    {/if}
  </div>

  <!-- Typespesifikke egenskaper -->
  <div class="space-y-2.5 rounded-md border border-border bg-background/50 p-3">
    <div class="text-[10.5px] font-semibold uppercase tracking-wider text-muted-foreground">
      Egenskaper
    </div>

    {#if obj.type === "hovedsignal3"}
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
        <div class="space-y-1">
          <FeltEtikett label="Rolle" forId="insp-hs3-rolle" hjelp={HJELP.hs3Rolle} />
          <select
            id="insp-hs3-rolle"
            class="w-full rounded-md border bg-background px-2 py-1.5 text-xs {manglerRolle ? 'border-warn text-warn' : 'border-border'}"
            value={obj.rolle || ""}
            onchange={(e) => oppdater({ rolle: e.currentTarget.value || undefined })}
          >
            <option value="">— rolle mangler —</option>
            <option value="innkjor">innkjør (20A blink)</option>
            <option value="utkjor">utkjør (20B fast)</option>
            <option value="indre">indre</option>
          </select>
          {#if manglerRolle}
            <span class="block text-[10.5px] text-warn font-medium">
              ⚠ Rolle mangler — signalet er ikke startsignalkandidat før rolle velges.
            </span>
          {/if}
        </div>
        <div class="space-y-1">
          <FeltEtikett label="Foran linjefelt" forId="insp-hs3-linje" hjelp={HJELP.hs3Linjefelt} />
          <select
            id="insp-hs3-linje"
            class="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs font-mono"
            value={obj.linjefelt || ""}
            onchange={(e) => oppdater({ linjefelt: e.currentTarget.value || undefined })}
          >
            <option value="">—</option>
            {#each linjefelter as lf}
              <option value={lf}>{lf}</option>
            {/each}
            {#if obj.linjefelt && !linjefelter.includes(obj.linjefelt)}
              <option value={obj.linjefelt}>{obj.linjefelt} (ukjent)</option>
            {/if}
          </select>
        </div>
      </div>
    {:else if obj.type === "hovedsignal2"}
      <div class="space-y-2.5">
        <div class="space-y-1">
          <FeltEtikett label="Rolle (tolys utkjør)" hjelp={HJELP.hs2Rolle} />
          {#if manglerRolle}
            <div class="flex flex-wrap items-center justify-between gap-2 rounded-md border border-warn/60 bg-warn/10 px-2.5 py-2 text-[11px] text-warn">
              <span>⚠ Rolle mangler — signalet er ikke startsignalkandidat før rollen settes.</span>
              <Button size="xs" variant="outline" onclick={() => oppdater({ rolle: "utkjor" })}>
                Sett utkjør
              </Button>
            </div>
          {:else}
            <div class="rounded-md border border-border bg-muted/40 px-2.5 py-1.5 text-xs text-muted-foreground">
              utkjør (tolys)
            </div>
          {/if}
        </div>
        <div class="space-y-1">
          <FeltEtikett label="Foran linjefelt" forId="insp-hs2-linje" hjelp={HJELP.hs2Linjefelt} />
          <select
            id="insp-hs2-linje"
            class="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs font-mono"
            value={obj.linjefelt || ""}
            onchange={(e) => oppdater({ linjefelt: e.currentTarget.value || undefined })}
          >
            <option value="">—</option>
            {#each linjefelter as lf}
              <option value={lf}>{lf}</option>
            {/each}
            {#if obj.linjefelt && !linjefelter.includes(obj.linjefelt)}
              <option value={obj.linjefelt}>{obj.linjefelt} (ukjent)</option>
            {/if}
          </select>
        </div>
      </div>
    {:else if obj.type === "forsignal2"}
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
        <div class="space-y-1">
          <FeltEtikett label="Montert med" forId="insp-fs-montert" hjelp={HJELP.fsMontert} />
          <select
            id="insp-fs-montert"
            class="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs font-mono"
            value={obj.montert_med || ""}
            onchange={(e) => oppdater({ montert_med: e.currentTarget.value || undefined })}
          >
            <option value="">— (frittstående)</option>
            {#each hovedsignaler as hs}
              <option value={hs}>{hs}</option>
            {/each}
          </select>
        </div>
        <div class="space-y-1">
          <FeltEtikett label="Varsler om" forId="insp-fs-varsler" hjelp={HJELP.fsVarsler} />
          <select
            id="insp-fs-varsler"
            class="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs font-mono"
            value={obj.varsler_om || ""}
            onchange={(e) => oppdater({ varsler_om: e.currentTarget.value || undefined })}
          >
            <option value="">auto (fra togvei)</option>
            {#each hovedsignaler as hs}
              <option value={hs}>{hs}</option>
            {/each}
          </select>
        </div>
      </div>
    {:else if isSkift(obj.type, draft.signaltyper)}
      <div class="space-y-1">
        <FeltEtikett label="På mast med hovedsignal" forId="insp-skift-montert" hjelp={HJELP.skiftMontert} />
        <select
          id="insp-skift-montert"
          class="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs font-mono"
          value={obj.montert_med || ""}
          onchange={(e) => oppdater({ montert_med: e.currentTarget.value || undefined })}
        >
          <option value="">— (egen mast)</option>
          {#each hovedsignaler as hs}
            <option value={hs}>{hs}</option>
          {/each}
        </select>
      </div>
      <div class="space-y-1.5">
        <FeltEtikett label="Gjelder sentralstilte veksler (maks 4)" hjelp={HJELP.skiftVeksler} />
        <div class="flex flex-wrap gap-2">
          {#each kjenteVekslerForSkift as vid}
            <label class="inline-flex items-center gap-1.5 rounded border border-border bg-background px-2 py-1 cursor-pointer font-mono">
              <input
                type="checkbox"
                checked={(obj.skift_sporveksler || []).includes(vid)}
                onchange={(e) => toggleSkiftVeksel(vid, e.currentTarget.checked)}
              />
              {vid}
            </label>
          {/each}
          {#each ugyldigeSkiftVeksler as uid}
            <label
              class="inline-flex items-center gap-1.5 rounded border border-warn/60 bg-warn/10 px-2 py-1 cursor-pointer font-mono text-warn"
              title="Ugyldig (slettet eller manuellveksel) — fjern avkryssingen"
            >
              <input
                type="checkbox"
                checked={true}
                onchange={() => toggleSkiftVeksel(uid, false)}
              />
              {uid} ⚠
            </label>
          {/each}
          {#if !kjenteVekslerForSkift.length && !ugyldigeSkiftVeksler.length}
            <span class="text-muted-foreground">Ingen sentralstilte veksler definert</span>
          {/if}
        </div>
      </div>
    {:else if isDverg(obj.type, draft.signaltyper)}
      <div class="space-y-1">
        <FeltEtikett label="På utkjørsignal" forId="insp-dverg-montert" hjelp={HJELP.dvergMontert} />
        <select
          id="insp-dverg-montert"
          class="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs font-mono"
          value={obj.montert_med || ""}
          onchange={(e) => oppdater({ montert_med: e.currentTarget.value || undefined })}
        >
          <option value="">—</option>
          {#each hovedsignaler as hs}
            <option value={hs}>{hs}</option>
          {/each}
        </select>
      </div>
    {:else if isVeksel(obj.type)}
      <div class="space-y-1">
        <FeltEtikett label="Stasjonsende" forId="insp-vx-side" hjelp={HJELP.vekselSide} />
        <select
          id="insp-vx-side"
          class="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs"
          value={obj.side || ""}
          onchange={(e) => oppdater({ side: (e.currentTarget.value as "" | "v" | "h") || undefined })}
        >
          <option value="">
            auto ({utlEnde === "v" ? "venstre" : utlEnde === "h" ? "høyre" : "ukjent"})
          </option>
          <option value="v">venstre (overstyrt)</option>
          <option value="h">høyre (overstyrt)</option>
        </select>
      </div>
    {:else if isManuell(obj.type)}
      <FeltEtikett label="Håndstilt — utenfor forriglingen" hjelp={HJELP.manuellveksel} />
    {:else if isSperre(obj.type)}
      <FeltEtikett label="Normalstilling pålagt (dekning)" hjelp={HJELP.sporsperre} />
    {:else if isLaas(obj.type)}
      <div class="space-y-1">
        <FeltEtikett
          label="Visningsnavn (/panel)"
          forId="insp-laas-navn"
          hjelp={`Visningsnavn med forbildets skrivemåte — vises i panelet og UI-et. Selve litraen (${obj.type === "samlelaas" ? "S1" : "RI1"}) brukes i MQTT-temaene.`}
        />
        <input
          id="insp-laas-navn"
          class="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-xs"
          value={obj.navn || ""}
          placeholder={obj.type === "samlelaas" ? "S.LÅS I" : "Ri. Sp.II/3"}
          oninput={(e) => oppdater({ navn: e.currentTarget.value || undefined })}
        />
      </div>
      <div class="space-y-1.5">
        <FeltEtikett
          label="Omfatter objekter i anlegget"
          hjelp={obj.type === "samlelaas" ? HJELP.laasOmfatterSamle : HJELP.laasOmfatterRigel}
        />
        <div class="flex flex-wrap gap-2">
          {#each kjenteObjForLaas as oid}
            <label class="inline-flex items-center gap-1.5 rounded border border-border bg-background px-2 py-1 cursor-pointer font-mono">
              <input
                type="checkbox"
                checked={(obj.omfatter || []).includes(oid)}
                onchange={(e) => toggleLaasObj(oid, e.currentTarget.checked)}
              />
              {oid}
            </label>
          {/each}
          {#if !kjenteObjForLaas.length}
            <span class="text-muted-foreground">Ingen veksler eller sporsperrer definert</span>
          {/if}
        </div>
      </div>
      <div class="space-y-1">
        <FeltEtikett
          label="+ utenfor anlegget (kommaseparert)"
          forId="insp-laas-utenfor"
          hjelp={HJELP.laasUtenfor}
        />
        <input
          id="insp-laas-utenfor"
          class="w-full rounded-md border border-border bg-background px-2.5 py-1.5 font-mono text-xs"
          value={laasUtenforTekst}
          placeholder="f.eks. V12"
          onchange={(e) => settLaasUtenfor(e.currentTarget.value)}
        />
      </div>
      <FeltEtikett label="Togvei-kravet settes i forriglingstabellen" hjelp={HJELP.laasTogveiKrav} />
    {:else if obj.type === "sporfelt"}
      {#if obj.rolle === "linjefelt"}
        <div class="space-y-1">
          <FeltEtikett
            label="Stasjonsende (påkrevd for linjefelt)"
            forId="insp-sf-side"
            hjelp={HJELP.linjefeltSide}
          />
          <select
            id="insp-sf-side"
            class="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs"
            value={obj.side || ""}
            onchange={(e) => oppdater({ side: (e.currentTarget.value as "" | "v" | "h") || undefined })}
          >
            <option value="">— velg ende —</option>
            <option value="v">venstre</option>
            <option value="h">høyre</option>
          </select>
        </div>
      {:else if obj.rolle === "varselfelt"}
        <div class="space-y-1">
          <FeltEtikett
            label="Koblet til linjefelt"
            forId="insp-vf-linje"
            hjelp={HJELP.varselfeltLinje}
          />
          <select
            id="insp-vf-linje"
            class="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs font-mono"
            value={obj.linjefelt || ""}
            onchange={(e) => oppdater({ linjefelt: e.currentTarget.value || undefined })}
          >
            <option value="">—</option>
            {#each linjefelter as lf}
              <option value={lf}>{lf}</option>
            {/each}
          </select>
        </div>
      {:else}
        <p class="text-[11.5px] text-muted-foreground">
          {obj.rolle === "togspor"
            ? "Stasjonsspor med togveistiller."
            : obj.rolle === "spor"
              ? "Tegnes kun på /panel (ingen forrigling)."
              : "Internt vekselfelt i stasjonshalsen."}
        </p>
      {/if}
    {:else if obj.type === "trykknapp"}
      <div class="space-y-1">
        <FeltEtikett label="Rolle" forId="insp-tk-rolle" hjelp={HJELP.trykknappRolle} />
        <select
          id="insp-tk-rolle"
          class="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs"
          value={obj.rolle || ""}
          onchange={(e) => oppdater({ rolle: e.currentTarget.value || undefined })}
        >
          <option value="">—</option>
          <option value="jord">jord (oppstartskvittering)</option>
        </select>
      </div>
    {:else if obj.type === "bryter"}
      <div class="space-y-1">
        <FeltEtikett label="Rolle" forId="insp-br-rolle" hjelp={HJELP.bryterRolle} />
        <select
          id="insp-br-rolle"
          class="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs"
          value={obj.rolle || ""}
          onchange={(e) => oppdater({ rolle: e.currentTarget.value || undefined })}
        >
          <option value="">—</option>
          <option value="signalstopp">signalstopp</option>
          <option value="lok-v">frigivning venstre ende</option>
          <option value="lok-h">frigivning høyre ende</option>
          <option value="gjennomgang">gjennomgangsdrift</option>
        </select>
      </div>
    {:else if obj.type === "klokke"}
      <FeltEtikett label="Alle klokkefunksjonene" hjelp={HJELP.klokkeGenerelt} />
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
        <div class="space-y-1">
          <FeltEtikett
            label="Hakkfrekvens (Hz, 10–250)"
            forId="insp-kl-hakk"
            hjelp={HJELP.klokkeHakk}
          />
          <input
            id="insp-kl-hakk"
            type="number"
            min="10"
            max="250"
            class="w-full rounded-md border border-border bg-background px-2.5 py-1.5 font-mono text-xs"
            value={obj.hakk_hz ?? 50}
            onchange={(e) =>
              oppdater({
                hakk_hz: Math.max(10, Math.min(250, parseInt(e.currentTarget.value, 10) || 50)),
              })}
          />
        </div>
        <div class="space-y-1">
          <FeltEtikett
            label="Duty (%, 10–90)"
            forId="insp-kl-duty"
            hjelp={HJELP.klokkeDuty}
          />
          <input
            id="insp-kl-duty"
            type="number"
            min="10"
            max="90"
            class="w-full rounded-md border border-border bg-background px-2.5 py-1.5 font-mono text-xs"
            value={obj.hakk_duty ?? 50}
            onchange={(e) =>
              oppdater({
                hakk_duty: Math.max(10, Math.min(90, parseInt(e.currentTarget.value, 10) || 50)),
              })}
          />
        </div>
      </div>
    {:else if obj.type === "amperemeter"}
      <div class="space-y-1">
        <FeltEtikett
          label="Viserutslag (%, 0–100)"
          forId="insp-amp-utslag"
          hjelp={HJELP.amperemeterUtslag}
        />
        <input
          id="insp-amp-utslag"
          type="number"
          min="0"
          max="100"
          class="w-28 rounded-md border border-border bg-background px-2.5 py-1.5 font-mono text-xs"
          value={obj.utslag ?? 100}
          onchange={(e) =>
            oppdater({
              utslag: Math.max(0, Math.min(100, parseInt(e.currentTarget.value, 10) || 0)),
            })}
        />
      </div>
    {:else}
      <p class="text-[11.5px] text-muted-foreground">Ingen ekstra egenskaper.</p>
    {/if}
  </div>

  <!-- Porter & Bindinger -->
  <div class="space-y-2">
    <div class="flex items-center justify-between">
      <span class="text-[10.5px] font-semibold uppercase tracking-wider text-muted-foreground">
        Porter &amp; Bindinger
      </span>
      {#if obj.type === "sporfelt" && obj.rolle !== "varselfelt"}
        <Button size="xs" variant="ghost" onclick={leggTilEkstraSporfelt}>
          <Plus class="w-3 h-3" /> Ekstra sporfelt
        </Button>
      {/if}
    </div>

    {#each rader as rad}
      {#each ([rad.a, rad.b].filter(Boolean) as string[]) as sted, sIdx}
        {@const b = finnBinding(sted, 0)}
        {@const inn = bindErInngang(obj.type, sted)}
        {@const konflikt = slotHarKonflikt(b)}
        {@const curI2c = b ? i2cNorm(b.i2c) : defaultI2c(obj.type, sted)}
        {@const kap = brikkeKapasitet(curI2c) ?? 16}
        {@const parDel = rad.par ? rad.par.split("·")[sIdx]?.trim() : ""}
        <div
          class="rounded-md border bg-background p-2.5 space-y-2 border-l-3 {inn ? 'border-l-inn' : 'border-l-ut'} {konflikt ? 'border-warn' : 'border-border'}"
        >
          <div class="flex items-center justify-between gap-2">
            <span class="font-medium flex items-center gap-1.5">
              <span class="font-mono {inn ? 'text-inn' : 'text-ut'}">{portSymbol(sted, obj.type)}</span>
              <span>{rad.navn}</span>
              {#if parDel}
                <span class="text-muted-foreground font-normal">· {parDel}</span>
              {/if}
            </span>
            <Badge variant={konflikt ? "warn" : inn ? "inn" : "ut"}>
              {konflikt ? "Konflikt" : inn ? "← inn" : "ut →"}
            </Badge>
          </div>
          <div class="grid grid-cols-[1.25fr_1fr_0.75fr] gap-1.5">
            <select
              class="rounded border border-border bg-card px-1.5 py-1 text-[11.5px] font-mono"
              value={b?.node || ""}
              onchange={(e) => oppdaterSlot(sted, 0, "node", e.currentTarget.value)}
            >
              <option value="">—</option>
              {#each nodeValg as nv}
                <option value={nv.val}>{nv.lbl}</option>
              {/each}
              {#if b?.node && !nodeValg.some((x) => x.val === b.node)}
                <option value={b.node}>{b.node} ?</option>
              {/if}
            </select>
            <select
              class="rounded border bg-card px-1.5 py-1 text-[11.5px] font-mono {inn ? 'border-inn/50' : 'border-ut/50'}"
              value={curI2c}
              disabled={!b?.node}
              onchange={(e) => oppdaterSlot(sted, 0, "i2c", e.currentTarget.value)}
            >
              {#each i2cValgFor(b?.node || "", curI2c) as a}
                <option value={a}>{i2cLabel(a)}</option>
              {/each}
            </select>
            <select
              class="rounded border border-border bg-card px-1.5 py-1 text-[11.5px] font-mono tabular"
              value={String(b?.port ?? 0)}
              disabled={!b?.node}
              onchange={(e) => oppdaterSlot(sted, 0, "port", e.currentTarget.value)}
            >
              {#each Array.from({ length: kap }, (_, p) => p) as p}
                <option value={String(p)}>
                  {curI2c === "gpio" ? `${p} (${GPIO_PINNER[p]})` : p}
                </option>
              {/each}
            </select>
          </div>
        </div>
      {/each}
    {/each}

    <!-- Ekstra sporfelt-sensorer (logisk OR) -->
    {#each ekstraSporfeltIndekser() as exIdx}
      {@const b = finnBinding("sensor", exIdx)}
      {@const curI2c = b ? i2cNorm(b.i2c) : "0x20"}
      {@const kap = brikkeKapasitet(curI2c) ?? 8}
      <div class="rounded-md border border-border border-l-3 border-l-inn bg-background p-2.5 space-y-2">
        <div class="flex items-center justify-between">
          <span class="font-medium flex items-center gap-1.5">
            <span class="font-mono text-inn">◎</span> ekstra sporfelt #{exIdx + 1}
          </span>
          <Button
            size="xs"
            variant="ghost"
            onclick={() => draft.settBinding(obj._rid, "sensor", null, exIdx)}
          >
            Fjern
          </Button>
        </div>
        <div class="grid grid-cols-[1.25fr_1fr_0.75fr] gap-1.5">
          <select
            class="rounded border border-border bg-card px-1.5 py-1 text-[11.5px] font-mono"
            value={b?.node || ""}
            onchange={(e) => oppdaterSlot("sensor", exIdx, "node", e.currentTarget.value)}
          >
            <option value="">—</option>
            {#each nodeValg as nv}
              <option value={nv.val}>{nv.lbl}</option>
            {/each}
          </select>
          <select
            class="rounded border border-inn/50 bg-card px-1.5 py-1 text-[11.5px] font-mono"
            value={curI2c}
            disabled={!b?.node}
            onchange={(e) => oppdaterSlot("sensor", exIdx, "i2c", e.currentTarget.value)}
          >
            {#each i2cValgFor(b?.node || "", curI2c) as a}
              <option value={a}>{i2cLabel(a)}</option>
            {/each}
          </select>
          <select
            class="rounded border border-border bg-card px-1.5 py-1 text-[11.5px] font-mono"
            value={String(b?.port ?? 0)}
            disabled={!b?.node}
            onchange={(e) => oppdaterSlot("sensor", exIdx, "port", e.currentTarget.value)}
          >
            {#each Array.from({ length: kap }, (_, p) => p) as p}
              <option value={String(p)}>
                {curI2c === "gpio" ? `${p} (${GPIO_PINNER[p]})` : p}
              </option>
            {/each}
          </select>
        </div>
      </div>
    {/each}
  </div>

  <!-- Sporplan-tegning (kun for veksler og sporsperrer) -->
  {#if erVekselGrp || isSperre(obj.type)}
    <div class="rounded-md border border-border bg-background/40">
      <button
        type="button"
        title={HJELP.tegningSeksjon}
        class="w-full flex items-center justify-between px-3 py-2 text-xs text-muted-foreground hover:text-foreground cursor-pointer"
        onclick={() => (visTegning = !visTegning)}
      >
        <span class="flex items-center gap-1.5 font-medium">
          {#if visTegning}<ChevronDown class="w-3.5 h-3.5" />{:else}<ChevronRight class="w-3.5 h-3.5" />{/if}
          Sporplan-tegning (kun /panel)
        </span>
        <span class="text-[10.5px]">ignoreres av master</span>
      </button>
      {#if visTegning}
        <div class="px-3 pb-3 pt-1 border-t border-border space-y-2.5">
          <p class="text-[11px] text-muted-foreground">{HJELP.tegningSeksjon}</p>
          {#if erVekselGrp}
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <div class="space-y-1">
                <FeltEtikett
                  label="Spiss peker mot"
                  forId="insp-tg-spiss"
                  hjelp={HJELP.tegningPortmodell}
                />
                <select
                  id="insp-tg-spiss"
                  class="w-full rounded border border-border bg-background px-2 py-1 text-xs"
                  value={obj.spiss || ""}
                  onchange={(e) => oppdater({ spiss: (e.currentTarget.value as "" | "v" | "h") || undefined })}
                >
                  <option value="">—</option>
                  <option value="v">venstre</option>
                  <option value="h">høyre</option>
                </select>
              </div>
              <div class="space-y-1">
                <FeltEtikett
                  label="Krumt ben"
                  forId="insp-tg-krumt"
                  hjelp={HJELP.tegningKrumt}
                />
                <select
                  id="insp-tg-krumt"
                  class="w-full rounded border border-border bg-background px-2 py-1 text-xs"
                  value={obj.avvik_ben || ""}
                  onchange={(e) => oppdater({ avvik_ben: (e.currentTarget.value as "" | "spiss" | "pluss") || undefined })}
                >
                  <option value="">minus (std)</option>
                  <option value="spiss">stammen</option>
                  <option value="pluss">pluss</option>
                </select>
              </div>
            </div>
            <div class="grid grid-cols-3 gap-2">
              {#each [
                ["+→ pluss", "pluss_til"],
                ["−→ minus", "minus_til"],
                ["st→ stamme", "spiss_til"],
              ] as [lbl, key]}
                {@const cur = (obj as any)[key] || ""}
                <label class="block space-y-1" title={HJELP.tegningPortmodell}>
                  <span class="text-[10.5px] text-muted-foreground">{lbl}</span>
                  <select
                    class="w-full rounded border border-border bg-background px-1.5 py-1 text-[11px] font-mono"
                    value={cur}
                    onchange={(e) => oppdater({ [key]: e.currentTarget.value || undefined })}
                  >
                    <option value="">—</option>
                    {#each topoValg as tv}
                      <option value={tv}>{tv}</option>
                    {/each}
                    {#if cur && !topoValg.includes(cur)}
                      <option value={cur}>{cur} (?)</option>
                    {/if}
                  </select>
                </label>
              {/each}
            </div>
          {:else if isSperre(obj.type)}
            <div class="space-y-1">
              <FeltEtikett
                label="Ligger i spor / veksel"
                forId="insp-tg-ligger"
                hjelp={HJELP.tegningLiggerI}
              />
              <select
                id="insp-tg-ligger"
                class="w-full rounded border border-border bg-background px-2 py-1 text-xs font-mono"
                value={obj.ligger_i || ""}
                onchange={(e) => oppdater({ ligger_i: e.currentTarget.value || undefined })}
              >
                <option value="">—</option>
                {#each topoValg as tv}
                  <option value={tv}>{tv}</option>
                {/each}
              </select>
            </div>
          {/if}
        </div>
      {/if}
    </div>
  {/if}

  <!-- Slett -->
  <div class="pt-2 border-t border-border flex justify-end">
    <Button variant="destructive" size="sm" onclick={() => (bekreftSlett = true)}>
      <Trash2 class="w-3.5 h-3.5" />
      Slett objekt
    </Button>
  </div>
</div>
{/key}

<ConfirmDialog
  bind:open={bekreftSlett}
  destructive
  title={`Slette ${obj.id || "(uten litra)"}?`}
  description="Objektet og alle dets bindinger fjernes fra utkastet. Endringen blir permanent først ved «Lagre og publiser»."
  confirmLabel="Slett"
  onconfirm={() => {
    draft.slettObjekt(obj._rid);
    ondeleted?.();
  }}
/>
