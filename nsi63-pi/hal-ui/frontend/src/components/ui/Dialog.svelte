<script lang="ts">
  import type { Snippet } from "svelte";
  import { Dialog as BitsDialog } from "bits-ui";
  import { X } from "@lucide/svelte";
  import { cn } from "$lib/utils";

  interface Props {
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
    title: string;
    description?: string;
    side?: "center" | "right" | "left";
    class?: string;
    children?: Snippet;
  }

  let {
    open = $bindable(false),
    onOpenChange,
    title,
    description,
    side = "center",
    class: className = "",
    children,
  }: Props = $props();
</script>

<BitsDialog.Root bind:open {onOpenChange}>
  <BitsDialog.Portal>
    <BitsDialog.Overlay
      class="fixed inset-0 z-50 bg-black/65 backdrop-blur-[1px]"
    />
    <BitsDialog.Content
      class={cn(
        "fixed z-50 bg-card text-foreground border border-border-strong shadow-2xl flex flex-col max-h-[92vh]",
        side === "center" &&
          "left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[calc(100%-24px)] max-w-lg rounded-lg p-5",
        side === "right" &&
          "right-0 top-0 h-full max-h-none w-full max-w-md border-l rounded-none p-4",
        side === "left" &&
          "left-0 top-0 h-full max-h-none w-64 border-r rounded-none p-3",
        className
      )}
    >
      <div
        class="flex items-start justify-between gap-3 pb-3 mb-3 border-b border-border shrink-0"
      >
        <div>
          <BitsDialog.Title class="text-sm font-semibold text-foreground">
            {title}
          </BitsDialog.Title>
          {#if description}
            <BitsDialog.Description class="text-xs text-muted-foreground mt-0.5">
              {description}
            </BitsDialog.Description>
          {/if}
        </div>
        <BitsDialog.Close
          class="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground cursor-pointer"
          aria-label="Lukk"
        >
          <X class="w-4 h-4" />
        </BitsDialog.Close>
      </div>
      <div class="overflow-y-auto flex-1 min-h-0">
        {@render children?.()}
      </div>
    </BitsDialog.Content>
  </BitsDialog.Portal>
</BitsDialog.Root>
