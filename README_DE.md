# Waves Tune Real-Time in SuperRack SoundGrid per MIDI steuern

[English](README.md) | **Deutsch**

Diese Anleitung zeigt, wie sich Grundton und Skala von **Waves Tune Real-Time** in **SuperRack SoundGrid**
zuverlässig per MIDI setzen lassen, auch für alle Tune-RT-Instanzen gleichzeitig.

Getestet im Oktober 2026 mit SuperRack SoundGrid 15.15.12 und Tune Real-Time unter macOS.
Alle Ergebnisse wurden direkt im Plugin abgelesen (Screenshot und Texterkennung). Der SoundGrid-Server war dabei
offline, die Parameter reagieren im Plugin aber trotzdem.

## Kurzfassung

- Tune RT selbst kann Grundton und Skala **nicht** über seinen eigenen MIDI-Eingang setzen.
  Target Pitch und Reference Tone nehmen nur einzelne Noten, eine nach der anderen.
- In SuperRack geht es über die **Plugin Controls** des MIDI-Controller-Moduls:
  **Continuous 7 = Scale Root**, **Continuous 8 = Scale Type** (auf Seite 2).
- Der Regler für Scale Root wirkt **relativ** zum vorherigen Zustand. Ein fester Wert entspricht also
  nicht immer demselben Grundton.
- Zuverlässig wird es so: erst Scale Type auf **Chromatic**, dann die gewünschte Skala. Danach steht der
  Grundton immer auf **A**. Von dort setzt eine feste Folge von 1 bis 3 Root-Werten jeden der 12 Grundtöne.
- Getestet mit **allen 42 Skalen** aus Tune RT, je alle 12 Grundtöne. Bei 41 Skalen gab es **keine Abweichung**.
  Die Ausnahme ist die **User Scale**.
- **Send to All** (Seite 3, Discrete 1) überträgt Skala und Grundton an **alle** anderen Tune-RT-Instanzen mit
  aktivem **Receive**.
- Ein bestimmtes Tune RT lässt sich absolut per **Hot Plugin** oder **User Key** wählen, ein Rack per Rack-Navigation.
- Das Python-Skript [`tunert_midi.py`](tunert_midi.py) erledigt alles in einem Aufruf:
  `key D --scale harmonic-minor --hot-plugin 2 --send-to-all`.

## Einrichtung: MIDI Controller in SuperRack

Alle Beispiele und das Skript verwenden diese Belegung. Sie liegt als Datei bei:
[`SuperRack_TuneRT_MIDI.mrrc`](SuperRack_TuneRT_MIDI.mrrc), exportiert aus SuperRack 15.15.12.

**Importieren:**
1. SETUP → INVENTORY → CONTROLLERS: ein **MIDI Controller**-Modul zuweisen, falls noch keins da ist.
2. Das Zahnrad unter dem Modul öffnet das Fenster „MIDI Controller“.
3. Unter **MIDI IN** den Port anhaken, über den die Befehle kommen. Für Befehle vom selben Mac eignet sich ein
   IAC-Bus, eingerichtet in „Audio-MIDI-Setup“ → MIDI-Studio → IAC-Treiber.
4. FILE → **IMPORT** → `SuperRack_TuneRT_MIDI.mrrc` wählen.
5. Fenster schliessen (siehe Hinweis zum Lernmodus unten).

![MIDI Controller mit der vollständigen Belegung](images/midi-controller.png)

`CC/0 42` heisst: Control Change 42 auf MIDI-Kanal 1 (SuperRack zählt die Kanäle ab 0).
Alle 51 Befehle laufen auf Kanal 1 als Control Change.

| Bereich | Befehl | CC |
|---|---|---|
| Plugin Controls | Continuous 1–8 | 21–28 |
| Plugin Controls | Discrete 1 | 20 |
| Plugin Controls | Discrete 2–8 | 29–35 |
| Plugin Controls | NEXT PAGE / PREV PAGE | 40 / 41 |
| Navigation | PREV RACK / NEXT RACK | 42 / 43 |
| Navigation | PREV PLUGIN / NEXT PLUGIN | 44 / 45 |
| Navigation | OPEN RACK | 46 |
| Hot Plugins | 1–12 | 50–61 |
| User Keys | 1–16 | 70–85 |

