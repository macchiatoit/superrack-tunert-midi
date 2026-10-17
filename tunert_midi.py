#!/usr/bin/env python3
"""Control Waves Tune Real-Time in SuperRack SoundGrid via MIDI.

Sets key and scale of Tune RT through the Plugin Controls of the SuperRack MIDI Controller,
optionally selects the target plugin first and presses "Send to All".
Requires the mapping from SuperRack_TuneRT_MIDI.mrrc (details: README.md).

Examples:
  python tunert_midi.py ports
  python tunert_midi.py key D --scale harmonic-minor
  python tunert_midi.py key Eb --scale dorian --hot-plugin 2 --send-to-all
  python tunert_midi.py key Gb --user-key 1
  python tunert_midi.py key A --rack 18

Helper commands for measuring and MIDI learn:
  python tunert_midi.py send 64 --cc 27
  python tunert_midi.py learn --cc 27
  python tunert_midi.py sweep --cc 27
  python tunert_midi.py sweep --cc 27 --auto 0.5
  python tunert_midi.py snapshot 3 --channel 16
"""

import argparse
import csv
import sys
import time
from datetime import datetime

import mido

# Root -> accepted inputs (case-insensitive). "B" is always B natural (German "H");
# B flat is written as Bb, A# or Ais. German note names are accepted as well.
ROOT_INPUTS = {
    "C": ["C", "His", "B#"],
    "C#": ["C#", "Cis", "Db", "Des"],
    "D": ["D"],
    "D#": ["D#", "Dis", "Eb", "Es"],
    "E": ["E", "Fes", "Fb"],
    "F": ["F", "Eis", "E#"],
    "F#": ["F#", "Fis", "Gb", "Ges"],
    "G": ["G"],
    "G#": ["G#", "Gis", "Ab", "As"],
    "A": ["A"],
    "A#": ["A#", "Ais", "Bb"],
    "B": ["B", "H", "Ces", "Cb"],
}
NOTE_ALIASES = {alias.upper(): root for root, aliases in ROOT_INPUTS.items() for alias in aliases}


def normalize_root(text):
    """Normalize a note name to the plugin's sharp spelling (Eb -> D#, Fis -> F# ...). Unknown input is returned as is."""
    t = text.strip().upper().replace("♯", "#").replace("♭", "B")
    return NOTE_ALIASES.get(t, text.strip())


def pick_port(wanted):
    names = mido.get_output_names()
    if not names:
        sys.exit("No MIDI outputs found.")
    if wanted:
        matches = [n for n in names if wanted.lower() in n.lower()]
        if not matches:
            sys.exit(f"No port matches '{wanted}'. Available: {names}")
        return matches[0]
    for needle in ("iac", "superrack"):
        for n in names:
            if needle in n.lower():
                return n
    return names[0]


def open_port(args):
    name = pick_port(args.port)
    print(f"Sending to: {name}  |  channel {args.channel}, CC {args.cc}")
    return mido.open_output(name)


def send_cc(out, args, value):
    out.send(mido.Message("control_change", channel=args.channel - 1,
                          control=args.cc, value=value))


def cmd_ports(_args):
    for n in mido.get_output_names():
        print(n)


def cmd_send(args):
    with open_port(args) as out:
        send_cc(out, args, args.value)
        print(f"Sent CC {args.cc} = {args.value}.")


def cmd_learn(args):
    """Send changing values so that SuperRack's MIDI learn picks up the CC."""
    with open_port(args) as out:
        print(f"Sending CC {args.cc} for {args.seconds:g}s - select the field in SuperRack now. Ctrl+C aborts.")
        end = time.time() + args.seconds
        value = 0
        try:
            while time.time() < end:
                send_cc(out, args, value)
                value = (value + 8) % 128
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        print("Done.")


