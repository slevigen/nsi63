let SIGNALTYPER = {};
// Signalklasse for en type — fra typedefinisjonen, ellers navneprefiks
function sigKlasse(t) {
  const st = SIGNALTYPER[t];
  if (st && st.klasse) return st.klasse;
  for (const k of ["forsignal", "skiftesignal", "dvergsignal",
                   "hovedsignal"])
    if ((t || "").startsWith(k)) return k;
  return null;
}
const erHoved = t => sigKlasse(t) === "hovedsignal";
const TYPES = ["hovedsignal3","hovedsignal2","forsignal2",
               "skiftesignal2","skiftesignal1",
               "dvergsignal3",
               "sporveksel","manuellveksel","sporsperre",
               "utgang","klokke",
               "sporfelt","bryter","trykknapp","inngang","amperemeter",
               "samlelaas","rigel"];
// Grupper i HAL-tabellen: objektene som inngår i forriglingen først,
// alt annet samlet nederst. Typevalget på raden begrenses til gruppen.
// Gruppene er HOMOGENE med vilje: alle typer i en gruppe har samme
// bindingsrader (se bindingsrader()). «venstre» og «hoyre» navngir de
// to portkolonnene der ALLE radene i gruppen deler samme par — for
// veksler er det normal og avvik. Der parene varierer fra rad til rad
// (sporfelt, låser) står de tomme, og radetiketten sier det i stedet.
const GRUPPER = [
  {navn: "Signaler",    typer: ["hovedsignal3","hovedsignal2",
                                "forsignal2",
                                "skiftesignal2","skiftesignal1",
                                "dvergsignal3"],
   venstre: "ute på anlegget", hoyre: "på stillerapparatet"},
  {navn: "Veksler", typer: ["sporveksel","manuellveksel"],
   venstre: "normal", hoyre: "avvik"},
  {navn: "Sporavsnitt", typer: ["sporfelt"],
   venstre: "", hoyre: ""},
  {navn: "Trykknapper og brytere", typer: ["trykknapp","bryter"],
   venstre: "inngangen", hoyre: "kontrollampe"},
  // Sporsperren er en egen ting: normalstillingen er PÅLAGT, den har
  // ingen ende og ingen Lok-frigivning. Den står her nede fordi det
  // er låsene som frigir den — men i EGEN gruppe, siden hovedbindingen
  // (ut-paalagt) er en annen enn låsenes (anlegg).
  {navn: "Sporsperrer", typer: ["sporsperre"],
   venstre: "pålagt", hoyre: "avlagt"},
  {navn: "Låser",       typer: ["samlelaas","rigel"],
   venstre: "", hoyre: ""},
  // «utgang» og «inngang» er RENE bindingsholdere: master har ingen
  // logikk for dem, så de driver ingenting av seg selv. De er nyttige
  // for å reservere porter og dokumentere kabling — men en port bundet
  // til «utgang» teller mot nodens 40-tak uten noen gang å bli satt.
  {navn: "Annet",       typer: ["utgang","inngang","klokke",
                                "amperemeter"],
   // Eneste gruppe som blander retning: «utgang» reserverer en
   // utgangsport, «inngang» en inngangsport. Radene er merket hver for
   // seg — retningsfargen på I2C-feltet sier hva porten er.
   venstre: "", hoyre: ""},
];
const COLLAPSED = new Set();   // sammenlagte grupper (per sidevisning)
// Utfoldede objektrader. Radene ligger i DOM-en uansett — bare skjult
// — så collect() leser dem som før og ingenting kan falle ut ved
// lagring fordi noe var sammenlagt.
const RADAAPEN = new Set();
let RAD_TELLER = 0;            // stabil id per rad, uavhengig av litra
let BARE_BUNDNE = false;       // filter: skjul porter uten binding
function gruppeIdx(type) {
  const i = GRUPPER.findIndex(g => g.typer.includes(type));
  return i < 0 ? GRUPPER.length - 1 : i;
}
// Full adresseliste — brukes som reserve når valgt node ikke har
// meldt brikkene sine (offline/aldri sett/planlegging).
// PCA9685: 16 kanaler (0-15), PCF8574: 8 pinner (0-7).
const I2C_ALLE = ["0x40","0x41","0x42","0x43","0x20","0x21","0x22","0x23"];
// GPIO-pseudobrikken (fw v4): nodens egne pinner, port 0-5 med fast
// kart til fysiske pinner på AtomS3 Lite. Inn ELLER ut per port —
// retningen avledes av bindingsstedet, master ordner resten.
const GPIO_PINNER = ["G5","G6","G7","G8","G38","G39"];
// Kort etikett — nedtrekket skal ikke være bredere enn det trenger.
// Brikkenavnet i klartekst står i select-ens title.
function i2cLabel(a) {
  if (a === "gpio") return "GPIO";
  return a + (a.startsWith("0x4") ? " PCA" : " PCF");
}
// Brikkene valgt node faktisk har meldt (null = ukjent -> full liste)
function i2cListFor(nodeVal) {
  const mac = (NODER[nodeVal] && NODER[nodeVal].mac) || nodeVal;
  const n = liveNodes.find(x => x.mac === mac);
  return (n && n.i2c && n.i2c.length) ? n.i2c : null;
}
function i2cOptions(nodeVal, sel) {
  const found = i2cListFor(nodeVal);
  const list = (found || I2C_ALLE).concat(["gpio"]);   // alltid tilbudt
  let out = "";
  for (const a of list) out += opt(a, i2cLabel(a), sel);
  if (sel && !list.includes(sel))
    out += opt(sel, i2cLabel(sel) + " (ikke funnet)", sel);
  return out;
}
let liveNodes = [];

const isSignal = t => t in SIGNALTYPER;
// EKSAKTE tester. «sporveksel» er sentralstilt og inngår i
// forriglingen; «manuellveksel» er håndstilt og står utenfor — den er
// med for å tegne panelet og for å kunne betjenes med knapp/bryter
// over nodens porter.
const isVeksel = t => t === "sporveksel";
const isManuell = t => t === "manuellveksel";
const isNoenVeksel = t => isVeksel(t) || isManuell(t);
const isSperre = t => t === "sporsperre";   // deler vekselmaskineriet
const isLaas = t => t === "samlelaas" || t === "rigel";
// Via sigKlasse(), ikke oppslag i SIGNALTYPER: da arves navne-
// fallbacken, og en håndredigert hal.json uten "klasse"-felt mister
// ikke tilleggsvalgene på raden.
const isDverg = t => sigKlasse(t) === "dvergsignal";
// Høyt skiftesignal finnes i to varianter (skiftesignal1 fjernstyrt,
// skiftesignal2 uten fjernstyring). UI-et skal behandle dem likt, så
// sjekk KLASSEN — aldri typenavnet. Da følger en eventuell tredje
// variant med av seg selv.
const isSkift = t => sigKlasse(t) === "skiftesignal";


