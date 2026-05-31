# Task as Quest - Home Assistant Integration

<img src="custom_components/taskasquest/brand/icon.png" width="150" align="right" />

Mach deinen Alltag zum Abenteuer! **Task as Quest** ist eine Home Assistant Integration, die nahtlos mit der *Task as Quest* Android App und PocketBase zusammenarbeitet. Sie verwandelt smarte Sensor-Ausfälle, Sensor-Werte und Routinen in Gamification-Quests für dich und deine Gefährten.

## Features
- 🎮 **Das Smart Home wird zum Abenteuer**: Verwandle Hausarbeiten und Sensor-Warnungen (wie "Blume gießen" oder "Batterie schwach") automatisch in spannende Quests in der *Task as Quest* App.
- 🛡️ **Allianz-Quests**: Verteile Aufträge direkt an deine Gefährten (Familienmitglieder/Mitbewohner). Home Assistant schickt die Quests gezielt an die richtigen Helden in deiner Gruppe.
- 📱 **Push-Benachrichtigungen**: Lass dich und deine Gefährten auf dem Smartphone benachrichtigen, sobald das Smart Home einen neuen, epischen Auftrag für euch hat.
- ⚙️ **Einfache Regeln**: Lege direkt in Home Assistant fest, bei welchen Sensor-Werten (z.B. Bodenfeuchtigkeit < 45%) ein neuer Quest am schwarzen Brett der App landen soll.
- 🔒 **Maximale Sicherheit**: Deine Smart Home Daten bleiben privat. Die Integration kommuniziert absolut sicher und Ende-zu-Ende verschlüsselt mit der App – niemand außer deinen Gefährten kann eure Quests mitlesen.

## Installation via HACS

Die einfachste Methode ist die Installation über den [Home Assistant Community Store (HACS)](https://hacs.xyz/).

1. Gehe in HACS auf **Integrationen**.
2. Klicke oben rechts auf die drei Punkte und wähle **Benutzerdefinierte Repositorys** (Custom Repositories).
3. Füge die URL dieses GitHub Repositories ein: `https://github.com/marcohildebrandtmail-hub/TaskAsQuest`
4. Wähle als Kategorie **Integration**.
5. Klicke auf Hinzufügen. Das Repository taucht nun in HACS auf.
6. Klicke auf "Herunterladen" und starte Home Assistant neu.

## Einrichtung

1. Gehe in Home Assistant zu **Einstellungen -> Geräte & Dienste**.
2. Klicke auf **Integration hinzufügen** und suche nach `Task as Quest`.
3. Gib deine Zugangsdaten ein:
   - **Login Name / E-Mail**
   - **Passwort**
   - **Verschlüsselungs-Code (Recovery Code)** (Wird für die E2E-Verschlüsselung benötigt!)
4. Klicke auf Senden.

## Regeln konfigurieren

Nachdem die Integration eingerichtet wurde, klicke auf **Konfigurieren** auf der Kachel der Integration:
- Du kannst neue Regeln hinzufügen, wie z.B.:
  - Wenn `sensor.kontaktsensor_briefkasten` gleich `unavailable` ist -> "Kontaktsensor prüfen"
  - Wenn `sensor.pflanze_soil_moisture` unter `45` fällt -> "Pflanze gießen!"
- Optional kannst du Quests einem oder mehreren Gefährten zuweisen (`Assignees`) und einstellen, ob die App sofort per Push benachrichtigen soll (`notify_app`).

## Home Assistant Dienste (Services)

Die Integration stellt zwei Dienste zur Verfügung:
- `taskasquest.create_quest`: Erstellt manuell eine Quest (z.B. aus Automatisierungen heraus).
- `taskasquest.add_rules`: Erlaubt den Massen-Import von Sensor-Regeln per YAML.
