# De twee andere richtingen

Aanbevolen is **Teletekst**; die staat volledig in [`DESIGN.md`](../../DESIGN.md). Hieronder de twee
alternatieven, kort. De plaatjes van alle drie staan in [`directions.html`](directions.html): echte uitvoer van
fzf 0.74.4, met voorbeelddata.

Kies je een van deze twee, dan moet `DESIGN.md` voor die richting opnieuw worden geschreven. In alle drie blijft
fzf de motor, blijft de bediening gelijk (Enter, klik, rechtsklik, Ctrl-F, Ctrl-R, Esc, typen om te zoeken) en
is het kanaal dat nu naar de tv gaat in de lijst gemarkeerd.

## Op zender

De regiekamer: één rode balk bovenaan brandt zolang de Mac een stream naar de tv stuurt.

- **Uiterlijk:** warm zwart, crème tekst, amber voor sterren en knoppen, rood alleen voor "op tv". Dunne
  rechte rand om het geheel, een lijn boven de knoppen.
- **Lijst:** één regel per kanaal, zonder puntjeslijnen. Het kanaal op tv heeft een rood bolletje en staat vet.
- **Groot venster (vanaf 100 kolommen):** rechts een paneel met twee blokken: "op tv" en "gekozen" (het kanaal
  onder de cursor), met titel, kijkers en hoe lang de stream bezig is.
- **Beweging:** het bolletje in de balk wisselt elke 2 seconden tussen ● en ◉.
- **Sterk:** de rustigste van de drie; vertelt het duidelijkst wat de tv doet; benut een breed venster het best.
- **Zwak:** donker met één accentkleur lijkt op wat je nu hebt, alleen rood in plaats van paars. Het minst
  schattig. De warme tinten bestaan alleen in truecolor: in Terminal.app wordt het neutraal grijs. Het paneel
  start een proces bij elke cursorbeweging.
- **Ruimte:** 11 kanalen in een venster van 64 × 20 (de rand kost twee kolommen en twee rijen).
- **Tests:** ongeveer dezelfde aanpassingen als bij Teletekst; de zijrand blijft, dus het aanklikken van regels in
  `test_interaction.py` hoeft minder te veranderen.

## Bank

De huiskamer: ronde rand, warme aubergine, twee regels per kanaal.

- **Uiterlijk:** aubergine ondergrond, crème tekst, mosterdgeel voor alles wat je kunt indrukken, terracotta voor
  de ster, salie voor "live" en "op tv". Ronde rand met de naam en de streamstatus erin.
- **Lijst:** boven de naam en het aantal kijkers, eronder de game, de titel van de stream en de duur. Zo zie je
  ook in een smal venster waar een stream over gaat. Een lege regel tussen de kanalen.
- **Beheer:** onder elke actie staat in gewone woorden wat ze doet ("de video op tv stopt; je lijst blijft").
- **Groot venster:** dezelfde kaart, maximaal 100 kolommen breed en gecentreerd.
- **Sterk:** de vriendelijkste; het makkelijkst met de muis, want elke regel is twee keer zo hoog.
- **Zwak:** 4 kanalen in een venster van 64 × 20, tegen 11 bij de andere twee. De kleuren zijn de bekende
  "gezellige app"-kleuren en bestaan alleen in truecolor. De gecentreerde kaart krijgt in fzf geen eigen
  achtergrond in de marges; die houden de kleur van je terminal.
- **Tests:** de grootste verbouwing. Regels van twee regels vragen `--read0` en een ander regelformaat uit
  `tui.py`; de testen op regelbreedte en op één tab per regel moeten anders.

## Waarom Teletekst toch

Het is de enige van de drie die zonder rand en zonder truecolor precies doet wat hij belooft, hij laat de meeste
ruimte over op de bank, en hij is van jou: Nederlands, tv, paginanummers. De andere twee zijn nettere versies van
iets wat al bestaat.