// Attributt-escaping. Litra, notater og kallenavn er BRUKERDATA og
// settes inn i HTML-attributter via innerHTML. Uten escaping bryter
// et anførselstegn ut av attributtet — et litra som «A" onfocus="…»
// ville kjørt vilkårlig skript i konfigverktøyet. Serversiden avviser
// riktignok en del tegn i litra, men notater og kallenavn er frie, og
// en importert backup kan inneholde hva som helst.
function attr(v) {
  return String(v == null ? "" : v)
    .replace(/&/g, "&amp;").replace(/"/g, "&quot;")
    .replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function opt(v, t, sel) {
  return `<option value="${v}" ${v===sel?"selected":""}>${t}</option>`;
}
let NODER = {};   // kallenavn -> {mac}
function aliasFor(mac) {
  for (const [a, v] of Object.entries(NODER)) if (v.mac === mac) return a;
  return null;
}
// Merk: statusen står som ETT tegn, ikke som «(aldri sett)» i
// klartekst. Et nedtrekk er like bredt som sitt bredeste valg, og
// dette gjentas på hver eneste bindingslinje — teksten kostet mer
// bredde enn den var verdt. Tegnene forklares i select-ens title.
//   ⊘ = kjent node som er offline nå
//   ? = aldri sett (planlagt, eller aldri startet)
function nodeOptions(sel, allowEmpty) {
  let out = allowEmpty ? opt("", "—", sel) : "";
  const seen = new Set();
  for (const [alias, v] of Object.entries(NODER)) {
    seen.add(alias); seen.add(v.mac);
    const live = liveNodes.find(n => n.mac === v.mac);
    out += opt(alias, alias + (live ? (live.online ? "" : " ⊘") : " ?"), sel);
  }
  for (const n of liveNodes) {
    if (seen.has(n.mac)) continue;
    out += opt(n.mac, n.mac + (n.online ? "" : " ⊘"), sel);
  }
  if (sel && !out.includes(`value="${sel}"`)) out += opt(sel, sel + " ?", sel);
  return out;
}
function portCount(addr) {
  if (addr === "gpio") return GPIO_PINNER.length;
  return addr.startsWith("0x4") ? 16 : 8;
}
function portOptions(n, sel, addr) {
  let out = "";
  for (let p = 0; p < n; p++) {
    const t = (addr === "gpio") ? `${p} (${GPIO_PINNER[p]})` : String(p);
    out += opt(String(p), t, String(sel));
  }
  return out;
}
function i2cChanged(sel, prefix) {
  // Bytt portliste når brikketypen endres (PCA: 0-15, PCF: 0-7)
  const portSel = sel.closest("tr").querySelector("." + prefix + "-port");
  const n = portCount(sel.value);
  const cur = Math.min(parseInt(portSel.value || "0"), n - 1);
  portSel.innerHTML = portOptions(n, cur, sel.value);
  portMerk();
}
function nodeChanged(sel, prefix) {
  // Nytt nodevalg -> vis den nodens faktiske brikker i I2C-listen
  const tr = sel.closest("tr");
  const i2cSel = tr.querySelector("." + prefix + "-i2c");
  const cur = i2cSel.value;
  i2cSel.innerHTML = i2cOptions(sel.value, cur);
  if (!i2cSel.value) i2cSel.selectedIndex = 0;
  i2cChanged(i2cSel, prefix);
}
// sted: hva slotten er FOR — avgjør brikkeforslag og retningsfarge, så
// det synes hvor det skal velges en inngang og hvor en utgang.
function bindCells(prefix, b, t, sted) {
  // Alle bindinger starter på "—" (ingen) — bare bevisste valg lagres
  const i2cVal = b.i2c || defaultI2c(t, sted);
  const kls = bindErInngang(t, sted) ? " retn-inn" : " retn-ut";
  return `
    <td class="pc"><select class="${prefix}-node" title="Noden porten sitter på. ⊘ = offline nå, ? = aldri sett" onchange="nodeChanged(this,'${prefix}')">${nodeOptions(b.node||"", true)}</select></td>
    <td class="pc i2c${kls}"><select class="${prefix}-i2c" title="I2C-brikke: 0x40–0x43 = PCA9685 (16 utganger), 0x20–0x23 = PCF8574 (8 innganger), GPIO = nodens egne pinner" onchange="i2cChanged(this,'${prefix}')">${i2cOptions(b.node||"", i2cVal)}</select></td>
    <td class="pc port"><select class="${prefix}-port" title="port på brikken">${portOptions(portCount(i2cVal), b.port??0, i2cVal)}</select></td>`;
}
// Er dette bindingsstedet en INNGANG (noe anlegget forteller master)
// eller en UTGANG (noe master driver)? Én kilde til sannhet for både
// brikkeforslaget og fargemerkingen i tabellen — de kan ikke komme i
// utakt. NB: «lokal-» er betjening (inngang), mens
// «lokalstillerlampe» er en LAMPE; bindestreken skiller dem.
function erInngang(sted) {
  return sted.startsWith("sensor") || sted.startsWith("stiller") ||
         sted.startsWith("lokal-") || sted === "kvittering";
}
// Samme spørsmål, men med TYPEN med: «trykknapp», «bryter» og
// «inngang» binder alle via stedet «anlegg», og der er det typen som
// sier at porten er en inngang. Samme liste som serverens
// _er_inngangsbinding og masterens erInngangsType.
function bindErInngang(t, sted) {
  if (sted === "anlegg" &&
      (t === "trykknapp" || t === "bryter" || t === "inngang")) return true;
  return erInngang(sted);
}
function defaultI2c(t, sted) {
  if (bindErInngang(t, sted)) return "0x20";   // PCF8574
  if (sted.startsWith("ut-")) return "0x41";   // PCA9685, drivutgang
  return "0x40";                               // PCA9685, lamper
}
// Én FUNKSJON per linje. sted2/b2 er den andre halvdelen av funksjonen
// — normal og avvik, ute og på apparatet, ytre og indre — aldri to
// urelaterte bindinger som tilfeldigvis ble stående på samme rad.
//
// Symbolet er det SAMME som på Kabling-siden (portSymbol), så en port
// har samme tegn uansett hvilken vei man leser anlegget. Fargen er
// retningen. Har de to halvdelene ulikt symbol (sensor + lampe),
// vises begge — da er det ingen tvil om hvilken kolonne som er hva.
function bindSym(t, sted) {
  const kls = bindErInngang(t, sted) ? "retn-inn" : "retn-ut";
  return `<span class="bsym ${kls}" title="${sted}">` +
         `${portSymbol(sted, t)}</span>`;
}
function addSubRow(fnTr, sted, b, removable, sted2, b2, navn, par) {
  b = b || {};
  const t = fnTr.querySelector(".f-type").value;
  const del = removable
    ? '<button class="row-del" onclick="this.closest(\'tr\').remove()">✕</button>'
    : "";
  const tr = document.createElement("tr");
  tr.className = "subrow";
  tr.dataset.sted = sted;
  if (sted2) tr.dataset.sted2 = sted2;
  let sym = bindSym(t, sted);
  if (sted2 && portSymbol(sted2, t) !== portSymbol(sted, t))
    sym += bindSym(t, sted2);
  const lbl = `${sym}` +
              `<span class="bnavn">${navn || sted}</span>` +
              (par ? `<span class="bpar">${par}</span>` : "");
  const hoyre = sted2 ? bindCells("t", b2 || {}, t, sted2)
                      : `<td colspan="3" class="tom"></td>`;
  tr.innerHTML = `
    <td colspan="2" class="sub-label">${lbl}</td>
    ${bindCells("s", b, t, sted)}
    ${hoyre}
    <td>${del}</td>`;
  let after = fnTr;
  while (after.nextElementSibling?.classList.contains("subrow"))
    after = after.nextElementSibling;
  after.insertAdjacentElement("afterend", tr);
}
function fillHovedSel(sel) {
  // Nedtrekk over hovedsignal-litraer — kun litraen vises (etiketten
  // står utenfor select-en)
  const cur = sel.value;
  // varsler-nedtrekket: tomt valg = auto (forriglingen avleder
  // utkjørsignalet fra togveiens spor); montert: tomt = ingen
  const tom = sel.classList.contains("f-varsler") ? "auto" : "—";
  let out = `<option value="">${tom}</option>`;
  for (const tr of document.querySelectorAll("#tbl tbody tr.fnrow")) {
    const ht = tr.querySelector(".f-type").value;
    if (!erHoved(ht)) continue;
    const id = tr.querySelector(".f-id").value.trim();
    if (id) out += opt(id, id, cur);
  }
  if (cur && !out.includes(`value="${cur}"`))
    out += opt(cur, `${cur} (ukjent)`, cur);
  sel.innerHTML = out;
  sel.value = cur;
}
function egenskapSum(full) {
  const deler = [];
  for (const el of full.querySelectorAll("select,input")) {
    if (el.type === "checkbox" || el.closest("[hidden]")) continue;
    // Bruk det brukeren SER i nedtrekket, ikke den rå verdien:
    // rollen «innkjor» heter «innkjør», og «» heter «auto (høyre)».
    const v = (el.tagName === "SELECT" && el.selectedOptions[0]
                 ? el.selectedOptions[0].textContent : el.value).trim();
    if (!v || v === "—" || v.startsWith("rolle: —")) continue;
    let n = el.previousSibling, lbl = "";
    while (n && !lbl) {
      if (n.nodeType === 1 && n.classList && n.classList.contains("hint"))
        lbl = n.textContent.replace(/[:\s]+$/, "");
      n = n.previousSibling;
    }
    deler.push(lbl ? `${lbl} ${v}` : v);
  }
  const kryss = [...full.querySelectorAll("input[type=checkbox]")]
                  .filter(c => c.checked && !c.closest("[hidden]"))
                  .map(c => c.value);
  if (kryss.length) deler.push(kryss.join(", "));
  return deler.join(" · ");
}
// Egenskapslinjen til et objekt: første underrad, rett under
// identiteten. Den ligger der HELE tiden — bare skjult når objektet er
// sammenlagt — så alt som leser feltene finner dem uansett.
function attrRad(tr) {
  const n = tr.nextElementSibling;
  return (n && n.classList.contains("attrrow")) ? n : null;
}
// Et felt på objektet, uansett om det står på identitetslinjen
// (litra, type) eller på egenskapslinjen under.
// Velgeren har TO etiketter for feltet mot linjen — blokksporfelt og
// linjefelt — men rollen som LAGRES er den samme. Forskjellen er
// linjeblokk-flagget. Alt som spør «er dette et linjefelt?» må gå
// gjennom denne, ellers svarer et blokksporfelt nei.
const rolleVerdi = v => (v === "blokksporfelt") ? "linjefelt" : v;
function radRolle(tr) {
  const s = felt(tr, ".f-rolle");
  return s ? rolleVerdi(s.value) : "";
}
function felt(tr, kl) {
  return tr.querySelector(kl) || (attrRad(tr) || tr).querySelector(kl);
}
function felter(tr, kl) {
  const a = [...tr.querySelectorAll(kl)];
  const ar = attrRad(tr);
  return a.length || !ar ? a : [...ar.querySelectorAll(kl)];
}
// Objektet en kontroll hører til — kontrollen kan stå på
// egenskapslinjen, og da er closest("tr") IKKE identitetslinjen.
function eierRad(el) {
  const tr = el.closest("tr");
  return tr.classList.contains("fnrow") ? tr : radHovedrad(tr);
}
function decorateRow(tr) {
  const t = tr.querySelector(".f-type").value;
  const arad = attrRad(tr);
  const extraCell = arad.querySelector(".xfull");
  if (t === "forsignal2") {
    // Etiketten står UTENFOR select-en, så litraen alltid er synlig
    const curM = tr.dataset.montert || "";
    const curV = tr.dataset.varsler || "";
    extraCell.innerHTML =
      `<span class="hint">montert:</span> ` +
      `<select class="f-montert" title="Hovedsignal på samme mast — forsignalet slukkes når det viser stopp" onfocus="fillHovedSel(this)">` +
      opt(curM, curM || "—", curM) + `</select><span class="axsep"></span>` +
      `<span class="hint">varsler:</span> ` +
      `<select class="f-varsler" style="margin-top:2px" title="Hovedsignalet forsignalet varsler om — bildet følger det automatisk. «auto»: forriglingen avleder utkjørsignalet fra den aktive togveiens spor (krever utkjørtogveier med spor satt i tabellen). Et valgt signal brukes som reserve når avledningen ikke finner noe." onfocus="fillHovedSel(this)">` +
      opt(curV, curV || "auto", curV) + `</select>`;
  } else if (t === "hovedsignal3") {
    const cur = tr.dataset.rolle || "utkjor";
    const curL = tr.dataset.linje || "";
    extraCell.innerHTML =
      `<select class="f-rolle" title="Innkjør viser 20A (blink) i stopp, utkjør viser 20B (fast). Indre hovedsignal brukes for togveier fra togspor til togspor.">` +
      opt("innkjor", "innkjør", cur) + opt("utkjor", "utkjør", cur) +
      opt("indre", "indre (ikke i master ennå)", cur) +
      `</select><span class="axsep"></span>` +
      `<span class="hint">foran:</span> ` +
      `<select class="f-linje" style="margin-top:2px" title="Linjefeltet signalet står FORAN (i signalets kjøreretning): innkjør foran linjefeltet det står ved på vei inn, utkjør foran linjefeltet toget kjører ut på. Brukes til å avlede signalet når togveier lages fra→til." onfocus="fillLinjeSel(this)">` +
      opt(curL, curL || "—", curL) + `</select>`;
  } else if (t === "hovedsignal2") {
    const curL = tr.dataset.linje || "";
    extraCell.innerHTML =
      `<select class="f-rolle" title="Tolys utkjørsignal: viser bare 20B (stopp) og 21 (kjør redusert) — for spor der utkjøring alltid går over veksel i avvik. Alltid rolle utkjør.">` +
      opt("utkjor", "utkjør (tolys)", "utkjor") + `</select><span class="axsep"></span>` +
      `<span class="hint">foran:</span> ` +
      `<select class="f-linje" style="margin-top:2px" title="Linjefeltet signalet står foran (linjefeltet toget kjører ut på)" onfocus="fillLinjeSel(this)">` +
      opt(curL, curL || "—", curL) + `</select>`;
  } else if (isSkift(t)) {
    const curM = tr.dataset.montert || "";
    extraCell.innerHTML =
      `<span class="hint">på mast:</span> ` +
      `<select class="f-montert" title="Hovedsignalet skiftesignalet er montert med (Sokna: ZL på utkjør L, ZM på utkjør M) — brukes av panelets sporplan til plasseringen. Tom = egen mast." onfocus="fillHovedSel(this)">` +
      opt(curM, curM || "—", curM) + `</select><span class="axsep"></span>` +
      `<span class="hint" title="Vekslene det høye skiftesignalet gjelder for — «ZM gjelder for skifting over veksel 1 forbi utkjørhovedsignalene M og O». Området er vekselen, ikke linjen: én stasjonshals kan betjene flere linjefelt. Stasjonsenden utledes av vekslene, så signalet trenger ingen egen venstre/høyre.">gjelder veksel:</span><span class="axsep"></span>` +
      skiftVekselBoks(tr);
  } else if (isDverg(t)) {
    const cur = tr.dataset.montert || "";
    extraCell.innerHTML =
      `<span class="hint">på signal:</span> ` +
      `<select class="f-montert" title="Utkjørhovedsignalet dvergsignalet står på eller ved. Bildet avledes: signal 45 når utkjørtogvei fra dette signalet er sikret, signal 46 når halsen er frigitt for lokal omlegging eller det høye skiftesignalet viser 42, ellers signal 43. Stasjonsenden arves fra hovedsignalets «foran»-linjefelt." onfocus="fillHovedSel(this)">` +
      opt(cur, cur || "—", cur) + `</select>`;
  } else if (isSignal(t)) {
    extraCell.textContent = SIGNALTYPER[t].lamper + " lamper";
  } else if (t === "trykknapp") {
    const cur = tr.dataset.rolle || "";
    extraCell.innerHTML =
      `<select class="f-rolle" title="jord: oppstartsritual — etter master-boot er alle signaler sperret til denne knappen trykkes (som forbildets strømstans-prosedyre). Panel-bindingen er den røde kontrollampen, tent mens anlegget er sperret.">` +
      opt("", "rolle: —", cur) + opt("jord", "jord (oppstart)", cur) +
      `</select>`;
  } else if (t === "amperemeter") {
    const u = tr.dataset.utslag || "100";
    extraCell.innerHTML =
      `<span class="hint">utslag:</span> ` +
      `<input class="f-utslag" type="number" min="0" max="100" ` +
      `style="max-width:60px" value="${u}" ` +
      `title="Viserutslag i % av fullt PWM-pådrag mens en veksel legger om. Instrumentet (dreiespole) kobles til PCA-kanalen i anleggsbindingen."> ` +
      `<span class="hint">%</span>`;
  } else if (t === "klokke") {
    const hk = tr.dataset.hakk || "50";
    const du = tr.dataset.duty || "50";
    extraCell.innerHTML =
      `<span class="hint" title="Én klokke gjør alle jobbene, som i forbildet: varselklokke (tog i anmarsj), vekselklokke (omlegging/ute av kontroll), togveiklokke (togveistiller holdes utslått) og signalstoppklokke — alle med 30 s spolevern per hendelse.">alle klokkefunksjonene</span><span class="axsep"></span>` +
      `<span class="hint">hakk:</span> ` +
      `<input class="f-hakk" type="number" min="10" max="250" ` +
      `style="max-width:60px" value="${hk}" ` +
      `title="Hakkfrekvensen for klokkens solenoid i Hz (standard 50). Gjelder GPIO-bindinger — solenoiden og klangbunnen har en mekanisk resonans, så prøv deg frem (f.eks. 30/40/50) til lyden bærer best. Trer i kraft ved lagring, uten ny firmware."> ` +
      `<span class="hint">Hz · duty:</span> ` +
      `<input class="f-duty" type="number" min="10" max="90" ` +
      `style="max-width:55px" value="${du}" ` +
      `title="Hvor stor del av hver hakkperiode spolen får strøm, i % (standard 50). Lavere = kaldere spole og lettere anslag, høyere = hardere anslag men mer varme — spolens snittvarme er direkte proporsjonal med duty. Kvantiseres til nærmeste 1/16. Trer i kraft ved lagring. Ringingen kappes uansett av masteren etter 30 s (spolevern); meldingslampen blinker videre til kvittering."> ` +
      `<span class="hint">%</span>`;
  } else if (t === "bryter") {
    const cur = tr.dataset.rolle || "";
    extraCell.innerHTML =
      `<select class="f-rolle" title="signalstopp: alle signaler i stopp og sperret mens bryteren står på. Frigivning: frigir sentralstilte veksler i enden for lokal omlegging (togveier over dem avvises, vekselfelt-vernet er ute av funksjon). Gjennomgangsdrift: låser stasjonen i normal for en ubetjent mellomstasjon; tog som melder seg på varselfeltet får signal gjennom hovedsporet (hvit stiller på /panel). Panel-bindingen er kontrollampen — tent når funksjonen er aktiv (gjennomgang: blink mens den venter på vilkårene).">` +
      opt("", "rolle: —", cur) +
      opt("signalstopp", "signalstopp", cur) +
      opt("lok-v", "frigivning venstre ende", cur) +
      opt("lok-h", "frigivning høyre ende", cur) +
      opt("gjennomgang", "gjennomgangsdrift", cur) +
      `</select>`;
  } else if (isNoenVeksel(t)) {
    // «ende» gjelder BARE den sentralstilte: den utledes av
    // togveitabellen, og manuellvekselen står ikke i noen togvei.
    // Tegnefeltene har begge — de er hele grunnen til at den
    // manuelle er definert i det hele tatt.
    const curSide = tr.dataset.side || "";
    const utl = isVeksel(t)
      ? utledetEnde(tr.querySelector(".f-id").value.trim()) : "";
    extraCell.innerHTML =
      (isVeksel(t)
        ? `<span class="hint" title="Stasjonsenden utledes av forriglingstabellen: vekselen hører til den enden hvis linjefelt togveiene over den når. Sett verdi her BARE for veksler ingen togvei berører (rene skifteveksler) eller som nås fra begge sider.">ende:</span> ` +
          `<select class="f-side">` +
          opt("", utl ? `auto (${utl === "v" ? "venstre" : "høyre"})`
                      : "auto (ukjent)", curSide) +
          opt("v", "venstre (overstyrt)", curSide) +
          opt("h", "høyre (overstyrt)", curSide) + `</select>`
        : `<span class="hint" title="Manuellvekselen står utenfor forriglingen: ingen ende, ingen togvei, ingen Lok-frigivning. Den er med for å tegne sporplanen, og kan betjenes med knapp eller bryter over nodens porter. Sikres i en togvei med samlelås eller rigel.">håndstilt — utenfor forriglingen</span>`) +
      // Sporplanens portmodell: spissen + hvor greinene fører. KUN
      // tegning — master leser ingen av feltene, så de ligger skjult
      // bak «tegning»-lenka (ikke alle vil ha et digitalt panel).
      `<span class="axsep"></span><a class="tegnvis" onclick="visTegn(this)" title="Felter som KUN styrer tegningen av sporplanen — masteren leser dem ikke. Trengs ikke uten digitalt panel.">tegning ▸</a>` +
      `<span class="tegnfelt" hidden> ` +
      `<span class="hint" title="Sporplanens portmodell — bare for tegningen, masteren leser det ikke. Spiss: enden tungespissen peker mot. +→/−→: sporet eller vekselen pluss-/minusgreina fører til (skriv «veksel 5» når den går rett i en annen veksel). st→: der stammen går videre i en kjede. Tomt = utledes av togveitabellen der det går.">spiss:</span> ` +
      `<select class="f-spiss">` +
      opt("", "—", tr.dataset.spiss) +
      opt("v", "venstre", tr.dataset.spiss) +
      opt("h", "høyre", tr.dataset.spiss) + `</select>` +
      ` <span class="hint">+→</span><select class="f-plusstil" onfocus="fillTopoSel(this)">` +
      opt(tr.dataset.plusstil, tr.dataset.plusstil || "—",
          tr.dataset.plusstil) + `</select>` +
      ` <span class="hint">−→</span><select class="f-minustil" onfocus="fillTopoSel(this)">` +
      opt(tr.dataset.minustil, tr.dataset.minustil || "—",
          tr.dataset.minustil) + `</select>` +
      ` <span class="hint">st→</span><select class="f-spisstil" onfocus="fillTopoSel(this)">` +
      opt(tr.dataset.spisstil, tr.dataset.spisstil || "—",
          tr.dataset.spisstil) + `</select>` +
      ` <span class="hint" title="Hvilket ben som er det FYSISK krumme (tegningen kan ikke utlede det): standard er at minusgreina bøyer av og fortsetter utover; «stammen» betyr at pluss- og minusgreina ligger i linje og stammen bøyer av — som veksel 11, der 6 og 3 ligger rett gjennom og det krumme benet går ned mot veksel 4.">krumt:</span>` +
      `<select class="f-avvikben">` +
      opt("", "minus (std)", tr.dataset.avvikben) +
      opt("spiss", "stammen", tr.dataset.avvikben) +
      opt("pluss", "pluss", tr.dataset.avvikben) + `</select></span>`;
  } else if (isLaas(t)) {
    const navn = tr.dataset.navn || "";
    const laasTip = t === "samlelaas"
      ? "Objektene nøkkelen låser (kontrollås/samlelås): så lenge låsen er SPERRET (nøkkelen står i kontroll) avvises all omlegging av disse — stiller, trykknapp og MQTT. Frigitt lås eller nøkkel ute sperrer til gjengjeld togveiene i virkeområdet (tosidig forrigling)."
      : "Objektene rigelen låser direkte (veksler og sporsperrer): sperret rigel avviser all omlegging, og togveiene i virkeområdet krever rigelen sperret. Tilbaketaking gir 10 s etterløp og fullføres først når alle objektene ligger i normal igjen (motordrevne modellobjekter rekker tilbake). Som i forbildet forholder anlegget seg bare til NØKLENES/rigelens status — stillingssensorer på låste objekter trengs ikke.";
    extraCell.innerHTML =
      `<span class="hint">navn:</span> ` +
      `<input class="f-navn" style="max-width:90px" value="${attr(navn)}" ` +
      `placeholder="${t === "samlelaas" ? "S.LÅS I" : "Ri. Sp.II/3"}" ` +
      `title="Visningsnavn med forbildets skrivemåte — vises i panelet og UI-et. Selve litraen (${t === "samlelaas" ? "S1" : "RI1"}) brukes i MQTT-temaene."><span class="axsep"></span>` +
      `<span class="hint" title="${laasTip}">omfatter:</span><span class="axsep"></span>` +
      skiftVekselBoks(tr, true) + `<span class="axsep"></span>` +
      `<span class="hint">+ utenfor anlegget:</span> ` +
      `<input class="f-omfrit" style="max-width:110px" ` +
      `value="${attr(utenforAnlegget(tr).join(", "))}" ` +
      `placeholder="f.eks. V12" ` +
      `title="Objekter låsen omfatter som IKKE er definert i anlegget: helt manuelle veksler/sperrer, eller slike som drives elektrisk av eget utstyr utenfor systemet. Anlegget ser da bare låsen — at objektene ligger riktig før sperring er operatørens ansvar, som med kontrollåsnøklene i forbildet. Kommaseparert liste; vises i panelet."><span class="axsep"></span>` +
      `<span class="hint" title="Hvilke togveier låsen sperrer står i TOGVEITABELLEN: hver togvei lister låsegruppene den krever sperret. Én kilde — låsen sier hva den holder, togveien sier hva den trenger.">togvei-kravet settes i forriglingstabellen</span>`;
  } else if (isSperre(t)) {
    extraCell.innerHTML =
      `<span class="hint" title="Sporsperre: normalstillingen er PÅLAGT — det er dekningen togveiene krever. Deler vekselmaskineriet: valgfrie drivutganger for motordrevet modellsperre, valgfrie sensorer (pålagt-kontroll — uten dem antas stillingen), lokal stiller. Omlegging gates av samlelås/rigel som eier sperren. Symbol på planen: skråstrek over sporet.">normalstilling pålagt (dekning)</span>` +
      `<span class="axsep"></span><a class="tegnvis" onclick="visTegn(this)" title="Felter som KUN styrer tegningen av sporplanen — masteren leser dem ikke. Trengs ikke uten digitalt panel.">tegning ▸</a>` +
      `<span class="tegnfelt" hidden> ` +
      `<span class="hint" title="Sporplanen: sporet eller forbindelsen skråstreken tegnes på — et sporfelt-litra, eller «veksel N» når sperren ligger på forbindelsen fra den vekselens stamme. Kun tegning; masteren leser det ikke.">ligger i:</span> ` +
      `<select class="f-liggeri" onfocus="fillTopoSel(this)">` +
      opt(tr.dataset.liggeri, tr.dataset.liggeri || "—",
          tr.dataset.liggeri) + `</select></span>`;
  } else if (t === "sporfelt") {
    const cur = tr.dataset.rolle || "";
    const curSide = tr.dataset.side || "";
    // Rollen står i TYPE-kolonnen (se typeCelle) — den er det som
    // skiller sporfeltene fra hverandre, og gruppen har bare én type.
    extraCell.innerHTML =
      (cur === "varselfelt" ? `` :
       `<button class="mini" onclick="addSubRow(eierRad(this),'sensor',null,true,null,null,'ekstra sporfelt')">+ sporfelt</button>`) +
      (cur === "linjefelt"
        ? `<span class="axsep"></span><span class="hint">ende:</span> ` +
          `<select class="f-side" title="Hvilken stasjonsende linjefeltet ligger i — togveistillerne bruker dette til å skille innkjør (dytt inn mot stasjonen) fra utkjør (dytt ut mot linjen)">` +
          opt("", "—", curSide) + opt("v", "venstre", curSide) +
          opt("h", "høyre", curSide) + `</select>`
        : cur === "varselfelt"
        ? `<span class="axsep"></span><span class="hint">linjefelt:</span> ` +
          `<select class="f-linje" title="Linjefeltet varselfeltet er koblet til — varslet gjelder den siden (siden arves fra linjefeltet)" onfocus="fillLinjeSel(this)">` +
          opt(tr.dataset.linje || "", tr.dataset.linje || "—",
              tr.dataset.linje || "") + `</select>`
        : ``);
  } else {
    extraCell.textContent = "";
  }
  // Kompakt sammendrag til den sammenlagte raden. Bygges av cellen
  // SELV — etikett (.hint) pluss verdien på kontrollen etter den — så
  // den følger med av seg selv når en type får nye felt. Skjulte
  // felter (tegnefeltene) utelates; de hører til utfoldet visning.
  const sum = tr.querySelector(".xsum");
  if (sum) sum.textContent = egenskapSum(extraCell);
  // Typer uten egenskaper skal ikke få en tom linje å folde ut.
  arad.dataset.tom = extraCell.innerHTML ? "" : "1";
}
// Typevelgeren. Sporvekselgruppen har bare TO typer, og de skiller
// seg i én egenskap: er vekselen sentralstilt eller ikke. Et
// avkryssingsfelt sier det rett ut; et nedtrekk med «sporveksel» og
// «manuellveksel» tvinger leseren til å huske hvilket av de to ordene
// som betyr hva.
//
// Nedtrekket blir stående SKJULT som verdibærer: «.f-type» er typen,
// og et tjuetalls steder leser den — collect, portKart, decorateRow,
// skiftVekselBoks, sporplanen. Avkryssingen styrer den, den erstatter
// den ikke.
const erVekselgruppe = t => GRUPPER[gruppeIdx(t)].typer.length === 2 &&
                            GRUPPER[gruppeIdx(t)].typer.includes("sporveksel");
// Rollevelgeren for sporfelt. Den bor i TYPE-kolonnen: gruppen har
// bare én type, så nedtrekket der hadde ett valg og sa ingenting.
// Rollen er det som faktisk skiller sporfeltene — togspor, linjefelt,
// varselfelt — og hører derfor hjemme på identitetslinjen.
// Feltet mot nabolinjen har TO betegnelser, og forskjellen er reell:
// har strekningen linjeblokk, er feltet et BLOKKSPORFELT — lærebokas
// eget ord («Arbeid på signalanlegg 1» s. 65 og 105–109: «nærmeste
// blokksporfelt blir belagt»). Uten linjeblokk finnes ingen
// blokkstrekning å være sporfelt for; strekningen kjøres på
// togmelding, og feltet er bare linjefeltet.
//
// Derfor ÉN velger for begge: rollen er den samme («linjefelt»), og
// valget setter linjeblokk-flagget. To kontroller for det samme
// faktum ville før eller siden sagt hver sin ting — og flagget er
// ikke pynt, det avgjør om innkjørtogveien krever sistevognskontroll.
//
// Grindvoll er fjernstyrt med linjeblokk: blokksporfelt. Sokna kjører
// togmelding i begge ender: linjefelt.
function rolleVelger(rolle, lblokk) {
  const valgt = rolle === "linjefelt"
    ? (lblokk ? "blokksporfelt" : "linjefelt") : rolle;
  return `<select class="f-rolle" onchange="rolleChanged(this)" ` +
    `title="Hva sporavsnittet ER, og dermed hva forriglingen gjør med ` +
    `det. vekselfelt: de interne avsnittene i halsen, mellom vekslene — ` +
    `de har ingen togvei som ender i dem, men vernes mot omlegging ` +
    `under tog. togspor: stasjonsspor der tog står, med togveistiller. ` +
    `blokksporfelt: avsnittet mot nabolinjen når strekningen har ` +
    `LINJEBLOKK — blokka gir automatisk kontroll av at hele toget er ` +
    `kommet inn. linjefelt: samme avsnitt der strekningen kjøres på ` +
    `TOGMELDING — da blir innkjørtogveien stående låst til txp har ` +
    `gjort sistevognskontroll og kvittert på den sorte knappen. ` +
    `varselfelt: kort avsnitt ute på linjen utenfor forsignalet — ` +
    `varselklokken ringer for tog i anmarsj. spor: utenfor anlegget, ` +
    `tegnes på sporplanen men har ingen lampe og ingen forrigling.">` +
    // Tom rolle ER vekselfeltet — det er ingen «ikke valgt», og
    // etiketten skal si hva feltet er, ikke at noe mangler.
    opt("", "vekselfelt", valgt) + opt("togspor", "togspor", valgt) +
    opt("blokksporfelt", "blokksporfelt", valgt) +
    opt("linjefelt", "linjefelt", valgt) +
    opt("varselfelt", "varselfelt", valgt) +
    opt("spor", "spor", valgt) + `</select>`;
}
function typeCelle(t, rolle, lblokk) {
  const typer = GRUPPER[gruppeIdx(t)].typer;
  const valg = typer.includes(t) ? typer : [t].concat(typer);
  // Nedtrekket skjules når det ikke er noe å velge — én type i
  // gruppen — eller når valget uttrykkes bedre på annet vis, som
  // vekslenes «sentralstilt». Det blir stående som VERDIBÆRER: et
  // tjuetalls steder leser «.f-type».
  const skjul = typer.length === 1 || erVekselgruppe(t);
  const sel = `<select class="f-type"${skjul ? " hidden" : ""}` +
    ` onchange="typeChanged(this)">${valg.map(x => opt(x, x, t)).join("")}` +
    `</select>`;
  // Plassen brukes til noe som sier noe: sporfeltets rolle, eller
  // vekselens sentralstilt-avkryssing.
  if (t === "sporfelt")
    return sel + rolleVelger(rolle || "", lblokk);
  if (!erVekselgruppe(t)) return sel;
  return sel + `<label class="sentralvalg" title="Sentralstilt veksel: ` +
    `legges om fra stillerapparatet og inngår i forriglingen. Uten ` +
    `avkryssing er den håndstilt — den står utenfor togveiene og ` +
    `sikres med samlelås eller rigel.">` +
    `<input type="checkbox" class="f-sentral" ` +
    `${isVeksel(t) ? "checked" : ""} onchange="sentralChanged(this)">` +
    `sentralstilt</label>`;
}
// Avkryssingen bytter type. De to vekseltypene deler bindingssteder —
// drivutgang og lokalbetjening finnes på begge — så det som fortsatt
// har en plass bæres over. Ellers ville et uhell på avkryssingen
// slette kablingen, og en avkryssing er lettere å treffe ved et uhell
// enn et valg i et nedtrekk.
function sentralChanged(cb) {
  const tr = cb.closest("tr");
  const sel = tr.querySelector(".f-type");
  sel.value = cb.checked ? "sporveksel" : "manuellveksel";
  const beholdt = [];
  let n = tr.nextElementSibling;
  while (n && n.classList.contains("subrow")) {
    const neste = n.nextElementSibling;
    if (!n.classList.contains("attrrow")) {
      beholdt.push(...lesSubrad(n));
      n.remove();
    }
    n = neste;
  }
  byggSubrader(tr, sel.value, beholdt);
  decorateRow(tr);
  grpOppdater();
}
function addRow(f, foerEl) {
  f = f || {id:"", type:"hovedsignal3", bindinger:[]};
  const t = f.type, binds = f.bindinger || [];
  const tr = document.createElement("tr");
  tr.className = "fnrow";
  tr.dataset.orgId = f.id || "";   // original-litra: omdøping spores
  tr.dataset.montert = f.montert_med || "";
  tr.dataset.varsler = f.varsler_om || "";
  tr.dataset.rolle = f.rolle || "";
  tr.dataset.side = f.side || "";
  // linjeblokk: standard PÅ (dagens oppførsel). Bare eksplisitt
  // false gir "0" — mangler feltet, er strekningen blokkstyrt.
  tr.dataset.lblokk = (f.linjeblokk === false) ? "0" : "1";
  tr.dataset.linje = f.linjefelt || "";
  tr.dataset.utslag = (f.utslag !== undefined) ? String(f.utslag) : "";
  tr.dataset.hakk = (f.hakk_hz !== undefined) ? String(f.hakk_hz) : "";
  tr.dataset.duty = (f.hakk_duty !== undefined) ? String(f.hakk_duty) : "";
  // Samlelåsens «omfatter» gjenbruker skiftv-sporet (samme form, og
  // et objekt er aldri både skiftesignal og samlelås); «navn» er
  // låsegruppens eget.
  tr.dataset.skiftv = JSON.stringify(f.skift_sporveksler ||
                                     f.omfatter || []);
  tr.dataset.navn = f.navn || "";
  tr.dataset.rid = ++RAD_TELLER;   // stabil id: litra kan endres mens man skriver
  // Sporplan-topologien (kun tegning; master ignorerer feltene)
  tr.dataset.spiss = f.spiss || "";
  tr.dataset.plusstil = f.pluss_til || "";
  tr.dataset.minustil = f.minus_til || "";
  tr.dataset.spisstil = f.spiss_til || "";
  tr.dataset.avvikben = f.avvik_ben || "";
  tr.dataset.liggeri = f.ligger_i || "";
  tr.innerHTML = `
    <td class="litra"><span class="rad-pil" onclick="radToggle(this)"
              title="Vis eller skjul portene for dette objektet">▸</span>` +
      `<input class="f-id" maxlength="6" value="${attr(f.id)}" ` +
      `placeholder="A" title="Litra — maks 6 tegn. Kort litra er ` +
      `forbildets egen skrivemåte (A, 01, ZM, SpIII), og det er det ` +
      `som får plass i portrutenettet og på panelet."></td>
    <td>${typeCelle(t, f.rolle || "", f.linjeblokk !== false)}</td>
    <td class="bindsum" colspan="6" onclick="radToggle(this)"
        ><span class="xsum"></span><span class="portsum"></span></td>
    <td><button class="row-del" onclick="delFn(this)">✕</button></td>`;
  const tb = document.querySelector("#tbl tbody");
  if (foerEl) tb.insertBefore(tr, foerEl);
  else tb.appendChild(tr);
  // Alt som kan REDIGERES ligger på egne linjer under: først
  // egenskapene, så bindingene. Identitetslinjen viser bare hva
  // objektet er og hvor mye av kablingen som er på plass — den skifter
  // aldri form, uansett om objektet er foldet ut eller ikke.
  nyLuftRad(tr);          // først: alt annet settes inn foran den
  nyAttrRad(tr);
  byggSubrader(tr, t, binds);
  decorateRow(tr);
  return tr;
}
// ---- gruppeoverskrifter i HAL-tabellen ----
function grpHeaderRow(gi) {
  const tr = document.createElement("tr");
  tr.className = "grphead";
  tr.dataset.grp = gi;
  // Kolonneteksten hører hjemme HER, ikke i tabellhodet: hva de to
  // portkolonnene er, avhenger av objektgruppen — normal og avvik for
  // veksler, pålagt og avlagt for sperrer. Der parene varierer fra rad
  // til rad står det tomt, og radetiketten sier det i stedet.
  const G = GRUPPER[gi];
  const kap = tekst => tekst
    ? `<td colspan="3" class="grpkol">${tekst}</td>`
    : `<td colspan="3"></td>`;
  tr.innerHTML = `<td colspan="2">
    <span style="cursor:pointer" onclick="grpToggle(${gi})">
      <span class="grp-pil">▾</span> <b>${G.navn}</b>
      <span class="hint grp-tall"></span></span>
    <button class="mini" style="margin-left:10px"
            onclick="grpAdd(${gi})">+ ny</button></td>
    ${kap(G.venstre)}${kap(G.hoyre)}
    <td></td>`;
  return tr;
}
function grpHeader(gi) {
  return document.querySelector('#tbl tbody tr.grphead[data-grp="' + gi + '"]');
}
function grpAdd(gi) {
  COLLAPSED.delete(gi);                     // vis gruppen det legges til i
  addRow({id:"", type: GRUPPER[gi].typer[0], bindinger:[]},
         grpHeader(gi + 1));                // null = nederst (siste gruppe)
  grpOppdater();
}
function grpToggle(gi) {
  COLLAPSED.has(gi) ? COLLAPSED.delete(gi) : COLLAPSED.add(gi);
  grpOppdater();
}
// Filter på Objekter-fanen: en hovedrad matcher hvis litra, type
// eller et bundet nodenavn inneholder søkestrengen; underradene
// følger hovedraden sin. Tomt felt viser alt. Selve vis/skjul eies
// av grpOppdater (som også håndterer sammenlagte grupper) — filteret
// er bare et ekstra kriterium der.
let HALFILTER = "";
function halFilter(q) {
  HALFILTER = (q || "").trim().toLowerCase();
  grpOppdater();
}
// Er noen bindingsplass på DENNE raden satt? Deaktiverte plasser
// (panelkolonnen der den ikke gjelder) teller ikke med — de kan
// uansett ikke bindes.
// ---- portkollisjoner, LEVENDE mens man redigerer ----
// Serversiden (_port_konflikter) kjenner reglene og avviser lagring,
// men da har man alt gjort arbeidet. Her regnes de ut av det som står
// i feltene NÅ, så en kollisjon vises i det den oppstår.
//
// Reglene er serversidens: inngang+inngang er LOVLIG (én knapp kan
// betjene flere funksjoner); inngang+utgang og utgang+utgang er alltid
// feil. Et signal opptar «lamper» påfølgende porter fra bindingsporten.
function radHovedrad(tr) {
  if (!tr.classList.contains("subrow")) return null;
  let n = tr.previousElementSibling;
  while (n && n.classList.contains("subrow")) n = n.previousElementSibling;
  return n && n.classList.contains("fnrow") ? n : null;
}
function portKart() {
  const kart = new Map();   // "node|i2c|port" -> [{...}]
  for (const tr of document.querySelectorAll("#tbl tbody tr")) {
    const fn = tr.classList.contains("fnrow") ? tr : radHovedrad(tr);
    if (!fn) continue;
    const type = fn.querySelector(".f-type").value;
    const st = SIGNALTYPER[type];
    for (const pre of ["s", "t"]) {
      const nd = tr.querySelector("." + pre + "-node");
      if (!nd || nd.disabled || !nd.value) continue;
      const i2c = tr.querySelector("." + pre + "-i2c").value;
      const pc = tr.querySelector("." + pre + "-port");
      const port = parseInt(pc.value) || 0;
      const sted = pre === "s" ? (tr.dataset.sted || "")
                               : (tr.dataset.sted2 || "");
      const n = (st && (sted === "anlegg" || sted === "panel"))
                  ? (st.lamper || 1) : 1;
      const inn = bindErInngang(type, sted);
      for (let k = 0; k < n; k++) {
        const nkl = nd.value + "|" + i2c + "|" + (port + k);
        if (!kart.has(nkl)) kart.set(nkl, []);
        kart.get(nkl).push({tr, celle: pc, sted, inn,
                            litra: fn.querySelector(".f-id").value});
      }
    }
  }
  return kart;
}
function portMerk() {
  for (const e of document.querySelectorAll("#tbl .portfeil"))
    e.classList.remove("portfeil");
  for (const e of document.querySelectorAll("#tbl .radfeil")) e.remove();
  const feilPaaRad = new Map();
  for (const [nkl, liste] of portKart()) {
    if (liste.length < 2 || liste.every(x => x.inn)) continue;
    const delt = nkl.split("|");
    for (const x of liste) {
      if (x.celle) x.celle.classList.add("portfeil");
      const fn = x.tr.classList.contains("fnrow") ? x.tr : radHovedrad(x.tr);
      const andre = liste.filter(y => y !== x)
        .map(y => y.litra + " (" + y.sted + ")").join(", ");
      if (fn && !feilPaaRad.has(fn))
        feilPaaRad.set(fn, "port " + delt[2] + " på " + delt[1] +
                           " deles med " + andre);
    }
  }
  for (const [fn, tekst] of feilPaaRad) {
    const sum = fn.querySelector(".bindsum");
    if (!sum) continue;
    const m = document.createElement("span");
    m.className = "radfeil";
    m.textContent = "  \u26a0 " + tekst;
    sum.appendChild(m);
  }
  return feilPaaRad.size;
}
function radPorter(tr) {
  let tot = 0, satt = 0;
  for (const sel of tr.querySelectorAll('select[class$="-node"]')) {
    if (sel.disabled) continue;
    tot++;
    if (sel.value) satt++;
  }
  return {tot, satt};
}
// Portsammendrag for et helt objekt: hovedraden pluss underradene.
function radSumTotal(tr) {
  let t = radPorter(tr);
  let n = tr.nextElementSibling;
  while (n && n.classList.contains("subrow")) {
    const p = radPorter(n);
    t = {tot: t.tot + p.tot, satt: t.satt + p.satt};
    n = n.nextElementSibling;
  }
  return t;
}
function radToggle(el) {
  const tr = el.closest("tr");
  const rid = tr.dataset.rid;
  RADAAPEN.has(rid) ? RADAAPEN.delete(rid) : RADAAPEN.add(rid);
  grpOppdater();
}
function halBareBundne(pa) { BARE_BUNDNE = !!pa; grpOppdater(); }
function radAlle(aapen) {
  RADAAPEN.clear();
  if (aapen)
    for (const tr of document.querySelectorAll("#tbl tbody tr.fnrow"))
      RADAAPEN.add(tr.dataset.rid);
  grpOppdater();
}

// ÉN funksjon regner ut synligheten fra ALLE tilstandene — sammenlagt
// gruppe, sammenlagt rad, tekstfilter og bare-bundne. Skrus display
// på ad hoc fra flere steder, ender de før eller siden i konflikt.
function grpOppdater() {
  let gi = -1;
  const tall = {};
  let radMatch = true;     // gjelder hovedraden OG underradene dens
  let radVist = true;      // hovedraden er synlig
  let radAapen = false;    // ... og utfoldet
  for (const tr of document.querySelectorAll("#tbl tbody tr")) {
    if (tr.classList.contains("grphead")) {
      gi = parseInt(tr.dataset.grp);
      tr.querySelector(".grp-pil").textContent =
        COLLAPSED.has(gi) ? "▸" : "▾";
      tr.style.display = "";
      continue;
    }
    if (tr.classList.contains("fnrow")) {
      tall[gi] = (tall[gi] || 0) + 1;
      radMatch = !HALFILTER ||
        [...tr.querySelectorAll("input,select")]
          .map(e => (e.value || "")).join(" ").toLowerCase()
          .includes(HALFILTER);
      // Med «bare bundne» skjules objekter uten en eneste binding —
      // hovedradens egne OG underradenes, som telles i sammendraget.
      const sum = radSumTotal(tr);
      radAapen = RADAAPEN.has(tr.dataset.rid);
      radVist = !COLLAPSED.has(gi) && radMatch &&
                (!BARE_BUNDNE || sum.satt > 0);
      tr.style.display = radVist ? "" : "none";
      // Sammendrag i stedet for portceller når raden er sammenlagt
      const pil = tr.querySelector(".rad-pil");
      if (pil) pil.textContent = radAapen ? "▾" : "▸";
      // Hovedraden viser det SAMME enten objektet er foldet ut eller
      // ikke — den skal ikke skifte form under fingeren på den som
      // klikker. Portene ligger på underradene.
      const ps = tr.querySelector(".portsum");
      if (ps) {
        ps.textContent = sum.tot
          ? `${sum.satt} av ${sum.tot} porter bundet`
          : "ingen porter";
        ps.className = "portsum" + (sum.satt ? " harbind" : "");
      }
      continue;
    }
    // Luftraden hører til objektet som helhet: den skal stå der
    // objektet vises, foldet ut eller ikke.
    if (tr.classList.contains("objluft")) {
      tr.style.display = radVist ? "" : "none";
      continue;
    }
    // underrad: synlig bare når hovedraden er det OG utfoldet
    let vis = radVist && radAapen;
    // Egenskapslinjen er ikke en portlinje: den skjules bare når typen
    // ikke HAR egenskaper, og filtreres ikke bort av «bare bundne».
    if (tr.classList.contains("attrrow")) vis = vis && tr.dataset.tom !== "1";
    else if (vis && BARE_BUNDNE) vis = radPorter(tr).satt > 0;
    tr.style.display = vis ? "" : "none";
  }
  GRUPPER.forEach((g, i) => {
    const h = grpHeader(i);
    if (h) h.querySelector(".grp-tall").textContent = "(" + (tall[i] || 0) + ")";
  });
  objektRammer();
  portMerk();
}
// Hvert objekt tegnes som ÉN ramme rundt identitetslinjen og linjene
// under — samme form som en celle på Kabling-siden. Rammen må lukkes
// på den siste SYNLIGE linjen: filteret, «bare bundne» og sammenlagte
// objekter endrer hvilken det er, så den kan ikke merkes én gang ved
// bygging. (Erstattet grenglyfene — de sa det samme som rammen sier
// tydeligere, og gjorde hver linje 15 px smalere.)
function objektRammer() {
  const rader = [...document.querySelectorAll("#tbl tbody tr")]
                  .filter(tr => tr.style.display !== "none");
  for (const tr of rader) tr.classList.remove("obj-sist");
  for (let i = 0; i < rader.length; i++) {
    if (!rader[i].classList.contains("fnrow")) continue;
    let j = i;
    while (j + 1 < rader.length && rader[j + 1].classList.contains("subrow"))
      j++;
    rader[j].classList.add("obj-sist");
  }
}

// Tegnefeltene (sporplanens portmodell m.m.) gjelder KUN tegningen av
// planen — masteren leser dem ikke, og ikke alle vil ha et digitalt
// panel. De ligger derfor skjult bak en «tegning»-lenke. Feltene står
// i DOM-en hele tiden, så collect() leser dem uansett.
function visTegn(a) {
  const sp = a.nextElementSibling;
  sp.hidden = !sp.hidden;
  a.textContent = sp.hidden ? "tegning ▸" : "tegning ▾";
}

function rolleChanged(sel) {   // sporfelt-rolle: vis/skjul tilleggsvalg
  const tr = eierRad(sel);
  tr.dataset.rolle = rolleVerdi(sel.value);
  // Valget ER linjeblokk-flagget: blokksporfelt = med blokk,
  // linjefelt = togmelding. Andre roller rører det ikke.
  if (sel.value === "blokksporfelt") tr.dataset.lblokk = "1";
  else if (sel.value === "linjefelt") tr.dataset.lblokk = "0";
  const side = felt(tr, ".f-side");
  tr.dataset.side = side ? side.value : (tr.dataset.side || "");
  const lin = felt(tr, ".f-linje");
  tr.dataset.linje = lin ? lin.value : (tr.dataset.linje || "");
  // Avkryssingen tegnes på nytt fra datasettet, så en ulagret
  // endring må speiles hit først — ellers spretter den tilbake
  // hver gang rollen endres.
  // Rollen bestemmer hvilke bindingslinjer feltet HAR — meldefeltet
  // har ytre/indre sensorer, togsporet har togveistillere. Les det som
  // står, riv alle linjene, og bygg dem på nytt fra verdiene: da
  // overlever alt som fortsatt har en plass. Det som ikke har det
  // (togveistilleren når feltet blir meldefelt) faller bort — som før,
  // men nå uten å kunne havne i feil slot.
  const beholdt = [];
  let n = tr.nextElementSibling;
  while (n && n.classList.contains("subrow")) {
    const neste = n.nextElementSibling;
    if (!n.classList.contains("attrrow")) {
      beholdt.push(...lesSubrad(n));
      n.remove();
    }
    n = neste;
  }
  byggSubrader(tr, "sporfelt", beholdt);
  decorateRow(tr);
}
// Speiler masterens utledning i UI-et: vekselen hører til den enden
// hvis linjefelt togveiene over den når. TOGVEIER er tabellen slik
// den ble lastet — utledningen viser altså LAGRET tilstand, ikke
// ulagrede endringer i Forrigling-fanen.
function utledetEnde(vLitra) {
  if (!vLitra) return "";
  const side = {};   // linjefelt-litra -> v/h fra Objekter-tabellen
  for (const tr of document.querySelectorAll("#tbl tbody tr.fnrow")) {
    if (tr.querySelector(".f-type").value !== "sporfelt") continue;
    if (radRolle(tr) !== "linjefelt") continue;
    const s = felt(tr, ".f-side");
    const id = tr.querySelector(".f-id").value.trim();
    if (id && s && s.value) side[id] = s.value;
  }
  let v = false, h = false;
  for (const tv of (TOGVEIER || [])) {
    if (!(tv.sporveksler || []).some(x => x.sporveksel === vLitra)) continue;
    for (const f of (tv.frie || [])) {
      if (side[f] === "v") v = true;
      else if (side[f] === "h") h = true;
    }
  }
  return (v && !h) ? "v" : (h && !v) ? "h" : "";
}
function fillLinjeSel(sel) {   // nedtrekk over linjefelt-litraer
  const cur = sel.value;
  let out = `<option value="">—</option>`;
  for (const tr of document.querySelectorAll("#tbl tbody tr.fnrow")) {
    if (tr.querySelector(".f-type").value !== "sporfelt") continue;
    if (radRolle(tr) !== "linjefelt") continue;
    const id = tr.querySelector(".f-id").value.trim();
    if (id) out += opt(id, id, cur);
  }
  if (cur && !out.includes(`value="${cur}"`))
    out += opt(cur, cur + " (ukjent)", cur);
  sel.innerHTML = out;
  sel.value = cur;
}
// Vekselvelger for høyt skiftesignal: avkryssing over vekslene i
// anlegget. Området er vekslene signalet GJELDER FOR (A-sirk. 3) —
// stasjonsenden følger med gjennom vekselens utledede ende, så
// skiltet trenger ingen egen venstre/høyre.
function skiftVekselBoks(tr, gruppe) {
  // To ulike utvalg, av samme grunn som i forbildet:
  //
  //   gruppe=false — HØYT SKIFTESIGNAL. Bare SENTRALSTILTE veksler.
  //     Signalet følger vekslene sine: det viser 41 så lenge en av dem
  //     er i bevegelse eller uten kontroll, og 42 igjen når stillingen
  //     er bekreftet. En lokalstilt veksel har ingen kontroll å gi —
  //     den blir stående V_UKJENT — så tas den med, låses signalet i
  //     41 for alltid og kommer aldri til 42.
  //
  //   gruppe=true — SAMLELÅS/RIGEL. Motsatt: det er nettopp de
  //     lokalstilte vekslene og sporsperrene låsen finnes for.
  //     Sentralstilte tas med der de inngår i låsegruppen.
  const valgt = new Set(JSON.parse(tr.dataset.skiftv || "[]"));
  const vist = new Set();
  let out = "";
  for (const r of document.querySelectorAll("#tbl tbody tr.fnrow")) {
    const rt = r.querySelector(".f-type").value;
    const passer = gruppe ? (isNoenVeksel(rt) || isSperre(rt))
                          : isVeksel(rt);
    if (!passer) continue;
    const id = r.querySelector(".f-id").value.trim();
    if (!id) continue;
    vist.add(id);
    out += `<label style="margin-right:8px;white-space:nowrap">` +
           `<input type="checkbox" class="f-skiftv" value="${attr(id)}" ` +
           `${valgt.has(id) ? "checked" : ""}>${id}</label>`;
  }
  // Alt som ALT er valgt, men ikke hører hjemme i utvalget over, vises
  // likevel — avkrysset og merket. Uten dette ville en konfig som
  // inneholder en lokalstilt veksel på et skiftesignal bli avvist av
  // valideringen UTEN at raden ga noen måte å fjerne den på: feilen
  // ville vært synlig og uopprettelig på samme tid.
  for (const id of valgt) {
    if (vist.has(id)) continue;
    out += `<label style="margin-right:8px;white-space:nowrap;` +
           `color:var(--warn,#e0c23c)" ` +
           `title="Hører ikke hjemme her — fjern avkryssingen. ` +
           `Enten er objektet slettet, eller det er en lokalstilt ` +
           `veksel, som et høyt skiftesignal ikke kan følge.">` +
           `<input type="checkbox" class="f-skiftv" value="${attr(id)}" ` +
           `checked>${id} ⚠</label>`;
  }
  if (out) return out;
  return `<span class="hint">${gruppe
    ? "ingen veksler eller sporsperrer definert"
    : "ingen sentralstilte veksler definert"}</span>`;
}
// Omfatter-litra som IKKE finnes som objekt i tabellen: objekter
// utenfor anlegget (helt manuelle / drevet av eget utstyr). De har
// intet avkryssingsvalg og vises i fritekstfeltet i stedet.
function utenforAnlegget(tr) {
  const kjent = new Set();
  for (const r of document.querySelectorAll("#tbl tbody tr.fnrow")) {
    const rt = r.querySelector(".f-type").value;
    if (isNoenVeksel(rt) || isSperre(rt))
      kjent.add(r.querySelector(".f-id").value.trim());
  }
  return JSON.parse(tr.dataset.skiftv || "[]").filter(x => !kjent.has(x));
}
// Nedtrekk for sporplan-topologien: alle sporfelt + «veksel N» for
// hver sporveksel (litraene kolliderer på tvers av navnerommene, så
// vekselreferanser prefikses). Fylles ved fokus, som fillLinjeSel.
function fillTopoSel(sel) {
  const cur = sel.value;
  let out = `<option value="">—</option>`;
  for (const r of document.querySelectorAll("#tbl tbody tr.fnrow")) {
    const rt = r.querySelector(".f-type").value;
    const id = r.querySelector(".f-id").value.trim();
    if (!id) continue;
    if (rt === "sporfelt") out += opt(id, id, cur);
  }
  for (const r of document.querySelectorAll("#tbl tbody tr.fnrow")) {
    const rt = r.querySelector(".f-type").value;
    const id = r.querySelector(".f-id").value.trim();
    if (!id) continue;
    if (isNoenVeksel(rt))   // begge tegnes på sporplanen
      out += opt(`veksel ${id}`, `veksel ${id}`, cur);
  }
  if (cur && !out.includes(`value="${cur}"`))
    out += opt(cur, cur + " (ukjent)", cur);
  sel.innerHTML = out;
  sel.value = cur;
}
// Bindingene som står på ÉN bindingslinje — den ene eller begge
// halvdelene. Både lagringen (collect) og rollebytte på et sporfelt
// leser linjene med denne, så de kan ikke komme i utakt om formen
// endres igjen.
function lesSubrad(tr) {
  const ut = [];
  for (const [pre, nkl] of [["s", "sted"], ["t", "sted2"]]) {
    const nd = tr.querySelector("." + pre + "-node");
    if (!nd || !nd.value || !tr.dataset[nkl]) continue;
    ut.push({sted: tr.dataset[nkl], node: nd.value,
             i2c: tr.querySelector("." + pre + "-i2c").value,
             port: parseInt(tr.querySelector("." + pre + "-port").value || "0")});
  }
  return ut;
}
function typeChanged(sel) {   // brukerbytte: bygg underrader på nytt
  const tr = sel.closest("tr");
  // Vekselområdet (skiftesignal) / omfatter-listen (samlelås, rigel)
  // hører til den GAMLE typen. Ble det stående, lagret en annen type
  // en usynlig skift_sporveksler som backend avviste, uten felt å
  // rette den i.
  delete tr.dataset.skiftv;
  // Egenskapslinjen blir stående — decorateRow fyller den på nytt for
  // den nye typen. Bindingslinjene rives: en annen type har andre
  // bindingssteder, og et sted som ikke finnes lenger skal ikke bæres
  // videre i det stille.
  let n = tr.nextElementSibling;
  while (n && n.classList.contains("subrow")) {
    const neste = n.nextElementSibling;
    if (!n.classList.contains("attrrow")) n.remove();
    n = neste;
  }
  byggSubrader(tr, sel.value, []);
  decorateRow(tr);
}
// ---- bindingsradene per objekttype ----
// ÉN rad per FUNKSJON, med de to halvdelene som faktisk hører sammen:
// normal og avvik, ute og på apparatet, ytre og indre.
//
// Før lå den ene bindingen på identitetslinjen og resten ble paret to
// og to i den rekkefølgen de tilfeldigvis var skrevet — vekselens
// drivutgang var delt over to rader, og ut-avvik delte linje med en
// stiller den ikke hadde noe med å gjøre. Derfor står tabellen HER,
// som data: paringen er en egenskap ved objekttypen, ikke ved
// rekkefølgen i en funksjon.
//
// «par» navngir halvdelene der de ikke er gruppens (normal/avvik);
// da står det i radetiketten i stedet for å måtte gjettes.
function bindingsrader(t, rolle) {
  if (isSkift(t))
    return [{navn: "signallamper", par: "ute · apparat",
             a: "anlegg", b: "panel"},
            {navn: "stiller", a: "stiller"},
            {navn: "middelkontrollampe", a: "middelkontrollampe"}];
  if (isSignal(t))
    return [{navn: "signallamper", par: "ute · apparat",
             a: "anlegg", b: "panel"}];
  if (isVeksel(t))
    return [{navn: "drivutgang", a: "ut-normal", b: "ut-avvik"},
            {navn: "stillingssensor", a: "sensor-normal",
             b: "sensor-avvik"},
            {navn: "kontrollampe", a: "panel-normal", b: "panel-avvik"},
            {navn: "apparatstiller", a: "stiller-normal",
             b: "stiller-avvik"},
            {navn: "lokalbetjening", a: "lokal-normal", b: "lokal-avvik"},
            {navn: "lokalstillerlampe", a: "lokalstillerlampe"}];
  if (isManuell(t))
    return [{navn: "drivutgang", a: "ut-normal", b: "ut-avvik"},
            {navn: "stillingssensor", a: "sensor-normal",
             b: "sensor-avvik"},
            {navn: "kontrollampe", a: "panel-normal", b: "panel-avvik"},
            {navn: "betjening", a: "lokal-normal", b: "lokal-avvik"}];
  if (isSperre(t))
    return [{navn: "drivutgang", a: "ut-paalagt", b: "ut-avlagt"},
            {navn: "kontroll pålagt", a: "sensor-paalagt"},
            {navn: "betjening", a: "lokal-paalagt", b: "lokal-avlagt"}];
  if (t === "sporfelt") {
    // Meldefeltet har IKKE den generiske sensoren — sensor-ytre og
    // sensor-indre ER sensorene, og rekkefølgen gir togretningen.
    if (rolle === "varselfelt")
      return [{navn: "sporfelt", par: "ytre · indre",
               a: "sensor-ytre", b: "sensor-indre"},
              {navn: "kvitteringsknapp", a: "kvittering"}];
    const r = [{navn: "sporfelt", par: "ute · på apparatet",
                a: "sensor", b: "panel"}];
    if (rolle === "togspor" || rolle === "linjefelt")
      r.push({navn: "togveistiller", par: "venstre · høyre",
              a: "stiller-v", b: "stiller-h"});
    if (rolle === "linjefelt")
      r.push({navn: "togveislampe", a: "togveislampe"});
    return r;
  }
  if (t === "samlelaas")
    return [{navn: "frigittlampe", par: "ved låsen · apparat",
             a: "anlegg", b: "panel"},
            {navn: "frigivningsstiller", a: "stiller"},
            {navn: "kvitteringsknapp", a: "kvittering"}];
  if (t === "rigel")
    return [{navn: "frigittlampe", par: "ved objektene · apparat",
             a: "anlegg", b: "panel"},
            {navn: "frigivningsstiller", a: "stiller"}];
  if (t === "trykknapp" || t === "bryter")
    return [{navn: t, par: "inngang · lampe", a: "anlegg", b: "panel"}];
  if (t === "klokke") return [{navn: "klokke", a: "anlegg"}];
  if (t === "amperemeter") return [{navn: "instrument", a: "anlegg"}];
  if (t === "inngang") return [{navn: "reservert inngang", a: "anlegg"}];
  return [{navn: "reservert utgang", a: "anlegg"}];
}
// Luft mellom objektene. Rammen tegnes av kanter på cellene, og et
// <tr> kan ikke ha margin — border-spacing ville lagt like mye luft
// MELLOM linjene inne i et objekt og revet rammen fra hverandre. En
// tom rad etter siste linje er den eneste måten å få avstanden til å
// gjelde objektet som helhet.
//
// Den ligger ETTER objektet, så addSubRow (som setter nye linjer inn
// etter den siste underraden) treffer riktig plass av seg selv.
function nyLuftRad(tr) {
  const l = document.createElement("tr");
  l.className = "objluft";
  l.innerHTML = `<td colspan="9"></td>`;
  tr.insertAdjacentElement("afterend", l);
  return l;
}
// Egenskapslinjen. Tom for typer uten egenskaper — da skjules den av
// grpOppdater, så det ikke går an å folde ut en tom linje.
function nyAttrRad(tr) {
  const a = document.createElement("tr");
  a.className = "subrow attrrow";
  // ÉN celle over hele bredden: egenskapene er få og korte, og delt
  // over to celler ble de presset inn i en kolonne de ikke passet i.
  a.innerHTML = `<td colspan="9" class="attrcell">` +
    `<span class="bsym">\u2699</span>` +
    `<span class="bnavn">egenskaper</span>` +
    `<span class="xfull"></span></td>`;
  tr.insertAdjacentElement("afterend", a);
  return a;
}
function byggSubrader(tr, t, binds) {
  const rader = bindingsrader(t, tr.dataset.rolle || "");
  const kjente = new Set();
  for (const r of rader) { kjente.add(r.a); if (r.b) kjente.add(r.b); }
  const brukt = new Set();
  const finn = sted => {
    const b = (binds || []).find(x => x.sted === sted && !brukt.has(x));
    if (b) brukt.add(b);
    return b;
  };
  for (let k = 0; k < rader.length; k++) {
    const r = rader[k];
    let a = finn(r.a);
    // Håndredigerte og eldgamle konfiger kan mangle «sted» helt. En
    // slik binding hørte til typens FØRSTE plass — legg den der i
    // stedet for å la den falle ut i stillhet ved neste lagring.
    // Bare TOMT sted fanges: serverens migrate() normaliserer navnene
    // før de når hit, så en ukjent sted-verdi er en binding som ikke
    // hører til typen, og den skal ikke tvinges inn i første ledige
    // plass (rollebytte på et sporfelt gjorde nettopp det).
    if (!a && k === 0) {
      a = (binds || []).find(x => !x.sted && !brukt.has(x));
      if (a) brukt.add(a);
    }
    addSubRow(tr, r.a, a, false, r.b, r.b ? finn(r.b) : null,
              r.navn, r.par);
  }
  // Et sporavsnitt kan være bygget av FLERE sporfelt — én rad per
  // sporfelt utover det første (logisk ELLER i master). «sensor» er
  // bindingsstedets navn i konfigen; det som kobles der ER sporfeltet.
  if (t === "sporfelt")
    for (const b of (binds || []))
      if (b.sted === "sensor" && !brukt.has(b))
        addSubRow(tr, "sensor", b, true, null, null, "ekstra sporfelt");
}
function delFn(btn) {
  const tr = btn.closest("tr");
  const id = tr.querySelector(".f-id").value.trim() || "(uten litra)";
  if (!confirm(`Slette ${id} med alle bindinger?\n\n` +
               `(Blir permanent først ved «Lagre og publiser».)`)) return;
  while (tr.nextElementSibling?.classList.contains("subrow"))
    tr.nextElementSibling.remove();
  if (tr.nextElementSibling?.classList.contains("objluft"))
    tr.nextElementSibling.remove();
  tr.remove();
  grpOppdater();
}
function collect() {
  const out = [];
  for (const tr of document.querySelectorAll("#tbl tbody tr")) {
    if (tr.classList.contains("grphead")) continue;
    if (tr.classList.contains("objluft")) continue;
    if (tr.classList.contains("subrow")) {
      const eier = out[out.length - 1];
      if (eier) eier.bindinger.push(...lesSubrad(tr));
      continue;
    }
    const t = tr.querySelector(".f-type").value;
    // Hovedraden har ingen bindinger — de ligger alle på underradene
    // over, og samles inn i grenen øverst i løkken.
    const fn = {id: tr.querySelector(".f-id").value.trim(), type: t,
                bindinger: []};
    if (tr.dataset.orgId && tr.dataset.orgId !== fn.id)
      fn.gammel_id = tr.dataset.orgId;   // referansene skrives om
    const montert = felt(tr, ".f-montert");
    if (montert && montert.value) fn.montert_med = montert.value;
    const varsler = felt(tr, ".f-varsler");
    if (varsler && varsler.value) fn.varsler_om = varsler.value;
    const rolle = felt(tr, ".f-rolle");
    if (rolle) fn.rolle = rolleVerdi(rolle.value);
    const side = felt(tr, ".f-side");
    if (side && side.value) fn.side = side.value;
    // Skriv linjeblokk bare når den er AV: true er standarden, og en
    // konfig full av "linjeblokk": true er bare støy. Flagget følger
    // rollevalget — «linjefelt» betyr togmelding, «blokksporfelt»
    // betyr blokk — og gjelder bare feltet mot linjen.
    if (rolle && rolleVerdi(rolle.value) === "linjefelt") {
      if (rolle.value !== "blokksporfelt") fn.linjeblokk = false;
    } else if (tr.dataset.lblokk === "0" &&
               tr.dataset.rolle === "linjefelt") fn.linjeblokk = false;
    const lin = felt(tr, ".f-linje");
    if (lin && lin.value) fn.linjefelt = lin.value;
    const us = felt(tr, ".f-utslag");
    if (us) fn.utslag = Math.max(0, Math.min(100,
        parseInt(us.value || "100") || 0));
    const hk = felt(tr, ".f-hakk");
    if (hk) fn.hakk_hz = Math.max(10, Math.min(250,
        parseInt(hk.value || "50") || 50));
    const du = felt(tr, ".f-duty");
    if (du) fn.hakk_duty = Math.max(10, Math.min(90,
        parseInt(du.value || "50") || 50));
    // Vekselvelgeren finnes bare på skiftesignalrader som ER dekorert.
    // Er boksene der, er de fasiten (også når ingen er huket av — da
    // har brukeren fjernet området med vilje). Er de IKKE der, faller
    // vi tilbake på det som ble lastet: en rad som av en eller annen
    // grunn ikke rakk å bli dekorert skal ALDRI slette området i
    // stillhet. Det var nettopp slik skift_sporveksler forsvant.
    if (isLaas(t) && felt(tr, ".f-navn")) {
      // Dekorert låserad: avkryssingene (objekter i anlegget) +
      // fritekstfeltet (objekter utenfor anlegget) ER fasiten —
      // også når begge er tomme (området fjernet med vilje).
      const valgte = [...felter(tr, ".f-skiftv:checked")]
                   .map(c => c.value);
      const frit = felt(tr, ".f-omfrit");
      if (frit) for (const x of frit.value.split(/[,\s]+/)) {
        const v = x.trim();
        if (v && !valgte.includes(v)) valgte.push(v);
      }
      fn.omfatter = valgte;
    } else if (felt(tr, ".f-skiftv")) {
      fn.skift_sporveksler = [...felter(tr, ".f-skiftv:checked")]
                           .map(c => c.value);
    } else {
      const lagret = JSON.parse(tr.dataset.skiftv || "[]");
      if (lagret.length) {
        if (isLaas(t)) fn.omfatter = lagret;
        else fn.skift_sporveksler = lagret;
      }
    }
    // Sporplan-topologien (portmodellen) — dekorert rad er fasit,
    // udekoreret faller tilbake på det som ble lastet
    for (const [kl, feltnavn, ds] of [["f-spiss","spiss","spiss"],
                                  ["f-plusstil","pluss_til","plusstil"],
                                  ["f-minustil","minus_til","minustil"],
                                  ["f-spisstil","spiss_til","spisstil"],
                                  ["f-avvikben","avvik_ben","avvikben"],
                                  ["f-liggeri","ligger_i","liggeri"]]) {
      const e2 = felt(tr, "." + kl);
      const v2 = e2 ? e2.value : tr.dataset[ds];
      if (v2) fn[feltnavn] = v2;
    }
    // Låsegruppens navn — samme fall-tilbake-prinsipp: en udekoreret
    // rad skal aldri slette verdier i stillhet
    const nv = felt(tr, ".f-navn");
    if (nv) { if (nv.value.trim()) fn.navn = nv.value.trim(); }
    else if (tr.dataset.navn) fn.navn = tr.dataset.navn;
    out.push(fn);
  }
  return out;
}
// Trygg JSON-lesing av API-svar: servertrøbbel (500/HTML i stedet for
// JSON) skal gi en LESBAR feilmelding i UI-et — aldri en stille krasj
// i r.json() som gjør at «ingenting skjer» ved lagring
async function apiJson(r) {
  try { return await r.json(); }
  catch (e) {
    return {error: `Serverfeil ${r.status} — sjekk ` +
                   `«journalctl -u nsi63-hal» på Pi-en`};
  }
}
async function save() {
  const msg = document.getElementById("msg");
  const r = await fetch("/api/hal", {method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({functions: collect()})});
  const j = await apiJson(r);
  if (r.ok) { msg.textContent = "Lagret og publisert " + j.version +
                (j.omdopt ? ` · ${j.omdopt} litra omdøpt, ` +
                            `${j.referanser} referanser fulgte med` : ``);
              msg.className = "ok";
              if (j.omdopt) await loadAll();   // orgId-sporene friskes
              pollAck(j.version); }
  else { msg.textContent = j.error; msg.className = "err"; }
}
async function restoreBackup(input) {
  const file = input.files[0];
  input.value = "";
  if (!file) return;
  if (!confirm(`Gjenopprette hele konfigurasjonen fra «${file.name}»?\n\n` +
               `Dagens konfig overskrives (last den ned først hvis du er ` +
               `usikker), og den gjenopprettede publiseres til master.`)) return;
  const fd = new FormData();
  fd.append("file", file);
  const msg = document.getElementById("msg");
  // Feilen vises som toast: #msg ligger på Objekter-fanen, mens
  // knappen sitter på Noder-fanen — der så ingen den
  let r, j;
  try {
    r = await fetch("/api/restore", {method: "POST", body: fd});
    j = await apiJson(r);
  } catch (e) {
    toast("Gjenoppretting feilet: " + e, true);
    return;
  }
  if (!r.ok) { msg.textContent = j.error;
               msg.className = "err"; toast(j.error, true); return; }
  const oppsummering = `Gjenopprettet ${j.functions} funksjoner` +
    (j.togveier != null ? ` + ${j.togveier} togveier` : "") +
    ` — publisert ` + j.version +
    (j.anlegg_i_backup ? ` · backup fra anlegg ${j.anlegg_i_backup} ` +
      `(anleggs-ID endres kun på ANLEGG-kortet)` : ``);
  toast(oppsummering);
  msg.textContent = oppsummering;
  msg.className = "ok";
  await loadAll();
  pollAck(j.version);
}
async function pollAck(version) {
  const msg = document.getElementById("msg");
  for (let i = 0; i < 10; i++) {
    await new Promise(res => setTimeout(res, 1000));
    const j = await (await fetch("/api/ack")).json();
    if (j.version === version) {
      msg.textContent =
        `Lagret — master kvitterte ${version} (${j.functions} funksjoner)`;
      return;
    }
  }
  msg.textContent += " — venter fortsatt på master-kvittering";
}
// ---------- backup-påminnelse ----------
// Pi-en husker hva siste nedlastede backup inneholdt (/api/backup-status);
// banneret står på ALLE faner til konfigen igjen finnes som fil hos
// brukeren. Et SD-kort som dør tar ellers med seg alt som er lagret
// siden sist.
let BACKUP = null;
const BACKUP_HVA = {hal: "objekter", forrigling: "forrigling",
                    anlegg: "anlegget"};
async function oppdaterBackup() {
  try {
    BACKUP = await (await fetch("/api/backup-status")).json();
  } catch (e) { return; }
  const b = document.getElementById("backupbanner");
  if (!b) return;
  if (BACKUP.endret) {
    document.getElementById("backupbanner-txt").textContent =
      (BACKUP.sist
        ? `Endret siden siste backup (` +
          BACKUP.hva.map(k => BACKUP_HVA[k] || k).join(", ") + `).`
        : `Ingen backup lastet ned fra denne Pi-en ennå.`) +
      ` Et SD-kort som svikter tar med seg alt som ikke er lastet ned.`;
    b.style.display = "";
  } else {
    b.style.display = "none";
  }
}
// Etter ENHVER vellykket skriving mot API-et: lagring av objekter,
// forrigling, anlegg, kallenavn, gjenoppretting … Én krok her i stedet
// for et kall i hver lagringsfunksjon, som en ny funksjon lett glemmer.
{
  const ekteFetch = window.fetch.bind(window);
  window.fetch = async (url, opt) => {
    const r = await ekteFetch(url, opt);
    const metode = ((opt && opt.method) || "GET").toUpperCase();
    if (metode !== "GET" && r.ok && String(url).startsWith("/api/")
        && !String(url).startsWith("/api/backup")) {
      setTimeout(oppdaterBackup, 300);
    }
    return r;
  };
}
function lastNedBackup() {
  location.href = "/api/backup";
  // Pi-en noterer nedlastingen når filen serveres
  setTimeout(async () => {
    await oppdaterBackup();
    if (currentView === "noder") renderNoder();
  }, 1500);
}
function fmtBackupTid(iso) {
  return iso ? new Date(iso).toLocaleString("nb-NO") : "aldri";
}

async function loadAll() {
  oppdaterBackup();
  fetch("/api/anlegg").then(r => r.json())
    .then(a => {
      settTittel(a.id);
      STATUS.anlegg = a.id || "";
      oppdaterStatus();
    }).catch(() => {});
  const nodes = await (await fetch("/api/nodes")).json();
  liveNodes = nodes.nodes || [];
  const hal = await (await fetch("/api/hal")).json();
  SIGNALTYPER = hal.signaltyper || {};
  NODER = hal.noder || {};
  STATUS.hal = hal.version;
  STATUS.noder = liveNodes.filter(n => n.online).length;
  // Togveiene hentes også her (ikke bare i Forrigling-fanen): vekselens
  // stasjonsende utledes av dem, og vekselradene tegnes rett under.
  try {
    const fr = await (await fetch("/api/forrigling")).json();
    TOGVEIER = fr.togveier || [];
    STATUS.fr = fr.version || "";
    STATUS.frAntall = TOGVEIER.length;
  } catch (e) { /* forrigling ikke lagret ennå: ende blir «ukjent» */ }
  oppdaterStatus();
  const tb = document.querySelector("#tbl tbody");
  tb.innerHTML = "";
  // Gruppert etter type (forriglingsobjektene først), alfabetisk på
  // litra innenfor gruppen (naturlig tallsortering: A2 før A10)
  const fns = (hal.functions || []).slice()
    .sort((a, b) => (a.id || "").localeCompare(b.id || "", "no",
                                               {numeric: true}));
  GRUPPER.forEach((g, gi) => {
    tb.appendChild(grpHeaderRow(gi));
    fns.filter(f => gruppeIdx(f.type) === gi).forEach(f => addRow(f));
  });
  // ANDRE RUNDE over radene som er avhengige av ANDRE rader.
  // addRow dekorerer inline, og gruppene tegnes i rekkefølge — så da
  // skiftesignalene (gruppe «Signaler») ble dekorert, fantes ikke
  // vekselradene (gruppe «Veksler») ennå. Vekselvelgeren ble tom,
  // collect() fant ingen avkryssinger, og skift_sporveksler ble SLETTET
  // ved neste lagring. Samme gjaldt vekselens utledede ende, som
  // leser linjefeltenes side fra sporfelt-gruppen lenger ned.
  for (const tr of document.querySelectorAll("#tbl tbody tr.fnrow")) {
    const t = tr.querySelector(".f-type").value;
    if (isSkift(t) || isNoenVeksel(t) || isSperre(t)) decorateRow(tr);
  }
  grpOppdater();
}
// ---------- Noder-fanen: full oversikt over noder og porter ----------
let currentView = "noder";   // «System»-fanen er landingssiden

// Statuslinjen oppe til høyre: alle tre lagrede konfigurasjonene
// (anlegg, objekter, forrigling) + nodetelling — alltid synlig,
// uavhengig av fane. Oppdateres av loadAll/frLoad/3s-intervallet.
const STATUS = {anlegg: "", hal: "", fr: "", frAntall: null, noder: 0};
function oppdaterStatus() {
  const d = [];
  if (STATUS.anlegg) d.push(`anlegg ${STATUS.anlegg}`);
  if (STATUS.hal) d.push(`objekter ${STATUS.hal}`);
  if (STATUS.fr) d.push(`forrigling ${STATUS.fr}` +
    (STATUS.frAntall != null ? ` (${STATUS.frAntall} togveier)` : ``));
  d.push(`${STATUS.noder} ${STATUS.noder === 1 ? "node" : "noder"} online`);
  document.getElementById("status").textContent = d.join(" · ");
}
// ==================== KABLING ====================
// Samme bindinger som objektlista, lest fra motsatt kant: node ->
// brikke -> port. Det er den fysiske arbeidsrekkefølgen — man sitter
// ved én node og fyller portene dens — og det er den eneste
// visningen som kan svare på «hvilke porter er ledige?» og vise at et
// signal med tre lamper spiser tre påfølgende kanaler.
//
// LESEVISNING. Redigering skjer fortsatt på Objekter-siden, som eier
// lagringen (collect() leser DOM-en der). To steder å redigere fra
// ville betydd to kilder til sannhet for hva som lagres.
let KBFN = [], KBNODER = {}, KBSIGT = {}, KBSKANN = {};
async function kbLoad() {
  const h = await (await fetch("/api/hal")).json();
  KBFN = h.functions || [];
  KBNODER = h.noder || {};
  KBSIGT = h.signaltyper || {};   // lampeantall -> portspenn
  // Nodene skanner I2C-bussen ved boot og melder hva de FANT. Det er
  // fasit for hvilke brikker som finnes — vi gjetter ikke.
  KBSKANN = {};
  try {
    const nd = await (await fetch("/api/nodes")).json();
    for (const n2 of (nd.nodes || []))
      KBSKANN[(n2.mac || "").toLowerCase()] =
        {i2c: n2.i2c || [], online: !!n2.online};
  } catch (e) { /* offline Pi: fall tilbake på bundne brikker */ }
  await kbInnHent();
  kbRender();
  kbInnOppdater();
}
// LEVENDE INNGANGSVERDI. Master videresender nodenes inngangsbytes på
// espnow/<mac>/in/<addr>, og Pi-en holder siste byte per brikke.
// Nøkkelen er «<mac>/0xNN» — GPIO-pseudobrikken er 0x00.
//
// Sensorene er AKTIV LAV, som i masterens egen lesning: bit 0 betyr at
// noe trekker porten ned — sporfeltet er belagt, knappen trykket,
// tunga i kontroll. Merket i cellen viser nettopp det, ikke råbiten,
// for det er den som betyr noe når man står med en multimeter.
let KBINN = {};
async function kbInnHent() {
  try { KBINN = await (await fetch("/api/inputs")).json(); }
  catch (e) { KBINN = {}; }
}
function kbInnOppdater() {
  // BARE cellene: symbolforklaringen har sine egne prikker med fast
  // tilstand, og de skal ikke nullstilles av en oppfriskning.
  for (const e of document.querySelectorAll("#kb-rutenett .kb-celle .kb-inn")) {
    const b = KBINN[e.dataset.k];
    const p = Number(e.dataset.p);
    e.classList.remove("kjent", "pa");
    if (b === undefined || b === null) {
      e.title = "ingen inngangsmelding fra noden";
      continue;
    }
    const aktiv = ((b >> p) & 1) === 0;
    e.classList.add("kjent");
    if (aktiv) e.classList.add("pa");
    e.title = aktiv ? "inngangen er AKTIV (porten trekkes lav)"
                    : "inngangen hviler";
  }
}
// Alle bindinger samlet per (node, brikke, port). En binding kan
// dekke FLERE porter: signaler legger lampene på påfølgende kanaler
// fra bindingsporten, så lampe 2 og 3 er opptatt uten å stå noe sted.
function kbKart(signaltyper) {
  const kart = {};      // node -> i2c -> port -> [{...}]
  const ordrer = {};    // node -> ordrepunkter (samme regning som master)
  for (const f of KBFN) {
    const st = (signaltyper || {})[f.type];
    for (const b of f.bindinger || []) {
      const nd = (b.node || "").trim();
      if (!nd) continue;
      const n = (st && (b.sted === "anlegg" || b.sted === "panel"))
                  ? (st.lamper || 1) : 1;
      // Samme regel som Objekter-siden og masteren: «trykknapp»,
      // «bryter» og «inngang» leses alle via stedet «anlegg», og det
      // er TYPEN som sier at porten er en inngang. Sto det bare
      // «inngang» her — som det gjorde — ble hver knapp og bryter på
      // stillerapparatet farget som utgang, talt som ordrepunkt mot
      // nodens 40-tak, og to knapper på samme port meldt som kollisjon.
      const inn = bindErInngang(f.type, b.sted);
      if (!inn) ordrer[nd] = (ordrer[nd] || 0) + n;
      else if (b.i2c === "gpio") ordrer[nd] = (ordrer[nd] || 0) + 1;
      const p0 = parseInt(b.port) || 0;
      for (let k = 0; k < n; k++) {
        ((kart[nd] = kart[nd] || {})[b.i2c] =
           kart[nd][b.i2c] || {})[p0 + k] =
          (kart[nd][b.i2c][p0 + k] || []).concat([
            {litra: f.id, type: f.type, sted: b.sted,
             del: k, av: n, inn}]);
      }
    }
  }
  return {kart, ordrer};
}
const KB_BRIKKER = ["0x40","0x41","0x42","0x43",
                    "0x20","0x21","0x22","0x23","gpio"];
function kbBrikkeNavn(a) {
  if (a === "gpio") return "GPIO på noden · 6 porter";
  return a.startsWith("0x4") ? a + " PCA9685 · 16 utganger"
                             : a + " PCF8574 · 8 innganger";
}
// ---- kablingsvisningen ----
// Rutenettet gir brikkens FORM: 16 kanaler på én linje for en
// PCA9685, 8 for en PCF8574. Hvor mye som er ledig, og hvor hullene
// ligger, ses da med ett blikk. En trevisning fantes en stund ved
// siden av, men rutenettet vant på begge deler.
// Rutenettet er 16 bredt — en PCA9685 får alle kanalene på ÉN linje,
// og brikkens bredde blir dermed dens kapasitet: en PCF8574 er synlig
// halvparten så bred, GPIO enda smalere. Ingen brikke kan da wrappe,
// men vakten under står likevel: den er det som holder en flis fra å
// late som den henger sammen over et radskift.
const KB_KOL = 16;
// Symbol per bindingstype. Portene skal kunne leses uten å slå opp
// hva «ut-avvik» eller «sensor-paalagt» betyr — formen sier hva som
// skal kobles der, fargen sier retningen, og litraen sier hvilket
// objekt. Bevisst enkle geometriske tegn: de må være lesbare på 11 px
// og finnes i alle systemfonter.
function portSymbol(sted, type) {
  if (sted === "anlegg" && SIGNAL_LAMPEFARGE[type]) return "\u25cf"; // ● lampe
  // Samlelåsens og rigelens «anlegg» er frigittlampen ved låsen — en
  // lampe, ikke en anonym utgang.
  if (sted === "anlegg" && (type === "samlelaas" || type === "rigel"))
    return "\u25cb";
  if (sted.startsWith("panel")) return "\u25cb";      // ○ kontrollampe
  if (sted === "lokalstillerlampe") return "\u25cb";  // ○ lampe ute
  if (sted === "togveislampe") return "\u25cb";
  if (sted === "middelkontrollampe") return "\u25cb";
  if (sted.startsWith("ut-")) return "\u21c4";        // ⇄ drivutgang
  if (sted.startsWith("sensor")) return "\u25ce";     // ◎ sensor
  if (sted.startsWith("stiller") || sted.startsWith("lokal-") ||
      sted === "kvittering") return "\u25a3";         // ▣ betjening
  if (type === "klokke") return "\u266a";             // ♪ klokke
  if (type === "amperemeter") return "\u25b3";        // △ instrument
  if (type === "trykknapp" || type === "bryter") return "\u25a3";
  if (type === "inngang") return "\u25ce";
  return "\u25aa";                                    // ▪ annen utgang
}
// Lampefargene ligger i ui/signalfarger.js — DELT med
// stillerapparatet, så kablingsvisningen og panelet ikke kan vise
// ulik farge på samme kanal.
function kbBrikkeKap(a) {
  return a === "gpio" ? 6 : (a.startsWith("0x4") ? 16 : 8);
}
function kbRender() {
  const visAlle = document.getElementById("kb-alle").checked;
  const {kart, ordrer} = kbKart(KBSIGT);
  const navn = Object.keys(KBNODER);
  for (const nd of Object.keys(kart)) if (!navn.includes(nd)) navn.push(nd);
  const el = document.getElementById("kb-rutenett");
  if (!navn.length) {
    el.innerHTML = '<span class="hint">Ingen noder definert ennå.</span>';
    return;
  }
  let h = "";
  for (const nd of navn) {
    const mac = (KBNODER[nd] || {}).mac || "ukjent MAC";
    const skann = KBSKANN[mac.toLowerCase()];
    const funnet = skann ? skann.i2c : null;
    const brukt = ordrer[nd] || 0;
    h += `<div class="kb-node"><b>${attr(nd)}</b>` +
         `<span class="kb-dim"> · ${attr(mac)} · </span>` +
         `<span class="${brukt > 34 ? "kb-konflikt" : "kb-dim"}">` +
         `${brukt} av 40 ordrepunkter</span>`;
    h += `<div class="kb-dim" style="font-size:11.5px;margin:2px 0 6px">` +
         (funnet
            ? `noden meldte ${funnet.length ? attr(funnet.join(", "))
                                            : "ingen I2C-brikker"}` +
              (skann.online ? "" : " (sist sett — offline nå)")
            : `noden har ikke meldt seg — viser bare det som er bundet`) +
         `</div>`;
    const brikker = KB_BRIKKER.filter(a => visAlle ||
      (kart[nd] && kart[nd][a]) || a === "gpio" ||
      (funnet && funnet.includes(a)));
    for (const a of brikker) {
      const porter = (kart[nd] || {})[a] || {};
      const kap = kbBrikkeKap(a);
      const fri = kap - Object.keys(porter).length;
      h += `<div class="kb-brikkerad"><span class="kb-brikke">` +
           `${kbBrikkeNavn(a)}</span>` +
           `<span class="kb-dim"> · ${fri} ledige</span></div>` +
           // Kolonnetallet settes PER BRIKKE, ellers reserverer grid-en
           // 16 spor også for en PCF8574 og bredden slutter å bety noe.
           `<div class="kb-grid" style="grid-template-columns:` +
           `repeat(${Math.min(kap, KB_KOL)}, 48px)">`;
      for (let p = 0; p < kap; p++) {
        const her = porter[p];
        if (!her) {
          h += `<div class="kb-celle kb-c-fri" title="port ${p}: ledig">` +
               `<span class="kb-nr">${p}</span></div>`;
          continue;
        }
        const konflikt = her.length > 1 && her.some(x => !x.inn);
        // LAMPESPENN: et signal med n lamper eier n påfølgende kanaler.
        // De tegnes som ÉN sammenhengende flis — mellomrommet lukkes og
        // de indre kantene fjernes — så spennet leses som det ene
        // objektet det er, ikke som tre løsrevne bindinger. Litraen
        // står bare på den første; de øvrige viser kun portnummeret.
        const x0 = her[0];
        const spenn = her.length === 1 && x0.av > 1;
        const radstart = p % KB_KOL === 0;
        let kls = konflikt ? "kb-c-feil"
                : x0.inn ? "kb-c-inn" : "kb-c-ut";
        if (spenn) {
          kls += " kb-spenn";
          // Ved radskift kan flisen ikke henge sammen visuelt — da
          // starter den på nytt, med runde hjørner igjen.
          const forts = x0.del > 0 && !radstart;
          if (forts) kls += " kb-spenn-forts";
          if (x0.del < x0.av - 1 && (p + 1) % KB_KOL !== 0)
            kls += " kb-spenn-mer";
        }
        const tips = her.map(y => y.litra + " " + y.type + " · " + y.sted +
                     (y.av > 1 ? ` (lampe ${y.del + 1} av ${y.av})` : ""))
                     .join("  +  ");
        // Tre soner: portnummer, symbol, litra — på HVER celle. Én
        // etikett strukket over spennet var mer elegant, men da måtte
        // man lese sidelengs for å finne ut hvem en port hører til.
        // Litraen på alle cellene svarer på det der man står.
        const farge = (her.length === 1 && !konflikt)
                        ? signalLampeFarge(x0.type, x0.del) : null;
        const sym = konflikt ? "\u2715"
                             : portSymbol(x0.sted, x0.type);
        const symStil = farge ? ` style="color:${farge}"` : "";
        // Porter som LESES får et levende merke i hjørnet. Bare de:
        // en utgang har ingen verdi å melde, og en port som deles av
        // inngang og utgang er uansett en kollisjon.
        const macN = ((KBNODER[nd] || {}).mac || nd).toLowerCase();
        const innMerke = her.every(y => y.inn)
          ? `<span class="kb-inn" data-k="${attr(macN)}/` +
            `${a === "gpio" ? "0x00" : attr(a)}" data-p="${p}"></span>`
          : "";
        h += `<div class="kb-celle ${kls}"` +
             ` title="port ${p}: ${attr(tips)}"` +
             ` onclick="kbGaaTil('${attr(x0.litra)}',` +
             `'${attr(x0.type)}')">` +
             `<span class="kb-nr">${p}</span>` +
             `<span class="kb-sym"${symStil}>${sym}</span>` +
             `<span class="kb-lit">${attr(x0.litra)}</span>` +
             innMerke + `</div>`;
      }
      h += `</div>`;
    }
    h += `</div>`;
  }
  // Symbolforklaring. Uten den må man gjette hva ◎ betyr, og formen
  // er hele poenget med visningen.
  const sym = [
    ["\u25cf", "lampe (i lampens egen farge)"],
    ["\u25cb", "kontrollampe eller frigittlampe"],
    ["\u21c4", "drivutgang — motor"],
    ["\u25ce", "sensor"],
    ["\u25a3", "betjening — stiller eller trykknapp"],
    ["\u266a", "klokke"],
    ["\u25b3", "amperemeter"],
    ["\u25aa", "annen utgang — reservert port"],
  ];
  el.innerHTML = h +
    `<div class="kb-nokler">` +
    `<div class="kb-nokkelrad"><b>Farge</b>` +
    `<span><span class="kb-nokkel kb-c-fri"></span> ledig</span>` +
    `<span><span class="kb-nokkel kb-c-inn"></span> bundet inngang</span>` +
    `<span><span class="kb-nokkel kb-c-ut"></span> bundet utgang</span>` +
    `<span><span class="kb-nokkel kb-c-feil"></span> ` +
    `<span class="kb-symnok">\u2715</span> kollisjon</span>` +
    `</div>` +
    `<div class="kb-nokkelrad"><b>Symbol</b>` +
    sym.map(([t, f]) =>
      `<span><span class="kb-symnok">${t}</span> ${f}</span>`).join("") +
    `</div>` +
    `<div class="kb-nokkelrad"><b>Inngang</b>` +
    `<span><span class="kb-inn kb-innnok"></span> ingen melding` +
    `</span>` +
    `<span><span class="kb-inn kb-innnok kjent"></span> hviler</span>` +
    `<span><span class="kb-inn kb-innnok kjent pa"></span> aktiv ` +
    `(porten trekkes lav)</span>` +
    `<span class="kb-dim">merket står i hjørnet av portene som leses` +
    `</span></div>` +
    `<div class="kb-nokkelrad"><b>Form</b>` +
    `<span>sammenhengende fliser = ett signals lampespenn, ` +
    `én kanal per lampe</span>` +
    `<span>tre linjer i cellen: portnummer \u00b7 symbol \u00b7 litra</span>` +
    `</div>` +
    `<p class="hint" style="margin:6px 0 0">Hold over en celle for ` +
    `detaljer, klikk for å redigere objektet på Objekter-siden.</p>` +
    `</div>`;
}
// Hopp til objektet på Objekter-siden, utfoldet
function kbGaaTil(litra, type) {
  gaaTilFane("hal");
  showView("hal");   // hashchange rekker ikke før vi leter etter raden
  for (const tr of document.querySelectorAll("#tbl tbody tr.fnrow")) {
    if (tr.querySelector(".f-id").value !== litra) continue;
    if (tr.querySelector(".f-type").value !== type) continue;
    RADAAPEN.add(tr.dataset.rid);
    const gi = gruppeIdx(type);
    COLLAPSED.delete(gi);
    grpOppdater();
    tr.scrollIntoView({block: "center"});
    tr.style.outline = "2px solid var(--acc)";
    setTimeout(() => { tr.style.outline = ""; }, 1600);
    return;
  }
}
// Fanen ligger i URL-hashen. Da virker nettleserens fram/tilbake av
// seg selv, en reload lander på samme fane, og en fane kan bokmerkes
// eller deles som lenke. hashchange er ÉN inngang: både klikk og
// historikknavigasjon går gjennom den, så de ikke kan komme i utakt.
const FANER = ["noder", "hal", "kabling", "forrigling"];
function gaaTilFane(v) {
  if (location.hash.slice(1) === v) return;   // ingen ny historikkpost
  location.hash = v;
}
function faneFraHash() {
  const v = decodeURIComponent(location.hash || "").slice(1);
  return FANER.includes(v) ? v : "noder";
}
function showView(v, btn) {
  currentView = v;
  for (const name of FANER)
    document.getElementById("view-" + name).style.display =
      v === name ? "" : "none";
  document.querySelectorAll(".tab").forEach(b =>
    b.classList.toggle("active", b.dataset.view === v));
  if (v === "noder") renderNoder();
  if (v === "forrigling") frLoad();
  if (v === "kabling") kbLoad();
}
window.addEventListener("hashchange", () => showView(faneFraHash()));
function fmtSek(s) {
  if (s == null) return "?";
  const d = Math.floor(s / 86400), t = Math.floor(s % 86400 / 3600),
        m = Math.floor(s % 3600 / 60);
  if (d) return d + "d " + t + "t";
  if (t) return t + "t " + m + "m";
  return m + "m";
}
async function renderNoder() {
  // Fanen tegnes på nytt hvert 3. sekund; en åpnet kopiliste skal ikke
  // klappe sammen under brukeren
  const autoApen = !!document.querySelector("#auto-kopier[open]");
  const [nodes, hal, master, lt, pi, an, ota, bs, ko] = await Promise.all([
    (await fetch("/api/nodes")).json(),
    (await fetch("/api/hal")).json(),
    (await fetch("/api/master")).json(),
    (await fetch("/api/lamptest")).json(),
    (await fetch("/api/pi")).json(),
    (await fetch("/api/anlegg")).json(),
    (await fetch("/api/ota")).json(),
    (await fetch("/api/backup-status")).json(),
    (await fetch("/api/ota/ko")).json(),
  ]);
  SIGNALTYPER = hal.signaltyper || SIGNALTYPER;
  NODER = hal.noder || {};
  const sec = document.getElementById("view-noder");
  let html = "";

  if (master.conflict) {
    html += `<div class="card" style="border-color:var(--warn)">
      <h2><span class="off">⚠ TO MASTERE AKTIVE</span></h2>
      <p>«${master.conflict.self}» og «${master.conflict.other}» publiserer
      samtidig. Skru av den ene umiddelbart — nodene låser seg til én,
      men MQTT-bildet er upålitelig så lenge begge kjører.</p></div>`;
  }

  // Anleggs-ID: skiller to anlegg på samme radiokanal (FREMO-treff)
  {
    const ack = an.ack || {};
    const mFersk = master.status === "online" &&
                   master.sist_hort_s != null && master.sist_hort_s < 35;
    const bekreftet = mFersk && ack.id === an.id;
    let st = "";
    if (an.id && bekreftet)
      st = `<span class="on">master kjører med ${ack.id}</span>`;
    else if (mFersk && an.id)
      st = `<span class="off">master har ikke bekreftet — kjører den
            firmware uten anleggsstøtte?</span>`;
    else if (!mFersk)
      st = `master er offline — bekreftes når den kobler seg til`;
    html += `<div class="card"><h2>ANLEGG ` +
      (an.id ? `<span class="on">${an.id}</span>`
             : `<span class="hint">ikke satt</span>`) + `</h2>
      <div class="bar" style="margin:8px 0 4px;flex-wrap:wrap">
        <input style="width:70px;flex:0 0 auto;text-transform:uppercase"
               id="anlegg-id" maxlength="3" value="${attr(an.id)}"
               placeholder="XXX" title="Anleggs-ID: tre store bokstaver">
        <input type="checkbox" id="anlegg-adopter"
               style="width:auto;flex:0 0 auto;margin:0"
               ${an.adopter ? "checked" : ""}>
        <label for="anlegg-adopter" class="hint"
               style="white-space:nowrap;flex:0 0 auto;cursor:pointer"
               title="PÅ: uparede noder adopteres ved første kontakt. Skru AV på treff.">
          adopter nye noder</label>
        <input type="checkbox" id="anlegg-dekning"
               style="width:auto;flex:0 0 auto;margin:0 0 0 10px"
               ${an.dekningsstilling ? "checked" : ""}>
        <label for="anlegg-dekning" class="hint"
               style="white-space:nowrap;flex:0 0 auto;cursor:pointer"
               title="Dekningsstilling: når en innkjørtogvei sikres, legges krysningsvekselen i motsatt ende VEKK fra togveiens spor — «pulses, men låses ikke» — som flankebeskyttelse mot utilsiktet materiellbevegelse. Vekselen låses aldri og kan legges om igjen. Hopper stille over hvis vekselen er låst, frigitt lokalt, belagt eller dekket av skifting.">
          dekningsstilling</label>
        <input type="checkbox" id="anlegg-fjern"
               style="width:auto;flex:0 0 auto;margin:0 0 0 10px"
               ${an.fjernstyrt ? "checked" : ""}>
        <label for="anlegg-fjern" class="hint"
               style="white-space:nowrap;flex:0 0 auto;cursor:pointer"
               title="Er stasjonen fjernstyrt? Foreløpig ren DOKUMENTASJON — ingenting i forriglingen leser flagget. Det avgjør hvilke varianter som er riktige: fjernstyrt anlegg har høyt skiftesignal med bare signal 42 (skiftesignal1) og middelkontrollampe; uten fjernstyring har det begge lamperekkene (skiftesignal2), og togekspeditøren gjør middelkontrollen selv med sistevognskontroll. Selve sistevognskontrollen styres av «linjeblokk» på hvert linjefelt, ikke av dette flagget.">
          fjernstyrt</label>
        <input type="checkbox" id="anlegg-test"
               style="width:auto;flex:0 0 auto;margin:0 0 0 10px"
               ${an.testmodus ? "checked" : ""}>
        <label for="anlegg-test" class="hint"
               style="white-space:nowrap;flex:0 0 auto;cursor:pointer;color:#e0b050"
               title="TESTMODUS: MQTT-kommandoer på nsi63/<klasse>/<litra>/set og nsi63/sporveksel/<id>/set omgår signalstopp, oppstartsperre, vekselfelt-vernet, togvei-låsen og skiftesignalets område. Stillerapparatet er ALDRI omgått, og sikring av togvei kontrolleres alltid. Skru AV før anlegget settes i drift.">
          testmodus</label>
        <input type="checkbox" id="anlegg-vis-sim"
               style="width:auto;flex:0 0 auto;margin:0 0 0 10px"
               ${an.vis_sim ? "checked" : ""}>
        <label for="anlegg-vis-sim" class="hint"
               style="white-space:nowrap;flex:0 0 auto;cursor:pointer"
               title="Vis simuleringsknappene under sporplanen på /panel: sporfeltenes Belagt/Fritt/Sensor og bryternes «Fysisk». Et testverktøy for benken — «Fritt» overstyrer sensorene, og forriglingen stoler på det. Skjult som standard; la det være av på et anlegg i drift.">
          sim-knapper</label>
        <button class="mini" style="flex:0 0 auto"
                onclick="saveAnlegg()">Lagre</button>
        <span class="hint" style="flex:1 1 220px">${st}</span>
      </div>
      <div class="bar" style="margin:0 0 4px;flex-wrap:wrap">
        <input style="width:150px;flex:0 0 auto" id="anlegg-navn"
               maxlength="24" value="${attr(an.navn)}"
               placeholder="stasjonsnavn"
               title="Stasjonsnavnet slik det står over stillerapparatet — vises midtstilt øverst på /panel. Tomt: anleggs-IDen brukes.">
        <input style="width:150px;flex:0 0 auto" id="anlegg-nabo-v"
               maxlength="24" value="${attr(an.nabo_venstre)}"
               placeholder="nabo venstre"
               title="Nabostasjonen i VENSTRE ende av sporplanen. Vises øverst til venstre på /panel, på linje med stasjonsnavnet.">
        <input style="width:150px;flex:0 0 auto" id="anlegg-nabo-h"
               maxlength="24" value="${attr(an.nabo_hoyre)}"
               placeholder="nabo høyre"
               title="Nabostasjonen i HØYRE ende av sporplanen. Vises øverst til høyre på /panel, på linje med stasjonsnavnet.">
      </div>
      <p class="hint">Navnene står over apparatet på
      <a href="/panel" target="_blank">/panel</a>: stasjonen midtstilt,
      nabostasjonene i hver sin ende av linjen. De er ren skilting —
      ingenting i forriglingen leser dem. Venstre og høyre er slik
      sporplanen tegnes, samme retning som Lok I og Lok II.</p>
      <p class="hint">Tre store bokstaver — jernbanens interne stasjonskode
      (f.eks. SKN). Skiller to anlegg på samme radiokanal i samme lokale:
      parede noder og master godtar kun sitt eget anlegg. Lagring døper
      samtidig om wifi-nettet til NSI63&lt;ID&gt; og Pi-ens hostname til
      det samme i små bokstaver — <b>AP-et restarter, og du må koble
      denne enheten til det nye nettet</b>. Master og noder finner frem
      selv. Nye (uparede) enheter lærer ID-en ved første kontakt — par
      dem hjemme, og skru AV «adopter nye noder» på treff. Langtrykk
      (10 s) på knappen til node/master glemmer paringen. Tom ID =
      filter av (alt adopteres, nettet heter NSI63).</p></div>`;
  }

  // TIDSLÅSENE. Skjemaet tegnes av beskrivelsen serveren sender
  // (tider_def), så forbildeverdiene og grensene står ETT sted — i
  // app.py, der de også validerer lagringen.
  {
    const def = an.tider_def || [];
    const naa = an.tider || {};
    html += `<div class="card"><h2>Tidslåser</h2>
      <p class="hint">Modelljernbaner kjører som regel med hurtigklokke,
      og da blir forbildets tider urimelig lange: 90 sekunders
      hjelpeutløsning er halvannet minutt ekte venting midt i en
      bevegelse som «egentlig» tok fem. Her settes hver enkelt. Master
      klemmer verdiene innenfor grensene på sin side også — et tidsvern
      skal ikke kunne settes til noe farlig utenfra.</p>
      <table class="tider"><tr>
        <th>Tidslås</th><th>Forbildet</th><th>I bruk</th></tr>`;
    for (const t of def) {
      const v = naa[t.navn] !== undefined ? naa[t.navn] : t.standard;
      html += `<tr><td><b>${t.tittel}</b>` +
        `<div class="hint">${t.hva}</div></td>` +
        `<td class="tid-forbilde">${t.forbilde}` +
        (t.kilde ? `<div class="hint">${t.kilde}</div>` : ``) + `</td>` +
        `<td class="tid-verdi"><input type="number" id="tid-${t.navn}"` +
        ` min="${t.av ? 0 : t.min}" max="${t.maks}" value="${v}">` +
        ` <span class="hint">${t.enhet}</span>` +
        `<div class="hint">${t.min}–${t.maks}` +
        (t.av ? ` · 0 = av` : ``) + `</div></td></tr>`;
    }
    html += `</table>
      <div class="bar" style="margin:8px 0 4px">
        <button class="mini" onclick="saveAnlegg()">Lagre tidslåser</button>
        <span class="hint">Lagres sammen med resten av
        anleggsinnstillingene, og publiseres til master straks.</span>
      </div></div>`;
  }

  // Backup: hele konfigurasjonen (objekter + forrigling + anleggs-ID)
  html += `<div class="card"><h2>Backup</h2>
    <p class="hint">Én fil med hele konfigurasjonen: objekter,
    forriglingstabell og anleggs-ID. Gjenoppretting overskriver dagens
    konfigurasjon og publiserer til master (anleggs-ID-en i backupen
    vises, men tas aldri i bruk automatisk).</p>
    <div class="bar" style="margin:8px 0 4px">
      <button class="mini" onclick="lastNedBackup()">
        Last ned backup</button>
      <button class="mini"
        onclick="document.getElementById('restoreFile').click()">
        Gjenopprett fra backup…</button>
      <span class="hint">sist lastet ned: ` + fmtBackupTid(bs.sist) +
      (bs.endret ? ` · <span class="off">endret siden</span>` : ``) +
      `</span>
    </div>` +
    ((bs.auto || []).length ? `
    <details id="auto-kopier" style="margin-top:6px"${autoApen ? " open" : ""}><summary class="hint">
      ${bs.auto.length} automatiske kopier på Pi-en</summary>
      <p class="hint">Tas etter hver lagring (de siste 20 beholdes) — for
      å angre en lagring som ble feil. De ligger på samme SD-kort som
      konfigen, så de erstatter ikke en nedlastet backup. Last ned en og
      bruk «Gjenopprett fra backup…».</p>
      <p class="hint">` + bs.auto.map(n =>
        `<a href="/api/backup-auto/${attr(n)}">` +
        attr(n.replace(/^nsi63-auto-|\.json$/g, "")) + `</a>`).join(" · ") +
      `</p></details>` : ``) + `</div>`;

  // Pi-kortet: temperatur, strøm, nett, klienter, tjenester
  {
    const thrNaa = (pi.throttled && pi.throttled.naa) || [];
    const thrHist = (pi.throttled && pi.throttled.historikk) || [];
    const varm = pi.temp != null && pi.temp >= 70;
    html += `<div class="card"><h2>PI <span class="hint">` +
      (pi.modell || "pi") + `</span></h2>`;
    if (thrNaa.length)
      html += `<p><span class="off">⚠ ` + thrNaa.join(", ").toUpperCase() +
        `</span> — sjekk strømforsyningen!</p>`;
    let l1 = [];
    if (pi.temp != null)
      l1.push(`temp <span class="` + (varm ? "off" : "on") + `">` +
              String(pi.temp).replace(".", ",") + `&deg;C</span>`);
    if (pi.last) l1.push(`last ` + pi.last[0].toFixed(2).replace(".", ","));
    if (pi.mem) l1.push(`minne ` + pi.mem.ledig_mb + `/` +
                        pi.mem.total_mb + ` MB ledig`);
    if (pi.disk) l1.push(`disk ` + pi.disk.ledig_gb + `/` +
                         pi.disk.total_gb + ` GB ledig`);
    html += `<p class="hint">` + l1.join(" · ") + `</p>`;
    let ks;
    if (pi.ntp) ks = `<span class="on">NTP ok</span>`;
    else if (pi.klokke_stilt)
      ks = `<span class="on">stilt fra nettleser kl. ` +
           pi.klokke_stilt.naar + `</span>`;
    else ks = `ingen RTC — stilles automatisk fra nettleseren ved behov`;
    html += `<p class="hint">oppetid ` + fmtSek(pi.oppetid_s) +
      ` · klokke ` + (pi.klokke || "?") + ` · ` + ks + `</p>`;
    // Hvilken kode som kjører (versjon.json fra deploy-pi.sh)
    const v = pi.hal_ui;
    html += `<p class="hint">HAL-UI ` + (v
      ? `<b>${attr(v.kort || "?")}</b> fra ${attr(v.gren || "?")}` +
        (v.ukommittert
          ? ` <span class="off" title="Deployet med endringer som ikke var committet — koden finnes ikke i noen commit">+ ukommittert</span>`
          : ``) +
        (v.tid ? ` · deployet ` + attr(new Date(v.tid).toLocaleString("nb-NO")) : ``)
      : `ingen versjonsinfo`) + `</p>`;
    if (thrHist.length)
      html += `<p class="hint">siden boot: ` + thrHist.join(", ") +
        ` har forekommet</p>`;
    const ipTxt = (pi.ips || []).map(i =>
      i.ifname + ` ` + i.addrs.join(", ") +
      (i.oper && i.oper !== "UP" ? ` (` + i.oper.toLowerCase() + `)` : ""))
      .join(` · `);
    if (ipTxt) html += `<p class="hint">IP: ` + ipTxt + `</p>`;
    const tj = pi.tjenester || {};
    html += `<p class="hint">` + Object.keys(tj).map(n =>
      n + ` <span class="` + (tj[n] === "active" ? "on" : "off") + `">` +
      (tj[n] === "active" ? "ok" : tj[n]) + `</span>`).join(" · ") + `</p>`;
    const kl = pi.klienter || [];
    if (kl.length) {
      html += `<div class="chips"><div class="chip"><table>` +
        `<caption>AP-klienter (` + kl.length + `)</caption>` +
        `<tr><th>Navn</th><th>IP</th><th>MAC</th><th>Signal</th>` +
        `<th>Tilkoblet</th></tr>`;
      for (const c of kl) {
        const erMaster = master.mac &&
          c.mac.replace(/:/g, "") === master.mac;
        html += `<tr><td>` +
          (c.navn || `<span class="fri">?</span>`) +
          (erMaster ? ` <span class="on">master</span>` : ``) +
          `</td><td>` + (c.ip || `–`) + `</td><td>` + c.mac +
          `</td><td>` + (c.signal != null ? c.signal + ` dBm` : `–`) +
          `</td><td>` + fmtSek(c.tid_s) + `</td></tr>`;
      }
      html += `</table></div></div>`;
    } else {
      html += `<p class="hint">ingen wifi-klienter tilkoblet</p>`;
    }
    // Én fil til feilsøking på avstand. Den er IKKE en backup og
    // nullstiller ikke backup-påminnelsen, selv om konfigen er med.
    html += `<div class="bar" style="margin:8px 0 4px">
      <button class="mini" onclick="location.href='/api/diagnostikk'">
        Last ned diagnostikk</button>
      <span class="hint">zip med Pi-, master- og nodestatus, konfig,
      hendelseslogg og tjenestenes journal — til feilsøking</span>
    </div>`;
    html += `</div>`;
  }

  // Firmware (OTA): ÉN felles binær for master og noder — rollen
  // velges med knappegest på enheten. Oppdater-knappene ligger på
  // enhetenes egne kort.
  const fwFil = "nsi63-atoms3.bin";
  {
    const stp = f => ota[f] ? (ota[f].stempel || "uten stempel") : null;
    const fs = stp(fwFil);
    const stat = fs ? `firmware ${fs} klar`
                    : `ingen firmware lastet opp ennå`;
    html += `<div class="card"><h2>Firmware (OTA)</h2>
      <p class="hint">Én felles binær for master og noder — rollen
      velges med knappegest på enheten (hold frontknappen 3 s ved
      strømpåslag = master). Bygg med <code>bash bygg-ota.sh</code> og
      last opp <code>.bin</code>-fila den lager. Master oppdateres fra
      sitt eget kort (hele anlegget i sikker tilstand ~1 min,
      selvhelende); nodene med «Oppdater alle noder» under, én om
      gangen — hver henter via en kort wifi-oppkobling til AP-et og er
      mørk ~1 min. MD5-verifisert mot
      passiv partisjon: feiler noe, kjører gammel firmware videre.
      Første OTA-runde krever USB-flash av OTA-støttet firmware.</p>
      <div class="bar" style="margin:8px 0 4px">
        <input type="file" id="ota-fil" accept=".bin" style="display:none"
               onchange="otaLastOpp(this)">
        <button class="mini"
          onclick="document.getElementById('ota-fil').click()">
          Last opp firmware…</button>
        <span class="hint">${stat}</span>
      </div>` + otaKoHtml(ko) + `</div>`;
  }

  // Master-kortet
  // Byggestempel-sammenlikning enhet vs. opplastet binær: markerer
  // kortene som gjenstår etter en OTA-runde. Stemplene er ÅÅÅÅMMDDTTMM,
  // så vanlig strengsammenlikning gir riktig kronologi. Uten stempel
  // på en av sidene (manuell opplasting / gammel fw) vises ingenting.
  const fwEldre = (bygget, fn) => {
    const s = ota[fn] && ota[fn].stempel;
    return s && bygget && bygget < s
      ? ` <span class="off">oppdatering tilgjengelig (${s})</span>` : ``;
  };
  {
    // Ferskhet: retained «online» tros bare når masterens 10 s-puls
    // på adminplanet (info/roster) faktisk kommer inn. En master som
    // har vært stille i 35 s+ vises som stille — uansett hva retained
    // sier. (Det var slik foreldet «online» villedet feilsøkingen.)
    const stille = master.sist_hort_s == null || master.sist_hort_s >= 35;
    const st = master.status === "online" && !stille;
    const inf = master.info || {};
    html += `<div class="card"><h2>MASTER ` +
      (master.mac ? `<span class="hint">${master.mac}</span> ` : "") +
      (st ? `<span class="on">online</span>`
          : master.status === "online" && stille
            ? `<span class="off">ingen livstegn på ${master.sist_hort_s ?? "?"} s — antatt frakoblet</span>`
            : `<span class="off">${master.status || "ukjent"}</span>`) +
      (inf.fw !== undefined
        ? ` <span class="hint">fw v${inf.fw}` +
          (inf.bygget ? ` · ${inf.bygget}` : ``) + `</span>` +
          fwEldre(inf.bygget, fwFil)
        : (st ? ` <span class="off">fw ukjent (gammel firmware?)</span>`
              : ``)) +
      `</h2><p class="hint">` +
      (inf.uptime !== undefined
        ? `oppetid ${inf.uptime}s · puls ${inf.pulse} · wifi ${inf.rssi} dBm · ` +
          `${inf.nodes} noder kjent`
        : `ingen info mottatt ennå`) +
      `</p>`;
    for (const m of master.meldinger || [])
      html += `<p><span class="off">⚠ ${m.tekst}</span> <span class="hint">(` +
        fmtSek(Date.now() / 1000 - m.ts) + ` siden)</span></p>`;
    if (ota[fwFil] && st)
      html += `<div class="bar" style="margin:8px 0 4px">
        ${ko.kjorer ? `` : `<button class="mini" onclick="otaStart('master')">Oppdater fw</button>`}
      </div>`;
    html += `<p class="hint">Bytte av master krever ingen konfigurasjon:
      skru av den gamle, hold frontknappen på en hvilken som helst
      reservenode inne i 3 s mens strømmen kobles til (fiolett lys
      kvitterer) — den nye masteren henter konfigurasjonen selv fra
      brokeren.</p></div>`;
  }

  const rosterFersk = master.sist_hort_s != null && master.sist_hort_s < 35;
  for (const n of nodes.nodes || []) {
    const alias = aliasFor(n.mac);
    html += `<div class="card"><h2>` +
      (alias ? `${alias} <span class="hint">${n.mac}</span> ` : `${n.mac} `) +
      (!rosterFersk
         ? `<span class="off">ukjent — master stille</span>`
         : n.online ? `<span class="on">online</span>`
                    : `<span class="off">offline</span>`) +
      (n.safe ? ` <span class="off">SIKKER TILSTAND</span>` : "") +
      (n.fw ? ` <span class="hint">fw v${n.fw}` +
              (n.bygget ? ` · ${n.bygget}` : ``) + `</span>` +
              fwEldre(n.bygget, fwFil)
            : ` <span class="off">fw ukjent (gammel firmware?)</span>`) +
      `</h2>
      <div class="bar" style="margin:8px 0 4px">
        <input style="max-width:220px;text-transform:uppercase"
               id="alias-${attr(n.mac)}" value="${attr(alias)}"
               placeholder="kallenavn, f.eks. SEKSJON1">
        <button class="mini" onclick="saveAlias('${n.mac}')">Lagre navn</button>
        <button class="mini" onclick="findNode('${n.mac}')">Finn (blink)</button>
        <button class="mini" onclick="forgetNode('${n.mac}')">Fjern node</button>` +
      // Noder oppdateres fra OTA-køen. Knappen står bare igjen for
      // noder UTEN byggestempel (svært gammel firmware): køen kan ikke
      // se når de er ferdige, og tar dem derfor ikke med.
      (ota[fwFil] && n.online && !n.bygget && !ko.kjorer ? `
        <button class="mini" onclick="otaStart('${n.mac}')">Oppdater fw</button>`
                            : ``) + `
      </div>` +
      // Portene står IKKE her lenger. Kabling-siden viser de samme
      // bindingene som et rutenett per brikke — med litra, symbol,
      // lampespenn og ledige porter. To lister over det samme går før
      // eller siden i utakt, og rutenettet er den som også viser
      // FORMEN på brikken.
      `<p class="hint">Porter og bindinger: se
       <a href="#kabling" onclick="gaaTilFane('kabling')">Kabling</a>.
       Noden meldte ` +
      ((n.i2c || []).length ? `<b>${(n.i2c || []).join(", ")}</b>`
                            : `ingen I2C-brikker`) +
      (n.fw >= 4 ? ` — GPIO finnes alltid` : ``) + `.</p>`;
    // Utganger via driver (nodekortet): én bryter per PCA9685. Noden
    // må ha kallenavn, for det er der valget lagres.
    const pca = (n.i2c || []).filter(a => /^0x4[0-3]$/.test(a));
    if (pca.length) {
      const drv = (alias && NODER[alias].driver) || [];
      html += `<p class="hint">Utganger via driver ` +
        pca.map(a => `<label style="white-space:nowrap;margin-left:10px"
          title="PÅ: kanalene går gjennom lampedriver (TBD62083/ULN2803) som trekker lasten til jord, og lampene sendes aktiv høy. AV: lampene er koblet felles anode rett på brikken.">
          <input type="checkbox" ${drv.includes(a) ? "checked" : ""}
                 ${alias ? "" : "disabled"}
                 onchange="settDriver('${n.mac}','${a}',this)"> ${a}</label>`)
           .join("") +
        (alias ? `` : ` — gi noden et kallenavn først`) + `</p>`;
    }
    html += `</div>`;   // .card
  }
  // Lampeprøve
  html += `<div class="card"><h2>Lampeprøve</h2>
    <p class="hint">Slukker alle lamper, blinker alle tre ganger i takt,
    og kjører så løpelys (0,5 s per lampe) til Stopp trykkes — lampen
    som lyser i stoppøyeblikket slukkes umiddelbart. Etterpå
    gjenoppretter master signalbildene automatisk.</p>
    <div class="bar" style="margin:8px 0 4px">
      <button class="mini" onclick="lampTest('start')">Start</button>
      <button class="mini" onclick="lampTest('stop')">Stopp</button>
      <span class="hint">` +
    (lt.running ? `pågår: ${lt.i}/${lt.total} — ${lt.progress}`
                : (lt.total ? `sist: ${lt.i}/${lt.total} (${lt.progress})` : "")) +
    `</span></div></div>`;
  // Foreldreløse kallenavn: peker på MAC-er master ikke kjenner
  // (aldri sett, eller glemt). Vises så de kan ryddes bort.
  const kjenteMac = new Set((nodes.nodes || []).map(n => n.mac));
  for (const [alias, v] of Object.entries(NODER)) {
    if (kjenteMac.has(v.mac)) continue;
    html += `<div class="card"><h2>${alias} ` +
      `<span class="hint">${v.mac}</span> ` +
      `<span class="off">aldri sett</span></h2>
      <p class="hint">Kallenavnet peker på en MAC som ikke er registrert
      hos master. Sett samme navn på en ny enhet fra kortet dens, eller
      slett kallenavnet her.</p>
      <div class="bar" style="margin:8px 0 4px">
        <button class="mini" onclick="deleteAlias('${v.mac}')">
          Slett kallenavn</button>
      </div></div>`;
  }

  // LED-tegnforklaring — operatøren skal slippe å huske fargespråket
  const dot = c => `<span style="color:${c};font-size:14px">●</span>`;
  html += `<div class="card"><h2>LED-språk <span class="hint">M5 AtomS3</span></h2>
    <p class="hint">Blink i sekundtakt = pulsen flyter (anleggets EKG);
    fast lys = låst tilstand. Pustende lys = aktiv søking.</p>
    <p class="hint"><b>Master:</b>
      ${dot("#4a90d9")} blink = alt vel &nbsp;
      ${dot("#e05252")} blink = node savnet/sikker tilstand &nbsp;
      ${dot("#e08a3c")} blink = wifi/MQTT nede &nbsp;
      ${dot("#b46be0")} blink = mangler konfig &nbsp;
      ${dot("#e05252")}${dot("#e05252")} dobbelt = TO mastere! &nbsp;
      ${dot("#3cc8c8")} fast = OTA pågår</p>
    <p class="hint"><b>Node:</b>
      ${dot("#5bb974")} blink = normal drift &nbsp;
      ${dot("#e0c23c")} blink = «Finn meg» &nbsp;
      ${dot("#e052e0")}${dot("#e052e0")} dobbelt = I2C-feil &nbsp;
      ${dot("#e05252")} fast = sikker tilstand &nbsp;
      ${dot("#e0c23c")} pustende = søker master &nbsp;
      ${dot("#3cc8c8")} fast = OTA pågår</p>
    <p class="hint"><b>Begge:</b> ${dot("#eeeeee")} fast hvitt under
      holdt knapp (10 s+) = slipp for å nullstille paringen.</p></div>`;

  // Hendelseslogg (svart boks) — alt på MQTT-flaten, én linje per
  // hendelse. Fylles av hentHendelser() etter render.
  html += `<div class="card"><h2>Hendelseslogg
      <span class="hint">svart boks</span></h2>
    <p class="hint">Alle hendelser på anlegget — togveier, signaler,
    sporfelt, betjening, driftsmeldinger — med tidsstempel. Nyeste
    nederst. Filteret matcher tema og innhold (f.eks. «togvei/A-01»,
    «avvist», «sporveksel»). Loggingen er AV som standard — slå den
    på ved feilsøking, innkjøring eller treff (skriver til SD-kortet;
    valget huskes over restart, og loggen beholdes når den slås av).</p>
    <div class="bar" style="margin:8px 0 4px">
      <label class="hint" style="white-space:nowrap">
        <input type="checkbox" id="h-aktiv"
               onchange="hendelserAktiv(this.checked)"> logging på</label>
      <input id="h-filter" placeholder="filter" style="max-width:220px"
             onkeydown="if(event.key==='Enter')hentHendelser()">
      <button class="mini" onclick="hentHendelser()">Oppdater</button>
      <a class="mini" href="/api/hendelser/fil" download
         style="text-decoration:none">Last ned alt</a>
      <span class="hint" id="h-antall"></span>
    </div>
    <div id="h-liste" style="max-height:320px;overflow:auto;
         font-family:monospace;font-size:12px;white-space:pre"></div>
    </div>`;

  sec.innerHTML = html || `<p class="hint">Ingen noder registrert ennå.</p>`;
  hentHendelser();
}
async function hentHendelser() {
  const el = document.getElementById("h-liste");
  if (!el) return;
  const filt = (document.getElementById("h-filter") || {}).value || "";
  const r = await fetch("/api/hendelser?n=300&filter=" +
                        encodeURIComponent(filt));
  const j = await apiJson(r);
  if (!r.ok) { el.textContent = j.error || "feil"; return; }
  const rad = h => {
    const d = new Date(h.ts * 1000);
    const t = d.toTimeString().slice(0, 8) + "." +
              String(d.getMilliseconds()).padStart(3, "0");
    return t + "  " + h.tema.padEnd(28) + "  " +
           (typeof h.data === "string" ? h.data : JSON.stringify(h.data)) +
           (h.r ? "   (retained)" : "");
  };
  el.textContent = (j.hendelser || []).map(rad).join("\n") ||
                   (j.aktiv ? "(ingen hendelser matcher)"
                            : "(logging er av — slå den på over)");
  el.scrollTop = el.scrollHeight;   // nyeste nederst — vis dem
  const cb = document.getElementById("h-aktiv");
  if (cb) cb.checked = !!j.aktiv;
  const an = document.getElementById("h-antall");
  if (an) an.textContent = (j.hendelser || []).length + " hendelser" +
                           (j.kuttet ? " (av flere — bruk Last ned alt)" : "");
}
async function hendelserAktiv(paa) {
  await fetch("/api/hendelser/aktiv", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({aktiv: paa})});
  hentHendelser();
}
async function deleteAlias(mac) {
  if (!confirm("Slette kallenavnet? Bindinger som bruker det vil vise " +
               "'(ukjent)' til de peker et annet sted.")) return;
  await fetch("/api/node-alias", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({mac, alias: ""})});
  await loadAll();
  renderNoder();
}
async function otaLastOpp(input) {
  const file = input.files[0];
  input.value = "";
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch("/api/ota/firmware", {method: "POST", body: fd});
  const j = await apiJson(r);
  if (!r.ok) { toast(j.error, true); return; }
  toast("Mottatt: " + j.fil +
        (j.stempel ? " (bygget " + j.stempel + ")" : " (uten stempel)"));
  renderNoder();
}
// Ikke-blokkerende melding nederst i vinduet — erstatter alert() for
// info og feil. confirm() beholdes bare der noe slettes/overskrives,
// og alert() bare ved AP-navnebytte (nettet restarter — meldingen MÅ
// leses før siden mister kontakten).
function toast(tekst, feil) {
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    el.onclick = () => { el.style.display = "none"; };
    document.body.appendChild(el);
  }
  el.textContent = tekst;
  el.style.cssText = "position:fixed;left:50%;bottom:24px;" +
    "transform:translateX(-50%);max-width:80%;z-index:99;" +
    "padding:10px 16px;border-radius:8px;cursor:pointer;" +
    "box-shadow:0 4px 16px rgba(0,0,0,.4);display:block;" +
    (feil ? "background:#5a1f1f;color:#ffb3b3;"
          : "background:#1f3a5a;color:#cfe4ff;");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.style.display = "none"; }, 6000);
}
// Masterens siste svar per togvei — vises som stille statuslinje i
// togveikortet (ingen popup). Overlever frRender via denne cachen.
const TVSVAR = {};
function visTvSvar(id, tekst) {
  TVSVAR[id] = tekst;
  const el = document.getElementById("tvsvar-" + id);
  if (el) {
    el.textContent = tekst;
    el.className = /^avvist/.test(tekst) ? "off" : "hint";
  }
}
async function betjenTogvei(id, hva) {
  visTvSvar(id, "…");
  const j = await apiJson(await fetch("/api/togvei-betjen", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({id, hva})}));
  // Masterens begrunnelse (fanget fra nsi63/togvei/<id>/info av
  // serveren): «sikret: kjorsignal satt», «avvist: …», «trinn 1:
  // signal i stopp …» osv. — aldri en popup som må kvitteres.
  visTvSvar(id, j.error ? "avvist: " + j.error
    : j.svar ? j.svar
    : "ingen svar fra master — sikring kan pågå (veksler legges om), " +
      "eller masteren er frakoblet");
}
// ---------- OTA-køen: alle utdaterte noder, én om gangen ----------
function otaKoNavn(n) { return attr(n.alias || n.mac); }
function otaKoHtml(ko) {
  if (!ko) return ``;
  let h = `<div style="margin-top:8px">`;
  if (ko.kjorer) {
    const nr = ko.ferdig.length + ko.feilet.length + (ko.aktiv ? 1 : 0);
    h += `<p><b>Oppdaterer noder: ${nr} av ${ko.antall}</b>` +
      (ko.aktiv ? ` — nå: ${otaKoNavn(ko.aktiv)}` : ``) +
      (ko.stopp ? ` <span class="off">stopper etter denne</span>` : ``) +
      `</p>` + (ko.stopp ? `` :
      `<button class="mini" onclick="otaKoStopp()">Stopp etter denne</button>`);
  } else if (ko.kandidater.length) {
    h += `<div class="bar" style="margin:0 0 4px">` +
      (ko.hindring
        ? `<span class="hint">${ko.kandidater.length} utdaterte noder — ` +
          `kan ikke kjøre køen nå: ${attr(ko.hindring)}</span>`
        : `<button class="mini" onclick="otaKoStart(${ko.kandidater.length})">
             Oppdater alle utdaterte noder (${ko.kandidater.length})</button>
           <span class="hint">én om gangen, neste når forrige har meldt
           seg tilbake med ny firmware</span>`) +
      `</div>`;
  } else {
    // Ingen kandidater: si HVORFOR, så funksjonen ikke er usynlig.
    // Den vanligste grunnen er at alle allerede er oppdatert.
    const stp = ko.fw_stempel;
    h += `<p class="hint">Oppdater alle noder: ` +
      (!ko.fw_finnes ? `last opp firmware først`
       : !stp ? `firmwaren mangler byggestempel (bygg med bygg-ota.sh), ` +
                `så køen kan ikke se hvem som er utdatert`
       : `alle online noder har ${attr(stp)} — ingenting å oppdatere`) +
      `</p>`;
  }
  // Siste kjøring (også mens den pågår)
  const rad = (n, tekst, kl) =>
    `<li><span class="${kl}">${otaKoNavn(n)}</span> ${tekst}</li>`;
  const linjer = [
    ...ko.ferdig.map(n => rad(n, `oppdatert (${n.sekunder} s)`, "on")),
    ...ko.feilet.map(n => rad(n, attr(n.grunn), "off")),
    ...(ko.aktiv ? [rad(ko.aktiv, `henter firmware…`, "hint")] : []),
    ...ko.venter.map(n => rad(n, `venter`, "hint")),
    ...ko.avbrutt.map(n => rad(n, `avbrutt`, "hint")),
  ];
  if (linjer.length)
    h += `<ul class="hint" style="margin:4px 0 0 18px;padding:0">` +
         linjer.join("") + `</ul>`;
  return h + `</div>`;
}
async function otaKoStart(antall) {
  if (!confirm(`Oppdatere ${antall} node${antall === 1 ? "" : "r"}, én om ` +
               `gangen?\n\nHver node er mørk (= stopp) i ~1 min mens den ` +
               `henter firmware. Master oppdateres ikke av køen.`)) return;
  const r = await fetch("/api/ota/ko", {method: "POST"});
  const j = await apiJson(r);
  if (!r.ok) { toast(j.error, true); return; }
  toast(`OTA-kø startet: ${j.antall} noder`);
  oppdaterOtaBanner();
  renderNoder();
}
async function otaKoStopp() {
  const r = await fetch("/api/ota/ko/stopp", {method: "POST"});
  const j = await apiJson(r);
  if (!r.ok) { toast(j.error, true); return; }
  toast("OTA-køen stopper når noden som oppdateres nå er ferdig");
  oppdaterOtaBanner();
}
// Banner på ALLE faner mens køen går: noder er mørke underveis, og det
// skal ikke kunne overses fra Forrigling-fanen
async function oppdaterOtaBanner() {
  let ko;
  try { ko = await (await fetch("/api/ota/ko")).json(); }
  catch (e) { return; }
  const b = document.getElementById("otabanner");
  if (!b) return;
  if (!ko.kjorer) { b.style.display = "none"; return; }
  const nr = ko.ferdig.length + ko.feilet.length + (ko.aktiv ? 1 : 0);
  document.getElementById("otabanner-txt").textContent =
    `node ${nr} av ${ko.antall}` +
    (ko.aktiv ? ` (${ko.aktiv.alias || ko.aktiv.mac})` : ``) +
    (ko.feilet.length ? ` · ${ko.feilet.length} feilet` : ``) +
    (ko.stopp ? ` · stopper etter denne` : ``);
  document.getElementById("otabanner-stopp").style.display =
    ko.stopp ? "none" : "";
  b.style.display = "";
}

