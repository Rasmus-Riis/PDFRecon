# Ændringslog

## 17.7.0

### ⚠️ Læs dette først, hvis du har eksisterende TouchUp-fund

Denne version retter fejl i udtrækket af TouchUp-tekst, som fandtes i tidligere
versioner, og som påvirkede det rapporterede resultat. **Fund, der bygger på
udtrukket TouchUp-tekst, bør køres igennem denne version igen, før de lægges
til grund.** Selve udtrækket var forkert på to forskellige måder, afhængigt af
hvordan PDFRecon blev kørt:

| | Hvad tidligere versioner rapporterede |
|---|---|
| **Fra .exe-filen** | Ingen TouchUp-tekst overhovedet. `pikepdf` blev aldrig pakket med, så udtrækket fejlede lydløst og feltet forblev tomt. Filer med TouchUp-redigeringer kunne se ud, som om intet kunne genskabes. |
| **Fra kildekoden** | Teksten fra **hele siden**, ikke kun det redigerede område. Maskeringen kørte aldrig, så urørt tekst blev vist i feltet "Udtrukket ændret tekst". |

Derudover blev TouchUp-områder, der er markeret indirekte gennem
`/Properties` — frem for med selve mærket skrevet direkte — slet ikke opdaget,
så visse redigerede dokumenter blev ikke flaget.

Alle tre er rettet. Detektion og udtræk opfører sig nu ens, uanset om du kører
den færdige .exe, GUI'en fra kildekoden eller kommandolinjen.

### Nyt: automatisk afkodning af volapyk-TouchUp-tekst

Når en skrifttypes `/ToUnicode`-CMap mangler, er ufuldstændig eller
ikke-standard, kom udtrukket TouchUp-tekst ud som volapyk, fx `ZK,KZK,ZP=GZ`.
Manualen beskrev en femtrinsprocedure til at afkode det i hånden. Det er nu
automatiseret.

Afkodningen kører i niveauer og stopper ved det første resultat, den kan stå
inde for:

| Niveau | Metode | Grundlag | Konfidens |
|--------|--------|----------|-----------|
| 0 | `tounicode` | Skrifttypens egen `/ToUnicode`-CMap | CERTAIN |
| 1 | `glyphnames` | `/Encoding /Differences` eller den indlejrede skrifttypes `post`-tabel / CFF-charset, via Adobe Glyph List | CERTAIN |
| 2 | `shapematch` | Den form, PDF'en faktisk tegner, sammenlignet med et referencealfabet | PROBABLE |

**Konfidens er en del af resultatet, ikke en eftertanke.** CERTAIN betyder, at
kortlægningen blev læst fra noget, filen angiver udtrykkeligt — det betyder
*ikke*, at teksten er ægte, for en forfalsket CMap giver en sikker læsning af
de forkerte tegn. PROBABLE betyder, at læsningen er udledt af glyffernes form
og er et efterforskningsspor. SPECULATIVE betyder, at mindst ét tegn slet ikke
kunne bestemmes; de positioner vises som `�` og gættes aldrig.

En læsning under CERTAIN bærer sin mærkat overalt, hvor den optræder — på
skærmen, i alle eksporter og i signerede rapporter — så den ikke ved et uheld
kan citeres som et bekræftet fund.

### Hvor du ser det

- **Inspektøren** — afkodet tekst med farvekodet konfidensmærkat og en knap
  **Afkodningsgrundlag**, der åbner hele grundlaget: metode, hvilke niveauer
  der kørte og hvad hvert af dem løste, skrifttypen og dens SHA-256, den rå
  operand, rangordnede alternative læsninger med marginen bag hver, samt den
  glyf dokumentet faktisk tegner, vist ved siden af det tegn den blev læst som.
  Det sidste er den hurtigste måde at revidere et resultat på — en glyf med
  teksten "læst som 4", der tydeligt er et 1-tal, afslører sig selv med det
  samme.
- **Eksporter** — kolonner for metode og konfidens i Excel, CSV, HTML og JSON,
  plus et selvstændigt *Text Decoding*-ark med rå operand, skrifttype-hash,
  niveauer og alternativer.
- **Chain of custody** — en `TEXT_DECODED`-post, der registrerer hvilke niveauer
  der kørte, hvilken konfidens der blev nået, og SHA-256 for Adobe Glyph List,
  referenceskrifttypen og dokumentets egen indlejrede skrifttype.
