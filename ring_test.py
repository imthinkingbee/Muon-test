#!/usr/bin/env python3
"""Concentric-ring opacity test for the muon detector's 16x16 NeoPixel panel.

Cycles a 16x16 NeoPixel matrix through concentric-ring patterns so a
3D-printed cover can be judged for opacity / diffusion: whether single LEDs
show through as hotspots, whether neighbouring rings stay distinguishable,
and how much light survives at lower brightness.

Colours come from the "Muon Ripple" panel design:
  warm  typical #dfe9ff, rare #ffb04a
  cool  typical #6fd8ff, rare #b996ff
  pride one stripe per ring: #ff3b3b #ff9a1f #ffe733 #2fd16a #3d7bff #b05cff

Two kinds of configuration are shown:
  static  fixed rings (thin / spaced / thick / solid) at several brightness levels
  ripple  rings expanding from the centre, same speed, width and fade as the
          Muon Ripple design (90 mm/s, 11 mm wide, 1.6 s fade, 10 mm pitch)

Hardware: Raspberry Pi 5, data on GPIO18 (header pin 12) by default, panel on
its own 5 V supply. Drives the LEDs with Adafruit's Pi 5 PIO driver
(pip install Adafruit-Blinka-Raspberry-Pi5-Neopixel). See README.md.

Run `python3 ring_test.py --preview` on any computer to see the patterns in
the terminal without a panel attached.
"""

import argparse
import math
import signal
import sys
import time

# ---- panel ------------------------------------------------------------------
N = 16                       # 16 x 16 LEDs
CENTRE = (N - 1) / 2         # 7.5: the rings are centred between the 4 middle LEDs
PITCH_MM = 10.0              # LED pitch, used to convert the ripple's mm to LEDs

# ---- power model (WS2812B, conservative) ------------------------------------
MA_PER_CHANNEL = 20.0        # mA per colour channel at 255 (~60 mA per LED at full white)
MA_IDLE_PER_LED = 1.0        # mA quiescent per LED, even when dark

# ---- colours (Muon Ripple design) --------------------------------------------
SCHEMES = {
    "warm": {"typ": (223, 233, 255), "hot": (255, 176, 74)},
    "cool": {"typ": (111, 216, 255), "hot": (185, 150, 255)},
}
PRIDE = [(255, 59, 59), (255, 154, 31), (255, 231, 51),
         (47, 209, 106), (61, 123, 255), (176, 92, 255)]

# ---- ripple (Muon Ripple design, mm -> LEDs at 10 mm pitch) ------------------
RING_V = 90.0 / PITCH_MM     # 9 LEDs/s outward speed
RING_W = 11.0 / PITCH_MM     # 1.1 LED gaussian ring width
FADE = 1.6                   # s
LIFE = FADE * 2.2            # s, a ripple is dropped after this
EDGE = 230.0 / PITCH_MM      # ring strength falls linearly to 0 at 23 LEDs
CORE_R = 8.0 / PITCH_MM      # impact core radius
CORE_T = 0.25                # s, impact core decay
RIPPLE_EVERY = 1.4           # s between ripples
FPS = 50

# ---- the test sequence -------------------------------------------------------
# (name, ring width in LEDs, ring period in LEDs, description); width == period is solid.
STATIC_PATTERNS = [
    ("thin rings, 1 on / 1 off", 1, 2, "adjacent rings separated by one dark ring"),
    ("thin rings, 1 on / 2 off", 1, 3, "single-LED rings, wider dark gaps"),
    ("thick rings, 2 on / 2 off", 2, 4, "two-LED rings, two-LED gaps"),
    ("solid, every ring lit", 1, 1, "all rings lit; uniformity and colour bleed"),
]
STATIC_LEVELS = [1.00, 0.50, 0.25]
RIPPLE_LEVELS = [1.00, 0.25]
SCHEME_ORDER = ["warm", "cool", "pride"]


def ring_index(x, y):
    """Concentric ring number of LED (x, y): 0 for the middle 4 LEDs, up to 10 at the corners."""
    return int(math.hypot(x - CENTRE, y - CENTRE))


def xy_to_index(x, y, layout):
    """Position of LED (x, y) along the data chain."""
    if layout == "serpentine" and y % 2 == 1:
        return y * N + (N - 1 - x)
    return y * N + x


def ring_colour(scheme, k):
    """Colour of the k-th lit ring: warm/cool alternate typical and rare, pride takes the next stripe."""
    if scheme == "pride":
        return PRIDE[k % len(PRIDE)]
    s = SCHEMES[scheme]
    return s["typ"] if k % 2 == 0 else s["hot"]


