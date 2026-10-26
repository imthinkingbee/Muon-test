#!/usr/bin/env python3
"""Concentric-ripple opacity test for the muon detector's 16x16 NeoPixel panel.

Drops "muon ripples" into the centre of the panel, animated the same way as
the "Muon Ripple" panel design, so a 3D-printed cover can be judged for
opacity / diffusion with the real animation behind it: whether single LEDs
show through as hotspots, and whether the moving rings stay crisp.

Each drop, as in Muon Ripple:
  - lands with a bright core that dies away in ~0.25 s
  - sends a ring outwards at 90 mm/s (9 LEDs/s), 11 mm wide, fading over ~1.6 s
  - gets a simulated muon energy (cos^3 zenith track through the 10x10x3.81 cm
    slab, Landau-like loss) that sets its brightness, and its colour:
    typical, or rare above 15.5 MeV
  - arrives at random (Poisson) times, 0.4 per second on average ("gallery
    pace"); --rate 1.7 gives the sea-level muon rate

The colour scheme changes on every drop, warm -> cool -> pride -> warm ...
  warm  typical #dfe9ff, rare #ffb04a
  cool  typical #6fd8ff, rare #b996ff
  pride typical: the next stripe of #ff3b3b #ff9a1f #ffe733 #2fd16a #3d7bff #b05cff,
        rare: a full rainbow round the ring; pride rings also throw off glitter

--scheme pumpkin swaps the ripples for Halloween: each drop grows a jack-o'-lantern
from a dot at the centre to full panel size in 0.9 s, holds it, then fades it out.

Hardware: Raspberry Pi 5, data on GPIO18 (header pin 12) by default, panel on
its own 5 V supply. Drives the LEDs with Adafruit's Pi 5 PIO driver
(pip install Adafruit-Blinka-Raspberry-Pi5-Neopixel). See README.md.

Run `python3 ring_test.py --preview` on any computer to see the ripples in
the terminal without a panel attached.
"""

import argparse
import math
import random
import signal
import sys
import time

# ---- panel ------------------------------------------------------------------
N = 16                       # 16 x 16 LEDs
CENTRE = (N - 1) / 2         # 7.5: ripples land between the 4 middle LEDs
PITCH = 10.0                 # mm between LEDs
FPS = 50

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
SCHEME_ORDER = ["warm", "cool", "pride"]

# ---- ripple (Muon Ripple design; mm and s) -------------------------------------
RING_V, RING_W, FADE = 90.0, 11.0, 1.6     # ring speed mm/s, width mm, fade s
LIFE = FADE * 2.2                          # s, a ripple is dropped after this
EDGE = 230.0                               # mm, ring strength falls linearly to 0 here
CORE_R, CORE_T = 8.0, 0.25                 # impact core: radius mm, decay s

# ---- muon energy (Muon Ripple design) -------------------------------------------
HALF, HZ = 50.0, 19.05                     # slab half-width and half-thickness, mm
MUON_PEAK = 8.6                            # MeV
FULL, HOT = 0.9 * MUON_PEAK, 1.8 * MUON_PEAK   # full brightness / rare colour from here

# ---- glitter on pride ripples (Muon Ripple design) ------------------------------
GLITTER = {"rate": 1.5, "wake": 0.08, "rise": 0.03, "tau": 0.15, "life": 0.45, "peak": 230, "tint": 0.35}

# ---- pumpkin (--scheme pumpkin) ------------------------------------------------------
# A jack-o'-lantern drawn on the panel's own 16x16 grid, so at full size every LED is
# cleanly lit or dark. A drop grows it from a dot to full size, holds, then fades.
PUMPKIN_ART = [
    "................",
    "........SS......",
    ".......SS.......",
    "....OOOOOOOO....",
    "..OOOOOOOOOOOO..",
    ".OOOOOOOOOOOOOO.",
    ".OOO.OOOOOO.OOO.",
    "OOO...OOOO...OOO",
    "OO.....OO.....OO",
    "OOOOOOOOOOOOOOOO",
    "OO.OOOOOOOOOO.OO",
    "OOO.....O....OOO",
    ".OOO........OOO.",
    "..OOOO....OOOO..",
    "...OOOOOOOOOO...",
    "....OOOOOOOO....",
]
PUMPKIN_COLOURS = {"O": (255, 100, 8), "S": (40, 150, 20)}
PUMPKIN_GROW = 0.9                         # s, dot -> full size (ease-out)
PUMPKIN_HOLD = 1.6                         # s, full brightness until here
PUMPKIN_FADE = 0.35                        # s, fade time constant after the hold
PUMPKIN_HANDOVER = 0.1                     # s, a pumpkin fades this fast once a new one lands


