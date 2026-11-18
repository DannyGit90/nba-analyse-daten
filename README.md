# NBA-Analyse: Betrieb und Bereinigung

Experimentelles öffentliches Projekt. Keine privaten Nutzer-/Wettdaten, keine Echtgeldfreigabe.

`PROJECT_INSTRUCTION.txt` verweist auf `CHAT_PROTOCOL.md`; bei START/CHECK neu lesen. BEOBACHTEN, UNGEPRÜFT, AUSLASSEN und Empfehlungen unterscheiden; Sieger, Handicap und Gesamtpunkte nachvollziehbar prüfen.

## Artefakte
- `reports/paper_latest.json` und `paper_evaluation.json`: letzter gespeicherter Paper-Lauf und prospektive Auswertung; Zeitstempel prüfen.
- `reports/paper_health.json`: ergänzende Betriebsdiagnose, erst nach angepasstem Workflow vorhanden. `ready_paper_only` ist keine Wettfreigabe, `partial` nur Teilabdeckung. Blockierte/veraltete/fehlerhafte Ausgabe lässt den Schlusscheck scheitern.
- `reports/model_summary.json`, `model_state.json`, `model_test.json`: anderer Modellzweig NBA-Ridge-GH-1, kein Ersatz für Paper-Prognosen. Historische Zeitplanangaben darin gelten für diesen Bericht/Zweig.
- `reports/season_prior_test.json`, `calibration_audit.json` und `diagnostics/`: Prüfartefakte, keine Tagesprognosen oder aktuelle Vollständigkeitsgarantie.
- `paper_log/`: von Monitor/Auswertung gelesene Vorabprognosen; nicht nach Ergebnis löschen, überschreiben, rückdatieren oder nachträglich ersetzen.

## Offener Datenengpass
Der Monitor lädt eine externe DuckDB bei jedem Lauf; keine Rohdatenbank im Repository. Berichte löschen aktualisiert die Quelle nicht. Im geprüften Lauf vom 18.11.2026, 06:17 UTC, fehlt nach Importfiltern Log `0022600257`; die globale Aktualitätsprüfung sperrt zwölf Prognosen. Ob ungefilterte Quelle oder Filter/Zuordnung ursächlich sind, bleibt ohne erneute Live-Abfrage ungeklärt. Ergebnisse des aktuellen UTC-Tages werden bewusst ausgeschlossen. Sperre nicht umgehen; bloßer Endstand genügt nicht für benötigte Team-Ratings und Tempo.

## Betrieb
Paper-Workflow planmäßig alle vier Stunden sowie manuell/bei passenden Codeänderungen; keine Ausführungsgarantie. Neue Betriebsdiagnose wird offline getestet und vor abschließendem Verfügbarkeitscheck gespeichert. Acht Stunden maximale Berichtalterung sind eine Betriebsgrenze (zwei Intervalle), keine statistische Sicherheitsmarge oder Preisaktualitätsgarantie. Sie ersetzt keine Injury-/Marktrecherche oder vollständige Prognosevalidierung.

Test: `python -m unittest discover -s scripts -p 'test_paper_health.py' -v`. Lokale Tests sind kein Live-End-to-End-Nachweis. Modellformeln, Parameter, Sperren, Freigaben und Zeitplan bleiben unverändert.

Keine sicher entbehrliche Datei identifiziert: Archive und Prüfartefakte bleiben erhalten. Bereinigt werden Anweisungen, Dokumentation und die Gleichsetzung von Ausführung und Verfügbarkeit. Weitere Import-/Modelländerungen oder Löschungen gezielt prüfen und separat bestätigen.
