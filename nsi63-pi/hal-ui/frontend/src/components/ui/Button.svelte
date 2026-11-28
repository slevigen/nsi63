<script lang="ts">
  import type { Snippet } from "svelte";
  import type { HTMLButtonAttributes } from "svelte/elements";
  import { tv, type VariantProps } from "tailwind-variants";
  import { cn } from "$lib/utils";

  const buttonVariants = tv({
    base: "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md font-medium transition-colors cursor-pointer disabled:pointer-events-none disabled:opacity-40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
    variants: {
      variant: {
        default:
          "bg-secondary text-foreground border border-border-strong hover:bg-accent hover:border-primary/70",
        primary:
          "bg-primary text-primary-foreground border border-primary font-semibold hover:brightness-105",
        destructive:
          "bg-warn/15 text-warn border border-warn/40 hover:bg-warn/25",
        ghost:
          "bg-transparent text-muted-foreground border border-transparent hover:bg-secondary hover:text-foreground",
        outline:
          "bg-transparent text-foreground border border-border hover:bg-secondary",
      },
      size: {
        xs: "h-6 px-2 text-[11px]",
        sm: "h-7 px-2.5 text-xs",
        md: "h-8 px-3 text-xs",
        icon: "h-7 w-7 p-0",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "md",
    },
  });

  type Props = HTMLButtonAttributes &
    VariantProps<typeof buttonVariants> & {
      children?: Snippet;
    };

  let {
    variant = "default",
    size = "md",
    class: className = "",
    type = "button",
    children,
    ...rest
  }: Props = $props();
</script>

<button
  {type}
  class={cn(buttonVariants({ variant, size }), className)}
  {...rest}
>
  {@render children?.()}
</button>