Jeder MIDI-Controller und jede Software, die diese CCs sendet, funktioniert. Das Skript ist nur eine Möglichkeit.

**Plugin Controls.** Damit werden Scale Root (Continuous 7), Scale Type (Continuous 8) und Send to All
(Discrete 1 auf Seite 3) angesprochen:

![Plugin Controls](images/midi-controller-plugin-controls.png)

**Navigation.** Rack-Wahl und Seiten-Rücksetzung:

![Navigation](images/midi-controller-navigation.png)

**User Keys und Hot Plugins.** Damit wird ein bestimmtes Tune RT direkt gewählt:

![User Keys](images/midi-controller-user-keys.png) ![Hot Plugins](images/midi-controller-hot-plugins.png)

Welches Plugin ein Hot Plugin oder User Key wählt, wird in SuperRack selbst festgelegt. Ein User Key zeigt sein
Ziel z. B. als `R32P2` an, also Rack 32, Plugin 2.

**Eigene Belegung anlernen:** Feld im Fenster anklicken, dann den CC vom Controller senden.
Danach das Fenster **schliessen**. Solange ein Feld ausgewählt ist, ist der Lernmodus aktiv. Dann löst jeder schon
belegte CC eine Rückfrage „already assigned … Yes/No“ aus, statt das Plugin zu steuern.

## Ablauf, um Tonart und Skala zu setzen

Voraussetzung: Tune RT ist das gewählte Plugin, und die Plugin Controls stehen auf **Seite 2** (Scale).
Nach jedem Rack- oder Plugin-Wechsel stehen sie auf **Seite 1**, also **einmal NEXT PAGE**.

**Wichtig:** Navigations- und Momentan-Knöpfe (NEXT/PREV PAGE, NEXT/PREV RACK, NEXT/PREV PLUGIN, Hot Plugins,
User Keys, Send to All) lösen bei **jeder** Nachricht aus, auch bei Wert 0. Darum pro Druck genau **eine**
Nachricht senden, z. B. Wert 127.

1. Scale Type (CC 28) = **4** (Chromatic). Das ist die Rücksetzung.
2. Scale Type (CC 28) = Wert der gewünschten Skala (Tabelle unten). Der Grundton steht jetzt auf **A**.
3. Scale Root (CC 27): die Werte aus der Grundton-Tabelle **nacheinander** senden.
4. Optional **Send to All**: NEXT PAGE (→ Seite 3), Discrete 1 (CC 20), PREV PAGE (zurück auf Seite 2).
   Alle anderen Tune RT mit aktivem Receive übernehmen jetzt Skala und Grundton.

Beispiel D Harmonic Minor, als Control Change auf Kanal 1:

| Schritt | CC | Wert |
|---|---|---|
| Chromatic | 28 | 4 |
| Harmonic Minor | 28 | 12 |
| Root-Schritt 1 | 27 | 36 |
| Root-Schritt 2 | 27 | 36 |
| Root-Schritt 3 → D | 27 | 54 |
| NEXT PAGE (optional, für Send to All) | 40 | 127 |
| Send to All | 20 | 127 |
| PREV PAGE | 41 | 127 |

### Scale Type (Continuous 8)

Der Wert wirkt absolut, unabhängig vom vorherigen Wert. Geprüft wurde das mit Sprüngen wie 0 → 50, 127 → 50 und 30 → 50.
Jede Skala belegt einen Bereich von meist 3 Werten. Am sichersten ist der mittlere Wert („empfohlen“).
Die Namen sind aus dem Plugin abgelesen. Mit „…“ steht da, wo das Plugin den Namen selbst abkürzt.

