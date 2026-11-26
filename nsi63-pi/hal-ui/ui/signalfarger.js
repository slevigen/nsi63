// Lampefarger — FELLES for stillerapparatet (/panel) og HAL-UI-ets
// kablingsvisning. Én kilde, fordi to tabeller med samme mening før
// eller siden sier ulike ting.
//
// Indeksen er KONFIGKANALEN: lampe 0 sitter på bindingsporten, lampe 1
// på neste, og så videre — samme indeks som signaltyper-tabellen
// bruker i sine bilder, og som master driver de fysiske linsene med.
// Panelet tegner ovenfra og ned og oversetter med sin egen «cfg».
//
// Fargene er faste. Skal en rettes, rettes den HER.
//
//   hovedsignal3   grønn (H1) · rød (H2) · grønn (H3)
//   hovedsignal2   grønn (H1) · rød (H2)
//   forsignal2     gul (F1)   · grønn (F2)
//   skiftesignal   gult i begge — høyt skiftesignal viser STREKER,
//                  ikke runde linser (42 skrå, 41 loddrett)
//   dvergsignal3   hvitt i alle tre (§ 8-23)
const SIGNAL_LAMPEFARGE = {
  hovedsignal3:  ["#1fe04e", "#ff2a1e", "#1fe04e"],
  hovedsignal2:  ["#1fe04e", "#ff2a1e"],
  forsignal2:    ["#ffb400", "#1fe04e"],
  skiftesignal2: ["#ffb400", "#ffb400"],
  skiftesignal1: ["#ffb400"],
  dvergsignal3:  ["#d7d9dc", "#d7d9dc", "#d7d9dc"],
};

// SLUKKET LINSE har sin EGEN farge, den regnes ikke ut av den tente.
//
// Før ble slukket blandet fram: lampens farge tynnet ut i mørk grå.
// Det virker for alle kulører unntatt gul — mørk oransjegul ER brun,
// uansett hvor lite av den man tar med. Fargen måtte forlate
// gultonen for å slippe unna, og det kan en blanding ikke gjøre.
//
// Her står paret i stedet: den slukkede linsen er valgt for seg, med
// øyet, mot både sporplanens hvite og betjeningsfeltets lakk. Gulen
// er dratt mot oliven — det er slik en gul signallinse uten lys
// faktisk ser ut, og den lar seg da skille fra den slukkede røde.
const SIGNAL_SLUKKET = {
  "#1fe04e": "#2b5c3c",   // grønn
  "#ff2a1e": "#83322c",   // rød
  "#ffb400": "#7a7040",   // gul   — oliven, ikke brun
  "#1f8fff": "#35597f",   // blå
  "#d7d9dc": "#676d76",   // hvit
};

// Stilen en lampelinse skal ha: tent farge i --pa, slukket i --av.
// Ukjent farge faller tilbake på en nøytral mørk, så en ny lampe
// aldri blir usynlig — den blir bare kjedelig til den føres opp her.
function lampeStil(farge) {
  return `--pa:${farge};--av:${SIGNAL_SLUKKET[farge] || "#3f454e"}`;
}

// Fargen på én kanal, eller null for objekter som ikke er lyssignaler
// (vekselmotor, klokke, kontrollampe — de har ingen egen signalfarge).
function signalLampeFarge(type, kanal) {
  const f = SIGNAL_LAMPEFARGE[type];
  return f && f[kanal] ? f[kanal] : null;
}