async function otaStart(maal) {
  const hvem = maal === "master"
    ? "master? Hele anlegget går i sikker tilstand ~1 min og henter " +
      "seg inn selv etterpå"
    : "noden " + maal + "? Den er mørk (= stopp) i ~1 min";
  if (!confirm("Starte trådløs firmwareoppdatering av " + hvem + ".")) return;
  const r = await fetch("/api/ota/start", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({maal})});
  const j = await apiJson(r);
  if (!r.ok) { toast(j.error, true); return; }
  renderNoder();
}
// Snarvei fra banneret: skru av omgåelsen uten å lete opp Noder-fanen
async function slaAvTestmodus() {
  const an = await (await fetch("/api/anlegg")).json();
  const r = await fetch("/api/anlegg", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({id: an.id, adopter: an.adopter,
                          fjernstyrt: an.fjernstyrt,
                          dekningsstilling: an.dekningsstilling,
                          tider: an.tider,
                          testmodus: false})});
  const j = await apiJson(r);
  if (!r.ok) { toast(j.error, true); return; }
  document.getElementById("testbanner").style.display = "none";
  if (currentView === "noder") renderNoder();
}
async function saveAnlegg() {
  const id = document.getElementById("anlegg-id").value.trim().toUpperCase();
  const adopter = document.getElementById("anlegg-adopter").checked;
  const testmodus = document.getElementById("anlegg-test").checked;
  const fjernstyrt = document.getElementById("anlegg-fjern").checked;
  const dekningsstilling = document.getElementById("anlegg-dekning").checked;
  const vis_sim = document.getElementById("anlegg-vis-sim").checked;
  const navn = document.getElementById("anlegg-navn").value.trim();
  const nabo_venstre = document.getElementById("anlegg-nabo-v").value.trim();
  const nabo_hoyre = document.getElementById("anlegg-nabo-h").value.trim();
  // Tidslåsene: les feltene som FINNES. Kortet tegnes av serverens
  // beskrivelse, så en ny tidslås dukker opp her av seg selv.
  //
  // Et TOMT eller ugyldig felt avviser lagringen. Før ble det 0, og for
  // tidslåsene der 0 betyr «av» (hjelpeutløsningens tidsrelé, Lok-
  // etterløpet) slo et tømt felt av en sikkerhetstidslås uten varsel.
  // Vil man ha den av, skriver man 0 selv.
  const tider = {};
  for (const e of document.querySelectorAll('[id^="tid-"]')) {
    const v = e.value.trim();
    if (!/^\d+$/.test(v)) {
      toast(`Tidslåsen «${e.id.slice(4)}» må ha et tall (0 = av)`, true);
      e.focus();
      return;
    }
    tider[e.id.slice(4)] = parseInt(v, 10);
  }
  const r = await fetch("/api/anlegg", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({id, navn, nabo_venstre, nabo_hoyre,
                          adopter, testmodus, fjernstyrt,
                          dekningsstilling, vis_sim, tider})});
  const j = await apiJson(r);
  if (!r.ok) { toast(j.error, true); return; }
  settTittel(j.id);
  if (j.ap_omdopt)
    alert("AP-et heter nå «" + j.ssid + "» — wifi-nettet du er koblet " +
          "til startet på nytt med nytt navn. Koble denne enheten til " +
          "det nye nettet og last siden på nytt (http://" + j.hostname +
          ".local:8080 eller 10.206.0.1:8080). Master og noder finner " +
          "frem selv.");
  renderNoder();
}
function settTittel(id) {
  const navn = "NSI63" + (id || "");
  document.title = navn + " — sikringsanlegg";
  const h1 = document.getElementById("tittel");
  if (h1 && h1.childNodes.length) h1.childNodes[0].textContent = navn;
}
async function saveAlias(mac) {
  const alias = document.getElementById("alias-" + mac)
                  .value.trim().toUpperCase();
  const r = await fetch("/api/node-alias", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({mac, alias})});
  const j = await apiJson(r);
  if (!r.ok) { toast(j.error, true); return; }
  await loadAll();          // bindingstabellen bruker nye kallenavn
  renderNoder();
}
// ---------- Forrigling: togvei-editor (modellbasert) ----------
let TOGVEIER = [];
let HALFN = [];   // HAL-funksjoner til nedtrekkene