| Bereich | empfohlen | Skala | `--scale` | Rezepte getestet |
|---|---|---|---|---|
| 0–1 | 0 | User Scale | – | ✗ funktioniert nicht |
| 2–4 | **4** | Chromatic | – | (Reset-Wert) |
| 5–7 | 6 | Major | `major` | ✓ 2× |
| 8–10 | 9 | Natural Minor | `natural-minor` | ✓ 2× |
| 11–13 | 12 | Harmonic Minor | `harmonic-minor` | ✓ 2× |
| 14–16 | 15 | Melodic Minor (Ascending) | `melodic-minor` | ✓ 2× |
| 17–19 | 18 | Melodic Minor (Ascending & Descending) | `melodic-minor-ad` | ✓ 2× |
| 20–22 | 21 | Major Justonic | `major-justonic` | ✓ |
| 23–25 | 24 | Minor Justonic | `minor-justonic` | ✓ |
| 26–28 | 27 | Dorian | `dorian` | ✓ |
| 29–31 | 30 | Mixolydian | `mixolydian` | ✓ |
| 32–33 | 32 | Blues | `blues` | ✓ |
| 34–36 | 35 | Phrygian | `phrygian` | ✓ |
| 37–39 | 38 | Locrian | `locrian` | ✓ |
| 40–42 | 41 | Lydian | `lydian` | ✓ |
| 43–45 | 44 | Whole Tone | `whole-tone` | ✓ |
| 46–48 | 47 | Diminished (W-H) | `diminished-wh` | ✓ |
| 49–51 | 50 | Diminished (H-W) | `diminished-hw` | ✓ |
| 52–54 | 53 | Bebop | `bebop` | ✓ |
| 55–57 | 56 | Major Pentatonic | `major-pentatonic` | ✓ |
| 58–60 | 59 | Minor Pentatonic | `minor-pentatonic` | ✓ |
| 61–63 | 62 | Major Pent… flat 3rd | `major-pentatonic-flat3` | ✓ |
| 64–66 | 65 | Minor Pen… + Blues | `minor-pentatonic-blues` | ✓ |
| 67–69 | 68 | Bebop + Blues | `bebop-blues` | ✓ |
| 70–72 | 71 | Pythagorean | `pythagorean` | ✓ |
| 73–75 | 74 | Maqam Ra…st-Rast) | `maqam-rast` | ✓ |
| 76–78 | 77 | Maqam Saba | `maqam-saba` | ✓ |
| 79–81 | 80 | Maqam Bayati | `maqam-bayati` | ✓ |
| 82–84 | 83 | Maqam Nahawand | `maqam-nahawand` | ✓ |
| 85–87 | 86 | Maqam Hijaz | `maqam-hijaz` | ✓ |
| 88–90 | 89 | Maqam Kurd | `maqam-kurd` | ✓ |
| 91–93 | 92 | Maqam Huzam | `maqam-huzam` | ✓ |
| 94–95 | 94 | Bilawal (Hindustani) | `bilawal-hindustani` | ✓ |
| 96–98 | 97 | Bilawal (Carnatic) | `bilawal-carnatic` | ✓ |
| 99–101 | 100 | Kafi (Hindustani) | `kafi-hindustani` | ✓ |
| 102–104 | 103 | Kafi (Carnatic) | `kafi-carnatic` | ✓ |
| 105–107 | 106 | Bhairavi (Hindustani) | `bhairavi-hindustani` | ✓ |
| 108–110 | 109 | Bhairavi (Carnatic) | `bhairavi-carnatic` | ✓ |
| 111–113 | 112 | Kalyan (Hindustani) | `kalyan-hindustani` | ✓ |
| 114–116 | 115 | Kalyan (Carnatic) | `kalyan-carnatic` | ✓ |
| 117–119 | 118 | Khamaj (Hindustani) | `khamaj-hindustani` | ✓ |
| 120–122 | 121 | Khamaj (Carnatic) | `khamaj-carnatic` | ✓ |
| 123–125 | 124 | Asavari (Hindustani) | `asavari-hindustani` | ✓ |
| 126–127 | 126 | Asavari (Carnatic) | `asavari-carnatic` | ✓ |

