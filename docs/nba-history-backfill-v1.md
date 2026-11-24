# Erweiterung der Teamhistorie

Ersetzt den bisherigen Fuenf-Saisons-Erstumfang der Teamprotokolle durch die
vom bestehenden Modell-Lader angeforderten Saisons ab Endjahr 2010.
Fehlende abgeschlossene Saisons werden automatisch geladen; vorhandene
wiederverwendet und geprueft. Keine feste Spielzahl pro Saison, keine
Ergaenzung fehlender Heimflags. Spielerhistorie und Modellparameter bleiben gleich.

Historien-Staging -> unveraenderter aktueller Kollektor -> validierter
Daten-Commit. Ein erfolgreicher Historienteilschritt ist kein erfolgreicher
Gesamtimport. Altbestand, Groessenlimits und Freigabesicherungen bleiben erhalten.

reports/store/status.json enthaelt kleine Tabellen-/Qualitaetszahlen und den
Hash des vorherigen Manifests statt langer Spielerlisten. Realen erweiterten
Import und spaetere Fortschreibung pruefen; lokale Tests ersetzen diese nicht.

Dieser Patch aendert noch keine Analysemodule und keine Analysezeitplaene.
Lokaler Analysezugriff und die verbindliche Import-vor-Analyse-Reihenfolge
bleiben der naechste Integrationsblock. Keine Modell- oder Wettfreigabe.
