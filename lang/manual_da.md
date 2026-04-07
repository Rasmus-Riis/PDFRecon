# PDFRecon - Manual

## Introduktion
PDFRecon er et værktøj designet til at assistere i efterforskningen af PDF-filer. Programmet analyserer filer for en række tekniske indikatorer, der kan afsløre ændring, redigering eller skjult indhold. Resultaterne præsenteres i en overskuelig tabel, der kan eksporteres til Excel for videre dokumentation.

## Vigtig bemærkning om tidsstempler
Kolonnerne 'Fil oprettet' og 'Fil sidst ændret' viser tidsstempler fra computerens filsystem. Vær opmærksom på, at disse tidsstempler kan være upålidelige. En simpel handling som at kopiere en fil fra én placering til en anden vil typisk opdatere disse datoer til tidspunktet for kopieringen. For en mere pålidelig tidslinje, brug funktionen 'Vis Tidslinje', som er baseret på metadata inde i selve filen.

## Klassificeringssystem
Programmet klassificerer hver fil baseret på de fundne indikatorer. Dette gøres for hurtigt at kunne prioritere, hvilke filer der kræver nærmere undersøgelse.

<red><b>JA (Høj Risiko):</b></red> Tildeles filer, hvor der er fundet stærke beviser for ændring. Disse filer bør altid undersøges grundigt. Indikatorer, der udløser dette flag, er typisk svære at forfalske og peger direkte på en ændring i filens indhold eller struktur.

<yellow><b>Indikationer Fundet (Mellem Risiko):</b></yellow> Tildeles filer, hvor der er fundet en eller flere tekniske spor, der afviger fra en standard, 'ren' PDF. Disse spor er ikke i sig selv et endegyldigt bevis på ændring, men de viser, at filen har en historik eller struktur, der berettiger et nærmere kig.

<green><b>IKKE PÅVIST (Lav Risiko):</b></green> Tildeles filer, hvor programmet ikke har fundet nogen af de kendte indikatorer. Dette betyder ikke, at filen med 100% sikkerhed er uændret, men at den ikke udviser de typiske tegn på ændring, som værktøjet leder efter.

---

## Generel brug (GUI)

### Grundlæggende arbejdsgang
1. **Start PDFRecon** (kør `app.py` eller `PDFRecon.exe`).
2. **Vælg mappe og scan** – Klik på hovedknappen og vælg en mappe med PDF-filer. Programmet scanner rekursivt og viser alle PDF’er med fundne indikatorer.
3. **Gennemse tabellen** – Rækkerne er farvemærket: rød = høj tillid til ændring, gul = indikationer fundet, grøn = ingen indikatorer. Brug kolonnen "Tegn på ændring" og filtre.
4. **Inspector** – Vælg en fil for at åbne Inspector. Brug fanerne: **Details** (alle indikatorer og noter), **EXPTool** (ExifTool-output), **Timeline**, **Revisionshistorik** og **PDF Viewer** (visuel visning med valgfrie lag for TouchUp, ELA, JPEG-anomalier, dublerede billeder m.m.).
5. **Gem sag** – Brug **Fil → Gem sag som...** for at gemme sessionen som en `.prc`-sag. Du kan senere åbne med **Fil → Åbn sag...** og fortsætte (noter, eksport, verifikation).
6. **Eksport** – Brug **Eksporter rapport** til Excel, CSV, JSON eller HTML. Alle eksporter kan digitalt signeres (SHA-256 sidecar og valgfri detached signatur) og logges i kæde-of-custody, når en sag er indlæst.
7. **Noter** – Højreklik på en fil → **Note** for at tilføje noter; de gemmes i sagen og markeres som ændret, indtil du gemmer sagen.
8. **Verificer integritet** – Med en indlæst sag: **Fil → Verificer integritet** sammenligner nuværende fil-hashes med de gemte evidence-hashes.

### Tastatur og navigation
- **Piletaster (Op/Ned)** – Flyt valg i fillisten (én række ad gangen). Virker også når Inspector er åben.
- **Højreklik** – Genvejsmenu: Vis PDF, Vis tidslinje, Revisionshistorik, Visuel diff (for revisioner), Note m.m.

---

## CLI-brug (kommandolinje)

PDFRecon har et kommandolinjeinterface til scripting og automation. Kør fra projektroden: `python cli.py <kommando> ...` (eller `pdfrecon` hvis installeret).

### Kommandoer