Bei Blues (32–33) und Bilawal (Hindustani) (94–95) ist der Bereich nur 2 Werte breit.
„✓ 2×“: alle 12 Grundtöne in zwei Durchgängen, „✓“: in einem Durchgang.

### Scale Root (Continuous 7): Folge ab Startpunkt A

Gilt für alle Skalen ausser User Scale.

| Grundton | Werte nacheinander | Eingabe für `key` |
|---|---|---|
| C | 36, 36 | `C`, `His`, `B#` |
| C♯ / D♭ | 36 | `C#`, `Cis`, `Db`, `Des` |
| D | 36, 36, 54 | `D` |
| D♯ / E♭ | 18, 54 | `D#`, `Dis`, `Eb`, `Es` |
| E | 54 | `E`, `Fes`, `Fb` |
| F | 72, 5 | `F`, `Eis`, `E#` |
| F♯ / G♭ | 18, 72 | `F#`, `Fis`, `Gb`, `Ges` |
| G | 72 | `G` |
| G♯ / A♭ | 90 | `G#`, `Gis`, `Ab`, `As` |
| A | 5 | `A` |
| A♯ / B♭ | 18, 108 | `A#`, `Ais`, `Bb` |
| B (H) | 18 | `B`, `H`, `Ces`, `Cb` |

Tune RT zeigt manche Grundtöne enharmonisch verwechselt an (z. B. G♭ statt F♯). Die Tonhöhe ist dieselbe.

### Send to All

- Liegt auf **Seite 3, Discrete 1**, direkt neben Receive (Seite 3, Discrete 2).
- Ohne Send to All ändert sich bei den anderen Instanzen nichts.
- Es wirkt auf **alle** Instanzen mit Receive. Instanzen, die nicht mitziehen sollen, brauchen Receive aus.
- Getestet: Eine Instanz wurde auf D Dorian bzw. F♯ Harmonic Minor gesetzt, dann Send to All gedrückt.
  Zwei weitere Instanzen mit Receive in anderen Racks übernahmen jeweils Skala und Grundton.

### Pausen zwischen den Nachrichten

Major, alle 12 Grundtöne × 2 Durchgänge pro Pausenlänge:

| Pause | richtig |
|---|---|
| 0,5 s | 24/24 |
| 0,3 s | 24/24 |
| 0,2 s | 24/24 |
| 0,1 s | 24/24 |
| 0,05 s | 24/24 |
| 0 s | 24/24 |

Das Skript nutzt standardmässig 0,1 s. Die Rezepttests für alle Skalen liefen mit 0,6 s bzw. 0,9 s.

## Ziel-Plugin wählen

Bei mehreren Tune-RT-Instanzen muss vorher die richtige gewählt sein. Dafür gibt es drei Wege:

| Weg | wählt | MIDI-Folge (je eine Nachricht) |
|---|---|---|
| Hot Plugin N (1–12) | das Plugin auf Hot Plugin N | PREV RACK, NEXT RACK, Hot Plugin N, NEXT PAGE |
| User Key N (1–16) | was User Key N auslöst | PREV RACK, NEXT RACK, User Key N, NEXT PAGE |
| Rack N | Rack N, mit dem dort zuletzt gewählten Plugin | PREV RACK × 64, NEXT RACK × N, PREV RACK, NEXT PAGE |

Hot Plugin und User Key wählen ein **bestimmtes Plugin** absolut, die Rack-Navigation nur das Rack.

**Warum vorher PREV RACK + NEXT RACK?** Die Plugin Controls springen nur bei einem echten Rack- oder
Plugin-Wechsel auf Seite 1. Ist das Ziel-Plugin schon gewählt, bleibt die Seite stehen, und NEXT PAGE landet
auf der falschen Seite. Das Hin und Her erzwingt einen Wechsel, auch am Rand: Bei Rack 1 bewegt sich PREV nicht,
NEXT aber schon. Beim letzten Rack ist es umgekehrt. Aus diesem Grund endet die Rack-Wahl mit NEXT × N und PREV × 1.

