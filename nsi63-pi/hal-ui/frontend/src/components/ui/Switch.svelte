<script lang="ts">
  import { Switch as BitsSwitch } from "bits-ui";
  import { cn } from "$lib/utils";

  interface Props {
    checked?: boolean;
    disabled?: boolean;
    danger?: boolean;
    id?: string;
    ariaLabel?: string;
    onchange?: (checked: boolean) => void;
  }

  let {
    checked = $bindable(false),
    disabled = false,
    danger = false,
    id,
    ariaLabel,
    onchange,
  }: Props = $props();
</script>

<BitsSwitch.Root
  {id}
  bind:checked
  {disabled}
  aria-label={ariaLabel}
  onCheckedChange={(v) => onchange?.(v)}
  class={cn(
    "peer inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border border-transparent transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-40",
    checked ? (danger ? "bg-warn" : "bg-ok") : "bg-border-strong"
  )}
>
  <BitsSwitch.Thumb
    class={cn(
      "pointer-events-none block h-4 w-4 rounded-full bg-white shadow transition-transform",
      checked ? "translate-x-4" : "translate-x-0.5"
    )}
  />
</BitsSwitch.Root>
