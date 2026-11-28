<script lang="ts">
  import type { Snippet } from "svelte";
  import { cn } from "$lib/utils";

  interface Props {
    title?: string;
    subtitle?: string;
    class?: string;
    actions?: Snippet;
    children?: Snippet;
  }

  let {
    title,
    subtitle,
    class: className = "",
    actions,
    children,
  }: Props = $props();
</script>

<section
  class={cn("rounded-lg border border-border bg-card p-4", className)}
>
  {#if title || actions}
    <div class="flex items-start justify-between gap-3 mb-3 flex-wrap">
      <div>
        {#if title}
          <h2 class="text-sm font-semibold text-foreground tracking-wide">
            {title}
          </h2>
        {/if}
        {#if subtitle}
          <p class="text-xs text-muted-foreground mt-0.5">{subtitle}</p>
        {/if}
      </div>
      {#if actions}
        <div class="flex items-center gap-2">
          {@render actions()}
        </div>
      {/if}
    </div>
  {/if}
  {@render children?.()}
</section>
