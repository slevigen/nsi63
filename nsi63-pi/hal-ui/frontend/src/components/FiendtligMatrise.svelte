<script lang="ts">
  import { frFiendtlig } from "$lib/domain/regler";
  import type { Togvei } from "$lib/types";

  interface Props {
    togveier: Togvei[];
  }

  let { togveier }: Props = $props();

  let valgtPar = $state<{ a: string; b: string; grunner: string[] } | null>(null);

  let matrise = $derived.by(() => {
    return togveier.map((a, i) =>
      togveier.map((b, j) => (i === j ? null : frFiendtlig(a, b)))
    );
  });
</script>

{#if togveier.length < 2}
  <div class="text-xs text-muted-foreground py-3">
    Legg til minst to togveier for å se fiendtlighetsmatrisen.
  </div>
{:else}
  <div class="space-y-2.5">
    <div class="overflow-x-auto">
      <table class="border-collapse text-[11px] font-mono">
        <thead>
          <tr>
            <th class="p-1.5 text-left text-muted-foreground"></th>
            {#each togveier as b, j (j)}
              <th class="p-1.5 text-center text-muted-foreground font-semibold">
                {b.id || `#${j + 1}`}
              </th>
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each togveier as a, i (i)}
            <tr>
              <th class="p-1.5 pr-2.5 text-right text-muted-foreground font-semibold whitespace-nowrap">
                {a.id || `#${i + 1}`}
              </th>
              {#each togveier as b, j (j)}
                {@const grunner = matrise[i]?.[j]}
                {#if grunner === null}
                  <td class="p-1 text-center text-muted-foreground/30 bg-secondary/20 border border-border/50 w-9 h-8">
                    —
                  </td>
                {:else if grunner.length > 0}
                  <td class="p-0.5 border border-border/50 w-9 h-8">
                    <button
                      type="button"
                      class="w-full h-full rounded bg-warn/20 hover:bg-warn/35 text-warn font-bold grid place-items-center cursor-pointer transition-colors"
                      title={`${a.id} × ${b.id}: ${grunner.join(" · ")}`}
                      onmouseenter={() =>
                        (valgtPar = {
                          a: a.id || `#${i + 1}`,
                          b: b.id || `#${j + 1}`,
                          grunner,
                        })}
                      onclick={() =>
                        (valgtPar = {
                          a: a.id || `#${i + 1}`,
                          b: b.id || `#${j + 1}`,
                          grunner,
                        })}
                    >
                      ×
                    </button>
                  </td>
                {:else}
                  <td class="p-0.5 border border-border/50 w-9 h-8">
                    <button
                      type="button"
                      class="w-full h-full rounded bg-ok/10 hover:bg-ok/25 text-ok grid place-items-center cursor-pointer transition-colors"
                      title={`${a.id} og ${b.id} kan sikres samtidig`}
                      onmouseenter={() =>
                        (valgtPar = {
                          a: a.id || `#${i + 1}`,
                          b: b.id || `#${j + 1}`,
                          grunner: [],
                        })}
                      onclick={() =>
                        (valgtPar = {
                          a: a.id || `#${i + 1}`,
                          b: b.id || `#${j + 1}`,
                          grunner: [],
                        })}
                    >
                      ✓
                    </button>
                  </td>
                {/if}
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <div class="text-xs rounded-md border border-border bg-secondary/40 px-3 py-2 min-h-[36px] flex items-center">
      {#if valgtPar}
        {#if valgtPar.grunner.length > 0}
          <span>
            <strong class="font-mono text-warn">{valgtPar.a} × {valgtPar.b}</strong>:
            {valgtPar.grunner.join(" · ")}
          </span>
        {:else}
          <span>
            <strong class="font-mono text-ok">{valgtPar.a} + {valgtPar.b}</strong>:
            kan sikres samtidig (ikke fiendtlige)
          </span>
        {/if}
      {:else}
        <span class="text-muted-foreground">
          Hold over eller klikk på en rute i matrisen for å se årsaken til fiendtlighet.
        </span>
      {/if}
    </div>
  </div>
{/if}
