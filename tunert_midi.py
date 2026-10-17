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
  python tunert_midi.py key A --hot-plugin 1

React to incoming MIDI (e.g. a pad or a program change) with a YAML mapping:
  python tunert_midi.py monitor --input "Launchpad Pro Standalone"
  python tunert_midi.py listen mapping.yaml --check
  python tunert_midi.py listen mapping.yaml

Helper commands for measuring and MIDI learn:
  python tunert_midi.py send 64 --cc 27
  python tunert_midi.py learn --cc 27
  python tunert_midi.py sweep --cc 27
  python tunert_midi.py sweep --cc 27 --auto 0.5
  python tunert_midi.py snapshot 3 --channel 16
"""

import argparse
import contextlib
import csv
import queue
import signal
import sys
import threading
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
    t = str(text).strip().upper().replace("♯", "#").replace("♭", "B")
    return NOTE_ALIASES.get(t, str(text).strip())


def pick_port(wanted, kind="output"):
    """Find a port by (part of) its name. Refuses to guess: ambiguous or missing names are an error."""
    names = mido.get_output_names() if kind == "output" else mido.get_input_names()
    option = "--port" if kind == "output" else "--input"
    if not names:
        sys.exit(f"No MIDI {kind}s found.")
    if not wanted:
        if kind == "input":
            sys.exit(f"Please choose a MIDI input with --input. Available: {names}")
        wanted = "IAC"  # default: the IAC bus SuperRack listens on
    exact = [n for n in names if n.lower() == wanted.lower()]
    matches = exact or [n for n in names if wanted.lower() in n.lower()]
    if not matches:
        sys.exit(f"No MIDI {kind} matches '{wanted}'. Choose one with {option}. Available: {names}")
    if len(matches) > 1:
        sys.exit(f"'{wanted}' matches several MIDI {kind}s: {matches}. Use a more specific {option}.")
    return matches[0]


def open_port(args):
    name = pick_port(args.port)
    print(f"Sending to: {name}  |  channel {args.channel}, CC {args.cc}")
    return mido.open_output(name)


def send_cc(out, args, value):
    out.send(mido.Message("control_change", channel=args.channel - 1,
                          control=args.cc, value=value))


def cmd_ports(_args):
    print("Outputs (--port):")
    for n in mido.get_output_names():
        print(f"  {n}")
    print("Inputs (--input):")
    for n in mido.get_input_names():
        print(f"  {n}")


def cmd_send(args):
    with open_port(args) as out:
        send_cc(out, args, args.value)
        print(f"Sent CC {args.cc} = {args.value}.")


def cmd_learn(args):
    """Send one CC for SuperRack's MIDI learn.

    One message is enough to assign a field. More would be harmful: navigation and momentary buttons fire on
    every message, so a stream of CCs jumps through racks or pages as soon as the field is no longer selected.
    """
    with open_port(args) as out:
        if args.delay:
            print(f"Select the field in the SuperRack MIDI Controller window now; sending in {args.delay:g}s ...")
            time.sleep(args.delay)
        send_cc(out, args, args.value)
        print(f"Sent CC {args.cc} = {args.value}. Close the MIDI Controller window when all fields are assigned.")


def send_snapshot(out, channel, number, always_bank=False):
    """Recall a SuperRack snapshot: Bank LSB (CC 32) + Program Change, both 0-based."""
    bank, program = divmod(number - 1, 128)
    if bank or always_bank:
        out.send(mido.Message("control_change", channel=channel - 1, control=32, value=bank))
    out.send(mido.Message("program_change", channel=channel - 1, program=program))
    return bank, program


def cmd_snapshot(args):
    name = pick_port(args.port)
    with mido.open_output(name) as out:
        bank, program = send_snapshot(out, args.channel, args.number, args.always_bank)
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

# Options of a key action with their defaults. Used by the "key" command and by "listen" mappings.
KEY_DEFAULTS = {
    "scale": "major", "scale_value": None,
    "rack": None, "hot_plugin": None, "user_key": None,
    "send_to_all": False,
    "pause": 0.1, "nav_pause": 0.02, "max_racks": 64,
    "root_cc": 27, "type_cc": 28, "send_cc": 20,
    "next_page_cc": 40, "prev_page_cc": 41, "prev_rack_cc": 42, "next_rack_cc": 43,
    "hot_plugin_cc": 50, "user_key_cc": 70,
}


def check_int(value, lo, hi, name, where=""):
    """A whole number within lo..hi. YAML booleans (true/yes) are rejected even though bool is an int in Python."""
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValueError(f"{where}{name} must be a whole number {lo}-{hi}, got {value!r}")
    return value


def check_number(value, lo, hi, name, where=""):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
        raise ValueError(f"{where}{name} must be a number {lo}-{hi}, got {value!r}")
    return value


def check_keys(raw, allowed, where="", what=""):
    unknown = set(raw) - set(allowed)
    if unknown:
        raise ValueError(f"{where}unknown option(s) {', '.join(sorted(map(str, unknown)))}{what}")


def resolve_key(root_text, opts):
    """Check a key action and return (root, scale_value, scale_name). Raises ValueError on bad input."""
    root = normalize_root(root_text)
    if not isinstance(root_text, str) or root not in ROOT_RECIPES:
        raise ValueError(f"unknown root '{root_text}'")
    if opts["scale_value"] is not None:
        value = check_int(opts["scale_value"], 5, 127, "scale_value")
        scale_value, scale_name = value, f"(Scale Type value {value})"
    else:
        if not isinstance(opts["scale"], str) or opts["scale"] not in SCALE_TYPES:
            raise ValueError(f"unknown scale '{opts['scale']}'")
        scale_value, scale_name = SCALE_TYPES[opts["scale"]]
    for name, hi in (("rack", 1024), ("hot_plugin", 12), ("user_key", 16)):
        if opts[name] is not None:
            check_int(opts[name], 1, hi, name)
    targets = [k for k in ("rack", "hot_plugin", "user_key") if opts[k] is not None]
    if len(targets) > 1:
        raise ValueError(f"only one of rack, hot_plugin, user_key allowed, got {', '.join(targets)}")
    if not isinstance(opts["send_to_all"], bool):
        raise ValueError(f"send_to_all must be true or false, got {opts['send_to_all']!r}")
    check_number(opts["pause"], 0, 10, "pause")
    check_number(opts["nav_pause"], 0, 10, "nav_pause")
    check_int(opts["max_racks"], 1, 1024, "max_racks")
    for name in ("root_cc", "type_cc", "send_cc", "next_page_cc", "prev_page_cc", "prev_rack_cc", "next_rack_cc"):
        check_int(opts[name], 0, 127, name)
    check_int(opts["hot_plugin_cc"], 0, 127 - 11, "hot_plugin_cc")  # Hot Plugins 1-12 follow
    check_int(opts["user_key_cc"], 0, 127 - 15, "user_key_cc")      # User Keys 1-16 follow
    return root, scale_value, scale_name


def run_key(out, channel, root_text, opts):
    """Send the MIDI sequence for one key action and return a short description."""
    root, scale_value, scale_name = resolve_key(root_text, opts)
    ch = channel - 1

    def cc(control, value, pause=opts["pause"]):
        out.send(mido.Message("control_change", channel=ch, control=control, value=value))
        time.sleep(pause)

    def press(control, times=1, pause=opts["pause"]):
        # Navigation and momentary buttons trigger on EVERY message (value 0 included),
        # so send exactly one message per press.
        for _ in range(times):
            cc(control, 127, pause)

    # Select the target plugin. The Plugin Controls only jump to page 1 on an actual rack or plugin
    # change, so at least one rack change is always forced.
    if opts["rack"]:
        # PREV RACK stops at rack 1; from there NEXT RACK counts every rack individually.
        # NEXT x N and PREV x 1 instead of NEXT x (N-1), so that rack 1 -> rack 1 still causes a change.
        press(opts["prev_rack_cc"], opts["max_racks"], opts["nav_pause"])
        press(opts["next_rack_cc"], opts["rack"], opts["nav_pause"])
        press(opts["prev_rack_cc"])
    elif opts["hot_plugin"] or opts["user_key"]:
        press(opts["prev_rack_cc"])
        press(opts["next_rack_cc"])
        if opts["hot_plugin"]:
            press(opts["hot_plugin_cc"] + opts["hot_plugin"] - 1)
        else:
            press(opts["user_key_cc"] + opts["user_key"] - 1)
    if opts["rack"] or opts["hot_plugin"] or opts["user_key"]:
        press(opts["next_page_cc"])  # page 1 -> page 2 (Scale)

    cc(opts["type_cc"], SCALE_CHROMATIC)
    cc(opts["type_cc"], scale_value)
    for v in ROOT_RECIPES[root]:
        cc(opts["root_cc"], v)
    if opts["send_to_all"]:
        # Send to All = Discrete 1 on page 3 (Transmission); then back to page 2.
        press(opts["next_page_cc"])
        press(opts["send_cc"])
        press(opts["prev_page_cc"])

    where = (f" in rack {opts['rack']}" if opts["rack"] else f" on Hot Plugin {opts['hot_plugin']}"
             if opts["hot_plugin"] else f" on User Key {opts['user_key']}" if opts["user_key"] else "")
    return (f"{root} {scale_name}{where}: CC {opts['type_cc']} = {SCALE_CHROMATIC}, {scale_value}; "
            f"CC {opts['root_cc']} = {ROOT_RECIPES[root]}" + ("; Send to All" if opts["send_to_all"] else ""))


def cmd_key(args):
    opts = {k: getattr(args, k) for k in KEY_DEFAULTS}
    opts["scale"] = args.scale or KEY_DEFAULTS["scale"]
    try:
        resolve_key(args.root, opts)
    except ValueError as e:
        sys.exit(f"Error: {e}")
    name = pick_port(args.port)
    with mido.open_output(name) as out:
        summary = run_key(out, args.channel, args.root, opts)
    print(f"Set {summary} (via {name})")


# --- listen: react to incoming MIDI with a YAML mapping ---------------------------------------

# Trigger type -> name of the number field
TRIGGER_NUMBER = {"note_on": "note", "note_off": "note", "control_change": "control", "program_change": "program"}
# Trigger type -> name of the optional value field
TRIGGER_VALUE = {"note_on": "velocity", "note_off": "velocity", "control_change": "value"}


def _range(value, field, where):
    """A number or [min, max] -> (min, max)."""
    if isinstance(value, list) and len(value) == 2:
        lo, hi = (check_int(v, 0, 127, field, where) for v in value)
        if lo > hi:
            raise ValueError(f"{where}{field} range must be [min, max], got {value!r}")
        return lo, hi
    if isinstance(value, list):
        raise ValueError(f"{where}{field} must be a number or [min, max], got {value!r}")
    v = check_int(value, 0, 127, field, where)
    return v, v


def _normalize_keys(raw):
    return {str(k).replace("-", "_"): v for k, v in raw.items()}


def parse_trigger(raw, where):
    if not isinstance(raw, dict):
        raise ValueError(f"{where}trigger must be a mapping like {{type: note_on, note: 36}}")
    raw = _normalize_keys(raw)
    kind = raw.get("type")
    if kind not in TRIGGER_NUMBER:
        raise ValueError(f"{where}trigger type must be one of {', '.join(TRIGGER_NUMBER)}, got {kind!r}")
    number, value = TRIGGER_NUMBER[kind], TRIGGER_VALUE.get(kind)
    check_keys(raw, {"type", "channel", number} | ({value} if value else set()), where, f" for {kind}")
    trig = {"type": kind}
    if "channel" in raw:
        trig["channel"] = check_int(raw["channel"], 1, 16, "channel", where) - 1
    if number not in raw:
        raise ValueError(f"{where}trigger needs '{number}'")
    trig[number] = _range(raw[number], number, where)
    if value and value in raw:
        trig[value] = _range(raw[value], value, where)
    return trig


def trigger_matches(trig, msg):
    kind = msg.type
    if kind == "note_on" and msg.velocity == 0:
        kind = "note_off"  # note_on with velocity 0 is a note off
    if kind != trig["type"]:
        return False
    if "channel" in trig and msg.channel != trig["channel"]:
        return False
    for field in (TRIGGER_NUMBER[kind], TRIGGER_VALUE.get(kind)):
        if field and field in trig:
            lo, hi = trig[field]
            if not lo <= getattr(msg, field) <= hi:
                return False
    return True


def triggers_overlap(a, b):
    """True if some MIDI message would match both triggers."""
    if a["type"] != b["type"]:
        return False
    if "channel" in a and "channel" in b and a["channel"] != b["channel"]:
        return False
    for field in (TRIGGER_NUMBER[a["type"]], TRIGGER_VALUE.get(a["type"])):
        if field:
            lo_a, hi_a = a.get(field, (0, 127))
            lo_b, hi_b = b.get(field, (0, 127))
            if hi_a < lo_b or hi_b < lo_a:
                return False
    return True


def describe_trigger(trig):
    parts = [trig["type"]]
    if "channel" in trig:
        parts.append(f"ch {trig['channel'] + 1}")
    for field in ("note", "control", "program", "velocity", "value"):
        if field in trig:
            lo, hi = trig[field]
            parts.append(f"{field} {lo}" if lo == hi else f"{field} {lo}-{hi}")
    return " ".join(parts)


def _optional_channel(raw, where):
    return None if raw.get("channel") is None else check_int(raw["channel"], 1, 16, "channel", where)


def parse_action(raw, defaults, where):
    if not isinstance(raw, dict):
        raise ValueError(f"{where}action must be a mapping, got {raw!r}")
    raw = _normalize_keys(raw)
    if "key" in raw:
        check_keys(raw, {"key"} | set(KEY_DEFAULTS), where)
        if "scale" in raw and "scale_value" in raw:
            raise ValueError(f"{where}use either scale or scale_value, not both")
        opts = {**KEY_DEFAULTS, **defaults}
        # A target or scale given in the action replaces the one from the defaults.
        if any(k in raw for k in ("rack", "hot_plugin", "user_key")):
            opts.update(rack=None, hot_plugin=None, user_key=None)
        if "scale" in raw or "scale_value" in raw:
            opts.update(scale=KEY_DEFAULTS["scale"], scale_value=None)
        opts.update({k: v for k, v in raw.items() if k != "key"})
        try:
            resolve_key(raw["key"], opts)
        except ValueError as e:
            raise ValueError(f"{where}{e}") from None
        return {"do": "key", "root": raw["key"], "opts": opts}
    if "cc" in raw:
        check_keys(raw, {"cc", "value", "channel"}, where, " for cc")
        return {"do": "cc", "cc": check_int(raw["cc"], 0, 127, "cc", where),
                "value": check_int(raw.get("value", 127), 0, 127, "value", where),
                "channel": _optional_channel(raw, where)}
    if "snapshot" in raw:
        check_keys(raw, {"snapshot", "channel"}, where, " for snapshot")
        return {"do": "snapshot", "number": check_int(raw["snapshot"], 1, 1024, "snapshot", where),
                "channel": _optional_channel(raw, where)}
    if "wait" in raw:
        check_keys(raw, {"wait"}, where, " for wait")
        return {"do": "wait", "seconds": float(check_number(raw["wait"], 0, 3600, "wait", where))}
    raise ValueError(f"{where}action needs one of key, cc, snapshot, wait")


def load_mapping(path):
    import yaml

    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except OSError as e:
        sys.exit(f"Cannot read {path}: {e}")
    except yaml.YAMLError as e:
        sys.exit(f"{path} is not valid YAML: {e}")
    try:
        if not isinstance(data, dict):
            raise ValueError("top level must be a mapping with 'mappings:'")
        check_keys(data, {"input", "output", "channel", "defaults", "mappings"}, "", " at top level")
        raw_defaults = data.get("defaults") or {}
        if not isinstance(raw_defaults, dict):
            raise ValueError(f"defaults must be a mapping like {{hot_plugin: 1}}, got {raw_defaults!r}")
        defaults = _normalize_keys(raw_defaults)
        check_keys(defaults, KEY_DEFAULTS, "", " in defaults")
        if "scale" in defaults and "scale_value" in defaults:
            raise ValueError("defaults: use either scale or scale_value, not both")
        channel = check_int(data.get("channel", 1), 1, 16, "channel")
        raw_mappings = data.get("mappings") or []
        if not isinstance(raw_mappings, list):
            raise ValueError("mappings must be a list (each entry starts with '- ')")
    except ValueError as e:
        sys.exit(f"{path}: {e}")

    mappings, errors = [], []
    for i, entry in enumerate(raw_mappings, 1):
        name = entry.get("name") if isinstance(entry, dict) else None
        where = f"mapping {i}" + (f" ({name})" if name else "") + ": "
        try:
            if not isinstance(entry, dict):
                raise ValueError(f"{where}must be a mapping")
            entry = _normalize_keys(entry)
            if "trigger" not in entry:
                raise ValueError(f"{where}missing 'trigger'")
            trig = parse_trigger(entry["trigger"], where)
            if "actions" in entry:
                if set(entry) - {"name", "trigger", "actions"}:
                    raise ValueError(f"{where}use either 'actions:' or a single action, not both")
                raw_actions = entry["actions"]
                if not isinstance(raw_actions, list) or not raw_actions:
                    raise ValueError(f"{where}actions must be a non-empty list")
            else:
                raw_actions = [{k: v for k, v in entry.items() if k not in ("name", "trigger")}]
            actions = [parse_action(a, defaults, f"{where[:-2]}, action {j}: ")
                       for j, a in enumerate(raw_actions, 1)]
            mappings.append({"name": str(name) if name else describe_trigger(trig), "trigger": trig,
                             "actions": actions})
        except ValueError as e:
            errors.append(str(e))
    if errors:
        sys.exit(f"{path} has errors:\n  " + "\n  ".join(errors))
    if not mappings:
        sys.exit(f"{path}: no mappings defined")
    for j, later in enumerate(mappings):
        earlier = next((m for m in mappings[:j] if triggers_overlap(m["trigger"], later["trigger"])), None)
        if earlier:
            print(f"Warning: '{later['name']}' overlaps with the trigger of '{earlier['name']}'. "
                  "The first matching mapping wins, so it may never fire for some messages.")
    return {"input": data.get("input"), "output": data.get("output"), "channel": channel, "mappings": mappings}


def describe_action(action, channel):
    if action["do"] == "key":
        o = action["opts"]
        root = normalize_root(action["root"])
        scale = SCALE_TYPES[o["scale"]][1] if o["scale_value"] is None else f"Scale Type value {o['scale_value']}"
        target = (f", rack {o['rack']}" if o["rack"] else f", Hot Plugin {o['hot_plugin']}" if o["hot_plugin"]
                  else f", User Key {o['user_key']}" if o["user_key"] else "")
        return f"key {root} {scale}{target}" + (", Send to All" if o["send_to_all"] else "")
    if action["do"] == "cc":
        return f"CC {action['cc']} = {action['value']} on channel {action['channel'] or channel}"
    if action["do"] == "snapshot":
        return f"snapshot {action['number']} on channel {action['channel'] or channel}"
    return f"wait {action['seconds']:g}s"


def run_action(out, action, channel, stop):
    if action["do"] == "key":
        return run_key(out, channel, action["root"], action["opts"])
    if action["do"] == "cc":
        out.send(mido.Message("control_change", channel=(action["channel"] or channel) - 1,
                              control=action["cc"], value=action["value"]))
    elif action["do"] == "snapshot":
        send_snapshot(out, action["channel"] or channel, action["number"])
    else:
        stop.wait(action["seconds"])  # a pause may be cut short by a stop request; MIDI sequences never are
    return describe_action(action, channel)


STOP_SIGNALS = tuple(getattr(signal, n) for n in ("SIGINT", "SIGTERM", "SIGHUP") if hasattr(signal, n))


@contextlib.contextmanager
def stop_requested():
    """Turn Ctrl+C, kill and a closed terminal into a stop flag instead of an exception.

    This works even when the process was started with SIGINT ignored (e.g. in the background), and it lets a
    running action finish: a half-sent sequence would leave Tune RT or the Plugin Controls page in an unknown state.
    """
    stop = threading.Event()
    previous = {sig: signal.signal(sig, lambda *_: stop.set()) for sig in STOP_SIGNALS}
    try:
        yield stop
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def incoming(port_name, stop):
    """Yield incoming messages until stop is set. Blocks without polling; checks the flag twice a second."""
    messages = queue.Queue()
    with mido.open_input(port_name, callback=messages.put):
        while not stop.is_set():
            try:
                yield messages.get(timeout=0.5)
            except queue.Empty:
                continue


def cmd_listen(args):
    mapping = load_mapping(args.mapping)
    channel = args.channel or mapping["channel"]
    print(f"{args.mapping}: {len(mapping['mappings'])} mapping(s)")
    for m in mapping["mappings"]:
        print(f"  {describe_trigger(m['trigger'])}  ->  "
              + " | ".join(describe_action(a, channel) for a in m["actions"])
              + (f"   [{m['name']}]" if m["name"] != describe_trigger(m["trigger"]) else ""))
    if args.check:
        print("Mapping OK.")
        return

    in_name = pick_port(args.input or mapping["input"], "input")
    out_name = pick_port(args.port or mapping["output"])
    if in_name == out_name:
        print(f"Warning: input and output are both '{in_name}'. Triggers also reach SuperRack, and the CCs sent "
              "here come back in. Keep the triggers on another channel than the SuperRack mapping.")
    print(f"Listening on '{in_name}', sending to '{out_name}' (SuperRack channel {channel}). Ctrl+C stops.")
    with stop_requested() as stop, mido.open_output(out_name) as out:
        for msg in incoming(in_name, stop):
            match = next((m for m in mapping["mappings"] if trigger_matches(m["trigger"], msg)), None)
            if not match:
                if args.verbose:
                    print(f"{datetime.now():%H:%M:%S}  (no mapping) {msg}")
                continue
            print(f"{datetime.now():%H:%M:%S}  {match['name']}")
            for action in match["actions"]:
                if stop.is_set():
                    print("    stop requested, remaining actions skipped")
                    break
                if args.dry_run:
                    print(f"    would do: {describe_action(action, channel)}")
                    continue
                try:
                    print(f"    {run_action(out, action, channel, stop)}")
                except Exception as e:  # keep listening even if one action fails
                    print(f"    failed: {e}")
    print("Stopped.")


def cmd_monitor(args):
    """Print incoming messages in the trigger format used by mapping files."""
    in_name = pick_port(args.input, "input")
    print(f"Listening on '{in_name}'. Copy a line into the mapping file as 'trigger:'. Ctrl+C stops.")
    with stop_requested() as stop:
        for msg in incoming(in_name, stop):
            if msg.type in ("clock", "active_sensing", "start", "stop", "continue", "songpos"):
                continue
            ch = getattr(msg, "channel", None)
            if msg.type in ("note_on", "note_off"):
                kind = "note_off" if msg.type == "note_off" or msg.velocity == 0 else "note_on"
                print(f"{{type: {kind}, channel: {ch + 1}, note: {msg.note}}}   # velocity {msg.velocity}")
            elif msg.type == "control_change":
                print(f"{{type: control_change, channel: {ch + 1}, control: {msg.control}, value: {msg.value}}}")
            elif msg.type == "program_change":
                print(f"{{type: program_change, channel: {ch + 1}, program: {msg.program}}}")
            else:
                print(f"# {msg}   (not usable as trigger)")
    print("Stopped.")


# --- sweep -------------------------------------------------------------------------------------

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
    if args.start > args.end:
        sys.exit(f"--start ({args.start}) must not be greater than --end ({args.end}).")
    values = list(range(args.start, args.end + 1, args.step))
    rows = []
    with open_port(args) as out:
        if args.auto is not None:
            try:
                for v in values:
                    send_cc(out, args, v)
                    print(f"CC {args.cc} = {v:3d}")
                    time.sleep(args.auto)
            except KeyboardInterrupt:
                print("\nStopped.")
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


def int_range(lo, hi):
    """argparse type for a whole number within lo..hi with a short error message."""
    def parse(text):
        try:
            value = int(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"must be a whole number {lo}-{hi}, got '{text}'") from None
        if not lo <= value <= hi:
            raise argparse.ArgumentTypeError(f"must be {lo}-{hi}, got {value}")
        return value
    return parse


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    outp = argparse.ArgumentParser(add_help=False)
    outp.add_argument("--port", help="output to SuperRack, (part of) the port name (default: the IAC port)")
    outp.add_argument("--channel", type=int_range(1, 16), default=1, metavar="1-16",
                      help="MIDI channel of the SuperRack mapping (default: 1)")
    ccp = argparse.ArgumentParser(add_help=False)
    ccp.add_argument("--cc", type=int_range(0, 127), default=20, metavar="0-127",
                     help="CC number (default: 20)")

    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ports", help="list MIDI outputs and inputs").set_defaults(func=cmd_ports)

    s = sub.add_parser("key", parents=[outp], help="set Tune RT root + scale (Plugin Controls)")
    s.add_argument("root", help="root note, e.g. D, F#, Bb (German names like Fis, Es, H work too)")
    scale = s.add_mutually_exclusive_group()
    scale.add_argument("--scale", choices=SCALE_TYPES, metavar="NAME",
                       help="scale, e.g. major, natural-minor, dorian (default: major; full list: README.md)")
    scale.add_argument("--scale-value", type=int_range(5, 127), metavar="5-127",
                       help="any scale by its Scale Type value (see README.md)")
    s.add_argument("--pause", type=float, default=KEY_DEFAULTS["pause"], metavar="SEC",
                   help="pause after each message (default: 0.1)")
    s.add_argument("--root-cc", type=int, default=KEY_DEFAULTS["root_cc"])
    s.add_argument("--type-cc", type=int, default=KEY_DEFAULTS["type_cc"])
    s.add_argument("--send-to-all", action="store_true",
                   help="press Send to All afterwards: all Tune RT with Receive take over scale and root")
    target = s.add_mutually_exclusive_group()
    target.add_argument("--rack", type=int, metavar="N", help="select rack N first (plugin selected there)")
    target.add_argument("--hot-plugin", type=int_range(1, 12), metavar="1-12",
                        help="select the plugin on Hot Plugin N first")
    target.add_argument("--user-key", type=int_range(1, 16), metavar="1-16",
                        help="trigger User Key N first (e.g. R32P2 = rack 32, plugin 2)")
    s.add_argument("--max-racks", type=int, default=KEY_DEFAULTS["max_racks"],
                   help="number of PREV RACK presses to reach rack 1 for sure")
    s.add_argument("--nav-pause", type=float, default=KEY_DEFAULTS["nav_pause"], metavar="SEC",
                   help="pause during rack navigation")
    s.add_argument("--prev-rack-cc", type=int, default=KEY_DEFAULTS["prev_rack_cc"])
    s.add_argument("--next-rack-cc", type=int, default=KEY_DEFAULTS["next_rack_cc"])
    s.add_argument("--hot-plugin-cc", type=int, default=KEY_DEFAULTS["hot_plugin_cc"],
                   help="CC of Hot Plugin 1, the others follow (default: 50)")
    s.add_argument("--user-key-cc", type=int, default=KEY_DEFAULTS["user_key_cc"],
                   help="CC of User Key 1, the others follow (default: 70)")
    s.add_argument("--send-cc", type=int, default=KEY_DEFAULTS["send_cc"],
                   help="Discrete 1 / Send to All (default: 20)")
    s.add_argument("--prev-page-cc", type=int, default=KEY_DEFAULTS["prev_page_cc"])
    s.add_argument("--next-page-cc", type=int, default=KEY_DEFAULTS["next_page_cc"])
    s.set_defaults(func=cmd_key)

    s = sub.add_parser("listen", help="react to incoming MIDI messages with actions from a YAML mapping")
    s.add_argument("mapping", help="YAML mapping file (see mapping.example.yaml)")
    s.add_argument("--input", help="MIDI input, part of the port name (overrides 'input:' in the file)")
    s.add_argument("--port", help="output to SuperRack (overrides 'output:' in the file)")
    s.add_argument("--channel", type=int_range(1, 16), metavar="1-16",
                   help="MIDI channel of the SuperRack mapping (overrides 'channel:' in the file)")
    s.add_argument("--check", action="store_true", help="only validate the mapping file, open no ports")
    s.add_argument("--dry-run", action="store_true", help="show what would be sent, send nothing")
    s.add_argument("--verbose", "-v", action="store_true", help="also print messages without a mapping")
    s.set_defaults(func=cmd_listen)

    s = sub.add_parser("monitor", help="print incoming MIDI messages in trigger format")
    s.add_argument("--input", help="MIDI input, part of the port name")
    s.set_defaults(func=cmd_monitor)

    s = sub.add_parser("send", parents=[outp, ccp], help="send a single CC value")
    s.add_argument("value", type=int_range(0, 127), metavar="0-127")
    s.set_defaults(func=cmd_send)

    s = sub.add_parser("learn", parents=[outp, ccp], help="send one CC for MIDI learn")
    s.add_argument("--delay", type=float, default=3, metavar="SEC",
                   help="seconds to select the field in SuperRack before the CC is sent (default: 3)")
    s.add_argument("--value", type=int_range(0, 127), default=127, metavar="0-127")
    s.set_defaults(func=cmd_learn)

    s = sub.add_parser("snapshot", parents=[outp], help="recall a SuperRack snapshot via Program Change")
    s.add_argument("number", type=int_range(1, 1024), metavar="1-1024")
    s.add_argument("--always-bank", action="store_true",
                   help="send Bank LSB for snapshots 1–128 as well")
    s.set_defaults(func=cmd_snapshot)

    s = sub.add_parser("sweep", parents=[outp, ccp], help="step through CC values and record the root")
    s.add_argument("--start", type=int_range(0, 127), default=0, metavar="0-127")
    s.add_argument("--end", type=int_range(0, 127), default=127, metavar="0-127")
    s.add_argument("--step", type=int_range(1, 127), default=1, metavar="1-127")
    s.add_argument("--auto", type=float, metavar="SEC",
                   help="run without input, SEC pause per value")
    s.add_argument("--output", "-o", help="CSV file (default: with timestamp)")
    s.set_defaults(func=cmd_sweep)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
