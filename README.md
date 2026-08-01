# Task as Quest für Home Assistant

<img src="custom_components/taskasquest/brand/icon.png" width="150" align="right" alt="Task as Quest" />

Task as Quest verbindet Home Assistant mit der Task-as-Quest-App. Sensorzustände können sofort Quests auslösen, offene Quests erscheinen als native To-do-Liste und neue Quests lassen sich aus Automationen erstellen.

## Funktionen

- Native To-do-Liste mit Erstellen, Bearbeiten, Abschließen, Löschen, Beschreibung und Fälligkeit
- Ereignisbasierte Regeln für Home-Assistant-Entitäten
- Wahlweise einmaliges Auslösen beim Übergang oder Wiederholung mit Cooldown
- Zuweisung an Gefährten und optionale App-Benachrichtigung
- Unterstützung für 2FA und verschlüsselte Quest-Felder
- Persistente Cooldowns und Quest-Zähler über Neustarts hinweg
- Mehrere Task-as-Quest-Konten, Reauthentifizierung, Neukonfiguration und Diagnostics
- Deutsche und englische Oberfläche

## Voraussetzungen

- Home Assistant 2026.1 oder neuer
- Ein Task-as-Quest-Konto
- Erreichbarer Task-as-Quest-Server, standardmäßig `https://app.taskasquest.de`

Ein separater Recovery Code wird von dieser Integration nicht abgefragt. Bei Konten mit geschützten Feldern wird die Verschlüsselung mit dem normalen Kontopasswort entsperrt.

## Installation über HACS

1. Öffne HACS und wähle **Integrationen**.
2. Öffne das Menü oben rechts und wähle **Benutzerdefinierte Repositorys**.
3. Füge `https://github.com/marcohildebrandtmail-hub/TaskAsQuest` als **Integration** hinzu.
4. Installiere Task as Quest und starte Home Assistant neu.
5. Öffne **Einstellungen → Geräte & Dienste → Integration hinzufügen** und suche nach „Task as Quest“.

## Entitäten

| Entität | Zweck |
|---|---|
| To-do-Liste „Quests“ | Offene Quests anzeigen und verwalten |
| Sensor „Offene Quests“ | Anzahl offener Quests |
| Sensor „Erstellte Quests“ | Persistente Anzahl durch HA-Regeln erstellter Quests |
| Sensor „Aktive Regeln“ | Anzahl aktivierter Regeln |

## Regeln

Regeln werden über **Einstellungen → Geräte & Dienste → Task as Quest → Konfigurieren** verwaltet.

Das Auslöseverhalten bestimmt, wann eine Quest erstellt wird:

- **Nur wenn die Bedingung neu wahr wird (`edge`)**: Erstellt eine Quest beim Übergang, beispielsweise wenn Bodenfeuchtigkeit erstmals unter 45 fällt. Das verhindert regelmäßige Wiederholungen bei unverändertem Zustand.
- **Wiederholen, solange die Bedingung wahr bleibt (`level`)**: Prüft die Bedingung zusätzlich bei jedem Cloud-Update und kann nach Ablauf des Cooldowns erneut eine Quest erstellen.

Eine offene Quest mit demselben Titel verhindert immer ein Duplikat. Cooldowns werden persistent pro Regel gespeichert.

## Actions

### `taskasquest.create_quest`

```yaml
action: taskasquest.create_quest
data:
  title: Pflanze gießen
  description: Die Bodenfeuchtigkeit ist niedrig.
  difficulty: easy
  due_date: "2026-07-14T21:59:00Z"
  notify_app: true
```

Bei mehreren eingerichteten Konten muss zusätzlich `config_entry_id` angegeben werden. Mit `response_variable` liefert die Action `task_id` und mögliche Warnungen zurück.

### `taskasquest.add_rules`

```yaml
action: taskasquest.add_rules
data:
  rules:
    - entity_id: sensor.plant_moisture
      condition: below
      value: "45"
      task_title: Pflanze gießen
      difficulty: easy
      trigger_mode: edge
      cooldown: 1440
      due_date_offset: "0"
      notify_app: true
      enabled: true
```

Exakt identische Regeln werden übersprungen. Mehrere unterschiedliche Regeln für dieselbe Entität sind erlaubt.

## Aktualisierung und Fehlerverhalten

Offene Quests werden standardmäßig alle 60 Sekunden vom Server abgefragt. Home-Assistant-Zustandsänderungen werden unmittelbar verarbeitet. Temporäre Server- und Netzwerkfehler machen die Entitäten vorübergehend nicht verfügbar; nur echte Authentifizierungsfehler starten eine erneute Anmeldung.

Über das Drei-Punkte-Menü des Config Entries kann eine anonymisierte Diagnose heruntergeladen werden. Quest-Titel, Zugangsdaten, Benutzer-IDs, Regelwerte und Gefährten-IDs werden daraus entfernt.

## Entfernen

Lösche den Config Entry unter **Einstellungen → Geräte & Dienste → Task as Quest**. Danach kann die Integration in HACS deinstalliert und Home Assistant neu gestartet werden.

## Entwicklung

Pull Requests werden mit Ruff, Pytest, Hassfest und der HACS-Validierung geprüft. Die wichtigsten Tests decken Regel-Normalisierung, Triggerbedingungen, Verschlüsselung, Config Flow, Coordinator und To-do-Schreibzugriffe ab.