def _summed_area(art, colours):
    """Per-channel summed-area tables of the art, (N+1) x (N+1), for box-filtering it at any size."""
    sat = [[[0.0] * (N + 1) for _ in range(N + 1)] for _ in range(3)]
    for c in range(3):
        for j in range(N):
            for i in range(N):
                v = colours.get(art[j][i], (0, 0, 0))[c]
                sat[c][j + 1][i + 1] = v + sat[c][j][i + 1] + sat[c][j + 1][i] - sat[c][j][i]
    return sat


PUMPKIN_SAT = _summed_area(PUMPKIN_ART, PUMPKIN_COLOURS)


def _area(table, x, y):
    """Integral of the art over [0, x] x [0, y] in art pixels (bilinear, so exact for pixel art)."""
    x, y = min(max(x, 0.0), N), min(max(y, 0.0), N)
    i, j = min(int(x), N - 1), min(int(y), N - 1)
    fx, fy = x - i, y - j
    return (table[j][i] * (1 - fx) * (1 - fy) + table[j][i + 1] * fx * (1 - fy)
            + table[j + 1][i] * (1 - fx) * fy + table[j + 1][i + 1] * fx * fy)


def pumpkin_size(t):
    """Pumpkin size 0..1 at t s after the drop: fast at first, settling at full size."""
    x = min(1.0, t / PUMPKIN_GROW)
    return max(0.02, 1 - (1 - x) ** 3)


def pumpkin_level(t):
    return 1.0 if t < PUMPKIN_HOLD else math.exp(-(t - PUMPKIN_HOLD) / PUMPKIN_FADE)


def muon_energy(rng):
    """Energy (MeV) a cosmic muon leaves in the slab: cos^3 zenith direction, random entry
    point, path length through the slab (corner clippers included), Landau-like spread."""
    cz = (1.0 - rng.random()) ** 0.25          # (0, 1], never 0
    sz = math.sqrt(1 - cz * cz)
    phi = 2 * math.pi * rng.random()
    dx, dy = sz * math.cos(phi) / cz, sz * math.sin(phi) / cz
    xm, ym = (rng.random() * 2 - 1) * HALF, (rng.random() * 2 - 1) * HALF
    inside = 0
    for k in range(21):
        z = -HZ + k * HZ / 10
        if abs(xm + dx * z) <= HALF and abs(ym + dy * z) <= HALF:
            inside += 1
    path = inside * math.sqrt(1 + dx * dx + dy * dy) * (2 * HZ / 20) / 10   # cm
    g = rng.gauss(0.0, 1.0)
    lam = -math.log(g * g + 1e-12)
    return 1.8 * path * max(0.3, 1 + 0.12 * lam)


def hsv(h):
    """Full-saturation hue 0..1 -> (r, g, b) 0..255."""
    def f(n):
        k = (n + h * 6) % 6
        return 255 * (1 - max(0, min(k, 4 - k, 1)))
    return (f(5), f(3), f(1))


# LED centres in mm from the middle of the panel (y up), and each one's distance
# and pride-rainbow colour; fixed, so worked out once.
LEDS = []
for _j in range(N):
    for _i in range(N):
        _x, _y = (_i - CENTRE) * PITCH, (CENTRE - _j) * PITCH
        _h = (math.atan2(_y, _x) / (2 * math.pi) + 1) % 1
        LEDS.append((_i, _j, math.hypot(_x, _y), hsv(_h)))


