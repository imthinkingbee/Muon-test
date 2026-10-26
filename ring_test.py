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

--scheme warm, cool or pride runs only that scheme's ripples.

--scheme pumpkin swaps the ripples for Halloween: each drop grows a jack-o'-lantern
from a dot at the centre to full panel size in 0.9 s, holds it, then fades it out.
--scheme pumpkin-warm, pumpkin-cool and pumpkin-pride colour the pumpkin's body like
that scheme's ripples (typical / rare; a rare pride pumpkin is a full rainbow), and
pride pumpkins sparkle like pride ripples.

--scheme soccer grows a white soccer ball with dark pentagon patches the same way.

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

# ---- shapes: pumpkins and the soccer ball --------------------------------------------
# Pixel art on the panel's own 16x16 grid, so at full size every LED is cleanly lit or
# dark. A drop grows the shape from a dot to full size, holds it, then fades it out.
PUMPKIN_ART = [                            # O = body (coloured by the scheme), S = stem
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
SOCCER_ART = [                             # W = white panels; the gaps are the pentagons
    ".....WWWWWW.....",
    "...WWW....WWW...",
    "..WWWWW..WWWWW..",
    ".WWWWWWWWWWWWWW.",
    ".WWWWWWWWWWWWWW.",
    "W..WWWW..WWWW..W",
    "W..WWW....WWW..W",
    "WWWWWW....WWWWWW",
    "WWWWWWWWWWWWWWWW",
    "WWWWWWWWWWWWWWWW",
    "WWWWWWWWWWWWWWWW",
    ".WW..WWWWWW..WW.",
    ".WW...WWWW...WW.",
    "..WWWWWWWWWWWW..",
    "...WWWWWWWWWW...",
    ".....WWWWWW.....",
]
SHAPE_ART = {"pumpkin": PUMPKIN_ART, "soccer": SOCCER_ART}
PUMPKIN_ORANGE = (255, 100, 8)            # body of the plain pumpkin
PUMPKIN_STEM = (40, 150, 20)
SOCCER_WHITE = (235, 235, 235)
SHAPE_GROW = 0.9                           # s, dot -> full size (ease-out)
SHAPE_HOLD = 1.6                           # s, full brightness until here
SHAPE_FADE = 0.25                          # s, fade time constant after the hold
SHAPE_HANDOVER = 0.1                       # s, a shape fades this fast once a new one lands
SHAPE_GLITTER = 0.3                        # pride pumpkins: sparkles per second per fully lit body LED
GLITTER_RESERVE = 0.15                     # share of --max-amps kept free for them (~0.5 A of 3.5 A)


def _summed_area(art, mark):
    """Summed-area table, (N+1) x (N+1), of where `mark` is in the art, for box-filtering it at any size."""
    sat = [[0.0] * (N + 1) for _ in range(N + 1)]
    for j in range(N):
        for i in range(N):
            v = 1.0 if art[j][i] == mark else 0.0
            sat[j + 1][i + 1] = v + sat[j][i + 1] + sat[j + 1][i] - sat[j][i]
    return sat


# Per shape, one table per part of the art ("O" body, "S" stem, "W" white panels).
SHAPE_SAT = {name: {mark: _summed_area(art, mark) for mark in sorted(set("".join(art)) - {"."})}
             for name, art in SHAPE_ART.items()}


def _area(table, x, y):
    """Integral of the art over [0, x] x [0, y] in art pixels (bilinear, so exact for pixel art)."""
    x, y = min(max(x, 0.0), N), min(max(y, 0.0), N)
    i, j = min(int(x), N - 1), min(int(y), N - 1)
    fx, fy = x - i, y - j
    return (table[j][i] * (1 - fx) * (1 - fy) + table[j][i + 1] * fx * (1 - fy)
            + table[j + 1][i] * (1 - fx) * fy + table[j + 1][i + 1] * fx * fy)


def shape_size(t):
    """Shape size 0..1 at t s after the drop: fast at first, settling at full size."""
    x = min(1.0, t / SHAPE_GROW)
    return max(0.02, 1 - (1 - x) ** 3)


def shape_level(t):
    return 1.0 if t < SHAPE_HOLD else math.exp(-(t - SHAPE_HOLD) / SHAPE_FADE)


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
        self.shape = "pumpkin" if scheme.startswith("pumpkin") else "soccer" if scheme == "soccer" else None
        # Shapes stop at 1x: above that colours clip (the orange would turn yellow).
        self.amp = min(1.0 if self.shape else 1.6, energy / FULL)
        self.stripe = stripe
        self.replaced_at = None      # shapes: when a newer shape took over
        self.fit = 1.0               # shapes: brightness that keeps the full-size one under the power limit

    def colour(self, rainbow):
        """Colour of the ripple, or of the pumpkin's body, at an LED with this rainbow hue."""
        if self.scheme == "pumpkin":
            return PUMPKIN_ORANGE
        base = self.scheme.removeprefix("pumpkin-")
        if base == "pride":
            return rainbow if self.hot else PRIDE[self.stripe]
        s = SCHEMES[base]
        return s["hot"] if self.hot else s["typ"]

    def part_colour(self, mark, rainbow):
        """Colour of one part of a shape's art."""
        if mark == "S":
            return PUMPKIN_STEM
        if mark == "W":
            return SOCCER_WHITE
        return self.colour(rainbow)  # "O", the pumpkin's body


class Ripples:
    """The panel's light field: active drops plus pride glitter, as Muon Ripple draws them."""

    def __init__(self, rng, level=1.0, max_amps=None):
        self.rng = rng
        self.level, self.max_amps = level, max_amps
        self.drops = []
        self.sparkles = []       # [led, t0, colour, strength]
        self.last = None

    def add(self, drop):
        if drop.shape:
            # One shape at a time: a new one takes over and the old one fades out quickly,
            # so the new one doesn't grow over the old one and fill in its dark parts.
            for d in self.drops:
                if d.shape and d.replaced_at is None:
                    d.replaced_at = drop.t0
            # Fix its brightness up front so the full-size shape fits the power limit; it then
            # grows at one steady brightness instead of dimming as it fills the panel.
            if self.max_amps is not None:
                art = SHAPE_ART[drop.shape]
                full = [[(0.0, 0.0, 0.0)] * N for _ in range(N)]
                for i, j, _dist, rainbow in LEDS:
                    if art[j][i] != ".":
                        full[j][i] = tuple(drop.amp * c for c in drop.part_colour(art[j][i], rainbow))
                keep = 1 - GLITTER_RESERVE if drop.scheme == "pumpkin-pride" else 1.0
                drop.fit = power_scale(full, self.level, self.max_amps * keep)
        self.drops.append(drop)

    def frame(self, now):
        """Returns frame[y][x] = [r, g, b] (may exceed 255; clipped on output)."""
        dt = 0.0 if self.last is None else min(0.1, now - self.last)
        self.last = now
        px = [[[0.0, 0.0, 0.0] for _ in range(N)] for _ in range(N)]
        self.drops = [d for d in self.drops if now - d.t0 <= LIFE]
        for d in self.drops:
            t = now - d.t0
            if d.shape:
                self._shape(px, d, t, now, dt)
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

    def _shape(self, px, d, t, now, dt):
        """Add a growing shape: each LED shows the average of the art under it."""
        level = shape_level(t)
        if d.replaced_at is not None:
            level *= math.exp(-max(0.0, now - d.replaced_at) / SHAPE_HANDOVER)
        v = d.amp * d.fit * level
        size = shape_size(t)
        h = 0.5 / size                     # half an LED, in art pixels

        def cover(s, x, y):                # fraction of the LED's footprint the art covers
            return (_area(s, x + h, y + h) - _area(s, x - h, y + h)
                    - _area(s, x + h, y - h) + _area(s, x - h, y - h)) / (4 * h * h)

        glitter = d.scheme == "pumpkin-pride"
        for n, (i, j, _dist, rainbow) in enumerate(LEDS):
            x = N / 2 + (i + 0.5 - N / 2) / size
            y = N / 2 + (j + 0.5 - N / 2) / size
            p = px[j][i]
            for mark, table in SHAPE_SAT[d.shape].items():
                f = cover(table, x, y)
                if f <= 1e-9:
                    continue
                col = d.part_colour(mark, rainbow)
                for c in range(3):
                    p[c] += v * f * col[c]
                # Pride pumpkins sparkle like pride ripples: white with a touch of the body colour.
                if (glitter and mark == "O" and
                        self.rng.random() < SHAPE_GLITTER * (1.5 if d.hot else 1) * d.amp * level * f * dt):
                    c = tuple((1 - GLITTER["tint"]) * 245 + GLITTER["tint"] * ch for ch in col)
                    # Dimmed with the pumpkin's power fit, so they stay in proportion to its body.
                    self.sparkles.append([n, now, c, (0.6 + 0.4 * self.rng.random()) * d.fit])


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
    if amps <= max_amps + 1e-6:            # tolerance: float rounding isn't a real overload
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
    p.add_argument("--scheme", choices=["rotate"] + SCHEME_ORDER + ["pumpkin"]
                   + [f"pumpkin-{s}" for s in SCHEME_ORDER] + ["soccer"], default="rotate",
                   help="rotate = warm, cool, pride in turn (default); warm, cool or pride = only that "
                        "scheme's ripples; pumpkin = orange jack-o'-lanterns; pumpkin-warm, "
                        "pumpkin-cool, pumpkin-pride = jack-o'-lanterns in that scheme's colours; "
                        "soccer = soccer balls")
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
    field = Ripples(rng, args.brightness, args.max_amps)

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
                if args.scheme == "rotate":
                    scheme = SCHEME_ORDER[count % len(SCHEME_ORDER)]
                else:
                    scheme = args.scheme
                drop = Drop(now, scheme, muon_energy(rng), stripe % len(PRIDE))
                if scheme in ("pride", "pumpkin-pride"):
                    stripe += 1
                field.add(drop)
                count += 1
                kind = "" if scheme in ("pumpkin", "soccer") else ("rare" if drop.hot else "typical")
                fit = f" | fitted to {drop.fit:.0%} for the power limit" if drop.fit < 1 else ""
                log(f"drop {count:4d} | {scheme:13s} | {kind:7s} | "
                    f"{drop.e:5.1f} MeV | brightness x{drop.amp:.2f}{fit}", out)
                next_drop = now + rng.expovariate(args.rate)
            frame = field.frame(now)
            level = args.brightness * power_scale(frame, args.brightness, args.max_amps)
            # Always applied; only logged when it's a visible (1 %+) dip, at most once a second.
            if level < 0.99 * args.brightness and now - last_limit_log >= 1.0:
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
