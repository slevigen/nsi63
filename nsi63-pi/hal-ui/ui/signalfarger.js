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
const SIGNAL_LAMPEFARGE = {
  hovedsignal3:  ["#1fe04e", "#ff2a1e", "#1fe04e"],
  hovedsignal2:  ["#1fe04e", "#ff2a1e"],
  forsignal2:    ["#ffb400", "#1fe04e"],
  skiftesignal2: ["#ffb400", "#ffb400"],
  skiftesignal1: ["#ffb400"],
};

// Fargen på én kanal, eller null for objekter som ikke er lyssignaler
// (vekselmotor, klokke, kontrollampe — de har ingen egen signalfarge).
function signalLampeFarge(type, kanal) {
  const f = SIGNAL_LAMPEFARGE[type];
  return f && f[kanal] ? f[kanal] : null;
}