function frLitraer(types) {
  return HALFN.filter(f => types.includes(f.type)).map(f => f.id);
}
function frTogspor() {
  return HALFN.filter(f => f.type === "sporfelt" && f.rolle === "togspor")
              .map(f => f.id);
}
function frEndeFelt() {   // lovlige rute-ender: linjefelt og togspor
  return HALFN.filter(f => f.type === "sporfelt" &&
    (f.rolle === "linjefelt" || f.rolle === "togspor")).map(f => f.id);
}
// Signalet avledes av endene: én kandidat = etikett, flere = valg
// blant kandidatene, ingen = veiledning (sett rolle/linjefelt på
// hovedsignalet under Objekter)
function frSignalCelle(tv, i) {
  const r = frRetning(tv);
  if (!r) return `<span class="hint">velg fra- og til-felt</span>`;
  const kand = frStartKandidater(tv);
  if (!kand.length)
    return `<span class="off">ingen ${r === "indre" ? "indre " : ""}` +
           `hovedsignal${r === "indre" ? "" : " ved " +
           (r === "innkjor" ? tv.fra : tv.til)} — sett rolle` +
           `${r === "indre" ? "" : "/linjefelt"} under Objekter</span>`;
  if (kand.length === 1)
    return `<span class="hint">signal:</span> <b>${kand[0]}</b>`;
  return `<span class="hint">signal:</span>
    <select style="max-width:150px"
            onchange="TOGVEIER[${i}].start=this.value;frRender()">
      ${kand.map(k => opt(k, k, tv.start)).join("")}</select>`;
}
async function frLoad() {
  const [hal, fr] = await Promise.all([
    (await fetch("/api/hal")).json(),
    (await fetch("/api/forrigling")).json(),
  ]);
  HALFN = hal.functions || [];
  TOGVEIER = fr.togveier || [];
  STATUS.fr = fr.version;
  STATUS.frAntall = TOGVEIER.length;
  oppdaterStatus();
  frRender();
}
function frSel(litraer, sel, allowEmpty) {
  let out = allowEmpty ? opt("", "—", sel) : "";
  for (const l of litraer) out += opt(l, l, sel);
  if (sel && !litraer.includes(sel)) out += opt(sel, sel + " (ukjent)", sel);
  return out;
}
function frBilde(tv) {
  const st = HALFN.find(f => f.id === tv.start &&
    erHoved(f.type));
  if (st && st.type === "hovedsignal2") return "kjor-redusert";  // tolys
  return (tv.sporveksler || []).some(v => v.stilling === "avvik")
    ? "kjor-redusert" : "kjor";
}
// Togvei-ID genereres av rute-endene, som i togveitabellene i
// forbildet: innkjør = <linjefelt><spor> (A01), utkjør =
// <spor><linjefelt> (01A). Retningen leses av startsignalets rolle,
// linjefeltet finnes blant de frie feltene.
function frGenId(tv) {
  frEnder(tv);
  return frRetning(tv) ? tv.fra + tv.til : "";
}
// En togvei går FRA et sporfelt TIL et sporfelt (som i forbildet):
// linjefelt→togspor = innkjør, togspor→linjefelt = utkjør,
// togspor→togspor = indre (større stasjoner). Signal, ID, frie felt
// og utløsningsfelt avledes av endene.
function feltRolle(id) {
  const f = HALFN.find(x => x.type === "sporfelt" && x.id === id);
  return f ? (f.rolle || "") : "";
}
function frRetning(tv) {
  const fr = feltRolle(tv.fra), tl = feltRolle(tv.til);
  if (fr === "linjefelt" && tl === "togspor") return "innkjor";
  if (fr === "togspor" && tl === "linjefelt") return "utkjor";
  if (fr === "togspor" && tl === "togspor" && tv.fra !== tv.til)
    return "indre";
  return "";
}
// Eldre rader (uten fra/til) migreres ved visning: endene regnes ut
// av startsignalets rolle + feltlisten
function frEnder(tv) {
  if (tv.fra && tv.til) return;
  const st = HALFN.find(f => erHoved(f.type) && f.id === tv.start) || {};
  const linje = (tv.frie || []).find(x =>
    feltRolle(x) === "linjefelt") || "";
  if (st.rolle === "innkjor") { tv.fra = linje; tv.til = tv.spor || ""; }
  else if (st.rolle === "utkjor") { tv.fra = tv.spor || ""; tv.til = linje; }
}
// Hovedsignal-kandidater for ruten: rolle + linjefelt-tilhørighet.
// Signaler med linjefelt satt foretrekkes; uten satt tilhørighet
// godtas som reserve (ukoblede eldre konfigurasjoner).
function frStartKandidater(tv) {
  const r = frRetning(tv);
  if (!r) return [];
  if (r === "indre")
    return HALFN.filter(f => erHoved(f.type) && f.rolle === "indre")
                .map(f => f.id);
  const mål = r === "innkjor" ? tv.fra : tv.til;
  const kand = HALFN.filter(f => erHoved(f.type) && f.rolle === r);
  const eksakte = kand.filter(f => f.linjefelt === mål);
  const uten = kand.filter(f => !f.linjefelt);
  return (eksakte.length ? eksakte : uten).map(f => f.id);
}
function frAutoFelt(tv) {
  frEnder(tv);
  const r = frRetning(tv);
  if (!r) return null;
  const vfelt = (tv.sporveksler || []).map(v => v.sporveksel).filter(x =>
    x && HALFN.some(f => f.type === "sporfelt" && f.id === x));
  if (r !== "indre" && !vfelt.length) return null;
  if (r === "innkjor")
    return {frie: [tv.fra, ...vfelt, tv.til], utlos: vfelt[0]};
  return {frie: [...vfelt, tv.til], utlos: vfelt[0] || ""};
}
// Minstekrav for togveier: ett linjefelt, TO togspor og en veksel —
// med bare ett togspor finnes det ingenting å forrigle (en
// endestasjon har ett linjefelt, men fortsatt flere togspor)
function frKrav() {
  const mangler = [];
  if (!HALFN.some(f => f.type === "sporfelt" && f.rolle === "linjefelt"))
    mangler.push("et linjefelt");
  const nSpor = HALFN.filter(f => f.type === "sporfelt" &&
                                  f.rolle === "togspor").length;
  if (nSpor < 2)
    mangler.push(nSpor ? "ett togspor til (minst to)" : "to togspor");
  if (!HALFN.some(f => f.type === "sporveksel"))
    mangler.push("en veksel");
  return mangler;
}
// ---- fiendtlighetsmatrise ----
// Speiler masterens fiendtlige() NØYAKTIG: samme startsignal, delt
// sporfelt, eller samme veksel krevd i ULIK stilling. Samme veksel i
// samme stilling er IKKE fiendtlig — begge togveier vil det samme.
// Matrisen er utledet av tabellen, ikke konfigurert; den viser hva
// forriglingen faktisk vil avvise, ikke hva noen har skrevet ned.
function frFiendtlig(a, b) {
  const grunner = [];
  if (a.start && a.start === b.start)
    grunner.push("samme startsignal " + a.start);
  const felles = (a.frie || []).filter(f => (b.frie || []).includes(f));
  if (felles.length) grunner.push("deler sporfelt " + felles.join(", "));
  for (const va of a.sporveksler || [])
    for (const vb of b.sporveksler || [])
      if (va.sporveksel === vb.sporveksel && va.stilling !== vb.stilling)
        grunner.push("veksel " + va.sporveksel + ": " +
                     va.stilling + " mot " + vb.stilling);
  return grunner;
}
function frMatrise() {
  const el = document.getElementById("fr-matrise");
  if (!el) return;
  const tv = TOGVEIER.filter(t => t.id);
  if (tv.length < 2) {
    el.innerHTML = '<span class="hint">trenger minst to togveier</span>';
    return;
  }
  let h = '<table class="matrise"><thead><tr><th></th>';
  for (const b of tv) h += `<th>${attr(b.id)}</th>`;
  h += "</tr></thead><tbody>";
  for (const a of tv) {
    h += `<tr><th>${attr(a.id)}</th>`;
    for (const b of tv) {
      if (a === b) { h += '<td class="m-selv">·</td>'; continue; }
      const g = frFiendtlig(a, b);
      h += g.length
        ? `<td class="m-fiendtlig" title="${attr(g.join(" · "))}">✕</td>`
        : '<td class="m-ok"></td>';
    }
    h += "</tr>";
  }
  el.innerHTML = h + "</tbody></table>" +
    '<p class="hint">✕ = kan ikke stå samtidig. Hold over for ' +
    'begrunnelsen. Tomt felt = forenlige.</p>';
}
function frRender() {
  // Normalisering per rad: migrer eldre rader til fra/til, avled
  // spor og startsignal av endene, og fyll tomme felt-lister.
  // Manuelle felt-valg røres aldri (auto-knappen overskriver).
  TOGVEIER.forEach(tv => {
    frEnder(tv);
    const r = frRetning(tv);
    if (r) {
      tv.spor = (r === "utkjor") ? tv.fra : tv.til;
      const kand = frStartKandidater(tv);
      if (kand.length && !kand.includes(tv.start)) tv.start = kand[0];
      // Ingen kandidat: tøm startsignalet, så det cellen viser
      // («ingen hovedsignal») også er det som lagres — og lagringen
      // nekter til objekttabellen har et hovedsignal for enden. Før ble
      // det gamle startsignalet stille beholdt, også fra motsatt ende.
      if (!kand.length) tv.start = "";
    }
    if ((tv.frie || []).filter(Boolean).length === 0) {
      const a = frAutoFelt(tv);
      if (a) {
        tv.frie = a.frie;
        if (!tv.utlosningsfelt) tv.utlosningsfelt = a.utlos;
      }
    }
  });
  const hoved = frLitraer(TYPES.filter(erHoved));
  const veksler = frLitraer(["sporveksel"]);   // manuellveksel: se validering
  const felt = frLitraer(["sporfelt"]);
  const laasgrupper = frLitraer(["samlelaas", "rigel"]);
  let html = "";
  TOGVEIER.forEach((tv, i) => {
    const gid = frGenId(tv) || tv.id || "";
    html += `<div class="card">
      <div class="bar" style="margin:0 0 8px">
        <b style="min-width:64px" title="Genereres automatisk av fra+til">${gid || "—"}</b>
        <select style="max-width:110px" title="Feltet togveien går FRA: linjefelt (innkjør) eller togspor (utkjør/indre)"
                onchange="TOGVEIER[${i}].fra=this.value;frRender()">
          ${frSel(frEndeFelt(), tv.fra||"", true).replace('">—<',
            '">fra: —<')}</select>
        <span class="hint">→</span>
        <select style="max-width:110px" title="Feltet togveien går TIL: togspor (innkjør/indre) eller linjefelt (utkjør)"
                onchange="TOGVEIER[${i}].til=this.value;frRender()">
          ${frSel(frEndeFelt(), tv.til||"", true).replace('">—<',
            '">til: —<')}</select>
        ${frSignalCelle(tv, i)}
        <input style="flex:1" value="${tv.notes||""}" placeholder="notat"
               onchange="TOGVEIER[${i}].notes=this.value.trim()">
        <span class="hint">bilde: ${frBilde(tv)}</span>
        <button class="mini" ${gid ? "" : "disabled"} title="Be master sikre togveien: forriglingen kontrollerer felt, fiendtlighet, frigivning og skifting, legger vekslene én om gangen og setter kjørsignal. Masterens svar vises på linjen under."
                onclick="betjenTogvei('${gid}', 'sikre')">Sikre</button>
        <button class="mini" ${gid ? "" : "disabled"} title="Hjelpeutløsning trinn 1: setter togveiens startsignal i stopp — togveien er fortsatt forriglet. Som togveistillerne MOT hverandre. (Ikke det samme som signalstopp-bryteren, som sperrer hele anlegget.)"
                onclick="betjenTogvei('${gid}', 'stopp')">Stopp</button>
        <button class="mini" ${gid ? "" : "disabled"} title="Hjelpeutløsning trinn 2: løser ut togveien. Avvises så lenge startsignalet viser kjørsignal — bruk Stopp først. Under sikring løses den ut direkte. Driftsbetjening: uten stillerapparatets 90 s tidsrelé."
                onclick="betjenTogvei('${gid}', 'hjelpeutlos')">Utløs</button>
        <button class="row-del" onclick="TOGVEIER.splice(${i},1);frRender()">✕</button>
      </div>
      <div class="bar" style="margin:0 0 4px">
        <span id="tvsvar-${gid}" class="${/^avvist/.test(TVSVAR[gid] || "") ? "off" : "hint"}">${TVSVAR[gid] || ""}</span>
      </div>
      <div class="bar" style="margin:4px 0">
        <span class="hint" style="min-width:90px">Veksler:</span>` +
      (tv.sporveksler||[]).map((v, j) => `
        <select style="max-width:130px" onchange="TOGVEIER[${i}].sporveksler[${j}].sporveksel=this.value;frRender()">
          ${frSel(veksler, v.sporveksel||"", true)}</select>
        <select style="max-width:100px" onchange="TOGVEIER[${i}].sporveksler[${j}].stilling=this.value;frRender()">
          ${opt("normal","normal",v.stilling)}${opt("avvik","avvik",v.stilling)}</select>
        <button class="row-del" onclick="TOGVEIER[${i}].sporveksler.splice(${j},1);frRender()">✕</button>`).join("") +
      `<button class="mini" onclick="(TOGVEIER[${i}].sporveksler=TOGVEIER[${i}].sporveksler||[]).push({sporveksel:'',stilling:'normal'});frRender()">+</button>
      </div>
      <div class="bar" style="margin:4px 0">
        <span class="hint" style="min-width:90px">Frie sporfelt:</span>
        <button class="mini" title="Avled feltene av endene: linjefelt + vekselfelt + togspor (innkjør) / vekselfelt + linjefelt (utkjør). Overskriver listen."
                onclick="frAutoFyll(${i})">auto</button>` +
      (tv.frie||[]).map((sf, j) =>
        `<span>${sf} <button class="row-del" onclick="TOGVEIER[${i}].frie.splice(${j},1);frRender()">✕</button></span>`).join("") +
      `<select style="max-width:130px" onchange="if(this.value){(TOGVEIER[${i}].frie=TOGVEIER[${i}].frie||[]).push(this.value);frRender()}">
        ${frSel(felt.filter(f=>!(tv.frie||[]).includes(f)), "", true)}</select>
      </div>
      <div class="bar" style="margin:4px 0">
        <span class="hint" style="min-width:90px"
              title="Låsegrupper (samlelås/rigel) som må være SPERRET for at togveien kan sikres. Slik kommer en håndstilt veksel inn i forriglingen: anlegget kan ikke kaste den, men låsen som holder den garanterer stillingen — og DEN kan anlegget kreve. Samme relasjon leses motsatt vei: låsen kan ikke frigis mens denne togveien er forriglet.">Krever låst:</span>` +
      (tv.laaser||[]).map((lg, j) =>
        `<span>${lg} <button class="row-del" onclick="TOGVEIER[${i}].laaser.splice(${j},1);frRender()">✕</button></span>`).join("") +
      `<select style="max-width:130px" onchange="if(this.value){(TOGVEIER[${i}].laaser=TOGVEIER[${i}].laaser||[]).push(this.value);frRender()}">
        ${frSel(laasgrupper.filter(l=>!(tv.laaser||[]).includes(l)), "", true)}</select>
        <span class="hint">tomt = togveien er uavhengig av låsegruppene</span>
      </div>
      <div class="bar" style="margin:4px 0">
        <span class="hint" style="min-width:90px">Utløsningsfelt:</span>
        <select style="max-width:130px" title="Vekselfeltet — belagt og deretter fritt river togveien"
                onchange="TOGVEIER[${i}].utlosningsfelt=this.value;frSkisse()">
          ${frSel(felt, tv.utlosningsfelt||"", true)}</select>
        <span class="hint">signalet faller ved belegg på ETHVERT felt i
        togveien; utløsningsfeltet belagt→fritt = togveien rives.
        Velg vekselfeltet togveien går over — togspor og linjefelt
        blir stående belagt av toget selv, og togveien ville aldri
        (eller for sent) blitt revet.</span>
      </div>
    </div>`;
  });
  const mangler = frKrav();
  const nyKnapp = document.getElementById("fr-ny");
  const kravEl = document.getElementById("fr-krav");
  if (nyKnapp) nyKnapp.disabled = mangler.length > 0;
  if (kravEl) {
    let k = "";
    if (mangler.length)
      k = `togveier trenger minst ${mangler.join(", ")} — legg til ` +
          `under Objekter først`;
    else if (!HALFN.some(f => erHoved(f.type)))
      k = `tips: legg til hovedsignaler (rolle innkjør/utkjør) under ` +
          `Objekter, så avledes signalet automatisk`;
    kravEl.textContent = k;
  }
  document.getElementById("fr-cards").innerHTML =
    html || (mangler.length
      ? `<p class="hint">Ingen togveier ennå. Definer anleggets objekter
         først: sporfelt (linjefelt og togspor), veksler og
         hovedsignaler — så lages togveiene her, fra felt til felt.</p>`
      : `<p class="hint">Ingen togveier ennå — trykk «+ Ny togvei».</p>`);
  frSkisse();
  frKonflikter();
  frMatrise();   // til slutt: id-er kan være utledet underveis
}
// ---- skjematisk skisse avledet av togveitabellen ----
// Én linje per togspor: venstre ende, innkjør-/utkjørsignaler,
// veksler med stilling (n/a), sporet, og det samme speilet mot høyre
// ende. «···» = togvei mangler. Ren dobbeltsjekk — tegnes på nytt
// ved hver endring og avslører hull og feilkoblinger i tabellen.
function frSkisse() {
  const el = document.getElementById("fr-skisse");
  const advEl = document.getElementById("fr-adv");
  if (!el) return;
  // Typede oppslag: litra er unik per objektklasse
  const sigAv = id => HALFN.find(f => f.id === id &&
    erHoved(f.type)) || {};
  const feltAv = id => HALFN.find(f => f.id === id &&
    f.type === "sporfelt") || {};
  const adv = [];

  const ruter = [];
  TOGVEIER.forEach(tv => {
    const id = tv.id || "(uten id)";
    if (!tv.start) { adv.push(`${id}: mangler startsignal`); return; }
    const rolle = sigAv(tv.start).rolle || "";
    if (rolle === "indre") {
      adv.push(`${id}: indre togvei (togspor til togspor) — vises ` +
               `ikke i skissen ennå`);
      return;
    }
    if (rolle !== "innkjor" && rolle !== "utkjor") {
      adv.push(`${id}: startsignalet ${tv.start} mangler rolle ` +
               `innkjør/utkjør under Objekter`);
      return;
    }
    const linje = (tv.frie || [])
      .find(f => feltAv(f).rolle === "linjefelt") || "";
    if (!linje) adv.push(`${id}: ingen av sporfeltene er linjefelt ` +
                         `(sett rolle under Objekter)`);
    if (!tv.spor) adv.push(`${id}: mangler spor`);
    ruter.push({id, retning: rolle, linje, spor: tv.spor || "",
                start: tv.start,
                veksler: (tv.sporveksler || []).filter(v => v.sporveksel)
                  .map(v => v.sporveksel + (v.stilling === "avvik" ? "a" : "n"))});
  });

  const cmp = (a, b) => a.localeCompare(b, "no", {numeric: true});
  const ender = HALFN.filter(f => f.type === "sporfelt" &&
                                  f.rolle === "linjefelt").map(f => f.id);
  ruter.forEach(r => { if (r.linje && !ender.includes(r.linje))
                         ender.push(r.linje); });
  ender.sort(cmp);
  const spor = HALFN.filter(f => f.type === "sporfelt" &&
                                 f.rolle === "togspor").map(f => f.id);
  ruter.forEach(r => { if (r.spor && !spor.includes(r.spor))
                         spor.push(r.spor); });
  spor.sort(cmp);

  if (!spor.length || !ender.length) {
    el.textContent = "(skissen tegnes når togveier med togspor og " +
                     "linjefelt er definert)";
    document.getElementById("fr-tegn").innerHTML = "";
    advEl.innerHTML = adv.map(a => "⚠ " + a).join("<br>");
    return;
  }
  // Endene plasseres etter linjefeltets «side» (settes i HAL);
  // uten side brukes alfabetisk rekkefølge
  let vEnde = ender.find(e => feltAv(e).side === "v") || null;
  let hEnde = ender.find(e => e !== vEnde && feltAv(e).side === "h") || null;
  if (!vEnde) vEnde = ender.find(e => e !== hEnde);
  if (!hEnde) hEnde = ender.find(e => e !== vEnde) || null;
  const utenfor = ender.filter(e => e !== vEnde && e !== hEnde);
  if (utenfor.length)
    adv.push(`flere enn to linjefelt (${utenfor.join(", ")}) — ` +
             `de vises ikke i skissen`);

  const rFor = (linje, sp, retning) => ruter.filter(r =>
    r.linje === linje && r.spor === sp && r.retning === retning);

  // konfliktsjekk: SAMME komplette vekselsett fra samme ende og
  // retning kan ikke føre til ULIKE spor (enkeltveksler kan gjerne
  // deles — det er kombinasjonen som må være entydig)
  const brukt = {};
  ruter.forEach(r => {
    if (!r.linje || !r.spor) return;
    const k = r.linje + "|" + r.retning + "|" +
              r.veksler.slice().sort().join("+");
    (brukt[k] = brukt[k] || new Set()).add(r.spor);
  });
  for (const [k, s] of Object.entries(brukt)) {
    if (s.size > 1) {
      const [linje, , vlist] = k.split("|");
      adv.push(`vekselstillingene [${vlist || "ingen"}] fra ${linje} ` +
               `fører til FLERE spor (${[...s].join(", ")}) — ` +
               `sjekk stillingene`);
    }
  }

  // mangel-advarsler (per spor og ende)
  const knapp = (linje, sp, retning) =>
    ` <button class="mini" onclick="frOpprett('` +
    `${linje.replace(/'/g, "\'")}','${sp.replace(/'/g, "\'")}',` +
    `'${retning}')">opprett</button>`;
  spor.forEach(sp => {
    for (const linje of [vEnde, hEnde]) {
      if (!linje) continue;
      if (!rFor(linje, sp, "innkjor").length)
        adv.push(`${sp}: mangler innkjørtogvei fra ${linje}` +
                 knapp(linje, sp, "innkjor"));
      if (!rFor(linje, sp, "utkjor").length)
        adv.push(`${sp}: mangler utkjørtogvei mot ${linje}` +
                 knapp(linje, sp, "utkjor"));
    }
  });

  // ---- sporplan-tegning ----
  // Signalplassering: innkjør og FELLES utkjør (flere spor) ved enden;
  // utkjørsignal for ETT spor tegnes på sporlinjen.
  const sigEnde = {};   // ende -> {inn:[], ut:[]}
  [vEnde, hEnde].filter(Boolean).forEach(e => sigEnde[e] = {inn: [], ut: []});
  const sigSpor = {};   // spor -> {v:[], h:[]}
  const utPerSig = {};
  ruter.forEach(r => {
    if (!r.linje) return;
    if (r.retning === "innkjor" && sigEnde[r.linje] &&
        !sigEnde[r.linje].inn.includes(r.start))
      sigEnde[r.linje].inn.push(r.start);
    if (r.retning === "utkjor")
      (utPerSig[r.start] = utPerSig[r.start] ||
        {spor: new Set(), linje: r.linje}).spor.add(r.spor);
  });
  for (const [sig, o] of Object.entries(utPerSig)) {
    if (o.spor.size > 1) {
      if (sigEnde[o.linje] && !sigEnde[o.linje].ut.includes(sig))
        sigEnde[o.linje].ut.push(sig);
    } else if (o.linje === vEnde || o.linje === hEnde) {
      const side = o.linje === vEnde ? "v" : "h";
      const sp = [...o.spor][0];
      ((sigSpor[sp] = sigSpor[sp] || {v: [], h: []})[side]).push(sig);
    }
  }
  // veksler per spor og side
  const vxSpor = {};
  ruter.forEach(r => {
    if (!r.spor || !r.linje) return;
    const side = r.linje === vEnde ? "v" : r.linje === hEnde ? "h" : null;
    if (!side) return;
    const o = vxSpor[r.spor] = vxSpor[r.spor] || {v: new Set(), h: new Set()};
    r.veksler.forEach(v => o[side].add(v));
  });
  // hovedspor = færrest avvik (rett gjennomkjøring); resten er grener
  const avvikTall = sp => ruter.filter(r => r.spor === sp)
    .reduce((n, r) => n + r.veksler.filter(v => v.endsWith("a")).length, 0);
  const hovedSpor = spor.slice().sort((a, b) =>
    avvikTall(a) - avvikTall(b) || cmp(a, b))[0];
  const grener = spor.filter(s => s !== hovedSpor);

  // Forsignaler: montert = på vertssignalets mast (vises som +F▷),
  // frittstående = ute på linjen FORAN innkjørsignalet. Hovedsignal
  // ▶/◀, forsignal ▷/◁ (hul pil), i kjøreretningen de gjelder.
  const forsignaler = HALFN.filter(f =>
    sigKlasse(f.type) === "forsignal");
  const sigFinnes = id => !!HALFN.find(f => f.id === id &&
    erHoved(f.type));
  const montertPaa = {}, frittFor = {};
  forsignaler.forEach(fs => {
    if (fs.montert_med) {
      if (!sigFinnes(fs.montert_med))
        adv.push(`forsignal ${fs.id}: montert med «${fs.montert_med}» — ` +
                 `finnes ikke som hovedsignal`);
      else (montertPaa[fs.montert_med] =
              montertPaa[fs.montert_med] || []).push(fs.id);
    } else if (fs.varsler_om) {
      if (!sigFinnes(fs.varsler_om))
        adv.push(`forsignal ${fs.id}: varsler om «${fs.varsler_om}» — ` +
                 `finnes ikke som hovedsignal`);
      else (frittFor[fs.varsler_om] =
              frittFor[fs.varsler_om] || []).push(fs.id);
    }
  });
  const sigTok = (sig, retn) => {   // retn "h" = peker mot høyre
    let t = retn === "h" ? sig + " ▶" : "◀ " + sig;
    (montertPaa[sig] || []).forEach(fs =>
      t += " " + (retn === "h" ? fs + " ▷" : "◁ " + fs));
    return t;
  };
  const fsTok = (fs, retn) => retn === "h" ? fs + " ▷" : "◁ " + fs;
  // varselfelt: korte felt ute på linjen, utenfor forsignalet —
  // koblet til sitt linjefelt (arver siden derfra)
  const varselfelt = HALFN.filter(f => f.type === "sporfelt" &&
                                      f.rolle === "varselfelt");
  varselfelt.forEach(m => {
    if (!m.linjefelt || feltAv(m.linjefelt).rolle !== "linjefelt")
      adv.push(`varselfelt ${m.id}: mangler kobling til linjefelt — ` +
               `varslet vet ikke hvilken side det gjelder`);
  });

  // Et togspor må ha en veksel i BEGGE ender for å kunne tegnes som
  // et gjennomgående spor. Har det bare én, tegner panelet det som et
  // buttspor: hele sporet klapper sammen til én x, og litra, lamper
  // og togveistiller havner oppå hverandre.
  //
  // Feilen kom snikende: så lenge de håndstilte vekslene sto i
  // togveitabellen, kunne panelet UTLEDE hvilket spor et vekselben
  // landet på (togveiens «spor» der vekselen ligger normalt). Da
  // manuellvekslene ble flyttet ut av togveiene og over i låsekravet,
  // forsvant den kilden — og Sokna veksel 5 sto igjen uten «+→»,
  // hvorpå spor 02 ble tegnet som en stubb. Ingen sa fra.
  // Gjennomgangssporet er unntatt: det tegnes kant til kant og
  // fortsetter forbi stasjonen i begge ender, så det HAR ingen veksel
  // som avslutter det. Panelets egen regel for hvilket spor det er:
  // det hvis togveier bare bruker veksler i NORMAL stilling.
  const gjennomgang = sp => TOGVEIER.filter(t => t.spor === sp)
    .every(t => (t.sporveksler || []).every(v => v.stilling === "normal"));
  HALFN.filter(f => f.type === "sporfelt" && f.rolle === "togspor")
       .forEach(sp => {
    if (gjennomgang(sp.id)) return;
    const ender = HALFN.filter(v => isNoenVeksel(v.type) &&
      [v.pluss_til, v.minus_til, v.spiss_til].includes(sp.id))
      .map(v => v.id);
    // Nøyaktig én = sidesporet har bare den ene enden koblet.
    if (ender.length === 1)
      adv.push(`togspor ${sp.id}: bare veksel ${ender[0]} peker på det ` +
               `(«tegning ▸» under Objekter). Et togspor trenger en ` +
               `veksel i hver ende — med bare én tegnes sporet som ` +
               `buttspor, og litra, lamper og togveistiller legger seg ` +
               `oppå hverandre i panelet`);
  });

  // ... og den andre halvdelen av samme problem: en veksel panelet
  // ikke KOMMER FRAM til. Vekselgata tegnes ved å følge pluss/minus
  // fra en rot, og en veksel som ingen peker på, og som ikke selv er
  // en rot, blir aldri plassert. Med den forsvinner alt som henger
  // under den — Sokna veksel 3 tok med seg veksel 7 og sidesporene 4
  // og 5 da den sluttet å være rot.
  {
    const vekslerAlle = HALFN.filter(f => isNoenVeksel(f.type));
    const pektPaa = new Set();
    for (const v of vekslerAlle)
      for (const r of [v.pluss_til, v.minus_til])
        if (String(r || "").startsWith("veksel "))
          pektPaa.add(String(r).slice(7));
    const iTogvei = new Set();
    for (const t of TOGVEIER)
      for (const v of t.sporveksler || []) iTogvei.add(v.sporveksel);
    const togsporLitra = new Set(HALFN
      .filter(f => f.type === "sporfelt" && f.rolle === "togspor")
      .map(f => f.id));
    for (const v of vekslerAlle) {
      if (pektPaa.has(v.id) || iTogvei.has(v.id)) continue;
      // rot: plussgreina i et togspor, og spissen sier hvilken ende
      if (togsporLitra.has(String(v.pluss_til)) &&
          (v.spiss === "v" || v.spiss === "h")) continue;
      adv.push(`veksel ${v.id}: ingen annen veksel peker på den, og den ` +
               `er ingen rot i et togspor — panelet finner den ikke og ` +
               `tegner den ikke. Sett «+→» til togsporet den ligger i, ` +
               `og «spiss» til stasjonsenden («tegning ▸» under ` +
               `Objekter)`);
    }
  }

  const sporTekst = sp => {
    const o = vxSpor[sp] || {v: new Set(), h: new Set()};
    const sg = sigSpor[sp] || {v: [], h: []};
    const midt = [];
    if (sg.v.length) midt.push(sg.v.map(s => sigTok(s, "v")).join(" "));
    midt.push(sp);
    if (sg.h.length) midt.push(sg.h.map(s => sigTok(s, "h")).join(" "));
    const deler = [];
    if (o.v.size) deler.push([...o.v].sort(cmp).join(","));
    deler.push("── " + midt.join(" ") + " ──");
    if (hEnde && o.h.size) deler.push([...o.h].sort(cmp).join(","));
    return deler.join(" ");
  };
  // Rekkefølgen fra linjen og innover mot togsporene: frittstående
  // forsignal — innkjørsignal — LINJEFELTET (som jo er strekningen
  // innenfor innkjørsignalet, dvs. signalfallfeltet) — utkjørsignal
  // ved feltets indre ende.
  const endeTekst = (ende, side) => {
    const sv = sigEnde[ende] || {inn: [], ut: []};
    const fritt = [];
    sv.inn.forEach(s => (frittFor[s] || []).forEach(fs => fritt.push(fs)));
    const mf = varselfelt.filter(m => m.linjefelt === ende).map(m => m.id);
    const d = [];
    if (side === "v") {
      mf.forEach(m => d.push(m));            // ytterst på linjen
      fritt.forEach(fs => d.push(fsTok(fs, "h")));
      sv.inn.forEach(s => d.push(sigTok(s, "h")));
      d.push(ende);
      sv.ut.forEach(s => d.push(sigTok(s, "v")));
      return "── " + d.join(" ── ") + " ──";
    }
    sv.ut.forEach(s => d.push(sigTok(s, "h")));
    d.push(ende);
    sv.inn.forEach(s => d.push(sigTok(s, "v")));
    fritt.forEach(fs => d.push(fsTok(fs, "v")));
    mf.forEach(m => d.push(m));              // ytterst på linjen
    return "── " + d.join(" ── ") + " ──";
  };
  const senter = (s, w, fyll) => {
    const tot = Math.max(0, w - s.length);
    const l = Math.floor(tot / 2);
    return fyll.repeat(l) + s + fyll.repeat(tot - l);
  };
  const nBr = grener.length;
  const W = Math.max(...spor.map(s => sporTekst(s).length)) + 2;
  const margL = endeTekst(vEnde, "v");
  const margR = hEnde ? endeTekst(hEnde, "h") : " ┤";
  const M = margL.length;
  const linjer = [];
  for (let j = nBr - 1; j >= 0; j--) {   // øverst = ytterste gren
    const stolper = "│".repeat(nBr - 1 - j);
    let rad = " ".repeat(M) + stolper + "┌" +
              senter(sporTekst(grener[j]), W + 2 * j, "─");
    rad += hEnde ? "┐" + stolper : "┤";
    linjer.push(rad);
  }
  let hoved = margL + "┴".repeat(nBr) +
              senter(sporTekst(hovedSpor), W, "─");
  hoved += hEnde ? "┴".repeat(nBr) + margR : margR;
  linjer.push(hoved);

  // Fargekoding: alle kjente tokens (lengst først, én passering så
  // korte litra aldri treffer inne i lengre). Justeringen er alt
  // beregnet på ren tekst — span-ene endrer ikke tegnbredder.
  const tokKart = [];
  HALFN.forEach(f => {
    if (erHoved(f.type)) {
      tokKart.push([f.id + " ▶", "sk-hs"], ["◀ " + f.id, "sk-hs"]);
    } else if (sigKlasse(f.type) === "forsignal") {
      tokKart.push([f.id + " ▷", "sk-fs"], ["◁ " + f.id, "sk-fs"]);
    } else if (f.type === "sporfelt" && f.rolle === "togspor") {
      tokKart.push([f.id, "sk-ts"]);
    } else if (f.type === "sporfelt" && f.rolle === "linjefelt") {
      tokKart.push([f.id, "sk-lf"]);
    } else if (f.type === "sporfelt" && f.rolle === "varselfelt") {
      tokKart.push([f.id, "sk-mf"]);
    } else if (isNoenVeksel(f.type)) {
      tokKart.push([f.id + "n", "sk-vx"], [f.id + "a", "sk-vx"]);
    }
  });
  tokKart.sort((a, b) => b[0].length - a[0].length);
  const kls = {};
  tokKart.forEach(([t, c]) => { if (!(t in kls)) kls[t] = c; });
  const esc = s => s.replace(/&/g, "&amp;").replace(/</g, "&lt;")
                    .replace(/>/g, "&gt;");
  if (tokKart.length) {
    const rx = new RegExp(tokKart.map(([t]) =>
      t.replace(/[.*?^$()|[\]{}\\]/g, "\\$&")).join("|"), "g");
    el.innerHTML = attr(linjer.join("\n")).replace(rx, m =>
      '<span class="' + kls[m] + '">' + m + "</span>");
  } else {
    el.textContent = linjer.join("\n");
  }
  document.getElementById("fr-tegn").innerHTML =
    '<span class="sk-hs">hovedsignal</span> · ' +
    '<span class="sk-fs">forsignal</span> · ' +
    '<span class="sk-ts">togspor</span> · ' +
    '<span class="sk-lf">linjefelt</span> · ' +
    '<span class="sk-mf">varselfelt</span> · ' +
    '<span class="sk-vx">veksel</span>';
  const unike = [...new Set(adv)];
  advEl.innerHTML = unike.length
    ? unike.map(a => "⚠ " + a).join("<br>")
    : `<span class="on">✓ alle togspor har togveier i begge retninger</span>`;
}

