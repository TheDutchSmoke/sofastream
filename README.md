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

## Bediening

- Klik of Enter: kanaal of overzicht openen.
- Ctrl-F of rechtsklik: ster wisselen. Dit wijzigt geen Twitch-follows.
- Ctrl-R: Twitch-status verversen.
- Esc: zoekopdracht wissen, teruggaan of sluiten.
- Beheer: favorieten, GUI-import, status, stoppen, logs en koppelen.
- De onderste statusregel volgt de Mac-stream automatisch, zonder de tv te bedienen.
- Video sluiten op de tv sluit de Mac-stream zodra VLC de HTTP-verbinding verbreekt.
- De melding ‘Afspelen gestart’ is een bevestiging van die actie; ‘Status’ is een
  gedateerde momentopname. De onderste regel geeft de actuele Mac-status.

`tv --help` toont de commando's. `tv stop` stopt alleen de eigen stream. Sluiten van
de TUI laat de video doorspelen; stoppen doe je op de tv of met `tv stop`.

## Development: @dev

`main` bevat releases. Nieuw werk gebeurt op `development` en komt alleen via een
beoordeelde pull request in `main`. Een dev-installatie verandert main niet.

```sh
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

De oorspronkelijke VLC-playback is op echte hardware bevestigd. Automatisch
wekken, stoppen en nieuwe devfuncties moeten nog op hardware worden bevestigd;
tijdens de ontwikkeling was de tv in gebruik. CI bewijst geen hardwarewerking.

Bronnen: [Streamlink HTTP-uitvoer](https://streamlink.github.io/cli.html#player-options),
[pyatv](https://pyatv.dev/documentation/atvremote/),
[Homebrew-taps](https://docs.brew.sh/How-to-Create-and-Maintain-a-Tap).
