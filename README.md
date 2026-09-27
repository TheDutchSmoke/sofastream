# SofaStream

Twitch kijken op Apple TV vanuit een terminal op je Mac. Live kanalen worden op
kijkeraantal gesorteerd, met je sterren bovenaan. Offline kanalen hebben een eigen
overzicht. De video speelt in VLC op Apple TV; Streamlink op de Mac levert de stream.

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
profiel en stuurt geen blinde OK-toets. Bij een trage ontwaking blijft dezelfde
startopdracht maximaal 30 seconden proberen VLC te openen, totdat de bediening
beschikbaar is. De stream wordt pas daarna gestart.

Na de eerste succesvolle verbinding gebruikt SofaStream het opgeslagen
Companion-adres en de VLC-appcode. Het controleert de koppeling bij iedere
verbinding; bij een gewijzigd adres of poort wordt het apparaat opnieuw gezocht.
Dit voorkomt de twee afzonderlijke zoekrondes van eerdere devversies. Je bestaande
koppeling blijft geldig; opnieuw koppelen is hiervoor niet nodig.

## Bediening

- Klik of Enter: kanaal of overzicht openen.
- Ctrl-F of rechtsklik: ster wisselen. Dit wijzigt geen Twitch-follows.
- Ctrl-R: Twitch-status verversen.
- Esc: zoekopdracht wissen, teruggaan of sluiten.
- Beheer: favorieten, GUI-import, status, stoppen, logs en koppelen.
- De status in de bovenrand volgt de Mac-stream automatisch, zonder de tv te bedienen.
- Video sluiten op de tv sluit de Mac-stream zodra VLC de HTTP-verbinding verbreekt.
- De melding ‘Afspelen gestart’ is een bevestiging van die actie; ‘Status’ is een
  gedateerde momentopname. De bovenrand geeft de actuele Mac-status.

`tv --help` toont de commando's. `tv stop` stopt alleen de eigen stream. Sluiten van
de TUI laat de video doorspelen; stoppen doe je op de tv of met `tv stop`.

## Development: @dev

`main` bevat releases. Nieuw werk gebeurt op `development` en komt alleen via een
beoordeelde pull request in `main`. Een dev-installatie verandert main niet.

```sh
brew trust --formula TheDutchSmoke/sofastream/sofastream-preview
brew install TheDutchSmoke/sofastream/sofastream@dev
tv-dev
```

Beide versies komen uit dezelfde tap. De devversie heeft eigen instellingen,
favorieten, cache, Streamlink-poort (8766) en proceslabel. De normale `tv` gebruikt
poort 8765. Met beide kun je dezelfde fysieke tv bedienen; start daar bewust maar
één stream tegelijk. Een installatie of upgrade benadert nooit de Apple TV.

Onder **Instellingen** heeft `tv-dev` een eigen **DEV**-sectie met versie-informatie
en een actie om ontbrekende voorkeuren uit stabiel over te nemen. Bestaande
devinstellingen worden behouden; koppelgegevens worden niet gekopieerd.
`tv-dev dev` toont de versie, het instellingenpad en het updatecommando.

## Gegevens en privacy

Stabiel gebruikt `~/.config/tv` en `~/.cache/tv`. Dev gebruikt
`~/.config/sofastream-dev` en `~/.cache/sofastream-dev`.
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

De oorspronkelijke VLC-playback is op echte hardware bevestigd. Automatisch
wekken, stoppen en nieuwe devfuncties moeten nog op hardware worden bevestigd;
tijdens de ontwikkeling was de tv in gebruik. CI bewijst geen hardwarewerking.

Bronnen: [Streamlink HTTP-uitvoer](https://streamlink.github.io/cli.html#player-options),
[pyatv](https://pyatv.dev/documentation/atvremote/),
[Homebrew-taps](https://docs.brew.sh/How-to-Create-and-Maintain-a-Tap).
