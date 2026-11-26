# Miele Plus – robuste Miele-Integration für Home Assistant

Eine eigenständige Custom Integration (`miele_plus`) für die Miele 3rd-Party-Cloud-API.
Sie läuft **parallel** zur offiziellen `miele`-Integration (andere Domain) und legt den
Schwerpunkt auf **Zuverlässigkeit** und **Automationsfreundlichkeit**.

## Was ist besser als bei der offiziellen Integration?

### Zuverlässigkeit
| Problem | Lösung in Miele Plus |
|---|---|
| Event-Stream (SSE) „hängt“ still, ohne dass ein Fehler kommt | **Watchdog**: kommt 90 s lang nichts (auch kein Ping), wird neu verbunden |
| Nach Verbindungsabbruch verpasste Zustandswechsel | Nach jedem Reconnect sofortiger **Abgleich per REST** |
| Push fällt aus → Werte frieren ein | **Automatischer Polling-Fallback**: 30 s solange ein Programm läuft, sonst konfigurierbar; bei gesundem Push nur 10‑min‑Sicherheitsnetz |
| Kurze Cloud-Aussetzer → alle Entitäten „nicht verfügbar“ | **Grace-Periode** (Standard 15 min): letzter bekannter Zustand bleibt erhalten |
| 5xx / 429 / Timeouts | Wiederholung mit **exponentiellem Backoff + Jitter**, `Retry-After` wird beachtet |
| Unerwartetes 401 trotz gültigem Token | **Erzwungener Token-Refresh** und erneuter Versuch; erst danach Reauth-Dialog |
| Große Payloads mit vielen Geräten | Eigener SSE-Parser ohne Zeilenlängen-Limit, UTF‑8 über Chunk-Grenzen hinweg |
| Neue Geräte erst nach Neustart sichtbar | Neue Geräte werden **live** hinzugefügt |
| Options-/Token-Updates lösen Reloads aus | Reload nur bei echten Optionsänderungen |
| Keine eigenen Abhängigkeiten | Kein externes PyPI-Paket → keine Versionskonflikte bei HA-Updates |

Diagnose-Sensor **„Aktualisierungsmodus“** (`push`/`polling`) mit Statistiken
(Reconnects, Fehler, Events, letzte Fehlermeldung) und ein vollständiger
**Diagnose-Download** (Seriennummern anonymisiert) helfen bei der Fehlersuche.

### Zusätzliche Features
- **Endzeit** und **Startzeit** (bei Startvorwahl) als Zeitstempel – stabil, ohne Minuten-Gezappel
- **Fortschritt in %**, Restzeit, Laufzeit, Programmphase, Schleuderdrehzahl, Trockenstufe
- **Energie‑ und Wasserzähler „gesamt“** (`total_increasing`, über Neustarts gespeichert)
  → direkt im **Energie-Dashboard** nutzbar, inkl. Wasser
- Verbrauch & Prognose des laufenden Programms
- **Event-Entität „Aktivität“** und Bus-Event `miele_plus_event` für:
  `program_started`, `program_finished`, `program_aborted`, `program_paused`,
  `program_resumed`, `failure`, `info`, `door_opened`, `door_closed`
  – `program_finished` enthält Dauer, kWh und Liter des Programms
- **Programm starten** per Select-Entität oder Dienst (inkl. Temperatur, Dauer, Startvorwahl)
- Buttons Start/Stop/Pause (nur verfügbar, wenn das Gerät die Aktion gerade erlaubt)
- Schalter Ein/Aus, SuperFrost, SuperKühlen (optimistisch, mit Rückfall)
- Zieltemperatur je Zone für Kühl-/Gefrier-/Weinschränke
- Licht und Ambientelicht (Dunstabzugshaube inkl. Farben als Effekte), Lüfterstufe
- Kochzonen-Stufen bei Kochfeldern, Kerntemperatur bei Backöfen, Akkustand beim Saugroboter
- Status als übersetzte **Enum** (sprachunabhängig in Automationen: `running`, `program_ended`, …)
- Sprache der Programm-/Phasennamen frei wählbar

## Installation

### HACS
1. HACS → Integrationen → ⋮ → *Benutzerdefinierte Repositories* →
   `https://github.com/lennertmenke/Miele-Integration-Claude`, Kategorie *Integration*.
2. „Miele Plus“ installieren und Home Assistant neu starten.

### Manuell
Ordner `custom_components/miele_plus` nach `<config>/custom_components/` kopieren und neu starten.

## Einrichtung
1. Unter <https://www.miele.com/f/com/en/register_api.aspx> einen API-Zugang beantragen.
   Als Redirect-URI `https://my.home-assistant.io/redirect/oauth` angeben.
2. Home Assistant → *Einstellungen → Geräte & Dienste → Integration hinzufügen → Miele Plus*.
3. Client-ID und Client-Secret eingeben und mit dem Miele-Konto anmelden.

> Tipp: Wenn die offizielle Miele-Integration bereits eingerichtet ist, kann derselbe
> Miele-Developer-Zugang verwendet werden.

### Optionen
| Option | Standard | Bedeutung |
|---|---|---|
| Sprache | HA-Sprache | Sprache der Programm-/Phasennamen von Miele |
| Push-Updates | an | Event-Stream verwenden |
| Abfrageintervall ohne Push | 60 s | Polling, wenn Push nicht verfügbar ist (läuft ein Programm: max. 30 s) |
| Grace-Periode | 15 min | So lange bleiben Werte bei Cloud-Fehlern erhalten |

## Dienste
| Dienst | Zweck |
|---|---|
| `miele_plus.start_program` | Programm per `program_id` oder `program` (Name) starten; optional `temperature`, `duration`, `start_delay` |
| `miele_plus.set_start_time` | Startvorwahl setzen |
| `miele_plus.get_programs` | Fernstartbare Programme abfragen (liefert Antwort) |
| `miele_plus.send_action` | Beliebige API-Aktion senden, z. B. `{"modes": 1}` (Sabbat-Modus) |
| `miele_plus.refresh` | Sofort aus der Cloud aktualisieren |

> Fernsteuerung funktioniert nur, wenn am Gerät *Fernsteuerung* bzw. *MobileStart*
> aktiviert ist (siehe Binärsensoren „Fernsteuerung“/„MobileStart“).

## Automationsbeispiele

Benachrichtigung, wenn die Waschmaschine fertig ist – mit Verbrauch:
```yaml
automation:
  - alias: Waschmaschine fertig
    triggers:
      - trigger: state
        entity_id: event.waschmaschine_aktivitat
    conditions:
      - condition: state
        entity_id: event.waschmaschine_aktivitat
        attribute: event_type
        state: program_finished
    actions:
      - action: notify.mobile_app_handy
        data:
          message: >
            {{ trigger.to_state.attributes.program }} ist fertig
            ({{ trigger.to_state.attributes.duration }} min,
            {{ trigger.to_state.attributes.energy_kwh }} kWh,
            {{ trigger.to_state.attributes.water_l }} l).
```

Geschirrspüler bei günstigem Strom starten:
```yaml
actions:
  - action: miele_plus.start_program
    data:
      device_id: <Geräte-ID>
      program: Eco
      start_delay: "02:30:00"
```

## Entwicklung
```bash
pip install -r requirements_test.txt
pytest
ruff check custom_components tests
```

## Hinweis
Dies ist kein offizielles Produkt der Miele & Cie. KG. „Miele“ ist eine Marke der Miele & Cie. KG.
