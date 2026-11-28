<script lang="ts">
  import { AlertDialog } from "bits-ui";
  import Button from "./Button.svelte";

  interface Props {
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
    title: string;
    description: string;
    confirmLabel?: string;
    cancelLabel?: string;
    destructive?: boolean;
    onconfirm: () => void | Promise<void>;
  }

  let {
    open = $bindable(false),
    onOpenChange,
    title,
    description,
    confirmLabel = "Bekreft",
    cancelLabel = "Avbryt",
    destructive = false,
    onconfirm,
  }: Props = $props();

  let busy = $state(false);

  async function bekreft() {
    busy = true;
    try {
      await onconfirm();
      open = false;
      onOpenChange?.(false);
    } finally {
      busy = false;
    }
  }
</script>

<AlertDialog.Root bind:open {onOpenChange}>
  <AlertDialog.Portal>
    <AlertDialog.Overlay
      class="fixed inset-0 z-50 bg-black/70 backdrop-blur-[1px]"
    />
    <AlertDialog.Content
      class="fixed left-1/2 top-1/2 z-50 w-[calc(100%-24px)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border-strong bg-card p-5 shadow-2xl"
    >
      <AlertDialog.Title class="text-sm font-semibold text-foreground">
        {title}
      </AlertDialog.Title>
      <AlertDialog.Description
        class="mt-2 text-xs text-muted-foreground whitespace-pre-line leading-relaxed"
      >
        {description}
      </AlertDialog.Description>
      <div class="mt-4 flex justify-end gap-2">
        <AlertDialog.Cancel>
          {#snippet child({ props })}
            <Button {...props} variant="ghost" disabled={busy}>
              {cancelLabel}
            </Button>
          {/snippet}
        </AlertDialog.Cancel>
        <Button
          variant={destructive ? "destructive" : "primary"}
          disabled={busy}
          onclick={bekreft}
        >
          {confirmLabel}
        </Button>
      </div>
    </AlertDialog.Content>
  </AlertDialog.Portal>
</AlertDialog.Root>
