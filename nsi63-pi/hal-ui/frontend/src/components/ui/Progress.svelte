<script lang="ts">
  import { cn } from "$lib/utils";

  interface Props {
    value: number;
    max: number;
    warnAt?: number;
    dangerAt?: number;
    class?: string;
  }

  let { value, max, warnAt, dangerAt, class: className = "" }: Props = $props();

  let pct = $derived(max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0);
  let farge = $derived(
    dangerAt !== undefined && value > dangerAt
      ? "bg-warn"
      : warnAt !== undefined && value > warnAt
        ? "bg-amber"
        : "bg-ok"
  );
</script>

<div
  class={cn(
    "h-1.5 w-full overflow-hidden rounded-full bg-background border border-border",
    className
  )}
>
  <div class={cn("h-full rounded-full transition-all", farge)} style="width:{pct}%"></div>
</div>