class Drop:
    def __init__(self, t0, scheme, energy, stripe):
        self.t0, self.scheme, self.e = t0, scheme, energy
        self.hot = energy > HOT
        # Pumpkins stop at 1x: above that the red channel clips and the orange turns yellow.
        self.amp = min(1.0 if scheme == "pumpkin" else 1.6, energy / FULL)
        self.stripe = stripe
        self.replaced_at = None      # pumpkins: when a newer pumpkin took over

    def colour(self, rainbow):
        if self.scheme == "pride":
            return rainbow if self.hot else PRIDE[self.stripe]
        s = SCHEMES[self.scheme]
        return s["hot"] if self.hot else s["typ"]


class Ripples:
    """The panel's light field: active drops plus pride glitter, as Muon Ripple draws them."""

    def __init__(self, rng):
        self.rng = rng
        self.drops = []
        self.sparkles = []       # [led, t0, colour, strength]
        self.last = None

    def add(self, drop):
        if drop.scheme == "pumpkin":
            # One jack-o'-lantern at a time: a new one takes over and the old one fades out
            # quickly, so the new one doesn't grow over the old face and fill it in.
            for d in self.drops:
                if d.scheme == "pumpkin" and d.replaced_at is None:
                    d.replaced_at = drop.t0
        self.drops.append(drop)

    def frame(self, now):
        """Returns frame[y][x] = [r, g, b] (may exceed 255; clipped on output)."""
        dt = 0.0 if self.last is None else min(0.1, now - self.last)
        self.last = now
        px = [[[0.0, 0.0, 0.0] for _ in range(N)] for _ in range(N)]
        self.drops = [d for d in self.drops if now - d.t0 <= LIFE]
        for d in self.drops:
            t = now - d.t0
            if d.scheme == "pumpkin":
                self._pumpkin(px, d, t, now)
                continue
            fade = math.exp(-t / (FADE / 2.2))
            r0 = RING_V * t
            core_t = math.exp(-t / CORE_T)
            glitter = d.scheme == "pride"
            for n, (i, j, dist, rainbow) in enumerate(LEDS):
                ring = math.exp(-(((dist - r0) / RING_W) ** 2))
                core = math.exp(-((dist / CORE_R) ** 2)) * core_t
                edge = 1 - min(1.0, dist / EDGE)
                v = d.amp * fade * (ring * edge + core)
                col = d.colour(rainbow)
                p = px[j][i]
                p[0] += v * col[0]
                p[1] += v * col[1]
                p[2] += v * col[2]
                if glitter:
                    g = d.amp * fade * (ring + (GLITTER["wake"] if dist < r0 else 0)) * edge
                    if g > 0.05 and self.rng.random() < GLITTER["rate"] * (1.5 if d.hot else 1) * g * dt:
                        c = tuple((1 - GLITTER["tint"]) * 245 + GLITTER["tint"] * ch for ch in col)
                        self.sparkles.append([n, now, c, 0.6 + 0.4 * self.rng.random()])
        self.sparkles = [s for s in self.sparkles if now - s[1] <= GLITTER["life"]]
        for n, t0, c, strength in self.sparkles:
            t = now - t0
            env = (t / GLITTER["rise"] if t < GLITTER["rise"]
                   else math.exp(-(t - GLITTER["rise"]) / GLITTER["tau"])) * strength
            i, j = LEDS[n][0], LEDS[n][1]
            p = px[j][i]
            for k in range(3):
                p[k] += env * GLITTER["peak"] / 255 * c[k]
        return px

    @staticmethod
    def _pumpkin(px, d, t, now):
        """Add a growing jack-o'-lantern: each LED shows the average of the art under it."""
        size, v = pumpkin_size(t), d.amp * pumpkin_level(t)
        if d.replaced_at is not None:
            v *= math.exp(-max(0.0, now - d.replaced_at) / PUMPKIN_HANDOVER)
        h = 0.5 / size                     # half an LED, in art pixels
        for j in range(N):
            y = N / 2 + (j + 0.5 - N / 2) / size
            for i in range(N):
                x = N / 2 + (i + 0.5 - N / 2) / size
                p = px[j][i]
                for c in range(3):
                    s = PUMPKIN_SAT[c]
                    box = (_area(s, x + h, y + h) - _area(s, x - h, y + h)
                           - _area(s, x + h, y - h) + _area(s, x - h, y - h))
                    p[c] += v * box / (4 * h * h)


