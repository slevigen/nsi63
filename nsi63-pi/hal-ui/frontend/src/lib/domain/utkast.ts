import type { HalFunction, SignalTypeDef } from "../types";
import { litraNs } from "./regler";

export interface DraftFunction extends HalFunction {
  _rid: number;
  _orgId: string;
}

export function klon<T>(v: T): T {
  return JSON.parse(JSON.stringify(v));
}

export function normaliserForLagring(fns: DraftFunction[]): HalFunction[] {
  return fns.map(({ _rid, _orgId, ...rest }) => {
    const ut: HalFunction = {
      ...klon(rest),
      id: (rest.id || "").trim(),
      bindinger: (rest.bindinger || [])
        .filter((b) => (b.node || "").trim() !== "")
        .map((b) => ({
          sted: b.sted,
          node: b.node.trim(),
          i2c: b.i2c,
          port: Number(b.port) || 0,
        })),
    };
    if (_orgId && _orgId !== ut.id) {
      ut.gammel_id = _orgId;
    } else {
      delete ut.gammel_id;
    }
    return ut;
  });
}

/**
 * Serialiserer en HalFunction-liste som sammenligningsgrunnlag uten `gammel_id`,
 * slik at sammenligning mot lagret tilstand ikke påvirkes av omdøpingsfeltet.
 */
export function halGrunnlagJson(fns: HalFunction[]): string {
  const renset = fns.map((f) => {
    const kopi = klon(f);
    kopi.id = (kopi.id || "").trim();
    kopi.bindinger = (kopi.bindinger || [])
      .filter((b) => (b.node || "").trim() !== "")
      .map((b) => ({
        sted: b.sted,
        node: b.node.trim(),
        i2c: b.i2c,
        port: Number(b.port) || 0,
      }));
    delete kopi.gammel_id;
    return kopi;
  });
  return JSON.stringify(renset);
}

/**
 * Bygger DraftFunction-liste fra serverdata og gjenbruker eksisterende `_rid`
 * slik at åpen inspektør overlever lagring, omdøping og SSE-omlasting.
 */
export function tilDraftFns(
  fns: HalFunction[],
  eksisterende: DraftFunction[],
  nesteRid: () => number,
  signaltyper?: Record<string, SignalTypeDef>
): DraftFunction[] {
  const bruktRid = new Set<number>();
  const eksMedNsId = new Map<string, DraftFunction>();
  const eksMedId = new Map<string, DraftFunction>();
  for (const g of eksisterende) {
    const id = (g.id || "").trim();
    if (!id) continue;
    const nsKey = `${litraNs(g.type, signaltyper)}|${id}`;
    if (!eksMedNsId.has(nsKey)) eksMedNsId.set(nsKey, g);
    if (!eksMedId.has(id)) eksMedId.set(id, g);
  }

  return fns
    .slice()
    .sort((a, b) =>
      (a.id || "").localeCompare(b.id || "", "no", { numeric: true })
    )
    .map((f) => {
      const id = (f.id || "").trim();
      const nsKey = `${litraNs(f.type, signaltyper)}|${id}`;
      const treff = eksMedNsId.get(nsKey) || eksMedId.get(id);
      let rid: number;
      if (treff && !bruktRid.has(treff._rid)) {
        rid = treff._rid;
        bruktRid.add(rid);
      } else {
        rid = nesteRid();
      }
      return {
        ...klon(f),
        bindinger: klon(f.bindinger || []),
        _rid: rid,
        _orgId: id,
      };
    });
}

/**
 * Etter en vellykket `POST /api/hal`:
 * - `_orgId` oppdateres KUN til den ID-en som faktisk ble sendt for hver `_rid`.
 * - Nye rader eller redigeringer gjort MENS lagringen pågikk beholdes urørt,
 *   og forblir merket som ulagrede fordi grunnlaget bygges fra det som ble sendt.
 */
export function oppdaterOrgIdFraSendt(
  aktuelle: DraftFunction[],
  sendtRidTilId: Map<number, string>
): DraftFunction[] {
  return aktuelle.map((f) => {
    if (!sendtRidTilId.has(f._rid)) return f;
    return {
      ...f,
      _orgId: sendtRidTilId.get(f._rid)!,
    };
  });
}
