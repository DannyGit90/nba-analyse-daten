# Vorschlag Protokoll v1.12 (Entwurf, nicht in Kraft)

Status: reiner Diskussionsentwurf. Aendert weder CHAT_PROTOCOL.md noch Modell, Parameter, Freigaben, Workflows oder Zeitplaene. `betting_release=false` bleibt.

## Anlass

Das Protokoll verlangt fuer jede Farbe ein geeignet begruendetes eigenes p von mindestens 65 %. Das experimentelle Modell liefert kein solches p: keine Personalkorrektur, keine Kalibrierung fuer Handicap/Total, Favoriten ab 65 % trafen in der Auswertung (Stand 27.11.2026, 65 bewertete Spiele) nur zu 65,1 % bei mittlerer Prognose 75,7 %. Folge: praktisch nie eine Farbe, und es gibt keine Daten, ob die Kandidaten Value hatten.

Ziel: Beweisfuehrung verbessern, nicht die Schwellen ohne Beleg senken.

## A. Kalibriertes Sieger-p

- p_kal = beobachtete Trefferquote der passenden Prognosegruppe aus `paper_evaluation.json` (Gruppen wie dort ausgewiesen), mit Wilson-95-%-Intervall offengelegt.
- Nur verwenden, wenn die Gruppe mindestens 20 bewertete Spiele hat. Sonst keine kalibrierte Schaetzung.
- Gilt nur fuer Sieger inklusive Verlaengerung. Fuer Handicap und Total erst nach eigener Vorwaertsauswertung je Markt.
- 65-%-Filter und EV-Schwellen werden auf p_kal angewendet. Rohes Modell-p allein schaltet keinen Filter frei (unveraendert).
- Bekannte Schwaeche: Gruppen sind nach Ergebnissen gebildet worden, Stichproben klein, Spieldaten nicht unabhaengig.

## B. Zwischenstufe PAPIER-GRUEN / PAPIER-GELB / PAPIER-ROT

- Gleiche EV-Grenzen wie die Valuebasisfarben, aber p aus Modell oder p_kal, ausdruecklich unvalidiert.
- Keine Empfehlung, keine Einsatzgroesse, keine Zaehlung als Empfehlung. Zweck: Kandidaten sichtbar und spaeter auswertbar machen.
- Ungewoehnlich hoher EV (z. B. ueber +15 %) wird als moeglicher Daten-/Modellfehler markiert statt hochgestuft.
- Offene Personalausfaelle stufen nur herab, nie hoch.

## C. Papier-Wettbuch (automatisch)

Felder je Eintrag: game_id, Markt, Auswahl, Linie, Quote, Anbieter, Preisstand, p_modell, p_kal, EV, Papierstufe, Eintragszeit, Ergebnis, Einheit (immer 1).

Regeln:
- Nur Eintraege vor Spielbeginn, nie nachtraeglich aendern oder loeschen.
- Erster Eintrag je Auswahl zaehlt, kein Ergebnis fliesst in die Auswahl.
- Auswertung: Trefferquote, Brier, Rendite in Einheiten, getrennt nach Stufe und Markt, mit Intervallen.
- Schwellenaenderungen erst nach ausreichender Stichprobe. Vorschlag (nicht validiert): mindestens 100 Eintraege und vier Wochen.
- Erzeugung automatisch per Workflow, keine Nutzerpflege. Bestehendes Archiv `paper_log/` bleibt unveraendert.

## Nicht Teil dieses Vorschlags

- Keine Senkung der 65-%-Grenze ohne Auswertung.
- Marktquoten werden nicht zur Erzeugung von p verwendet.
- Kein Wettangebot, keine Einsatzempfehlung, keine Echtgeldfreigabe.
- Keine Aenderung am Modell oder an Kalibrierungsstatus.

## Offene Fragen

1. Gruppengrenzen fuer p_kal (derzeit die Baender aus paper_evaluation.json)?
2. Mindestgroesse n=20 und Wilson-Intervall ausreichend?
3. Schwelle fuer die Fehlerwarnung bei hohem EV?
4. Zusammenspiel mit dem Personal-Diagnose-Pull-Request (scripts/personnel_effect_diagnostic.py)?
