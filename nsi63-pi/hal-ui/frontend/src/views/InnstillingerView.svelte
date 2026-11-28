<script lang="ts">
  import { onMount } from "svelte";
  import {
    AlertTriangle,
    Clock,
    Download,
    HardDrive,
    RotateCcw,
    Save,
    Settings,
    Upload,
  } from "@lucide/svelte";
  import { toast } from "svelte-sonner";
  import Badge from "$components/ui/Badge.svelte";
  import Button from "$components/ui/Button.svelte";
  import Card from "$components/ui/Card.svelte";
  import ConfirmDialog from "$components/ui/ConfirmDialog.svelte";
  import Dialog from "$components/ui/Dialog.svelte";
  import Switch from "$components/ui/Switch.svelte";
  import { gjenopprettBackup } from "$lib/api/klient";
  import { validerTidslas } from "$lib/domain/regler";
  import { draft } from "$lib/stores/draft.svelte";
  import { live } from "$lib/stores/live.svelte";

  type UnderFane = "anlegg" | "tider" | "backup";
  let aktivFane = $state<UnderFane>("anlegg");

  let lagrer = $state(false);
  let bekreftApBytte = $state(false);
  let apOmdoptInfo = $state<{ ssid: string; hostname: string } | null>(null);

  // Backup-gjenoppretting
  let filInput = $state<HTMLInputElement | null>(null);
  let valgtBackupFil = $state<File | null>(null);
  let backupSammendrag = $state<string>("");
  let bekreftRestore = $state(false);
  let gjenoppretter = $state(false);

  let idEndret = $derived(
    !!draft.anlegg &&
      !!draft.anleggLagret &&
      draft.anlegg.id.trim().toUpperCase() !==
        (draft.anleggLagret.id || "").trim().toUpperCase()
  );

  async function utforLagring() {
    lagrer = true;
    try {
      const res = await draft.lagreAnleggDraft();
      if (res.ok && res.ap_omdopt && res.ssid && res.hostname) {
        apOmdoptInfo = { ssid: res.ssid, hostname: res.hostname };
      }
    } finally {
      lagrer = false;
    }
  }

  function startLagring() {
    if (!draft.anlegg) return;
    if (idEndret) {
      bekreftApBytte = true;
      return;
    }
    utforLagring();
  }

  onMount(() => {
    const handler = () => startLagring();
    window.addEventListener("nsi63:lagre-anlegg", handler);
    return () => window.removeEventListener("nsi63:lagre-anlegg", handler);
  });

  function tilbakestillTider() {
    if (!draft.anlegg?.tider_def) return;
    const neste: Record<string, string> = {};
    for (const def of draft.anlegg.tider_def) {
      neste[def.navn] = String(def.standard);
    }
    draft.tiderTekst = neste;
    toast.info("Tidslåser satt til forbildets standardverdier (husk å lagre)");
  }

  async function velgBackupFil(file: File | undefined) {
    if (!file) return;
    try {
      const txt = await file.text();
      const j = JSON.parse(txt);
      const deler: string[] = [];
      if (j.anlegg?.id || j.anlegg?.navn) {
        deler.push(`Anlegg: ${j.anlegg.id || "?"} (${j.anlegg.navn || "—"})`);
      }
      const fnAnt = Array.isArray(j.hal?.functions)
        ? j.hal.functions.length
        : Array.isArray(j.functions)
          ? j.functions.length
          : null;
      if (fnAnt !== null) deler.push(`${fnAnt} objekter`);
      const tvAnt = Array.isArray(j.forrigling?.togveier)
        ? j.forrigling.togveier.length
        : null;
      if (tvAnt !== null) deler.push(`${tvAnt} togveier`);
      if (j.exported || j.updated) deler.push(`dato ${j.exported || j.updated}`);
      backupSammendrag = deler.length
        ? deler.join(" · ")
        : `Fil: ${file.name} (${Math.round(file.size / 1024)} kB)`;
      valgtBackupFil = file;
      bekreftRestore = true;
    } catch {
      toast.error("Filen er ikke gyldig JSON — kan ikke gjenopprettes");
    }
  }

  async function kjorRestore() {
    if (!valgtBackupFil) return;
    gjenoppretter = true;
    try {
      const res = await gjenopprettBackup(valgtBackupFil);
      await draft.lastAlt(false);
      toast.success(
        `Gjenopprettet ${res.functions} objekter` +
          (res.togveier !== null ? ` og ${res.togveier} togveier` : "")
      );
    } catch (e: any) {
      toast.error(e?.message || "Klarte ikke å gjenopprette backup");
    } finally {
      gjenoppretter = false;
      valgtBackupFil = null;
      if (filInput) filInput.value = "";
    }
  }
