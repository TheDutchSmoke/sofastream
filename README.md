# SofaStream

Twitch kijken op Apple TV vanuit een terminal op je Mac. Live kanalen worden op
kijkeraantal gesorteerd, met je sterren bovenaan. Offline kanalen hebben een eigen
overzicht. De video speelt in VLC op Apple TV; op de Mac filtert Streamlink de reclame
en houdt een doorgeefluik (`app/relay.py`) één stream naar VLC open.

## Installeren

```sh
brew install TheDutchSmoke/sofastream/sofastream
tv
```

Dit is een eigen Homebrew-tap, geen pakket in homebrew/core. Vereist macOS,
VLC op Apple TV en beide apparaten op hetzelfde lokale netwerk.

Voor de eerste weergave:

```sh
tv settings
```

Kies **Zoek Apple TVs op het netwerk**, selecteer een apparaat en ga terug.
Opgeslagen apparaten zijn zichtbaar zonder te scannen. Een wijziging geldt bij
de volgende kanaalkeuze; status en stoppen blijven bij de actieve sessie horen.
Een apparaat wordt ook bij een gewijzigd IP-adres herkend aan zijn apparaat-ID.
Handmatig instellen kan met `tv configure <host> [naam]`.

Open VLC en schakel **Afspelen op afstand / Remote Playback** in. Kies daarna een
kanaal in `tv`. De Mac moet aanblijven tijdens het kijken.
Eenmalig `tv pair` koppelt de afstandsbediening voor automatisch wekken en VLC
openen. Hierbij verschijnt een pincode op de Apple TV: doe dit wanneer die vrij is.
HDMI-CEC bepaalt of ook het fysieke televisiescherm automatisch aangaat.

Automatisch starten in de devversie stel je eenmalig in met
`sofastream@dev pair` (of **Instellingen → Automatische start**). Voer de pincode
op de Apple TV in wanneer die vrij is. Dit slaat de koppeling alleen in je
devprofiel op en schakelt automatisch starten in. Instellingen toont of voor de
geselecteerde Apple TV een koppeling is opgeslagen. Een kanaal kiezen controleert
eerst de stream, wekt de gekoppelde Apple TV, opent VLC, wacht op de bediening en
start daarna de stream. Staat VLC al klaar, dan is wekken niet nodig.
VLC moet geïnstalleerd zijn en **Afspelen op afstand** moet eenmalig zijn aangezet.
Een Apple TV zonder stroom of netwerk kan niet worden gewekt.