def cmd_snapshot(args):
    """Recall a SuperRack snapshot: Bank LSB (CC 32) + Program Change, both 0-based."""
    bank, program = divmod(args.number - 1, 128)
    name = pick_port(args.port)
    with mido.open_output(name) as out:
        if bank or args.always_bank:
            out.send(mido.Message("control_change", channel=args.channel - 1, control=32, value=bank))
        out.send(mido.Message("program_change", channel=args.channel - 1, program=program))
    print(f"Snapshot {args.number}: channel {args.channel}, Bank LSB {bank}, Program Change {program} "
          f"({program + 1} when counting from 1) sent to {name}.")


# Measured with SuperRack 15.15 / Tune RT, Plugin Controls page with Scale Root (Continuous 7)
# and Scale Type (Continuous 8). Chromatic -> scale sets the root to A; from there CC 27 acts
# relative, so some roots can only be reached in several steps.
ROOT_RECIPES = {
    "A": [5], "B": [18], "C#": [36], "E": [54], "G": [72], "G#": [90],
    "C": [36, 36], "D#": [18, 54], "F#": [18, 72], "A#": [18, 108], "F": [72, 5],
    "D": [36, 36, 54],
}
SCALE_CHROMATIC = 4
# Scale Type values (middle value of each range, see README.md).
# User Scale (0) is left out on purpose: Chromatic -> User Scale does not reset the root to A.
SCALE_TYPES = {
    "major": (6, "Major"),
    "natural-minor": (9, "Natural Minor"),
    "harmonic-minor": (12, "Harmonic Minor"),
    "melodic-minor": (15, "Melodic Minor (Ascending)"),
    "melodic-minor-ad": (18, "Melodic Minor (Ascending & Descending)"),
    "major-justonic": (21, "Major Justonic"),
    "minor-justonic": (24, "Minor Justonic"),
    "dorian": (27, "Dorian"),
    "mixolydian": (30, "Mixolydian"),
    "blues": (32, "Blues"),
    "phrygian": (35, "Phrygian"),
    "locrian": (38, "Locrian"),
    "lydian": (41, "Lydian"),
    "whole-tone": (44, "Whole Tone"),
    "diminished-wh": (47, "Diminished (W-H)"),
    "diminished-hw": (50, "Diminished (H-W)"),
    "bebop": (53, "Bebop"),
    "major-pentatonic": (56, "Major Pentatonic"),
    "minor-pentatonic": (59, "Minor Pentatonic"),
    "major-pentatonic-flat3": (62, "Major Pent… flat 3rd"),
    "minor-pentatonic-blues": (65, "Minor Pen… + Blues"),
    "bebop-blues": (68, "Bebop + Blues"),
    "pythagorean": (71, "Pythagorean"),
    "maqam-rast": (74, "Maqam Ra…st-Rast)"),
    "maqam-saba": (77, "Maqam Saba"),
    "maqam-bayati": (80, "Maqam Bayati"),
    "maqam-nahawand": (83, "Maqam Nahawand"),
    "maqam-hijaz": (86, "Maqam Hijaz"),
    "maqam-kurd": (89, "Maqam Kurd"),
    "maqam-huzam": (92, "Maqam Huzam"),
    "bilawal-hindustani": (94, "Bilawal (Hindustani)"),
    "bilawal-carnatic": (97, "Bilawal (Carnatic)"),
    "kafi-hindustani": (100, "Kafi (Hindustani)"),
    "kafi-carnatic": (103, "Kafi (Carnatic)"),
    "bhairavi-hindustani": (106, "Bhairavi (Hindustani)"),
    "bhairavi-carnatic": (109, "Bhairavi (Carnatic)"),
    "kalyan-hindustani": (112, "Kalyan (Hindustani)"),
    "kalyan-carnatic": (115, "Kalyan (Carnatic)"),
    "khamaj-hindustani": (118, "Khamaj (Hindustani)"),
    "khamaj-carnatic": (121, "Khamaj (Carnatic)"),
    "asavari-hindustani": (124, "Asavari (Hindustani)"),
    "asavari-carnatic": (126, "Asavari (Carnatic)"),
}


