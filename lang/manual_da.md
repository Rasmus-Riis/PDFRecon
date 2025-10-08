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

<b>Multiple DocumentID / Different InstanceID</b>
*<i>Ændret:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: Hver PDF har et unikt DocumentID, der ideelt set er det samme for alle versioner. InstanceID ændres derimod for hver gang, filen gemmes. Hvis der findes flere forskellige DocumentID'er (f.eks. Trailer ID Changed: Fra [ID1...] til [ID2...]), eller hvis der er et unormalt højt antal InstanceID'er, peger det på en kompleks redigeringshistorik, potentielt hvor dele fra forskellige dokumenter er blevet kombineret.

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
• Hvad det betyder: Oprettelses- og ændringsdatoer i PDF’ens Info-felt stemmer ikke overens med datoerne i XMP-metadata (f.eks. Creation Date Mismatch: Info='20230101...', XMP='2023-01-02...'). Sådanne uoverensstemmelser kan pege på skjulte eller uautoriserede ændringer.