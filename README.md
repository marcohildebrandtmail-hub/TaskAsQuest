# Task as Quest - Home Assistant Integration

![Icon](custom_components/taskasquest/icon.png)

Mach deinen Alltag zum Abenteuer! **Task as Quest** ist eine Home Assistant Integration, die nahtlos mit der *Task as Quest* Android App und PocketBase zusammenarbeitet. Sie verwandelt smarte Sensor-Ausfälle, Sensor-Werte und Routinen in Gamification-Quests für dich und deine Gefährten.

## Features
- 🎮 **Automatische Quests:** Erstelle Quests basierend auf Home Assistant Sensor-Werten (z.B. "Briefkastensensor ausgefallen" oder "Blume gießen, Feuchtigkeit < 45%").
- 🛡️ **Allianz-Quests (E2E Verschlüsselung):** Erstelle Quests, die an Gefährten (Assignees) zugewiesen werden. Die Integration nutzt End-to-End Verschlüsselung, sodass Quests sicher über PocketBase an die TAQ-App verteilt werden.
- 📱 **Push-Benachrichtigungen:** Aktiviere optional App-Benachrichtigungen, wenn ein bestimmter Quest von Home Assistant generiert wird.
- ⚙️ **Konfigurations-UI:** Einfaches Anlegen und Verwalten der Regeln über die Home Assistant Benutzeroberfläche.
- 🧹 **Zero-Knowledge Architecture:** Die gesamte Kommunikation mit der PocketBase Instanz wird mit deinem Master-Passwort bzw. Recovery-Code sicher und lokal verschlüsselt, bevor sie Home Assistant verlässt.

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
   - **PocketBase URL** (z.B. `http://192.168.10.177:8080`)
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