def xy_to_index(x, y, layout):
    """Position of LED (x, y) along the data chain."""
    if layout == "serpentine" and y % 2 == 1:
        return y * N + (N - 1 - x)
    return y * N + x


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


def log(msg, out):
    # In preview the panel is redrawn in place, so logs go to stderr to keep it tidy.
    print(msg, file=sys.stderr if isinstance(out, TerminalPreview) else sys.stdout, flush=True)


def main():
    p = argparse.ArgumentParser(description="Muon-ripple opacity test for a 16x16 NeoPixel panel on a Pi 5.")
    p.add_argument("--rate", type=float, default=0.4,
                   help="average drops per second, at random times (default 0.4 'gallery pace'; 1.7 = sea level)")
    p.add_argument("--scheme", choices=["rotate", "pumpkin"], default="rotate",
                   help="rotate = warm, cool, pride in turn (default); pumpkin = only jack-o'-lanterns")
    p.add_argument("--brightness", type=float, default=1.0, help="brightness 0..1 (default 1.0)")
    p.add_argument("--duration", type=float, default=0, help="stop after this many seconds (default 0 = run until Ctrl+C)")
    p.add_argument("--pin", type=int, default=18, help="BCM GPIO number of the data line (default 18 = header pin 12)")
    p.add_argument("--max-amps", type=float, default=3.5,
                   help="panel current limit in A; frames are dimmed to stay under it (default 3.5, for a 5 V 4 A supply)")
    p.add_argument("--layout", choices=["serpentine", "progressive"], default="serpentine",
                   help="data-chain wiring of the matrix (default serpentine, as on Adafruit's 16x16)")
    p.add_argument("--seed", type=int, default=None, help="random seed, to repeat the same run of drops")
    p.add_argument("--preview", action="store_true", help="draw in the terminal instead of driving the panel")
    args = p.parse_args()

    if args.rate <= 0:
        p.error("--rate must be positive")
    if not 0 < args.brightness <= 1:
        p.error("--brightness must be above 0 and at most 1")
    if args.duration < 0:
        p.error("--duration can't be negative")
    if args.max_amps <= N * N * MA_IDLE_PER_LED / 1000.0:
        p.error(f"--max-amps must be above the panel's idle draw ({N * N * MA_IDLE_PER_LED / 1000.0:.2f} A)")

    rng = random.Random(args.seed)
    out = TerminalPreview() if args.preview else Panel(args.pin)
    field = Ripples(rng)

    # systemd / kill send SIGTERM; turn it into the same clean exit as Ctrl+C.
    def stop(signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)

    try:
        start = time.monotonic()
        next_drop = start            # the first drop lands straight away
        count, stripe, last_limit_log = 0, 0, -1.0
        while True:
            now = time.monotonic()
            if args.duration and now - start >= args.duration:
                break
            if now >= next_drop:
                if args.scheme == "pumpkin":
                    scheme = "pumpkin"
                else:
                    scheme = SCHEME_ORDER[count % len(SCHEME_ORDER)]
                drop = Drop(now, scheme, muon_energy(rng), stripe % len(PRIDE))
                if scheme == "pride":
                    stripe += 1
                field.add(drop)
                count += 1
                kind = "" if scheme == "pumpkin" else ("rare" if drop.hot else "typical")
                log(f"drop {count:4d} | {scheme:7s} | {kind:7s} | "
                    f"{drop.e:5.1f} MeV | brightness x{drop.amp:.2f}", out)
                next_drop = now + rng.expovariate(args.rate)
            frame = field.frame(now)
            level = args.brightness * power_scale(frame, args.brightness, args.max_amps)
            if level < args.brightness and now - last_limit_log >= 1.0:
                log(f"  POWER-LIMITED: dimmed to {level:.0%} to stay under {args.max_amps} A", out)
                last_limit_log = now
            out.show(frame, level, args.layout)
            time.sleep(max(0.0, 1.0 / FPS - (time.monotonic() - now)))
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
