<script lang="ts">
  import Dialog from "./ui/Dialog.svelte";

  interface Props {
    open?: boolean;
  }
  let { open = $bindable(false) }: Props = $props();
</script>

<Dialog
  bind:open
  title="LED-språk — M5 AtomS3"
  description="Blink i sekundtakt = pulsen flyter (anleggets EKG). Fast lys = låst tilstand. Pustende lys = aktiv søking."
>
  <div class="space-y-4 text-xs">
    <div>
      <h3 class="font-semibold text-foreground mb-1.5">Master</h3>
      <ul class="space-y-1.5 text-muted-foreground">
        <li class="flex items-center gap-2"><span class="w-2.5 h-2.5 rounded-full bg-[#4a90d9] shrink-0"></span><span><b class="text-foreground">Blå blink</b> — alt vel</span></li>
        <li class="flex items-center gap-2"><span class="w-2.5 h-2.5 rounded-full bg-[#e05252] shrink-0"></span><span><b class="text-foreground">Rød blink</b> — node savnet / sikker tilstand</span></li>
        <li class="flex items-center gap-2"><span class="w-2.5 h-2.5 rounded-full bg-[#e08a3c] shrink-0"></span><span><b class="text-foreground">Oransje blink</b> — WiFi / MQTT nede</span></li>
        <li class="flex items-center gap-2"><span class="w-2.5 h-2.5 rounded-full bg-[#b46be0] shrink-0"></span><span><b class="text-foreground">Fiolett blink</b> — mangler konfigurasjon</span></li>
        <li class="flex items-center gap-2"><span class="w-2.5 h-2.5 rounded-full bg-[#e05252] ring-2 ring-[#e05252]/40 shrink-0"></span><span><b class="text-foreground">Rød dobbeltblink</b> — TO mastere aktive!</span></li>
        <li class="flex items-center gap-2"><span class="w-2.5 h-2.5 rounded-full bg-[#3cc8c8] shrink-0"></span><span><b class="text-foreground">Cyan fast</b> — OTA pågår</span></li>
      </ul>
    </div>
    <div>
      <h3 class="font-semibold text-foreground mb-1.5">Node</h3>
      <ul class="space-y-1.5 text-muted-foreground">
        <li class="flex items-center gap-2"><span class="w-2.5 h-2.5 rounded-full bg-[#5bb974] shrink-0"></span><span><b class="text-foreground">Grønn blink</b> — normal drift</span></li>
        <li class="flex items-center gap-2"><span class="w-2.5 h-2.5 rounded-full bg-[#e0c23c] shrink-0"></span><span><b class="text-foreground">Gul blink</b> — «Finn meg» (10 s)</span></li>
        <li class="flex items-center gap-2"><span class="w-2.5 h-2.5 rounded-full bg-[#e052e0] ring-2 ring-[#e052e0]/40 shrink-0"></span><span><b class="text-foreground">Magenta dobbeltblink</b> — I2C-feil</span></li>
        <li class="flex items-center gap-2"><span class="w-2.5 h-2.5 rounded-full bg-[#e05252] shrink-0"></span><span><b class="text-foreground">Rød fast</b> — sikker tilstand</span></li>
        <li class="flex items-center gap-2"><span class="w-2.5 h-2.5 rounded-full bg-[#e0c23c]/75 shrink-0"></span><span><b class="text-foreground">Gul pustende</b> — søker master</span></li>
        <li class="flex items-center gap-2"><span class="w-2.5 h-2.5 rounded-full bg-[#3cc8c8] shrink-0"></span><span><b class="text-foreground">Cyan fast</b> — OTA pågår</span></li>
      </ul>
    </div>
    <div class="rounded-md bg-muted/60 border border-border p-2.5 text-muted-foreground">
      <b class="text-foreground">Begge:</b> Fast hvitt lys under holdt frontknapp (10 s+) — slipp for å nullstille paring. Hold frontknappen 3 s ved strømpåslag (fiolett kvittering) for å sette rollen som master.
    </div>
  </div>
</Dialog>