**`scan <mappe>`** – Scanner en mappe for PDF’er og opretter en sag og valgfri kæde-of-custody-log.

```bash
python cli.py scan C:\Evidence\PDFs
python cli.py scan C:\Evidence\PDFs --output-dir C:\Cases -j 4
python cli.py scan C:\Evidence\PDFs --custody-log C:\Cases\custody.log
```

| Option | Beskrivelse |
|--------|-------------|
| `dir` | Mappe der skal scannes (påkrævet) |
| `--output-dir`, `-o` | Outputmappe for sagfil (standard: samme som scanmappe) |
| `--custody-log`, `-c` | Sti til kæde-of-custody-logfil |
| `--jobs`, `-j` | Antal parallelle workers (standard: CPU-antál − 1) |

Sagfilen gemmes som `case_cli_ÅÅÅÅMMDD_HHMMSS.prc` i outputmappen.

**`export-signed <sagfil>`** – Eksporterer en digitalt signeret rapport fra en eksisterende `.prc`-sag.

```bash
python cli.py export-signed C:\Cases\case_cli_20250101_120000.prc
python cli.py export-signed case.prc --output report.json --custody --sign-key key.pem
```

| Option | Beskrivelse |
|--------|-------------|
| `case` | Sti til `.prc`-sagfil (påkrævet) |
| `--output` | Outputrapportsti (standard: &lt;case&gt;.signed_report.json) |
| `--custody` | Tilføj eksport til kæde-of-custody-log |
| `--sign-key` | Sti til PEM privat nøgle til detached signatur (valgfri) |

**`extract-js <PDF-fil>`** – Udpakker indlejret JavaScript fra en PDF (fx til analyse af ondsindede filer).

```bash
python cli.py extract-js mistænkelig.pdf
python cli.py extract-js mistænkelig.pdf --output scripts.txt
```

| Option | Beskrivelse |
|--------|-------------|
| `file` | Sti til PDF-fil (påkrævet) |
| `--output`, `-o` | Skriv udtrukne scripts til fil (standard: stdout) |

**Version:** `python cli.py --version`

---

## Anbefalede værktøjer til manuel analyse

| Værktøj | Formål | Download |
|---------|--------|----------|
| HxD | Gratis hex-editor til Windows | https://mh-nexus.de/en/hxd/ |
| 010 Editor | Professionel hex-editor med skabeloner | https://www.sweetscape.com/010editor/ |
| QPDF | PDF-manipulation og -dekomprimering | https://github.com/qpdf/qpdf |
| mutool | PDF-inspektion (del af MuPDF) | https://mupdf.com/ |
| ExifTool | Metadata-udtræk | https://exiftool.org/ |
| pdfimages | Udpak billeder fra PDF | Del af poppler-utils |

---

## Forklaring af Indikatorer
Nedenfor er en detaljeret forklaring af hver indikator, som PDFRecon leder efter.

<b>Has Revisions</b>
*<i>Ændret:</i>* <red>JA</red>
• Hvad det betyder: PDF-standarden tillader, at man gemmer ændringer oven i en eksisterende fil (inkrementel lagring). Dette efterlader den oprindelige version af dokumentet intakt inde i filen. PDFRecon har fundet og udtrukket en eller flere af disse tidligere versioner. Dette er et utvetydigt bevis på, at filen er blevet ændret efter sin oprindelige oprettelse.

<b>TouchUp_TextEdit</b>
*<i>Ændret:</i>* <red>JA</red>
• Hvad det betyder: Dette er et specifikt metadata-flag, som Adobe Acrobat efterlader, når en bruger manuelt har redigeret tekst direkte i PDF-dokumentet. Det er et meget stærkt bevis på direkte ændring af indholdet.