function frKonflikter() {
  const out = [];
  for (let a = 0; a < TOGVEIER.length; a++) {
    for (let b = a + 1; b < TOGVEIER.length; b++) {
      const A = TOGVEIER[a], B = TOGVEIER[b], grunner = [];
      const feltA = new Set(A.frie || []);
      for (const sf of B.frie || [])
        if (feltA.has(sf)) grunner.push("felles sporfelt " + sf);
      for (const va of A.sporveksler || [])
        for (const vb of B.sporveksler || [])
          if (va.sporveksel && va.sporveksel === vb.sporveksel &&
              va.stilling !== vb.stilling)
            grunner.push(`${va.sporveksel} i ulik stilling`);
      if (A.start && A.start === B.start) grunner.push("samme startsignal");
      if (grunner.length)
        out.push(`<b>${A.id||"?"} × ${B.id||"?"}</b>: ${grunner.join(", ")}`);
    }
  }
  document.getElementById("fr-konflikter").innerHTML = out.length
    ? `<div class="card"><h2>Fiendtlige togveier (utledet)</h2>
       <p class="hint">${out.join("<br>")}</p></div>`
    : (TOGVEIER.length > 1
       ? `<p class="hint">Ingen konflikter utledet av tabellen.</p>` : "");
}
function frAdd() {
  const mangler = frKrav();
  if (mangler.length) {
    toast("Togveier trenger minst " + mangler.join(", ") +
          " — legg til under Objekter først.", true);
    return;
  }
  TOGVEIER.push({id:"", start:"", spor:"",
                 sporveksler:[], frie:[], utlosningsfelt:"", notes:""});
  frRender();
}
function frOpprett(linje, sp, retning) {
  const fra = retning === "innkjor" ? linje : sp;
  const til = retning === "innkjor" ? sp : linje;
  const mot = TOGVEIER.find(tv => tv.fra === til && tv.til === fra);
  TOGVEIER.push({id: "", start: "", spor: "", fra: fra, til: til,
                 frie: [], utlosningsfelt: "", notes: "",
                 sporveksler: (mot && mot.sporveksler || []).map(v =>
                   ({sporveksel: v.sporveksel, stilling: v.stilling}))});
  frRender();   // signal, ID, frie og utløsning avledes av endene
}
function frAutoFyll(i) {
  const a = frAutoFelt(TOGVEIER[i]);
  if (!a) {
    toast("Velg startsignal, spor og minst én veksel først — feltene " +
          "avledes av endene.", true);
    return;
  }
  TOGVEIER[i].frie = a.frie;
  TOGVEIER[i].utlosningsfelt = a.utlos;
  frRender();
}
async function frSave() {
  const msg = document.getElementById("fr-msg");
  // Betjeningen er stiller-avledet — gamle knappefelter ryddes bort
  TOGVEIER.forEach(tv => { delete tv.startknapp; delete tv.sluttknapp;
                           delete tv.signalfall; });
  // ID-ene genereres av rute-endene; ufullstendige rader beholder
  // evt. gammel ID til endene er valgt
  for (const tv of TOGVEIER) {
    frEnder(tv);
    if ((tv.fra || tv.til) && !frRetning(tv)) {
      msg.textContent = `Togvei ${tv.id || tv.fra + "→" + tv.til}: ` +
        `endene må være linjefelt→togspor (innkjør), ` +
        `togspor→linjefelt (utkjør) eller togspor→togspor (indre)`;
      msg.className = "err";
      return;
    }
    if (frRetning(tv) && !tv.start) {
      msg.textContent = `Togvei ${frGenId(tv)}: mangler hovedsignal — ` +
        `sett rolle/linjefelt på signalet under Objekter`;
      msg.className = "err";
      return;
    }
  }
  const sett = new Set();
  for (const tv of TOGVEIER) {
    const g = frGenId(tv);
    if (g) tv.id = g;
    if (tv.id) {
      if (sett.has(tv.id)) {
        msg.textContent = `To togveier får samme ID (${tv.id}) — samme ` +
          `retning, linjefelt og spor. Slett duplikatet.`;
        msg.className = "err";
        return;
      }
      sett.add(tv.id);
    }
  }
  frRender();
  const r = await fetch("/api/forrigling", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({togveier: TOGVEIER})});
  const j = await apiJson(r);
  if (!r.ok) { msg.textContent = j.error; msg.className = "err"; return; }
  msg.textContent = "Lagret og publisert " + j.version;
  msg.className = "ok";
  for (let i = 0; i < 10; i++) {
    await new Promise(res => setTimeout(res, 1000));
    const a = await (await fetch("/api/forrigling-ack")).json();
    if (a.version === j.version) {
      msg.textContent =
        `Lagret — master kvitterte ${j.version} (${a.togveier} togveier)`;
      return;
    }
  }
  msg.textContent += " — venter fortsatt på master-kvittering";
}

