# Twitch GUI-follows importeren in tv

Gebruik `tv fav import` of **GUI-follows importeren** in het `tv`-menu.
Het resultaat wordt toegevoegd aan de bestaande favorieten. Herhaald importeren
maakt geen duplicaten en verwijdert geen handmatig toegevoegde kanalen.

Alleen controleren: `node ~/.config/tv/gui-importer/import.mjs --check`.

## Werkwijze en grenzen

1. Lees alleen de Local Storage-database van Streamlink Twitch GUI. Maak daarvan
   een tijdelijke kopie in een map met rechten 0700 en controleer dat de bron
   tijdens het kopiëren niet veranderde. De database-engine opent alleen de kopie.
2. Gebruik `classic-level` 3.0.0 en de vastgezette afhankelijkheden in
   `package-lock.json` om de huidige logische `auth`-waarde te lezen. Geen zoeken
   naar tekstfragmenten in binaire bestanden: overschreven en verwijderde records
   worden door LevelDB zelf afgehandeld.
3. Valideer de bestaande GUI-login bij Twitch en haal account, client-ID en de
   toestemming `user:read:follows` uit dat antwoord. De login wordt niet gelogd,
   op de commandoregel gezet of blijvend opgeslagen door de importer. De tijdelijke
   databasekopie wordt na het uitlezen verwijderd.
4. Haal alle pagina's van de officiële Twitch-API op. Accepteer de lijst alleen
   wanneer de kanalen geldig zijn en het aantal overeenkomt met Twitchs totaal.
5. Maak een back-up naast `favorites` en vervang het bestand atomair nadat de
   volledige import succesvol is. Voeg uitsluitend ontbrekende kanalen toe.

Getest met Streamlink Twitch GUI 2.5.3 op macOS. De officiële Twitch-API is
onafhankelijk van de GUI-layout. Alleen het uitlezen van de bestaande login blijft
afhankelijk van Chromium Local Storage en het GUI-authenticatieschema. Bij een
onbekend formaat stopt de import; reeds geïmporteerde favorieten en het tv-menu
blijven werken. Een verlopen login wordt vernieuwd door in de GUI opnieuw in te
loggen, waarna de import weer kan worden gestart. Er wordt geen debugpoort geopend.

De import is bewust een afzonderlijke actie: geen koppeling in `.zshrc`-startup,
geen achtergrondtaak, en geen opnieuw toevoegen van verwijderde favorieten bij elke
opening van het menu.

## Onderhoud

Tests: `node --test ~/.config/tv/gui-importer/import.test.mjs`.
Afhankelijkheden herstellen: `npm ci --prefix ~/.config/tv/gui-importer --ignore-scripts`.
Op deze Mac gebruikt de bibliotheek de meegeleverde native binary.

Bronnen:
- https://dev.twitch.tv/docs/api/reference/#get-followed-channels
- https://dev.twitch.tv/docs/authentication/validate-tokens/
- https://github.com/Level/classic-level
- Geïnstalleerde GUI-bron: `app.nw/main.js`, auth-adapter en channels/followed-model.