<b>Multiple Font Subsets</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Når tekst tilføjes til en PDF, indlejres ofte kun de tegn fra en skrifttype, der rent faktisk bruges (et 'subset'). Hvis en fil redigeres med et andet program, der ikke har adgang til præcis samme skrifttype, kan der opstå et nyt subset af den samme grundlæggende skrifttype. At finde flere subsets (f.eks. Multiple Font Subsets: 'Arial':F1+ArialMT', 'F2+Arial-BoldMT er en stærk indikation på, at tekst er blevet tilføjet eller ændret på forskellige tidspunkter eller med forskellige værktøjer.

<b>Multiple Creators / Producers</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: PDF-filer indeholder metadata om, hvilket program der har oprettet (/Creator) og genereret (/Producer) filen. Hvis der findes flere forskellige navne i disse felter (f.eks. Multiple Creators (Fundet 2): "Microsoft Word", "Adobe Acrobat Pro"), indikerer det, at filen er blevet behandlet af mere end ét program. Dette sker typisk, når en fil oprettes i ét program og derefter redigeres i et andet.

<b>xmpMM:History / DerivedFrom / DocumentAncestors</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Dette er forskellige typer af XMP-metadata, som gemmer information om filens historik. De kan indeholde tidsstempler for, hvornår filen er gemt, ID'er fra tidligere versioner, og hvilket software der er brugt. Fund af disse felter beviser, at filen har en redigeringshistorik.

---

<b>Historik og Relationer (xmpMM & Revisioner)</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Denne fane kombinerer to typer historik: logisk XMP-historik (Asset Relationships) og fysiske inkrementelle gemninger (revisioner).
- **Afledning (Source)**: Identificerer det umiddelbare forældredokument (kilde), som dette dokument er skabt fra.
- **Ingredienser (Ingredients)**: Lister de komponenter (billeder, PDF'er), der er indsat i filen. Hvis filen findes i det scannede materiale, kan du navigere direkte til den.
- **Pantry**: Indeholder komplette metadata-pakker for de indsatte komponenter.
- **Revisioner**: Viser tidsstempler og ændringer for hver gang filen er blevet gemt inkrementelt (fx ved digital signering eller redigering i Acrobat).

> [!NOTE]
> Pladsholder-ID'er som `xmp.did:...` undertrykkes automatisk i brugerfladen for at gøre overblikket renere. Et dokument, der viser rigtige ID'er i disse felter, har en mere sporbar oprindelse end et med kun pladsholdere. Hvis en relateret fil ikke kan findes i sagen, markeres den som "(ikke fundet)".

---

<b>Forensiske anomalier i dokumenthistorik</b>
*<i>Ændret:</i>* <red>JA</red> (hvis fundet)
• Hvad det betyder: Der er en modstrid i metadataene vedrørende dokumentets eller dets komponenters identitet.
- **ID-uoverensstemmelse**: Dokument-ID'et refereret i en `xmpMM:Ingredients`-indgang matcher ikke det Dokument-ID, der findes i den tilsvarende `xmpMM:Pantry`-pakke.
- **Fortolkning**: Dette tyder kraftigt på, at en komponent er blevet udskiftet efterfølgende, eller at metadata er manuelt manipuleret for at skjule oprindelsen.

<b>Multiple DocumentID / Different InstanceID</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Hver PDF har et unikt DocumentID, der ideelt set er det samme for alle versioner. InstanceID ændres derimod for hver gang, filen gemmes. Hvis der findes flere forskellige DocumentID'er (f.eks. Trailer ID Changed: Fra [ID1...] til [ID2...]), eller hvis der er et unormalt højt antal InstanceID'er, peger det på en kompleks redigeringshistorik, potentielt hvor dele fra forskellige dokumenter er blevet kombineret.

<b>Ikke-indlejret skrifttype (Non-Embedded Font)</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: PDF'en bruger en skrifttype, der ikke er indlejret i filen. Selvom det nogle gange gøres for at spare plads, er det et typisk tegn på redigeringer foretaget efter oprettelsen (f.eks. med Acrobat "TouchUp"), som ofte benytter lokale system-skrifttyper uden at indlejre dem.

<b>Hul i XMP-historik (XMP History Gap)</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Dokumentets metadata-historik (`xmpMM:History`) indeholder hændelser, der enten er i forkert rækkefølge eller har mistænkeligt store tidsspring. Dette tyder på, at historik-punkter kan være blevet slettet manuelt for at skjule bestemte redigeringstrin.

<b>Multiple startxref</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: 'startxref' er et nøgleord, der fortæller en PDF-læser, hvor den skal begynde at læse filens struktur. En standard, uændret fil har kun ét. Hvis der er flere, er det et tegn på, at der er foretaget inkrementelle ændringer (se 'Has Revisions').

<b>Objekter med generation > 0</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Hvert objekt i en PDF-fil har et versionsnummer (generation). I en original, uændret fil er dette nummer typisk 0 for alle objekter. Hvis der findes objekter med et højere generationsnummer (f.eks. '12 1 obj'), er det et tegn på, at objektet er blevet overskrevet i en senere, inkrementel gemning. Dette indikerer, at filen er blevet opdateret.

<b>Flere Lag End Sider</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Dokumentets struktur indeholder flere lag (Optional Content Groups) end der er sider. Hvert lag er en container for indhold, som kan vises eller skjules. Selvom det er teknisk muligt, er det usædvanligt at have flere lag end sider. Det kan indikere et komplekst dokument, en fil der er blevet kraftigt redigeret, eller potentielt at information er skjult på lag, som ikke er knyttet til synligt indhold. Filer med denne indikation bør undersøges nærmere i en PDF-læser, der understøtter lag-funktionalitet.

<b>Linearized / Linearized + updated</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: En "linearized" PDF er optimeret til hurtig webvisning. Hvis en sådan fil efterfølgende er blevet ændret (updated), vil PDFRecon markere det. Det kan indikere, at et ellers færdigt dokument er blevet redigeret senere.

<b>Has PieceInfo</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Nogle programmer, især fra Adobe, gemmer ekstra tekniske spor (PieceInfo) om ændringer eller versioner. Det kan afsløre, at filen har været behandlet i bestemte værktøjer som f.eks. Illustrator.

<b>Has Redactions</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Dokumentet indeholder tekniske felter for sløring/sletning af indhold. I nogle tilfælde kan den skjulte tekst stadig findes i filen. Derfor bør redaktioner altid vurderes kritisk.

<b>Has Annotations</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Dokumentet rummer kommentarer, noter eller markeringer. De kan være tilføjet senere og kan indeholde oplysninger, der ikke fremgår af det viste indhold.

<b>AcroForm NeedAppearances=true</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Formularfelter kan kræve, at visningen genskabes, når dokumentet åbnes. Felt-tekster kan derfor ændre udseende eller udfyldes automatisk. Det kan skjule eller forplumre det oprindelige indhold.

<b>Has Digital Signature</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Dokumentet indeholder en digital signatur. En gyldig signatur kan bekræfte, at dokumentet ikke er ændret siden signering. En ugyldig/brudt signatur kan være et stærkt tegn på efterfølgende ændring.

<b>Dato-inkonsistens (Info vs. XMP)</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Oprettelses- og ændringsdatoer i PDF'ens Info-felt stemmer ikke overens med datoerne i XMP-metadata (f.eks. Creation Date Mismatch: Info='20230101...', XMP='2023-01-02...'). Sådanne uoverensstemmelser kan pege på skjulte eller uautoriserede ændringer.

### Avancerede Detektionsmetoder (Nye)

<b>Stablede filtre (Sløring)</b>
*<i>Ændret:</i>* <red>JA</red>
• Hvad det betyder: Et stream-objekt bruger flere krypterings- eller komprimeringsfiltre (fx `[/FlateDecode /ASCIIHexDecode]`). Selvom det er teknisk lovligt, er det en almindelig teknik, der bruges til at sløre ondsindet indhold (såsom JavaScript eller shellcode) og undgå detektion fra antivirus-scannere.

<b>Ondsindet skrifttype-remapping</b>
*<i>Ændret:</i>* <red>JA</red>
• Hvad det betyder: PDF-fonten indeholder et `/ToUnicode` CMap, der mapper visuelle tegn til helt andre Unicode-tegn (fx visuelt 'A' -> Unicode 'B'). Dette resulterer i "copy-paste forfalskning", hvor den tekst, du udtrækker, er anderledes end den tekst, du ser.

<b>Duplikate objekt-ID'er (Skygge-angreb)</b>
*<i>Ændret:</i>* <red>JA</red>
• Hvad det betyder: Flere krydsreferencetabeller (XREF) i en inkrementelt gemt PDF redefinerer det samme objekt-ID. Dette er grundlaget for et "Skygge-angreb" (Shadow Attack), hvor forskellige PDF-læsere kan vise forskelligt indhold for den samme side.

<b>Formularfelt-overlay / Misforhold</b>
*<i>Ændret:</i>* <red>JA</red>
• Hvad det betyder: Et formularfelt har en værdi (`/V`), men dets afgrænsningsboks (`/BBox` eller `/Rect`) er ekstremt lille, usynlig eller placeret uden for det synlige sideområde. Dette bruges i "Overlay-angreb" til at indsmugle data, som brugeren ikke kan se, men som software vil udtrække.

<b>Ubalancerede obj/endobj strukturer</b>
*<i>Ændret:</i>* <red>JA</red>
• Hvad det betyder: Antallet af `obj`-erklæringer matcher ikke antallet af `endobj`-markører. Dette indikerer en fejlbehæftet PDF-struktur, der ofte bruges til at forvirre automatiske parsere og skjule objekter.

<b>PDF-version/funktionsmodstrid</b>
*<i>Ændret:</i>* <red>JA</red>
• Hvad det betyder: PDF-headeren påstår en gammel version (fx 1.3), men filen bruger funktioner introduceret i langt senere versioner (fx Object Streams eller XRef Streams fra 1.5+). Dette sker typisk, når en moderne PDF manuelt nedgraderes i headeren uden at ændre strukturen.

<b>Uoverensstemmelse i Metadata-version</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Metadata påstår, at PDF'en blev oprettet med gammelt software (f.eks. Acrobat 4 eller PDF 1.3), men filen bruger moderne PDF-funktioner (PDF 1.7+). Denne uoverensstemmelse antyder, at metadata kan være manipuleret, eller at filen er blevet redigeret med andet software end påstået.

<b>Mistænkelig tekstpositionering</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: PDF'en indeholder et usædvanligt højt antal tekstpositioneringskommandoer (Tm/Td operatører) i sekvens. Dette mønster opstår ofte, når tekst overlægges på eksisterende indhold for at skjule eller erstatte original tekst.

<b>Hvidt rektangel-overlay</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Flere hvide rektangler er blevet tegnet i dokumentet. Dette er en almindelig teknik til at skjule indhold ved at tegne hvide former over tekst eller billeder for at gøre dem usynlige, selvom de stadig er til stede i filen.

<b>Overdreven tegningsoperationer</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: En side indeholder et unormalt højt antal tegnekommandoer (>50). Dette kan indikere komplekse redigeringsoperationer eller forsøg på at skjule indhold gennem lagdeling.

<b>Ikke-refererede objekter</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Objekter er defineret i PDF'en, men aldrig refereret til. Et lille antal er normalt, men mange antyder omfattende redigering, hvor indhold blev fjernet, men ikke renset ud af selve filen.

<b>Hængende Referencer</b>
*<i>Ændret:</i>* <red>JA</red>
• Hvad det betyder: PDF'en refererer til objekter (f.eks. via krydsreferencetabellen), der ikke findes i filen. Dette indikerer delvis sletning af indhold, korruption eller ukorrekt redigering.

<b>Store huller i objektnumre</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Der er betydelige huller i objektnummersekvensen (>30% mangler). Dette antyder omfattende redigering, hvor objekter blev slettet eller erstattet.

<b>Strukturel rensning detekteret (Structural Scrubbing)</b>
*<i>Ændret:</i>* <red>JA</red>
• Hvad det betyder: Der er fundet store blokke af nul-bytes eller usædvanligt mange på hinanden følgende mellemrum i filens struktur. Dette er et typisk tegn på manuel "rensning", hvor data er blevet slettet ved at overskrive rå bytes i stedet for at generere PDF-strukturen korrekt på ny.

<b>PDF/A-overtrædelse (PDF/A Violation)</b>
*<i>Ændret:</i>* <red>JA</red>
• Hvad det betyder: Dokumentet påstår at være en PDF/A (arkivfil), men indeholder funktioner, der er forbudt i standarden (såsom JavaScript, kryptering eller ikke-indlejrede skrifttyper). Dette beviser, at filen er blevet ændret efter sin oprindelige "arkiv-færdiggørelse".

<b>Contains JavaScript</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: PDF'en indeholder JavaScript-kode. Selvom det er legitimt i nogle tilfælde, kan JavaScript bruges til at skjule ændringer eller dynamisk modificere indhold, når dokumentet åbnes.

<b>JavaScript Auto-Execute / Additional Actions</b>
*<i>Ændret:</i>* <red>JA</red>
• Hvad det betyder: PDF'en er konfigureret til automatisk at udføre JavaScript ved åbning (OpenAction) eller har yderligere handlinger (AA) tilknyttet. Dette er meget mistænkeligt og kan indikere forsøg på at modificere eller skjule indhold dynamisk.

<b>Duplicate Images With Different Xrefs</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Det samme billede (identificeret ved hash) forekommer flere gange med forskellige objektreferencer. Dette kan indikere, at billedet blev tilføjet, fjernet og genindsat under redigering.

<b>Images With EXIF</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Indlejrede billeder indeholder EXIF-metadata. Disse metadata kan afsløre, hvornår og med hvilken enhed billedet blev oprettet, hvilket muligvis ikke matcher PDF'ens påståede oprettelsesdato.

<b>CropBox/MediaBox Mismatch</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Det synlige område (CropBox) er betydeligt mindre end den fulde sidestørrelse (MediaBox). Dette antyder, at indhold kan være skjult uden for det synlige område.

<b>Excessive Form Fields</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Dokumentet indeholder et usædvanligt højt antal formularfelter (>50). Dette kunne indikere en kompleks formular eller potentiel manipulation af feltværdier.

<b>Duplicate Bookmarks</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Flere bogmærker har identiske titler. Dette kan indikere, at dokumentstrukturen blev ændret, eller at bogmærker blev kopieret forkert under redigering.

<b>Invalid Bookmark Destinations</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Bogmærker peger på sider, der ikke eksisterer i dokumentet. Dette opstår typisk, når sider slettes efter bogmærker blev oprettet, hvilket indikerer strukturelle ændringer.

<b>Starter med Nul-byte</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Filen starter med en Nul-byte (`0x00`) lige før PDF-headeren (`%PDF-`). Dette indikerer ofte, at filen er genereret eller manipuleret af ustandardiserede scripts eller visse programbiblioteker.

<b>Mulige E-mailadresser</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Detekterer e-mailadresser skjult i filens rå data. Dette kan utilsigtet identificere forfatteren, organisationen eller den softwarelicens, der blev brugt til at oprette dokumentet.

<b>Mulige Webadresser</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Detekterer URL'er fundet i den rå fil, som måske peger på ondsindede payloads, interne systemer eller den webbaserede software, der genererede PDF'en.

<b>JPEG-analyse (Fingeraftryk)</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Et sæt af 64 tal (Kvantiseringstabeller), der bruges under JPEG-komprimering til at bestemme, hvor mange detaljer der smides væk. Forskellige enheder (Canon, iPhone, HP-scannere) og software (Photoshop, GIMP) bruger unikke tabeller. Disse fungerer som et "digitalt fingeraftryk."
• Mistænkelige fund: 
    * Ugyldigt fingeraftryk (QT=1): Indikerer computergenererede forfalskninger.
    * Forfalsket fingeraftryk (Alle værdier ens): Tegn på kunstig skabelse.
    * Softwarematch: Hvis fingeraftrykket matcher software som "Adobe Photoshop", men filen påstår at være en original scanning.

---

## Detaljeret manuel verifikation

For trin-for-trin hex-editor- og kommandolinje-instruktioner for hver indikator (fx TouchUp_TextEdit, Has Revisions, JavaScript, Dangling References, tidsstempler, XRef-tabeller, PDF-operatører) henvises til den fulde engelske manual (**manual_en.md**) eller PDFRecon HTML-manualen (**Help → Manual** i appen), som indeholder de samme afsnit på begge sprog.

---

## Forensisk ordliste

**Kvantiseringstabeller (QT) / digitale fingeraftryk**  
Sæt af 64 tal under JPEG-komprimering. Forskellige enheder og programmer bruger unikke tabeller ("digitalt fingeraftryk"). Mistænkeligt: ugyldigt fingeraftryk (QT=1), forfalsket (alle værdier ens), eller softwarematch mod "original scan".

**Error Level Analysis (ELA)**  
Teknik der viser "komprimeringsalder" i forskellige dele af et billede. Ændrede områder har ofte anden fejlniveau end baggrunden.

**XREF (krydsreference)-tabel**  
PDF-filens "indeks" der angiver hvor hvert objekt findes. Flere startxref eller inkrementelle opdateringer betyder at indekset er genopbygget (fil ændret efter første gem).

**Tekstoperatører (TJ / Tj)**  
Lavniveau-kommandoer der tegner tekst. Usædvanlige positioner eller renderingstyper kan tyde på manuel indsættelse.

---

## Nyttige kommandoer til manuel analyse

```bash
# Dekomprimer PDF til læsbare content streams
qpdf --qdf --object-streams=disable input.pdf output.pdf

# Udpak al tekst
pdftotext -layout file.pdf output.txt

# List objekter og typer
mutool show file.pdf trailer
mutool show file.pdf xref

# Udpak alle billeder
pdfimages -all file.pdf prefix

# Hent metadata
exiftool -a -G -s file.pdf

# Tjek digitale signaturer
pdfsig file.pdf

# Tæl %%EOF-markører
grep -c "%%EOF" file.pdf
```

---

## Komplet indikatorliste (kort reference)

Listen svarer til de indikatorer der beskrives i manualen og i appen. **JA** = høj risiko (rød); **Indikationer** = mellem (gul).

| Indikator | Klassifikation | Kort betydning |
|-----------|----------------|-----------------|
| Has Revisions | JA | Tidligere versioner bevaret i filen; bevis på ændring efter oprettelse. |
| TouchUp_TextEdit | JA | Acrobat TouchUp tekstværktøj brugt til at redigere tekst. |
| JavaScript Auto-Execute / Additional Actions | JA | JavaScript kører ved åbning eller har AA-triggers. |
| Hængende referencer | JA | PDF refererer til objekter der ikke findes. |
| Strukturel rensning | JA | Store null/space-runs tyder på manuel byte-rensning. |
| PDF/A-overtrædelse | JA | Dokument påstår PDF/A men indeholder forbudte funktioner. |
| Timestamp Spoofing | JA | Filsystemdato ældre end intern PDF-dato. |
| Phishing-direktiver (SubmitForm/Launch) | JA | SubmitForm- eller Launch-handlinger til stede. |
| Multiple Font Subsets | Indikationer | Samme skrifttype indlejret med forskellige subsets. |
| Multiple Creators / Producers | Indikationer | Fil behandlet af mere end ét program. |
| xmpMM:History / DerivedFrom / DocumentAncestors | Indikationer | XMP redigeringshistorik til stede. |
| Dokumenthistorik | Indikationer | Kombineret visning af XMP-forhold og fysiske revisioner i filen. |
| Relation-anomalier | JA | Modstrid mellem ingrediens-ID og pantry-ID (tegn på manipulation). |
| Multiple DocumentID / Trailer ID Change | Indikationer | Dokument- eller instance-ID’er tyder på sammenlægning eller tung redigering. |
| Ikke-indlejret skrifttype | Indikationer | Skrifttype ikke indlejret; typisk efter TouchUp/Edit PDF. |
| XMP History Gap | Indikationer | Historikposter i forkert rækkefølge eller med mistænkelige spring. |
| Multiple startxref | Indikationer | Flere krydsreferencetabeller (inkrementelle gemmer). |
| Objekter med generation > 0 | Indikationer | Objektnumre genbrugt efter sletning. |
| Flere lag end sider | Indikationer | Usædvanligt antal lag. |
| Linearized / Linearized Updated | Indikationer | Web-optimeret PDF er senere ændret. |
| Has PieceInfo | Indikationer | PieceInfo til stede (fx Illustrator). |
| Has Redactions | Indikationer | Redaktionsannoteringer; skjult tekst kan stadig findes. |
| Has Annotations | Indikationer | Kommentarer/annoteringer til stede. |
| AcroForm NeedAppearances=true | Indikationer | Formularvisning genereret ved visning. |
| Has Digital Signature | Indikationer | Dokument signeret; brudt signatur = ændret efter signering. |
| Dato-inkonsistens (Info vs XMP) | Indikationer | Info- og XMP-datoer uoverensstemmende. |
| Metadata Version Mismatch | Indikationer | Påstår gammel PDF-version men bruger moderne funktioner. |
| Suspicious Text Positioning | Indikationer | Usædvanlig tæthed af Tm/Td-operatører. |
| White Rectangle Overlay | Indikationer | Hvide former tegnet over indhold. |
| Excessive Drawing Operations | Indikationer | Usædvanligt mange tegnekommandoer. |
| Ikke-refererede objekter | Indikationer | Definerede men aldrig refereret. |
| Large Object Number Gaps | Indikationer | Store huller i objektnumrene. |
| Contains JavaScript | Indikationer | JavaScript til stede (ikke nødvendigvis auto-run). |
| Duplicate Images With Different Xrefs | Indikationer | Samme billede gemt som separate objekter. |
| Images With EXIF | Indikationer | Indlejrede billeder indeholder EXIF. |
| CropBox/MediaBox Mismatch | Indikationer | Synligt område mindre end side; indhold kan skjules. |
| Excessive Form Fields | Indikationer | Usædvanligt mange formularfelter. |
| Duplicate Bookmarks | Indikationer | Bogmærker med identiske titler. |
| Invalid Bookmark Destinations | Indikationer | Bogmærker peger på ikke-eksisterende sider. |
| Starter med Nul-byte | Indikationer | Nul-byte før %PDF- header. |
| Mulige e-mailadresser | Indikationer | E-mailadresser i rå data. |
| Mulige webadresser | Indikationer | URL’er i rå data. |
| JPEG-analyse (kvantiseringstabeller) | Indikationer | Mistænkeligt QT-fingeraftryk (fx ugyldigt/forfalsket eller softwarematch). |
| Error Level Analysis (ELA) | Indikationer | Indlejrede billeder viser afvigende komprimeringsmønstre. |
| Hidden Annotations | Indikationer | Annoteringer med Hidden/Invisible-flag. |
| Stablede filtre | JA | Brug af flere filtre til at sløre indhold. |
| Skrifttype-remapping | JA | Visuelle tegn mappet til forkerte Unicode-tegn. |
| Duplikate objekt-ID'er | JA | Samme objekt-ID defineret flere gange (Skygge-angreb). |
| Formfelt-overlay | JA | Felt-værdi eksisterer men er usynlig/skjult. |
| Ubalancerede objekter | JA | Modstrid mellem antal obj og endobj. |
| Version/funktion-modstrid | JA | Gamle versioner der bruger moderne PDF-funktioner. |
| Invisible Text (Rendering Mode 3) | Indikationer | Tekst ikke renderet. |
| Digital Signature (analyse) | Indikationer | Signatur til stede; verificer gyldighed og ByteRange. |

---

## Udvikler og kontakt

**Udvikler:** Rasmus Riis  
**E-mail:** riisras@gmail.com  
**Projekt:** PDFRecon – PDF Forensic Analysis Tool  
**Repository:** https://github.com/Rasmus-Riis/PDFRecon

Manualen og de forensiske indikatorer vedligeholdes med PDFRecon-projektet. Bidrag, fejl eller ønsker til funktioner kan rettes via GitHub-repositoryet.

---

## Bilag: Fuldstændig Indikatorliste

Oversigt over alle tekniske forensiske indikatorer.

| Indikator Nøgle | Fulde Navn |
|---|---|
| `HasXFAForm` | HasXFAForm |
| `HasDigitalSignature` | HasDigitalSignature |
| `MultipleStartxref` | MultipleStartxref |
| `IncrementalUpdates` | IncrementalUpdates |
| `Linearized` | Linearized |
| `LinearizedUpdated` | LinearizedUpdated |
| `HasRedactions` | HasRedactions |
| `HasAnnotations` | HasAnnotations |
| `HasPieceInfo` | HasPieceInfo |
| `HasAcroForm` | HasAcroForm |
| `AcroFormNeedAppearances` | AcroFormNeedAppearances |
| `ObjGenGtZero` | ObjGenGtZero |
| `TrailerIDChange` | TrailerIDChange |
| `XMPIDChange` | XMPIDChange |
| `XMPHistory` | XMPHistory |
| `MultipleCreators` | MultipleCreators |
| `MultipleProducers` | MultipleProducers |
| `CreateDateMismatch` | CreateDateMismatch |
| `ModifyDateMismatch` | ModifyDateMismatch |
| `MultipleFontSubsets` | MultipleFontSubsets |
| `OrphanedObjects` | OrphanedObjects |
| `MissingObjects` | MissingObjects |
| `LargeObjectNumberGaps` | LargeObjectNumberGaps |
| `HiddenAnnotations` | HiddenAnnotations |
| `TimestampSpoofing` | TimestampSpoofing |
| `SubmitFormAction` | SubmitFormAction |
| `LaunchShellAction` | LaunchShellAction |
| `ExtractedJavaScript` | ExtractedJavaScript |
| `TouchUp_TextEdit` | TouchUp_TextEdit |
| `ExifToolMismatch` | ExifToolMismatch |
| `SuspiciousObjectContent` | SuspiciousObjectContent |
| `HasLayers` | HasLayers |
| `MoreLayersThanPages` | MoreLayersThanPages |
| `ColorProfileMismatch` | ColorProfileMismatch |
| `HighDefImage` | HighDefImage |
| `HiddenText` | HiddenText |
| `XMPHistoryGap` | XMPHistoryGap |
| `StructuralScrubbing` | StructuralScrubbing |
| `PDFAViolation` | PDFAViolation |
| `RelatedFiles` | RelatedFiles |
