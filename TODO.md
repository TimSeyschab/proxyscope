# TODO

Priorisierte naechste Schritte fuer `proxyscope`, abgeleitet aus dem aktuellen Repo-Stand am 2026-03-11.

## P0 - Als Naechstes sinnvoll

- [x] Replay robust machen
  Aktuell basiert Replay auf `body_preview` aus dem In-Memory-Journal. Dadurch koennen groessere oder binaere Requests abgeschnitten oder verfremdet erneut gesendet werden. Sinnvoll waere eine Trennung zwischen Vorschau fuer die UI und vollstaendigem Raw-Request fuer Replay/Export.

- [ ] Echte Integrations-/Socket-Tests in einer CI-Pipeline absichern
  Die reine Logik ist gut getestet, aber die servernahen Tests fuer Forwarding, CONNECT und MITM-Bootstrap brauchen echte Socket-Binds. Diese Pfade sind produktkritisch und sollten in CI ausserhalb der aktuellen Sandbox verifiziert werden.

- [ ] Request-/Response-Streaming statt Full-Buffering vorbereiten
  `UpstreamForwarder` laedt Antworten komplett in den Speicher (`response.content`). Das ist fuer Debugging bequem, skaliert aber schlecht bei grossen Bodies, Downloads und langen Streams. Ein naechster sinnvoller Schritt ist ein Streaming-Modus mit Groessenlimits fuer UI-Preview und Logging.

- [ ] TUI um Filter und Suche erweitern
  Die Request-Liste ist aktuell eine einfache Chronologie. Fuer ein Proxy-Debugging-Tool sind Filter nach Host, Methode, Status und Freitextsuche der direkteste Produktivitaetsgewinn.

## P1 - Danach hoher Nutzen

- [ ] Export von Mitschnitten als HAR oder JSON
  Das Projekt sammelt bereits strukturierte Exchanges. Ein Exportformat waere der naechste logische Schritt fuer Team-Sharing, Bugreports und Offline-Analyse.

- [ ] Persistente Session-Historie fuer Requests einfuehren
  Im Moment ist das Journal rein im Speicher. Optionales Speichern und Wiederladen vergangener Sessions wuerde den Wert des Tools deutlich erhoehen.

- [ ] Policy-System um URL-Prefix-/Host-Regeln und Prioritaeten ausbauen
  Es gibt schon statische Antworten und Editor-Policies, aber fuer reale Workflows fehlen komfortable Regelstufen wie Host-weit, Prefix-weit, explizite Prioritaet und Konfliktauflosung.

- [ ] Bessere Steuerung fuer MITM im CLI/Config ergaenzen
  MITM wird beim Server-Bootstrap behandelt, aber nicht als klar sichtbare Runtime-/CLI-Funktion praesentiert. Sinnvoll waeren explizite Flags und Konfigurationsoptionen fuer an/aus, Zertifikatspfade und Failover-Verhalten.

- [ ] Strukturierte Response-Manipulation ohne externen Editor anbieten
  Der Editor-Flow ist flexibel, aber langsam fuer kleine Anpassungen. Einfache Built-ins fuer Header-Override, Statuscode-Override oder Body-Templates wuerden haeufige Faelle beschleunigen.

## P2 - Technische Qualitaet und Produktreife

- [ ] HTTP-Semantik sauberer absichern
  Pruefen und haerten: Hop-by-hop-Header, Chunked-Encoding, Kompression, Redirect-Verhalten, sehr grosse Bodies und Timeout-/Abbruch-Szenarien. Das senkt spaetere Proxy-Sonderfaelle deutlich.

- [ ] Mehr Beobachtbarkeit einbauen
  Nuetzlich waeren Metriken oder zumindest strukturiertere Diagnosen fuer Upstream-Fehler, Tunnel-Abbrueche, Policy-Treffer und Replay-Ergebnisse.

- [ ] Dokumentation fuer typische Workflows ausbauen
  README deckt Start und Grundfunktionen ab. Es fehlen kurze, reproduzierbare Beispiele fuer Browser-Setup, CA-Trust, Replay, Policy-Editing und Troubleshooting.

- [ ] Packaging und Release-Qualitaet erweitern
  Vor einem breiteren Einsatz sinnvoll: Changelog, reproduzierbare Release-Checks, eventuell Wheel-Smoke-Test und klarere Alpha-Einschraenkungen in der Doku.

## Konkrete Reihenfolge

1. Replay robust machen.
2. Socket-Integrations-Tests in CI absichern.
3. TUI-Filter/Suche liefern.
4. Exportformat und persistente Sessions ergaenzen.
5. Streaming-/Speichergrenzen fuer grosse Transfers angehen.
