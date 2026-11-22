# Forsyning Online for Home Assistant

Henter dit vandforbrug **time for time** fra kundeportalen på
[forsyningonline.dk](https://forsyningonline.dk) (bruges af en række danske
vandværker) og gør det tilgængeligt i Home Assistant.

> **Uofficiel.** Integrationen bruger det samme interne API som portalens egen
> hjemmeside. Det er ikke dokumenteret, og det kan ændre sig uden varsel.
> Projektet har ingen tilknytning til Forsyning Online eller dit vandværk.

*An unofficial Home Assistant integration that reads hourly water usage from
the forsyningonline.dk customer portal.*

## Hvad får du

- **Langtidsstatistik** `forsyningonline:water_total` (m³, kumulativ) med
  timeopløsning. Den kan vælges direkte som vandkilde i **Indstillinger →
  Dashboards → Energi → Vandforbrug**.
- Sensorer: **Vandforbrug i dag**, **i går** og **seneste time** (m³).
- Historik hentes ved første opsætning (som standard 30 dage).

## Installation (HACS, som brugerdefineret repository)

1. Åbn **HACS → ⋮ → Brugerdefinerede repositories**.
2. Tilføj `https://github.com/hsk-dk/home-assistant-forsyningonline`, kategori
   **Integration**.
3. Find **Forsyning Online** i HACS, vælg **Download**, og genstart Home
   Assistant.
4. **Indstillinger → Enheder & tjenester → Tilføj integration → Forsyning
   Online**.

## Opsætning

Brug det **brugernavn og den adgangskode**, du logger ind med på
forsyningonline.dk. MitID virker ikke, da Home Assistant skal kunne logge ind
igen af sig selv.

Under integrationens **Indstillinger** kan du ændre opdateringsintervallet
(standard 60 min, mindst 15 min). Vær venlig mod portalen: timedata skifter
kun én gang i timen.

## Sådan virker det

Portalens token er kun gyldigt i ca. 15 minutter, så integrationen logger ind
ved hver opdatering. Den læser timeforbruget for i går og i dag, regner en
løbende sum og skriver den som ekstern statistik. Fremtidige timer springes
over. Ved nedetid hentes de manglende dage ved næste opdatering.

## Kendte begrænsninger

- Kun den samlede måler (`Totalt forbrug`) bruges.
- Skiftedage mellem sommer- og vintertid er ikke testet.
- Hvis portalen ændrer sit side-id, kan det rettes under Indstillinger.

## Udvikling

```
pip install pytest
pytest
```

Licens: MIT
