# Dauerhafter NBA-Quellenbestand v1

Eigene versionierte JSONL-Tabellen unter data/nba, mit SHA-256-Manifest.
Git erhaelt fruehere angenommene Staende. Kein fluechtiger Cache und kein
kostenpflichtiger Datenbankserver. Der neue Workflow laeuft nur in oeffentlichen
Repositories auf Standardrunnern. Keine Aenderung bestehender Analyseworkflows.

Umfang: gesamter Quellen-Spielerkatalog; alle 30 aktuellen NBA-Teams; datierte
Kader und Spielplan der aktuellen Saison; regulaere Team-Spielprotokolle der
aktuellen und vier vorigen Saisons; regulaere Spieler-Spielprotokolle der
aktuellen und vorigen Saison mit den expliziten Importfeldern. Keine gesamte
NBA-Historie, kein Play-by-play, keine historische Injury-/Quoten-Vollabdeckung.

Sechs geplante Aktualisierungen taeglich plus manueller Start und Code-Push.
Aktive Saisonpartitionen werden neu geprueft; vorhandene abgeschlossene Saisons
werden wiederverwendet, nicht automatisch nachkorrigiert. Neue Saisonpartitionen
entstehen dynamisch; alte bleiben erhalten. Neue Spieler nach ID ohne Namensfix.
Fehlende Katalog-IDs bleiben als source_present=false gespeichert. Keine
Verschmelzung gleicher Namen und keine automatische Aufloesung mehrdeutiger IDs.
Kaderaenderungen sind beobachtete Differenzen, keine bestaetigten Transaktionen
oder exakten Wirksamkeitszeitpunkte. Datumskorrekturen bleiben in Git erhalten.

Erst komplett getrennt vorbereiten und validieren, dann Daten plus Manifest
in einem Git-Commit speichern. Bei Fehler bleibt der Altbestand unveraendert;
reports/store/latest.json zeigt den letzten Versuch, data/nba/manifest.json den
letzten angenommenen Stand. Verschwundene Spielschluessel sperren die Uebernahme.

Schutzgrenzen: Quellenmetadaten maximal 72 Stunden, Kadertag maximal drei Tage
alt; 200000 Zeilen je Abfrage, 20 MB je Tabelle, 100 MB Gesamtbestand. Bei
Ueberschreitung Fehler statt Abschneiden. Kein automatisches Archivloeschen;
Git-Speicher waechst mit der Historie. Die 30-Team-Pruefung belegt Quellabdeckung,
nicht unabhaengig jeden Vertrag oder Echtzeitaktualitaet. Quelle nur lesend,
keine verifizierte quellenseitige Gesamttransaktion. Beobachtungszeit ist kein
historischer Veroeffentlichungsnachweis. Das min-Feld bleibt unveraendert und
wird nicht als validiertes Merkmal freigegeben. Fehlender Injury-Eintrag heisst
nicht gesund.

Abnahme: lokale DuckDB-Testtabellen fuer Erstaufbau, Wiederholung, neue Spieler,
Teamwechsel, Korrekturen und Fehlerisolation. Danach realen Erstimport und einen
spaeteren Aktualisierungslauf lesen. Die bisherigen Analysemodule lesen noch
extern; ihre Umstellung auf diesen Datenvertrag bleibt ein weiterer Patch.
Keine Aenderung von Modellparametern, Prognosearchiven oder Freigaben.