Gemessen:
- Hot Plugins und User Keys wählen ihr Plugin auch beim zweiten Druck. Sie schalten nichts zurück, und es geht kein Zusatzfenster auf.
- PREV RACK bleibt bei Rack 1 stehen. NEXT RACK zählt jedes Rack einzeln, auch leere. 20 ms pro Schritt reichen.
- PREV/NEXT PLUGIN laufen im Kreis über die belegten Slots eines Racks, und SuperRack merkt sich pro Rack das
  zuletzt gewählte Plugin. Für die Wahl eines bestimmten Slots taugen sie darum nicht.
  „Nächstes + vorheriges Plugin“ setzt die Seite nur zurück, wenn das Rack mindestens 2 Plugins hat.

Getestet mit drei Tune-RT-Instanzen in Rack 32 (Slot 2), Rack 17 und Rack 18. Hot Plugin 1 / User Key 1 zeigten auf
Rack 32, Hot Plugin 2 / User Key 2 auf Rack 17:

| Aufruf | Ergebnis |
|---|---|
| `key Fis --scale dorian --hot-plugin 1` | Rack 32 = F♯ Dorian |
| `key A --hot-plugin 2 --send-to-all` | Rack 17 = A Major, Rack 32 übernimmt A Major |
| `key E --scale natural-minor --user-key 2` | Rack 17 = E Natural Minor, Rack 32 bleibt A Major |
| `key C --user-key 1` | Rack 32 = C Major |
| `key G --rack 18` | Rack 18 = G Major, Rack 17 bleibt E Natural Minor |

Ausserdem 6 Ausgangslagen für die Seiten-Rücksetzung, alle richtig: Plugin schon gewählt, Seite um 1 bzw. 2
verschoben, Wechsel zwischen zwei Instanzen, Start bei Rack 1.

## Das Skript `tunert_midi.py`