def static_frame(scheme, width, period):
    """Fixed concentric rings; returns frame[y][x] = (r, g, b) floats 0..255."""
    frame = [[(0.0, 0.0, 0.0)] * N for _ in range(N)]
    for y in range(N):
        for x in range(N):
            r = ring_index(x, y)
            if r % period < width:
                frame[y][x] = ring_colour(scheme, r // period)
    return frame


def ripple_frame(ripples, now):
    """Expanding rings from the centre, as the Muon Ripple design draws them."""
    frame = [[[0.0, 0.0, 0.0] for _ in range(N)] for _ in range(N)]
    for t0, colour in ripples:
        t = now - t0
        if t < 0 or t > LIFE:
            continue
        fade = math.exp(-t / (FADE / 2.2))
        r0 = RING_V * t
        core_t = math.exp(-t / CORE_T)
        for y in range(N):
            for x in range(N):
                d = math.hypot(x - CENTRE, y - CENTRE)
                ring = math.exp(-(((d - r0) / RING_W) ** 2))
                core = math.exp(-((d / CORE_R) ** 2)) * core_t
                v = fade * (ring * (1 - min(1.0, d / EDGE)) + core)
                px = frame[y][x]
                px[0] += v * colour[0]
                px[1] += v * colour[1]
                px[2] += v * colour[2]
    return frame


def current_amps(frame, level):
    """Estimated panel current for a frame shown at a brightness level."""
    total = sum(min(255.0, c) for row in frame for px in row for c in px)
    return (N * N * MA_IDLE_PER_LED + MA_PER_CHANNEL * level * total / 255.0) / 1000.0


def power_scale(frame, level, max_amps):
    """Extra factor (<= 1) that keeps the frame's estimated current under max_amps."""
    idle = N * N * MA_IDLE_PER_LED / 1000.0
    amps = current_amps(frame, level)
    if amps <= max_amps:
        return 1.0
    return max(0.0, (max_amps - idle) / (amps - idle))


def encode(frame, level, layout):
    """Frame -> GRB byte buffer in data-chain order."""
    buf = bytearray(N * N * 3)
    for y in range(N):
        for x in range(N):
            i = 3 * xy_to_index(x, y, layout)
            r, g, b = (int(round(min(255.0, c) * level)) for c in frame[y][x])
            buf[i], buf[i + 1], buf[i + 2] = g, r, b
    return buf


# ---- outputs -----------------------------------------------------------------
class Panel:
    """The real panel on a Pi 5 GPIO pin, via Adafruit's PIO driver."""

    def __init__(self, gpio):
        try:
            from adafruit_raspberry_pi5_neopixel_write import neopixel_write
        except ImportError:
            sys.exit("Missing the Pi 5 NeoPixel driver: "
                     "pip install Adafruit-Blinka-Raspberry-Pi5-Neopixel (see README.md)")
        self._write = neopixel_write
        self.id = gpio           # the driver reads the BCM GPIO number from .id

    def show(self, frame, level, layout):
        self._write(self, encode(frame, level, layout))

    def off(self):
        self._write(self, bytearray(N * N * 3))


class TerminalPreview:
    """Draws the panel in a truecolour terminal instead of driving LEDs."""

    def __init__(self):
        self.drawn = False

    def show(self, frame, level, layout):
        # Decode the exact bytes the panel would get, so the preview also checks encode().
        buf = encode(frame, level, layout)
        lines = []
        for y in range(N):
            row = []
            for x in range(N):
                i = 3 * xy_to_index(x, y, layout)
                g, r, b = buf[i], buf[i + 1], buf[i + 2]
                row.append(f"\x1b[48;2;{r};{g};{b}m  ")
            lines.append("".join(row) + "\x1b[0m")
        if self.drawn:
            sys.stdout.write(f"\x1b[{N}F")
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()
        self.drawn = True

    def off(self):
        self.drawn = False


# ---- sequence ------------------------------------------------------------------
def build_sequence():
    seq = []
    for name, width, period, about in STATIC_PATTERNS:
        for scheme in SCHEME_ORDER:
            for level in STATIC_LEVELS:
                seq.append({"kind": "static", "scheme": scheme, "level": level,
                            "width": width, "period": period,
                            "label": f"{name} | {scheme} | {level:.0%}", "about": about})
    for scheme in SCHEME_ORDER:
        for level in RIPPLE_LEVELS:
            seq.append({"kind": "ripple", "scheme": scheme, "level": level,
                        "label": f"expanding ripple | {scheme} | {level:.0%}",
                        "about": "rings grow from the centre every 1.4 s, as in Muon Ripple"})
    return seq


def log(msg, out):
    # In preview the panel is redrawn in place, so logs go to stderr to keep it tidy.
    print(msg, file=sys.stderr if isinstance(out, TerminalPreview) else sys.stdout, flush=True)


def run_static(cfg, out, args):
    frame = static_frame(cfg["scheme"], cfg["width"], cfg["period"])
    scale = power_scale(frame, cfg["level"], args.max_amps)
    level = cfg["level"] * scale
    amps = current_amps(frame, level)
    note = f"  ~{amps:.2f} A"
    if scale < 1.0:
        note += f"  POWER-LIMITED: shown at {level:.0%} instead of {cfg['level']:.0%}"
    log(note, out)
    out.show(frame, level, args.layout)
    time.sleep(args.hold)


def run_ripple(cfg, out, args):
    scheme = cfg["scheme"]
    start = time.monotonic()
    ripples, k, next_ripple = [], 0, start
    peak_amps, min_scale = 0.0, 1.0
    while True:
        now = time.monotonic()
        if now - start >= args.hold:
            break
        if now >= next_ripple:
            ripples.append((now, ring_colour(scheme, k)))
            k += 1
            next_ripple += RIPPLE_EVERY
        ripples = [r for r in ripples if now - r[0] <= LIFE]
        frame = ripple_frame(ripples, now)
        scale = power_scale(frame, cfg["level"], args.max_amps)
        level = cfg["level"] * scale
        peak_amps = max(peak_amps, current_amps(frame, level))
        min_scale = min(min_scale, scale)
        out.show(frame, level, args.layout)
        time.sleep(max(0.0, 1.0 / FPS - (time.monotonic() - now)))
    note = f"  peak ~{peak_amps:.2f} A"
    if min_scale < 1.0:
        note += f"  POWER-LIMITED at times (down to {cfg['level'] * min_scale:.0%})"
    log(note, out)


def main():
    p = argparse.ArgumentParser(description="Concentric-ring opacity test for a 16x16 NeoPixel panel on a Pi 5.")
    p.add_argument("--pin", type=int, default=18, help="BCM GPIO number of the data line (default 18 = header pin 12)")
    p.add_argument("--hold", type=float, default=8.0, help="seconds per configuration (default 8)")
    p.add_argument("--max-amps", type=float, default=3.5,
                   help="panel current limit in A; frames are dimmed to stay under it (default 3.5, for a 5 V 4 A supply)")
    p.add_argument("--layout", choices=["serpentine", "progressive"], default="serpentine",
                   help="data-chain wiring of the matrix (default serpentine, as on Adafruit's 16x16)")
    p.add_argument("--start", type=int, default=1, help="configuration number to start from (see --list)")
    p.add_argument("--once", action="store_true", help="run the sequence once instead of looping")
    p.add_argument("--list", action="store_true", help="print the configurations and exit")
    p.add_argument("--preview", action="store_true", help="draw in the terminal instead of driving the panel")
    args = p.parse_args()

    seq = build_sequence()
    if args.list:
        for n, cfg in enumerate(seq, 1):
            print(f"{n:3d}  {cfg['label']}")
        return
    if not 1 <= args.start <= len(seq):
        p.error(f"--start must be 1..{len(seq)}")
    if args.hold <= 0:
        p.error("--hold must be positive")
    if args.max_amps <= N * N * MA_IDLE_PER_LED / 1000.0:
        p.error(f"--max-amps must be above the panel's idle draw ({N * N * MA_IDLE_PER_LED / 1000.0:.2f} A)")

    out = TerminalPreview() if args.preview else Panel(args.pin)

    # systemd / kill send SIGTERM; turn it into the same clean exit as Ctrl+C.
    def stop(signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)

    try:
        first = args.start - 1
        while True:
            for n in range(first, len(seq)):
                cfg = seq[n]
                log(f"[{n + 1}/{len(seq)}] {cfg['label']}  ({cfg['about']})", out)
                (run_static if cfg["kind"] == "static" else run_ripple)(cfg, out, args)
            first = 0
            if args.once:
                break
    except KeyboardInterrupt:
        pass
    finally:
        try:
            out.off()
            log("panel off", out)
        except Exception as e:  # don't hide the error that got us here
            log(f"could not blank the panel: {e}", out)


if __name__ == "__main__":
    main()
