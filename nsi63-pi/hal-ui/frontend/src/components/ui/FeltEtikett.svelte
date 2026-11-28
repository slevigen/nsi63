<script lang="ts">
  import { HelpCircle } from "@lucide/svelte";

  interface Props {
    label: string;
    forId?: string;
    hjelp: string;
    class?: string;
  }

  let { label, forId, hjelp, class: className = "" }: Props = $props();

  let apen = $state(false);
</script>

<div class="space-y-1 {className}">
  <div class="flex items-center justify-between gap-1.5">
    {#if forId}
      <label for={forId} class="text-[11px] text-muted-foreground font-medium">
        {label}
      </label>
    {:else}
      <span class="text-[11px] text-muted-foreground font-medium">
        {label}
      </span>
    {/if}
    <button
      type="button"
      title={hjelp}
      aria-label={`Hjelp for ${label}`}
      aria-expanded={apen}
      onclick={() => (apen = !apen)}
      class="inline-flex items-center justify-center rounded p-0.5 cursor-pointer transition-colors {apen
        ? 'text-primary bg-primary/15'
        : 'text-muted-foreground/70 hover:text-foreground hover:bg-secondary'}"
    >
      <HelpCircle class="w-3.5 h-3.5" />
    </button>
  </div>

  {#if apen}
    <p
      class="rounded-md border border-border bg-secondary/70 px-2.5 py-1.5 text-[11px] leading-relaxed text-foreground/90"
    >
      {hjelp}
    </p>
  {/if}
</div>
