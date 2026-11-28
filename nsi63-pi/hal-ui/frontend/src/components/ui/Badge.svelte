<script lang="ts">
  import type { Snippet } from "svelte";
  import { tv, type VariantProps } from "tailwind-variants";
  import { cn } from "$lib/utils";

  const badgeVariants = tv({
    base: "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium border whitespace-nowrap",
    variants: {
      variant: {
        default: "bg-secondary text-foreground border-border",
        muted: "bg-muted text-muted-foreground border-border",
        ok: "bg-ok/15 text-ok border-ok/35",
        warn: "bg-warn/15 text-warn border-warn/40",
        amber: "bg-amber/15 text-amber border-amber/40",
        inn: "bg-inn/15 text-inn border-inn/40",
        ut: "bg-ut/15 text-ut border-ut/40",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  });

  type Props = VariantProps<typeof badgeVariants> & {
    class?: string;
    title?: string;
    children?: Snippet;
  };

  let { variant = "default", class: className = "", title, children }: Props =
    $props();
</script>

<span {title} class={cn(badgeVariants({ variant }), className)}>
  {@render children?.()}
</span>