async function lampTest(action) {
  await fetch("/api/lamptest", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({action})});
  setTimeout(renderNoder, 300);
}
async function settDriver(mac, i2c, boks) {
  const r = await fetch("/api/node-driver", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({mac, i2c, driver: boks.checked})});
  const j = await apiJson(r);
  if (!r.ok) { toast(j.error, true); boks.checked = !boks.checked; return; }
  await loadAll();
  renderNoder();
}
async function findNode(mac) {
  await fetch("/api/find", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({mac})});
}
async function forgetNode(mac) {
  const alias = aliasFor(mac);
  if (!confirm(`Fjerne node ${alias || mac}?\n\nRetained-temaer slettes og ` +
               `noden forsvinner fra oversikten. En node som fortsatt er i ` +
               `drift vil melde seg inn igjen av seg selv.`)) return;
  await fetch("/api/forget", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({mac})});
  setTimeout(renderNoder, 1500);
}

// Stille klokkeinnmelding: denne enheten har (antagelig) riktig tid.
// Pi-en justerer seg bare ved stort avvik uten NTP — se /api/klokke.
async function klokkeSjekk() {
  try {
    await fetch("/api/klokke", {method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({epoch_ms: Date.now()})});
  } catch (e) { /* Pi-en svarer ikke — pytt */ }
}