def cmd_key(args):
    root = normalize_root(args.root)
    if root not in ROOT_RECIPES:
        sys.exit(f"Unknown root '{args.root}'.")
    if args.scale_value is not None:
        scale_value, scale_name = args.scale_value, f"(Scale Type value {args.scale_value})"
    else:
        scale_value, scale_name = SCALE_TYPES[args.scale]
    name = pick_port(args.port)
    ch = args.channel - 1
    with mido.open_output(name) as out:
        def cc(control, value, pause=args.pause):
            out.send(mido.Message("control_change", channel=ch, control=control, value=value))
            time.sleep(pause)

        def press(control, times=1, pause=args.pause):
            # Navigation and momentary buttons trigger on EVERY message (value 0 included),
            # so send exactly one message per press.
            for _ in range(times):
                cc(control, 127, pause)

        # Select the target plugin. The Plugin Controls only jump to page 1 on an actual rack or plugin
        # change, so at least one rack change is always forced.
        if args.rack:
            # PREV RACK stops at rack 1; from there NEXT RACK counts every rack individually.
            # NEXT x N and PREV x 1 instead of NEXT x (N-1), so that rack 1 -> rack 1 still causes a change.
            press(args.prev_rack_cc, args.max_racks, args.nav_pause)
            press(args.next_rack_cc, args.rack, args.nav_pause)
            press(args.prev_rack_cc)
        elif args.hot_plugin or args.user_key:
            press(args.prev_rack_cc)
            press(args.next_rack_cc)
            if args.hot_plugin:
                press(args.hot_plugin_cc + args.hot_plugin - 1)
            else:
                press(args.user_key_cc + args.user_key - 1)
        if args.rack or args.hot_plugin or args.user_key:
            press(args.next_page_cc)  # page 1 -> page 2 (Scale)

        cc(args.type_cc, SCALE_CHROMATIC)
        cc(args.type_cc, scale_value)
        for v in ROOT_RECIPES[root]:
            cc(args.root_cc, v)
        if args.send_to_all:
            # Send to All = Discrete 1 on page 3 (Transmission); then back to page 2.
            press(args.next_page_cc)
            press(args.send_cc)
            press(args.prev_page_cc)
    where = (f" in rack {args.rack}" if args.rack else f" on Hot Plugin {args.hot_plugin}" if args.hot_plugin
             else f" on User Key {args.user_key}" if args.user_key else "")
    print(f"Set {root} {scale_name}{where} via {name}: CC {args.type_cc} = {SCALE_CHROMATIC}, {scale_value}; "
          f"CC {args.root_cc} = {ROOT_RECIPES[root]}" + ("; Send to All" if args.send_to_all else ""))


def summarize(rows):
    """Merge consecutive values with the same root into ranges."""
    ranges = []
    for value, root in rows:
        if ranges and ranges[-1][2] == root:
            ranges[-1][1] = value
        else:
            ranges.append([value, value, root])
    return ranges