Benötigt Python 3 und die Pakete aus [`requirements.txt`](requirements.txt) (`mido`, `python-rtmidi`):

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python tunert_midi.py ports
```

`ports` listet die MIDI-Ausgänge. Ohne `--port` nimmt das Skript den ersten Ausgang, der „IAC“ oder „SuperRack“
im Namen hat. Mit `--port <Teil des Namens>` lässt sich ein anderer wählen.

Tonart setzen:

```bash
.venv/bin/python tunert_midi.py key D --scale harmonic-minor
.venv/bin/python tunert_midi.py key Es --scale dorian --hot-plugin 2 --send-to-all
.venv/bin/python tunert_midi.py key Fis --scale-value 41 --rack 18
```

| Option | Bedeutung |
|---|---|
| `ROOT` | Grundton, Schreibweisen siehe Grundton-Tabelle (Gross-/Kleinschreibung egal; `B` = H) |
| `--scale NAME` | Skala aus der Spalte `--scale`, Standard `major` |
| `--scale-value N` | Skala über ihren Scale-Type-Wert |
| `--hot-plugin N` / `--user-key N` / `--rack N` | vorher das Ziel-Plugin wählen (schliessen sich gegenseitig aus) |
| `--send-to-all` | danach Send to All drücken |
| `--pause SEK` | Pause nach jeder Nachricht, Standard 0,1 |
| `--root-cc`, `--type-cc`, `--send-cc`, `--next-page-cc`, `--prev-page-cc`, `--prev-rack-cc`, `--next-rack-cc`, `--hot-plugin-cc`, `--user-key-cc` | andere CCs, falls die Belegung abweicht |

Ohne `--hot-plugin`, `--user-key` oder `--rack` geht das Skript davon aus, dass Tune RT schon gewählt ist und
Seite 2 aktiv ist.

Weitere Befehle: `send` (einzelner CC), `learn` (CC wiederholt senden zum Anlernen), `sweep` (CC-Werte
durchmessen und Ergebnis als CSV speichern), `snapshot` (SuperRack-Snapshot per Program Change abrufen).

## Messdaten

### Ein Schritt ab A (Major, Durchlauf 0–127, jeweils vorher Chromatic → Major)

| CC-Wert | Grundton |
|---|---|
| 0–9 | A |
| 10–27 | B |
| 28–45 | D♭ |
| 46–63 | E |
| 64–81 | G |
| 82–99 | A♭ |
| 100–127 | B |

Der Regler kennt also 8 Stufen zu je 18 Werten (0–9, 10–27, …, 118–127).

### Zwei Schritte ab A (Zeile = 1. Wert, Spalte = 2. Wert)

| 1. \ 2. | 5 | 18 | 36 | 54 | 72 | 90 | 108 | 122 |
|---|---|---|---|---|---|---|---|---|
| **5** | A | B | D♭ | E | G | A♭ | B | B |
| **18** | A♭ | B | C♯ | E♭ | G♭ | G♯ | B♭ | B |
| **36** | G♭ | A | C | D♭ | E | G♭ | A♭ | B |
| **54** | G♭ | A | C | D♭ | E | F♯ | A♭ | B |
| **72** | F | G♯ | C | C | D♯ | E | G | A♯ |
| **90** | A♭ | B | D♭ | E♭ | G♭ | A♭ | B♭ | B |
| **108** | A♭ | B | C♯ | E♭ | G♭ | G♯ | B♭ | B |
| **122** | A♭ | B | C♯ | E♭ | G♭ | G♯ | B♭ | B |

Mit zwei Schritten sind 11 Grundtöne erreichbar. D braucht drei (36, 36, 54).

### Ohne Rücksetzung: nicht verwendbar

Ohne Chromatic → Skala vorher hängt das Ergebnis vom vorherigen Grundton ab.
Beispiel: CC 50 von 0 aus angefahren ergab E♭, von 127 aus angefahren D♯. Die Folge 0, 1, 2, 3, 4, 5 ergab
G♯, F♯, G♭, E, G♭, E.

## Belegung der Plugin Controls für Tune RT

Für Tune RT gibt es drei Seiten. NEXT/PREV PAGE springen nach der letzten wieder zur ersten.
Nach jedem Rack- oder Plugin-Wechsel steht Seite 1 aktiv.

| Seite | Feld | Tune-RT-Parameter |
|---|---|---|
| 1 (Regler) | Continuous 1 | Correction (Stärke) |
| 1 (Regler) | Continuous 3 | Vibrato-Stärke |
| 1 (Regler) | Continuous 5 | Note Transition |
| 1 (Regler) | Continuous 6 | Tolerance Time |
| 1 (Regler) | Continuous 7 | Tolerance Cents |
| 1 (Regler) | Continuous 8 | Speed |
| 1 (Regler) | Discrete 1 | Correction ON (schaltet um) |
| 1 (Regler) | Discrete 2 | Formant |
| 1 (Regler) | Discrete 3 | Vibrato ON |
| 1 (Regler) | Discrete 8 | Link |
| **2 (Scale)** | Continuous 1 | Level (MIDI Input) |
| **2 (Scale)** | Continuous 3 | Reference (Hz) |
| **2 (Scale)** | Continuous 4 | Range (Bass … Generic) |
| **2 (Scale)** | **Continuous 7** | **Scale Root** |
| **2 (Scale)** | **Continuous 8** | **Scale Type** |
| **2 (Scale)** | Discrete 1 | Reference Tone |
| **2 (Scale)** | Discrete 2 | Target Pitch |
| **2 (Scale)** | Discrete 5 | Group Octaves |
| **2 (Scale)** | Discrete 6 | vermutlich Reset Scale (nicht separat getestet) |
| **2 (Scale)** | Discrete 7 | ♭/♯-Anzeige |
| 3 (Transmission) | **Discrete 1** | **Send to All** |
| 3 (Transmission) | Discrete 2 | Receive |
| 3 (Transmission) | Continuous 7/8 | Ausschnitt der Tastatur-Anzeige |

Reset Scale und Send to All sind kurz gedrückte Knöpfe und zeigen im eigenen Plugin keine sichtbare Wirkung.
Send to All wurde über die Wirkung auf die anderen Instanzen gefunden. Für den Ablauf oben braucht es Reset Scale nicht.