loadAll();
showView(faneFraHash());   // reload/bokmerke lander på riktig fane
klokkeSjekk();
setInterval(klokkeSjekk, 300000);
let backupTikk = 0;
setInterval(async () => {
  // Levende inngangsverdier på Kabling-siden. Bare når fanen er
  // framme — ellers ville hvert eneste anlegg hentet dem hvert
  // sekund uten at noen ser dem.
  const kb = document.getElementById("view-kabling");
  if (kb && kb.style.display !== "none") {
    await kbInnHent();
    kbInnOppdater();
  }
  const nodes = await (await fetch("/api/nodes")).json();
  liveNodes = nodes.nodes || [];
  STATUS.noder = liveNodes.filter(n => n.online).length;
  oppdaterStatus();
  // Lampeprøve-banner på ALLE faner: prøven eier lampene i inntil
  // 10 min — det skal være umulig å glemme at den står på
  try {
    const lt = await (await fetch("/api/lamptest")).json();
    const b = document.getElementById("lpbanner");
    if (lt.running) {
      const igjen = lt.start_ts
        ? Math.max(0, 600 - Math.round(Date.now() / 1000 - lt.start_ts)) : null;
      document.getElementById("lpbanner-txt").textContent =
        (lt.progress || "") +
        (igjen != null ? ` · sikkerhetsstopp om ${Math.floor(igjen / 60)}:` +
          String(igjen % 60).padStart(2, "0") : "");
      b.style.display = "";
    } else {
      b.style.display = "none";
    }
  } catch (e) {}
  // Testmodus-banner på ALLE faner: en sikkerhetsomgåelse som står
  // på skal være umulig å overse, uansett hvilken fane man er på
  try {
    // Master er fasiten: den kan kjøre testmodus fra sitt eget flash
    // uten at Pi-ens anlegg.json vet om det. Lokal konfig er reserve
    // for tilfellet master ikke har meldt seg ennå.
    const m = await (await fetch("/api/master")).json();
    let paa = m.testmodus === "paa";
    if (m.testmodus == null) {
      const an = await (await fetch("/api/anlegg")).json();
      paa = !!an.testmodus;
    }
    document.getElementById("testbanner").style.display = paa ? "" : "none";
  } catch (e) {}
  // Backup-banneret: hvert 15. sekund holder (lagringer i denne
  // fanen oppdaterer det straks via loadAll)
  if (++backupTikk % 5 === 0) oppdaterBackup();
  oppdaterOtaBanner();
  if (currentView === "noder") {
    // Ikke tegn på nytt mens brukeren skriver i et felt på fanen
    const ae = document.activeElement;
    if (ae && ae.tagName === "INPUT" && ae.closest("#view-noder")) return;
    renderNoder();
  }
}, 3000);