Verschijnt bij ontwaken **Wie kijkt er?**, zet dan op de Apple TV eenmalig
**Instellingen → Profielen en accounts → Kies profiel bij uitschakelen
sluimerstand** uit ([Apple-uitleg](https://support.apple.com/nl-nl/guide/tv/atvb13056b3d/tvos)).
Zo kan de kanaalkeuze direct doorgaan naar VLC. SofaStream kiest geen willekeurig
profiel en stuurt geen blinde OK-toets. Sluit tvOS VLC doordat je na het wekken een
profiel kiest, dan opent SofaStream VLC binnen 30 seconden na de start één keer
opnieuw en herstart de stream. Sluit je in die eerste 30 seconden zelf bewust de
video, dan gebeurt dat dus ook één keer; `tv stop` of een ander kanaal kiezen
annuleert het herstarten. Bij een trage ontwaking blijft dezelfde
startopdracht maximaal 30 seconden proberen VLC te openen, totdat de bediening
beschikbaar is. De stream wordt pas daarna gestart.

Na de eerste succesvolle verbinding gebruikt SofaStream het opgeslagen
Companion-adres en de VLC-appcode. Het controleert de koppeling bij iedere
verbinding; bij een gewijzigd adres of poort wordt het apparaat opnieuw gezocht.
Dit voorkomt de twee afzonderlijke zoekrondes van eerdere devversies. Je bestaande
koppeling blijft geldig; opnieuw koppelen is hiervoor niet nodig.

## 2K (1440p)

Twitch biedt 1440p alleen in H.265 aan, en meestal alleen aan ingelogde kijkers.
Zet in **Instellingen → 2K** aan; dit vraagt een Apple TV 4K (H.265-decodering).
SofaStream leest je Twitch-login uit de macOS-sleutelhanger (dienst
`streamlink-twitch-auth`, account `twitch`); de login komt niet in instellingen,
launchd of het Streamlink-log. Eenmalig opslaan: open twitch.tv ingelogd, kopieer in
de browserconsole `copy(document.cookie.match(/auth-token=([^;]+)/)[1])` en voer uit:

```sh
security add-generic-password -U -a twitch -s streamlink-twitch-auth -w "$(pbpaste)" && pbcopy < /dev/null
```

Zonder (geldige) login speelt het kanaal gewoon af in maximaal 1080p; het
Streamlink-log meldt dan waarom. Een andere dienstnaam kan met
`TV_TWITCH_KEYCHAIN_SERVICE`.

Streamlink leest ook je eigen Streamlink-config (`config` en `config.twitch`). Staat
daar een login (`twitch-api-header`), dan gebruikt SofaStream die ook. Instellingen
toont dat. Is die login verlopen, dan meldt een kanaalkeuze dat, in plaats van
"offline". Met 2K uit speelt SofaStream altijd H.264, ook als je config H.265 of AV1
aanzet. SofaStream logt altijd op niveau `info`, zodat de login niet in het
Streamlink-log komt, ook niet bij `loglevel=debug` in je config.

## Bediening

- Klik of Enter: kanaal of overzicht openen.
- Ctrl-F of rechtsklik: ster wisselen. Dit wijzigt geen Twitch-follows.
- Ctrl-R: Twitch-status verversen.
- Esc: zoekopdracht wissen, teruggaan of sluiten.
- Beheer: favorieten, GUI-import, status, stoppen, logs en koppelen.
- De status in de bovenrand volgt de Mac-stream automatisch, zonder de tv te bedienen,
  met de kwaliteit die de tv krijgt, bijvoorbeeld `ACTIEF · kanaal · 1440p60 · 2K`.
- Het menu gebruikt het hele terminalvenster, zoals `less` of `top`; na het sluiten
  staat je terminal er weer bij zoals ervoor.
- Video sluiten op de tv sluit de Mac-stream zodra VLC de HTTP-verbinding verbreekt.
- De melding ‘Afspelen gestart’ is een bevestiging van die actie; ‘Status’ is een
  gedateerde momentopname. De bovenrand geeft de actuele Mac-status.
- Een ander kanaal wisselt binnen dezelfde stream: VLC krijgt geen opdracht, het oude
  kanaal speelt tot het nieuwe beeld heeft. (VLC 3.0.24 op tvOS faalt op een tweede
  item in één sessie en opent een stream met een korte proefverbinding.)

`tv --help` toont de commando's. `tv stop` stopt alleen de eigen stream. Sluiten van
de TUI laat de video doorspelen; stoppen doe je op de tv of met `tv stop`.
Een nieuwere kanaalkeuze of `tv stop` gaat altijd voor op een start die nog bezig is,
ook in een ander venster of bij het eenmalig herstarten na een profielkeuze.
Ctrl-C tijdens het starten stopt Streamlink als de tv nog niet verbonden is.

## Development: @dev

`main` bevat releases. Nieuw werk gebeurt op `development` en komt alleen via een
beoordeelde pull request in `main`. Een dev-installatie verandert main niet.

```sh
brew trust --formula TheDutchSmoke/sofastream/sofastream-preview
brew install TheDutchSmoke/sofastream/sofastream@dev
tv-dev
```

Homebrew ondersteunt `@dev` via een alias naar de interne preview-formule.
Daarom vereist recent Homebrew vertrouwen voor die interne naam. Beide versies
komen uit dezelfde tap; er is geen aparte dev-tap. De devversie heeft eigen instellingen,
favorieten, cache, Streamlink-poort (8766) en proceslabel. De normale `tv` gebruikt
poort 8765. Met beide kun je dezelfde fysieke tv bedienen; start daar bewust maar
één stream tegelijk. Een installatie of upgrade benadert nooit de Apple TV.

Onder **Instellingen** heeft `tv-dev` een eigen **DEV**-sectie met versie-informatie
en een actie om ontbrekende voorkeuren uit stabiel over te nemen. Bestaande
devinstellingen worden behouden; koppelgegevens worden niet gekopieerd.
`tv-dev dev` toont de versie, het instellingenpad en het updatecommando.

## Gegevens en privacy

Stabiel gebruikt `~/.config/tv` en `~/.cache/tv`. Dev gebruikt
`~/.config/sofastream-dev` en `~/.cache/sofastream-dev`. Het Streamlink-log staat in
de cachemap (`stream.log`, `stream.err`), niet meer in `/tmp`.
Instellingen, favorieten, pairings, tokens en gebruikerslogs horen niet in Git.
De GUI-importer leest een tijdelijke kopie van Chromium LevelDB en haalt volgtabellen
op via de Twitch API. [Werkwijze en grenzen](app/gui-importer/README.md).
Publieke Twitch-metadata gebruikt de web-GQL-interface; bij een fout blijft de TUI
werken en worden verouderde gegevens als onbekend gemarkeerd.

## Ontwikkelen

```sh
git clone https://github.com/TheDutchSmoke/sofastream.git
cd sofastream
git switch development
./scripts/setup
./bin/tv-dev
```

`scripts/setup` installeert vastgezette Python- en Node-afhankelijkheden en maakt
geen verbinding met Apple TV. Tests gebruiken tijdelijke bestanden en lokale
VLC-fixtures. Hardwaretests worden apart en alleen op een beschikbare tv gedaan.

Een nieuwe devversie publiceren: verhoog `VERSION` (bijvoorbeeld `0.2.0-dev.2`),
commit en push naar `development`, wacht op groene CI en voer
`./scripts/publish-release` uit. Dat maakt een prerelease en werkt uitsluitend
`sofastream@dev` in dezelfde tap bij. Voor een stabiele release verloopt de
wijziging eerst via een pull request naar `main`; gebruik daar een versie zonder
`-dev` en hetzelfde script. Het script gebruikt je bestaande `gh`-login.

Homebrew ondersteunt letters na `@` via een tap-alias. De naam voor installatie
en updates is `sofastream@dev`; intern verwijst die naar de preview-formule.
Homebrew vereist vertrouwen voor die interne formulenaam; alleen vertrouwen op
de alias is niet voldoende. Dit is dezelfde tap, geen aparte dev-tap.
Gebruik bij voorkeur fzf 0.74.4 of nieuwer: oudere versies hebben bekende fouten
bij het lezen van muisinvoer. CI gebruikt de vastgezette 0.74.4-release en
controleert de officiële SHA-256 van de download.

Op echte hardware bevestigd (15 november 2026): VLC-playback, automatisch wekken
en VLC openen, en video sluiten op de tv laat de Mac-stream gestopt. Het eenmalig
herstarten na een profielkeuze moet nog op hardware worden bevestigd.
Op 19 november bevestigd op VLC 3.0.24: 0.3.0 start na een eerdere stream zonder VLC te
herstarten, en wisselt binnen één stream (H.265 1440p ↔ H.264 1080p), ongeveer een seconde
achter de browser. Een wissel duurt 2–5 s: zo lang levert Twitch het eerste beeld. Na veel
wissels raakte VLC uit de pas (geluid weg) doordat elke bron zijn klok bij nul begon; sinds
0.3.1 loopt de klok door (op de Mac nagebootst: 0 in plaats van 88 weggegooide beelden).
CI bewijst geen hardwarewerking.

Bronnen: [Streamlink HTTP-uitvoer](https://streamlink.github.io/cli.html#player-options),
[pyatv](https://pyatv.dev/documentation/atvremote/),
[Homebrew-taps](https://docs.brew.sh/How-to-Create-and-Maintain-a-Tap).