</script>

<div class="space-y-4">
  <!-- Faner -->
  <div class="flex flex-wrap items-center gap-1.5 border-b border-border pb-3">
    <button
      type="button"
      class="inline-flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium cursor-pointer transition-colors {aktivFane === 'anlegg'
        ? 'bg-primary/15 text-primary border border-primary/40'
        : 'text-muted-foreground hover:bg-secondary hover:text-foreground border border-transparent'}"
      onclick={() => (aktivFane = "anlegg")}
    >
      <Settings class="w-3.5 h-3.5" />
      Anlegg & Skilting
    </button>
    <button
      type="button"
      class="inline-flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium cursor-pointer transition-colors {aktivFane === 'tider'
        ? 'bg-primary/15 text-primary border border-primary/40'
        : 'text-muted-foreground hover:bg-secondary hover:text-foreground border border-transparent'}"
      onclick={() => (aktivFane = "tider")}
    >
      <Clock class="w-3.5 h-3.5" />
      Tidslåser
    </button>
    <button
      type="button"
      class="inline-flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium cursor-pointer transition-colors {aktivFane === 'backup'
        ? 'bg-primary/15 text-primary border border-primary/40'
        : 'text-muted-foreground hover:bg-secondary hover:text-foreground border border-transparent'}"
      onclick={() => (aktivFane = "backup")}
    >
      <HardDrive class="w-3.5 h-3.5" />
      Backup & Gjenoppretting
      {#if live.backup.endret}
        <span class="w-1.5 h-1.5 rounded-full bg-inn"></span>
      {/if}
    </button>
  </div>

  {#if aktivFane === "anlegg" && draft.anlegg}
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
      <!-- Identitet & Skilting -->
      <Card class="p-4 space-y-4">
        <div>
          <h2 class="text-sm font-semibold">Stasjonsidentitet & skilting</h2>
          <p class="text-xs text-muted-foreground">
            Styrer stasjonsskiltet på /panel, WiFi-navn og vertsnavn på Pi-en.
          </p>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
          <div class="space-y-1">
            <label class="text-[11px] font-medium text-muted-foreground" for="an-id">
              Stasjons-ID (3 tegn)
            </label>
            <input
              id="an-id"
              type="text"
              maxlength="6"
              class="w-full font-mono uppercase"
              value={draft.anlegg.id}
              oninput={(e) => {
                if (!draft.anlegg) return;
                draft.anlegg = {
                  ...draft.anlegg,
                  id: e.currentTarget.value.toUpperCase(),
                };
              }}
              placeholder="SKN"
            />
          </div>
          <div class="sm:col-span-2 space-y-1">
            <label class="text-[11px] font-medium text-muted-foreground" for="an-navn">
              Stasjonsnavn
            </label>
            <input
              id="an-navn"
              type="text"
              class="w-full"
              value={draft.anlegg.navn}
              oninput={(e) => {
                if (!draft.anlegg) return;
                draft.anlegg = { ...draft.anlegg, navn: e.currentTarget.value };
              }}
              placeholder="Sokna"
            />
          </div>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
          <div class="space-y-1">
            <label class="text-[11px] font-medium text-muted-foreground" for="an-nv">
              Nabostasjon venstre
            </label>
            <input
              id="an-nv"
              type="text"
              class="w-full"
              value={draft.anlegg.nabo_venstre}
              oninput={(e) => {
                if (!draft.anlegg) return;
                draft.anlegg = {
                  ...draft.anlegg,
                  nabo_venstre: e.currentTarget.value,
                };
              }}
              placeholder="Hønefoss"
            />
          </div>
          <div class="space-y-1">
            <label class="text-[11px] font-medium text-muted-foreground" for="an-nh">
              Nabostasjon høyre
            </label>
            <input
              id="an-nh"
              type="text"
              class="w-full"
              value={draft.anlegg.nabo_hoyre}
              oninput={(e) => {
                if (!draft.anlegg) return;
                draft.anlegg = {
                  ...draft.anlegg,
                  nabo_hoyre: e.currentTarget.value,
                };
              }}
              placeholder="Gulsvik"
            />
          </div>
        </div>

        <!-- Mini-skilt forhåndsvisning -->
        <div class="rounded-md border border-border bg-[#0d1016] px-4 py-3 flex items-center justify-between gap-2 text-xs">
          <span class="text-muted-foreground font-mono truncate">
            ← {draft.anlegg.nabo_venstre || "—"}
          </span>
          <span class="px-3 py-1 rounded bg-[#182230] border border-border-strong font-bold tracking-wider uppercase text-foreground">
            {draft.anlegg.navn || draft.anlegg.id || "NSI63"}
          </span>
          <span class="text-muted-foreground font-mono truncate">
            {draft.anlegg.nabo_hoyre || "—"} →
          </span>
        </div>

        {#if idEndret}
          <div class="rounded-md border border-amber/40 bg-amber/10 px-3 py-2 text-[11.5px] text-amber flex items-start gap-2">
            <AlertTriangle class="w-4 h-4 shrink-0 mt-0.5" />
            <span>
              Endring av stasjons-ID omdøper Pi-ens WiFi-nett til
              <strong class="font-mono">NSI63{draft.anlegg.id.trim().toUpperCase()}</strong>
              og starter aksesspunktet på nytt etter lagring.
            </span>
          </div>
        {/if}
      </Card>

      <!-- Driftsmoduser -->
      <Card class="p-4 space-y-4">
        <div>
          <h2 class="text-sm font-semibold">Driftsmoduser</h2>
          <p class="text-xs text-muted-foreground">
            Sendes til masteren ved lagring.
          </p>
        </div>

        <div class="divide-y divide-border/60 text-xs">
          <label class="flex items-start justify-between gap-4 py-2.5 cursor-pointer">
            <div>
              <div class="font-medium">Adopter nye noder automatisk</div>
              <div class="text-[11px] text-muted-foreground">
                Slipper nye M5 AtomS3-noder inn i ESP-NOW-nettet når de slås på.
              </div>
            </div>
            <Switch
              checked={draft.anlegg.adopter}
              onchange={(v) => {
                if (draft.anlegg) draft.anlegg = { ...draft.anlegg, adopter: v };
              }}
            />
          </label>

          <label class="flex items-start justify-between gap-4 py-2.5 cursor-pointer">
            <div>
              <div class="font-medium">Dekningsstilling</div>
              <div class="text-[11px] text-muted-foreground">
                Stiller beskyttende veksler automatisk i dekningsstilling ved sikring av togvei.
              </div>
            </div>
            <Switch
              checked={draft.anlegg.dekningsstilling}
              onchange={(v) => {
                if (draft.anlegg)
                  draft.anlegg = { ...draft.anlegg, dekningsstilling: v };
              }}
            />
          </label>

          <label class="flex items-start justify-between gap-4 py-2.5 cursor-pointer">
            <div>
              <div class="font-medium">Fjernstyrt (merking)</div>
              <div class="text-[11px] text-muted-foreground">
                Ren dokumentasjon/merking av om stasjonen er tenkt fjernstyrt — påvirker ikke forriglingen.
              </div>
            </div>
            <Switch
              checked={draft.anlegg.fjernstyrt}
              onchange={(v) => {
                if (draft.anlegg) draft.anlegg = { ...draft.anlegg, fjernstyrt: v };
              }}
            />
          </label>

          <label class="flex items-start justify-between gap-4 py-2.5 cursor-pointer">
            <div>
              <div class="font-medium text-ut">Testmodus</div>
              <div class="text-[11px] text-muted-foreground">
                Tillater direkte MQTT-kommandoer utenom forrigling. Viser varsellinje i hele UI-et.
              </div>
            </div>
            <Switch
              danger
              checked={draft.anlegg.testmodus}
              onchange={(v) => {
                if (draft.anlegg) draft.anlegg = { ...draft.anlegg, testmodus: v };
              }}
            />
          </label>

          <label class="flex items-start justify-between gap-4 py-2.5 cursor-pointer">
            <div>
              <div class="font-medium text-ut">Vis simulering på /panel</div>
              <div class="text-[11px] text-muted-foreground">
                Viser simuleringsverktøy for belegg/veksler i det digitale stillerapparatet.
              </div>
            </div>
            <Switch
              danger
              checked={draft.anlegg.vis_sim}
              onchange={(v) => {
                if (draft.anlegg) draft.anlegg = { ...draft.anlegg, vis_sim: v };
              }}
            />
          </label>
        </div>

        <div class="pt-2 flex flex-wrap items-center justify-between gap-2">
          <div class="text-[11.5px]">
            {#if draft.anleggAck.status === "venter"}
              <Badge variant="amber">
                {draft.anleggAck.tidsutlopt
                  ? "Venter fortsatt på master-kvittering"
                  : "Venter på master-kvittering…"}
              </Badge>
            {:else if draft.anleggAck.status === "kvittert"}
              <Badge variant="ok">✓ Master kvitterte ({draft.anleggAck.version})</Badge>
            {/if}
          </div>
          <div class="flex items-center gap-2">
            <Button
              size="sm"
              variant="ghost"
              disabled={!draft.anleggDirty || lagrer}
              onclick={() => draft.forkastAnlegg()}
            >
              Forkast
            </Button>
            <Button
              size="sm"
              variant="primary"
              disabled={!draft.anleggDirty || lagrer}
              onclick={startLagring}
            >
              <Save class="w-3.5 h-3.5" />
              Lagre innstillinger
            </Button>
          </div>
        </div>
      </Card>
    </div>
  {/if}

  {#if aktivFane === "tider" && draft.anlegg}
    <Card class="p-4 space-y-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 class="text-sm font-semibold">Tidslåser & sikkerhetstider</h2>
          <p class="text-xs text-muted-foreground">
            Alle felt krever et gyldig heltall — et tomt felt lagres aldri som 0.
          </p>
        </div>
        <div class="flex items-center gap-2">
          <Button size="xs" variant="outline" onclick={tilbakestillTider}>
            <RotateCcw class="w-3 h-3" />
            Tilbakestill til forbilde
          </Button>
          <Button
            size="sm"
            variant="primary"
            disabled={!draft.anleggDirty || lagrer}
            onclick={startLagring}
          >
            <Save class="w-3.5 h-3.5" />
            Lagre
          </Button>
        </div>
      </div>

      <div class="divide-y divide-border/60">
        {#each draft.anlegg.tider_def || [] as def (def.navn)}
          {@const raw = draft.tiderTekst[def.navn] ?? ""}
          {@const sjekk = validerTidslas(raw, def)}
          <div class="py-3 grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_180px] gap-3 items-start text-xs">
            <div class="space-y-0.5">
              <div class="font-semibold text-foreground">{def.tittel}</div>
              <div class="text-muted-foreground">{def.hva}</div>
              <div class="text-[11px] text-muted-foreground/80">
                Forbilde: <strong class="text-foreground/80">{def.forbilde}</strong>
                {#if def.kilde} · {def.kilde}{/if}
              </div>
              {#if !sjekk.ok}
                <div class="text-[11px] text-warn font-medium pt-0.5">
                  ⚠ {sjekk.feil}
                </div>
              {/if}
            </div>

            <div class="space-y-1">
              <div class="flex items-center gap-1.5">
                <input
                  type="text"
                  inputmode="numeric"
                  class="w-full font-mono text-right {!sjekk.ok ? 'border-warn!' : ''}"
                  value={raw}
                  oninput={(e) => {
                    draft.tiderTekst = {
                      ...draft.tiderTekst,
                      [def.navn]: e.currentTarget.value,
                    };
                  }}
                />
                <span class="text-[11px] text-muted-foreground w-8 shrink-0">
                  {def.enhet}
                </span>
              </div>
              <div class="text-[10.5px] text-muted-foreground font-mono text-right">
                {def.min}–{def.maks}{def.av ? " (0 = av)" : ""} · std {def.standard}
              </div>
            </div>
          </div>
        {/each}
      </div>
    </Card>
  {/if}

  {#if aktivFane === "backup"}
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
      <!-- Manuell backup & gjenoppretting -->
      <Card class="p-4 space-y-4">
        <div>
          <h2 class="text-sm font-semibold">Last ned & gjenopprett</h2>
          <p class="text-xs text-muted-foreground">
            Én JSON-fil inneholder hele anlegget (HAL, forrigling og anleggsinnstillinger).
          </p>
        </div>

        <div class="rounded-md border border-border bg-secondary/40 p-3 text-xs space-y-2">
          <div class="flex items-center justify-between gap-2">
            <span class="text-muted-foreground">Siste nedlastede backup</span>
            <span class="font-mono">{live.backup.sist || "Aldri"}</span>
          </div>
          {#if live.backup.endret}
            <Badge variant="inn">
              Endret siden siste backup: {live.backup.hva.join(", ") || "konfigurasjon"}
            </Badge>
          {:else}
            <Badge variant="ok">Backup er oppdatert</Badge>
          {/if}
        </div>

        <div class="flex flex-wrap items-center gap-2">
          <a
            href="/api/backup"
            class="inline-flex items-center gap-1.5 h-8 px-3 text-xs font-semibold rounded-md bg-primary text-primary-foreground hover:bg-[#58a6ff] no-underline"
          >
            <Download class="w-3.5 h-3.5" />
            Last ned komplett backup
          </a>

          <input
            bind:this={filInput}
            type="file"
            accept=".json,application/json"
            class="hidden"
            onchange={(e) => velgBackupFil(e.currentTarget.files?.[0])}
          />
          <Button
            size="sm"
            variant="outline"
            disabled={gjenoppretter}
            onclick={() => filInput?.click()}
          >
            <Upload class="w-3.5 h-3.5" />
            Gjenopprett fra .json…
          </Button>
        </div>
      </Card>

      <!-- Automatiske sikkerhetskopier på Pi -->
      <Card class="p-4 space-y-3">
        <div>
          <h2 class="text-sm font-semibold">Automatiske kopier på Pi-en</h2>
          <p class="text-xs text-muted-foreground">
            Pi-en tar vare på de 20 siste versjonene automatisk før hver lagring.
          </p>
        </div>

        {#if !(live.backup.auto || []).length}
          <div class="py-6 text-center text-xs text-muted-foreground">
            Ingen automatiske kopier ennå.
          </div>
        {:else}
          <div class="max-h-72 overflow-y-auto divide-y divide-border/60 rounded-md border border-border text-xs">
            {#each live.backup.auto as navn (navn)}
              <div class="px-3 py-2 flex items-center justify-between gap-2">
                <span class="font-mono text-[11.5px] truncate">{navn}</span>
                <a
                  href="/api/backup-auto/{encodeURIComponent(navn)}"
                  class="text-primary hover:underline shrink-0 text-[11.5px]"
                >
                  Last ned
                </a>
              </div>
            {/each}
          </div>
        {/if}
      </Card>
    </div>
  {/if}
</div>

<ConfirmDialog
  bind:open={bekreftApBytte}
  title="Endre stasjons-ID og WiFi-nett?"
  description={`Stasjons-ID endres til ${draft.anlegg?.id?.trim().toUpperCase()}. Pi-en starter WiFi-aksesspunktet (hostapd) på nytt ~1,5 sekunder etter lagring, slik at du midlertidig mister forbindelsen og må koble til det nye nettet.`}
  confirmLabel="Lagre og omdøp WiFi"
  destructive
  onconfirm={utforLagring}
/>

<Dialog
  open={apOmdoptInfo !== null}
  onOpenChange={(o) => {
    if (!o) apOmdoptInfo = null;
  }}
  title="WiFi-aksesspunktet starter på nytt"
>
  {#if apOmdoptInfo}
    <div class="space-y-3 text-xs">
      <p>
        Pi-en har lagret ny stasjons-ID og starter WiFi-nettet på nytt nå. Koble enheten din til:
      </p>
      <div class="rounded-md border border-border bg-secondary p-3 space-y-1 font-mono">
        <div>WiFi-nett (SSID): <strong>{apOmdoptInfo.ssid}</strong></div>
        <div>Adresse: <strong>http://{apOmdoptInfo.hostname}.local:8080</strong></div>
      </div>
      <div class="flex justify-end">
        <Button size="sm" variant="primary" onclick={() => (apOmdoptInfo = null)}>
          Forstått
        </Button>
      </div>
    </div>
  {/if}
</Dialog>

<ConfirmDialog
  bind:open={bekreftRestore}
  title="Gjenopprett konfigurasjon fra backup?"
  description={`Dette erstatter dagens lagrede konfigurasjon på Pi-en og publiserer den til masteren. Innhold: ${backupSammendrag}`}
  confirmLabel="Gjenopprett nå"
  destructive
  onconfirm={kjorRestore}
/>