- **Kommandolinjen** — `pdfrecon scan` udskriver en afkodningsblok;
  `--decoding-detail` viser hvert tegn med score og margin.
- **Manualen** — et nyt afsnit *CID-tekstafkodning* på dansk og engelsk, der
  forklarer hvert niveau, hvad konfidensniveauerne betyder, og hvordan man
  verificerer eller anfægter en afkodning i hånden.

### Indstillinger

Nye valgmuligheder i `config.ini`, alle med dokumenterede standardværdier:

| Indstilling | Standard | Formål |
|---|---|---|
| `CIDReferenceFontPath` | medfølgende skrifttype | Den skrifttype, niveau 2 sammenligner med. **Den enkeltstående mest effektive justering** — se nedenfor. |
| `CIDCharacterInventory` | `0020-007E,00A0-00FF,0100-017F` | Hvilke tegn niveau 2 må foreslå. Den medfølgende skrifttype dækker også Latin Extended-B, græsk, kyrillisk, tegnsætning og valuta, så `0370-03FF` eller `0400-04FF` kræver ingen ekstra filer. |
| `CIDShapeCertainMargin` | `0.25` | Hvor meget et match skal slå næstbedste kandidat for at kaldes CERTAIN. |
| `CIDShapeMinScore` | `0.45` | Herunder tilbydes ingen kandidat, og koden rapporteres som uløst. |
| `CIDTier0ToUnicode` / `CIDTier1GlyphNames` / `CIDTier2ShapeMatch` | slået til | Kontakter pr. niveau; et deaktiveret niveau registreres i resultatet. |

**Om referenceskrifttypen.** Nøjagtigheden i niveau 2 afhænger mere af, hvor
meget referenceskrifttypen ligner dokumentets, end af nogen tærskelværdi. Den
samme serif-satte linje blev afkodet med 5 ud af 11 tegn korrekt mod den
medfølgende grotesk-reference og 11 ud af 11 mod en serif-reference. Er et
dokument sat med seriffer, så peg `CIDReferenceFontPath` mod noget tilsvarende.

### Reproducerbarhed

Niveau 0–2 indeholder ingen tilfældighed, ingen stikprøver og ingen
netværksadgang. Den samme fil med de samme indstillinger giver byte-identisk
output på enhver maskine. Standardmarginen for CERTAIN er empirisk: målt over
131 glyffer fra ni skrifttyper og tre skriftsystemer var den højestrangerede
kandidat korrekt 82 % af gangene ved enhver margin, 97,9 % over en margin på
0,15 og 100 % over 0,20. Standarden ligger på 0,25, ét trin strengere end
målingen kræver, fordi en fejlagtigt CERTAIN læsning er den mest skadelige fejl,
værktøjet kan begå.

### Også rettet

- **Den færdigpakkede .exe kunne ikke starte** og fejlede med `No module named
  'src.popups'`. En backslash inde i et f-string-udtryk er først gyldigt fra
  Python 3.12; byggefortolkeren var 3.11, så modulet blev aldrig oversat og
  udeladt lydløst af bygningen.
- **`pikepdf` manglede i `requirements.txt`** og i bygningen, hvilket er
  årsagen til, at TouchUp-udtrækket var slået fra i .exe-filen. Den er nu
  erklæret og pakket med, og `build.bat` afbryder med en læsbar fejl, hvis
  byggefortolkeren ikke kan importere det, der leveres.
- **`PDFRecon.spec` er nu versionsstyret.** Den stod i `.gitignore`, så
  rettelser til bygningen ikke kunne committes, og en frisk klon byggede en
  defekt .exe.

### Noter til vedligeholdere

- Kræver Python 3.10+ at køre og at bygge. `build.bat` tager nu fortolkeren fra
  en `PY`-variabel øverst i scriptet.
- De medfølgende filer fylder ca. 170 kB: Adobe Glyph List og et udsnit af
  DejaVu Sans, brugt som reference til formsammenligning, omdøbt som licensen
  kræver og leveret med den licens.
- `tools/decode_touchup.py` kører dekoderen på givne PDF'er og kan skrive de
  gengivne glyfbitmaps ud som PNG'er til visuel gennemgang.

---

## 17.6.4 og tidligere

Se commit-historikken.