def cmd_sweep(args):
    values = list(range(args.start, args.end + 1, args.step))
    rows = []
    with open_port(args) as out:
        if args.auto is not None:
            for v in values:
                send_cc(out, args, v)
                print(f"CC {args.cc} = {v:3d}")
                time.sleep(args.auto)
            return

        print("For each value, enter the root shown in the plugin (e.g. C, F#, Bb).")
        print("Enter = same as before, u = undo one step, q = quit.\n")
        i = 0
        last = ""
        while i < len(values):
            v = values[i]
            send_cc(out, args, v)
            hint = f" [{last}]" if last else ""
            try:
                answer = input(f"CC {args.cc} = {v:3d} -> root{hint}: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if answer.lower() == "q":
                break
            if answer.lower() == "u":
                if rows:
                    rows.pop()
                    i -= 1
                    last = rows[-1][1] if rows else ""
                continue
            root = normalize_root(answer) if answer else last
            if not root:
                print("  Please enter a root for the first value.")
                continue
            rows.append((v, root))
            last = root
            i += 1

    if not rows:
        return
    out_file = args.output or f"scale_root_cc{args.cc}_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with open(out_file, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cc_value", "scale_root"])
        w.writerows(rows)
    print(f"\nSaved: {out_file}\n")
    print("Ranges:")
    for lo, hi, root in summarize(rows):
        print(f"  {lo:3d}–{hi:3d}  {root}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--port", help="part of the port name (default: first IAC/SuperRack port)")
    common.add_argument("--channel", type=int, default=1, choices=range(1, 17), metavar="1-16")
    common.add_argument("--cc", type=int, default=20, choices=range(128), metavar="0-127",
                        help="CC number (default: 20)")

    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ports", help="list MIDI outputs").set_defaults(func=cmd_ports)

    s = sub.add_parser("send", parents=[common], help="send a single CC value")
    s.add_argument("value", type=int, choices=range(128), metavar="0-127")
    s.set_defaults(func=cmd_send)

    s = sub.add_parser("learn", parents=[common], help="send a CC repeatedly for MIDI learn")
    s.add_argument("--seconds", type=float, default=10)
    s.set_defaults(func=cmd_learn)

    s = sub.add_parser("key", parents=[common], help="set Tune RT root + scale (Plugin Controls)")
    s.add_argument("root", help="root note, e.g. D, F#, Bb (German names like Fis, Es, H work too)")
    s.add_argument("--scale", choices=SCALE_TYPES, default="major", metavar="NAME",
                   help="scale, e.g. major, natural-minor, dorian (full list: README.md)")
    s.add_argument("--scale-value", type=int, choices=range(5, 128), metavar="5-127",
                   help="any scale by its Scale Type value (see README.md)")
    s.add_argument("--pause", type=float, default=0.1, metavar="SEC",
                   help="pause after each message (default: 0.1)")
    s.add_argument("--root-cc", type=int, default=27)
    s.add_argument("--type-cc", type=int, default=28)
    s.add_argument("--send-to-all", action="store_true",
                   help="press Send to All afterwards: all Tune RT with Receive take over scale and root")
    target = s.add_mutually_exclusive_group()
    target.add_argument("--rack", type=int, metavar="N", help="select rack N first (plugin selected there)")
    target.add_argument("--hot-plugin", type=int, choices=range(1, 13), metavar="1-12",
                        help="select the plugin on Hot Plugin N first")
    target.add_argument("--user-key", type=int, choices=range(1, 17), metavar="1-16",
                        help="trigger User Key N first (e.g. R32P2 = rack 32, plugin 2)")
    s.add_argument("--max-racks", type=int, default=64, help="number of PREV RACK presses to reach rack 1 for sure")
    s.add_argument("--nav-pause", type=float, default=0.02, metavar="SEC", help="pause during rack navigation")
    s.add_argument("--prev-rack-cc", type=int, default=42)
    s.add_argument("--next-rack-cc", type=int, default=43)
    s.add_argument("--hot-plugin-cc", type=int, default=50, help="CC of Hot Plugin 1, the others follow (default: 50)")
    s.add_argument("--user-key-cc", type=int, default=70, help="CC of User Key 1, the others follow (default: 70)")
    s.add_argument("--send-cc", type=int, default=20, help="Discrete 1 / Send to All (default: 20)")
    s.add_argument("--prev-page-cc", type=int, default=41)
    s.add_argument("--next-page-cc", type=int, default=40)
    s.set_defaults(func=cmd_key)

    s = sub.add_parser("snapshot", parents=[common], help="recall a SuperRack snapshot via Program Change")
    s.add_argument("number", type=int, choices=range(1, 1025), metavar="1-1024")
    s.add_argument("--always-bank", action="store_true",
                   help="send Bank LSB for snapshots 1–128 as well")
    s.set_defaults(func=cmd_snapshot)

    s = sub.add_parser("sweep", parents=[common], help="step through CC values and record the root")
    s.add_argument("--start", type=int, default=0)
    s.add_argument("--end", type=int, default=127)
    s.add_argument("--step", type=int, default=1)
    s.add_argument("--auto", type=float, metavar="SEC",
                   help="run without input, SEC pause per value")
    s.add_argument("--output", "-o", help="CSV file (default: with timestamp)")
    s.set_defaults(func=cmd_sweep)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
