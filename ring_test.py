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

--scheme bloody swaps the ripples for Muon Ripple's blood: each drop splats where it
lands (a seeded, lumpy splat with spikes and droplets), spreading from the ripple's
8 mm impact circle in 0.18 s. It's drawn in two colours, a body at drive 31 and a small
highlight at drive 102, and projected onto the grid by area. It holds until 0.45 s, then
fades out as a whole on one smooth curve, gone by 3.05 s. Pure red. Newer splats land on
top of older ones; rare drops splat bigger.

Colours, fades and glitter are worked out in display units and turned into LED drive
levels with a 2.2 gamma, as the Muon Ripple board does, so a ring dims the way it looks
on the simulation page instead of lingering at the bottom of the LEDs' range.

--listen drops nothing on its own: each press of the space bar drops one muon (r drops a
rare one), so a single splat or ripple can be watched on its own. Not in --help: t drops a
blood splat that stops once it has landed; t again fades it out. It picks up
exactly where it stopped, so a jump on a press points at the phase that has it wrong.

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
import struct
import sys
import time

# ---- panel ------------------------------------------------------------------
N = 16                       # 16 x 16 LEDs
CENTRE = (N - 1) / 2         # 7.5: ripples land between the 4 middle LEDs
PITCH = 10.0                 # mm between LEDs
FPS = 60                     # default frames per second (--fps)
PANEL_MAX_FPS = 125          # 256 LEDs x 24 bits at 800 kbit/s is 7.7 ms, plus the 0.3 ms latch
GAMMA = 2.2                  # display units -> LED drive levels (linear light)

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

# ---- blood (Muon Ripple design) -------------------------------------------------------
# The splat is drawn in two colours, then projected onto the 16 x 16 grid: each LED shows
# the area-weighted mix of what falls in its 10 mm cell, in drive levels (linear light).
# Anything on the panel between the two colours is that blending, or spatial aliasing.
#   body       pure red at drive 31
#   highlight  pure red at drive 102, the brightest colour: a small disc a light up and to
#              the north-west would catch on the wet surface
# It lands as the ripple's impact circle and spreads to the full splatter on an ease-out
# (0.18 s), holds until 0.45 s, then the whole splat fades out together, by 3.05 s, on one
# smooth curve that eases out of the hold and eases into black (a smoothstep on perceived
# brightness).
# On the panel the splat is pure red: any green or blue rounds to level 1 on the LEDs and
# reads pink in a dim room.
BLOOD = {"highlight": 102.0, "body": 31.0,   # drive levels, before projection
         "spot": (0.25, 0.3),             # highlight disc: centre towards the light, radius; in splat radii
         "land": 0.18, "wet": 0.45, "fade": 2.6}
BLOOD_IMPACT = 8.0                         # mm
BLOOD_SAMPLES = 3                          # coverage samples per LED cell, each way, for the splat
SPOT_SAMPLES = 6                           # ... and for the highlight disc
BLOOD_END = BLOOD["wet"] + BLOOD["fade"]


def blood_fade(t):
    """Drive multiplier for the whole splat t s after landing: 1 while fresh, then to 0."""
    y = clamp((t - BLOOD["wet"]) / BLOOD["fade"], 0.0, 1.0)
    q = 1 - y * y * (3 - 2 * y)                                  # perceived: smoothstep down
    return q ** GAMMA


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


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


# Level 1 is the LED's dimmest and still shows through the cover, so the curve starts there:
# anything meant to be lit, however faint, gets at least level 1, with the curve spread over
# levels 1 to 255 above it. Only values below DARK (display units) are black.
DARK = 1.0
DARK_DRIVE = 255.0 * (DARK / 255.0) ** GAMMA


def lift(d):
    """Drive level from the plain gamma curve -> drive level starting at the LED's level 1."""
    return 0.0 if d < DARK_DRIVE else 1.0 + d * 254.0 / 255.0


def to_drive(v):
    """Display units (0..255, as the simulation page draws) -> LED drive level (0..255)."""
    return lift(255.0 * clamp(v / 255.0, 0.0, 1.0) ** GAMMA)


def mulberry32(a):
    """Seeded uniform 0..1: a splat keeps its shape."""
    def rand():
        nonlocal a
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = ((a ^ (a >> 15)) * (a | 1)) & 0xFFFFFFFF
        t = ((t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF) ^ t
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    return rand


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


class Splat:
    """A blood splat landing at the panel's centre: a lumpy blob (random harmonics on its
    radius), tapering spikes, droplets at some spike tips and stray satellites, and how
    much of each LED's 10 mm cell it covers. Worked out once, when the drop lands."""

    HARM = (2, 3, 4, 5, 7)

    def __init__(self, seed, energy, hot):
        rand = mulberry32(seed)

        def u(lo, hi):
            return lo + (hi - lo) * rand()
        big = 1.3 if hot else 1.0
        r0 = self.r0 = clamp(15 * math.sqrt(energy / MUON_PEAK), 10, 26) * big
        self.harm = [(k, u(0, 0.3 / math.sqrt(k)), u(0, 2 * math.pi)) for k in self.HARM]
        self.spikes = [(u(0, 2 * math.pi), u(0.08, 0.2) * r0, r0 * u(1.3, 2.7))
                       for _ in range(int(u(5, 11) * big + 0.5))]
        self.drops = []
        for th, _w, length in self.spikes:
            if rand() < 0.5:
                self.drops.append((length * math.cos(th), length * math.sin(th), u(1.5, 3.5)))
        for k in range(int(u(3, 9) * big + 0.5)):     # satellites, mostly along the spikes
            th = self.spikes[k % len(self.spikes)][0] + u(-0.2, 0.2) if rand() < 0.6 else u(0, 2 * math.pi)
            d = r0 * u(1.7, 3.5)
            self.drops.append((d * math.cos(th), d * math.sin(th), u(1.2, 4.5)))
        self.reach = max([r0 * 1.5] + [length for _th, _w, length in self.spikes]
                         + [math.hypot(x, y) + r for x, y, r in self.drops])
        s = BLOOD_SAMPLES
        self.cover = []
        for i, j, dist, _rainbow in LEDS:
            hit = 0
            if dist <= self.reach + PITCH:
                cx, cy = (i - CENTRE) * PITCH, (CENTRE - j) * PITCH
                for a in range(s):
                    for b in range(s):
                        hit += self.inside(cx + ((a + 0.5) / s - 0.5) * PITCH, cy + ((b + 0.5) / s - 0.5) * PITCH)
            self.cover.append(hit / (s * s))
        # The highlight disc's share of each LED's cell (where the splat also is), sampled finely
        # near the disc: before projection the splat is body or highlight, nothing between.
        hx, hy = -BLOOD["spot"][0] * r0 * math.sqrt(0.5), BLOOD["spot"][0] * r0 * math.sqrt(0.5)
        hr = BLOOD["spot"][1] * r0
        q = SPOT_SAMPLES
        self.spot = []
        for i, j, _dist, _rainbow in LEDS:
            cx, cy = (i - CENTRE) * PITCH, (CENTRE - j) * PITCH
            hit = 0
            if math.hypot(cx - hx, cy - hy) <= hr + PITCH:
                for a in range(q):
                    for b in range(q):
                        x, y = cx + ((a + 0.5) / q - 0.5) * PITCH, cy + ((b + 0.5) / q - 0.5) * PITCH
                        hit += math.hypot(x - hx, y - hy) < hr and self.inside(x, y)
            self.spot.append(hit / (q * q))

    def inside(self, dx, dy):
        r, th = math.hypot(dx, dy), math.atan2(dy, dx)
        rb = self.r0 + sum(self.r0 * a * math.cos(k * th + p) for k, a, p in self.harm)
        if r < rb:
            return True
        for sth, w, length in self.spikes:
            if r > length:
                continue
            dth = abs((th - sth + 3 * math.pi) % (2 * math.pi) - math.pi)
            if dth * r < w * (1 - r / length) + 0.4:       # a streak tapering to its tip
                return True
        return any(math.hypot(dx - x, dy - y) < r for x, y, r in self.drops)


class Drop:
    def __init__(self, t0, scheme, energy, stripe, stops=()):
        self.t0, self.scheme, self.e = t0, scheme, energy
        self.stops = list(stops)     # its own clock holds at each of these until released
        self.paused = 0.0            # seconds spent held so far
        self.hot = energy > HOT
        self.shape = "pumpkin" if scheme.startswith("pumpkin") else "soccer" if scheme == "soccer" else None
        # Seeded from the drop itself, not the run's random numbers, so drop timing is unchanged.
        seed = (struct.unpack("<I", struct.pack("<f", energy))[0] * 2654435761) & 0xFFFFFFFF
        self.splat = Splat(seed, energy, self.hot) if scheme == "bloody" else None
        self.life = BLOOD_END if self.splat else LIFE
        # Shapes stop at 1x: above that colours clip (the orange would turn yellow).
        self.amp = min(1.0 if self.shape else 1.6, energy / FULL)
        self.stripe = stripe
        self.replaced_at = None      # shapes: when a newer shape took over
        self.fit = 1.0               # shapes: brightness that keeps the full-size one under the power limit

    def time(self, now):
        """Seconds into its animation: real time since it landed, less time spent held."""
        t = now - self.t0 - self.paused
        return min(t, self.stops[0]) if self.stops else t

    def release(self, now):
        """Play on from the stop it's held at (if it has reached it)."""
        if self.stops and now - self.t0 - self.paused >= self.stops[0]:
            self.paused = now - self.t0 - self.stops.pop(0)

    def held(self, now):
        return bool(self.stops) and now - self.t0 - self.paused >= self.stops[0]

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
    """The panel's light field: active drops plus pride glitter, as Muon Ripple draws them.
    Ripples, glitter and splats are added up in display units and gamma-corrected to LED
    drive levels; overlapping ripples add, and each splat lands on top of what's there.
    Shapes are pixel art drawn straight in drive levels, as before."""

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
        """Returns frame[y][x] = [r, g, b] in LED drive levels (may exceed 255; clipped on output)."""
        dt = 0.0 if self.last is None else min(0.1, now - self.last)
        self.last = now
        disp = [[[0.0, 0.0, 0.0] for _ in range(N)] for _ in range(N)]   # display units
        drive = [[[0.0, 0.0, 0.0] for _ in range(N)] for _ in range(N)]  # shapes, already drive levels
        self.drops = [d for d in self.drops if d.time(now) <= d.life]
        for d in self.drops:                   # oldest first: a newer splat lands on top
            t = d.time(now)
            if d.shape:
                self._shape(drive, d, t, now, dt)
                continue
            if d.splat:
                self._splat(drive, d, t)
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
                p = disp[j][i]
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
            p = disp[j][i]
            for k in range(3):
                p[k] += env * GLITTER["peak"] / 255 * c[k]
        for j in range(N):
            for i in range(N):
                p, q = disp[j][i], drive[j][i]
                for k in range(3):
                    q[k] += to_drive(p[k])
        return drive

    def _splat(self, px, d, t):
        """Lay a blood splat over the frame, in drive levels: it spreads out from the solid
        impact circle on an ease-out, holds fresh, then fades out as a whole. Coverage is a
        share of the cell's area, so it scales the light (drive), not the display value."""
        sp = d.splat
        ease = 1 - (1 - max(0.0, t) / BLOOD["land"]) ** 3 if t < BLOOD["land"] else 1.0
        rho = BLOOD_IMPACT + (sp.reach - BLOOD_IMPACT) * ease
        hi, body, m = BLOOD["highlight"], BLOOD["body"], blood_fade(t)
        for n, (i, j, dist, _rainbow) in enumerate(LEDS):
            a = sp.cover[n]
            if ease < 1:
                a *= clamp((rho - dist) / PITCH + 0.5, 0.0, 1.0)
                a = max(a, clamp(1 - (dist - BLOOD_IMPACT) / PITCH, 0.0, 1.0) * (1 - ease))
            if a <= 0:
                continue
            # the cell's mix of highlight and body, by area (all body where only the impact covers it)
            share = min(1.0, sp.spot[n] / sp.cover[n]) if sp.cover[n] > 0 else 0.0
            drive = (body + (hi - body) * share) * m
            p = px[j][i]
            p[0] = lift(drive * a) + p[0] * (1 - a)       # pure red; faint cells still at least level 1
            p[1] *= 1 - a
            p[2] *= 1 - a

    def _shape(self, px, d, t, now, dt):
        """Add a growing shape in drive levels: each LED shows the average of the art under it."""
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
    """Frame -> GRB byte buffer in data-chain order, each level rounded to the nearest."""
    buf = bytearray(N * N * 3)
    for y in range(N):
        for x in range(N):
            i = 3 * xy_to_index(x, y, layout)
            r, g, b = (min(255, int(min(255.0, c) * level + 0.5)) for c in frame[y][x])
            buf[i], buf[i + 1], buf[i + 2] = g, r, b
    return buf


def snake(rows):
    """LED (x, y) positions of a snake through these rows: along the first, down one, back
    along the next, and so on; the rows between the lit ones are blank but for the turns."""
    path = []
    for k, r in enumerate(rows):
        xs = range(N) if k % 2 == 0 else range(N - 1, -1, -1)
        path += [(x, r) for x in xs]
        if k + 1 < len(rows):
            path += [(path[-1][0], y) for y in range(r + 1, rows[k + 1])]
    return path


GAMMA_TEST_COLOURS = {"red": (1, 0, 0), "green": (0, 1, 0), "blue": (0, 0, 1), "white": (1, 1, 1)}


def gamma_test_frame(colour):
    """Two snakes, 100 % at the head to 0 at the tail: the top one straight in drive levels,
    the bottom one through the display-units-to-drive gamma (perceptually even, if it's right)."""
    frame = [[[0.0, 0.0, 0.0] for _ in range(N)] for _ in range(N)]
    rgb = GAMMA_TEST_COLOURS[colour]
    for path, curve in ((snake([0, 2, 4, 6]), lambda u: 255.0 * u),
                        (snake([8, 10, 12, 14]), lambda u: to_drive(255.0 * u))):
        for k, (x, y) in enumerate(path):
            u = 1 - k / (len(path) - 1)
            frame[y][x] = [c * curve(u) for c in rgb]
    return frame


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
        # Decode the exact bytes the panel would get, so the preview also checks encode(),
        # then undo the gamma: the terminal shows display units, the panel emits linear light.
        buf = encode(frame, level, layout)
        lines = []
        for y in range(N):
            row = []
            for x in range(N):
                i = 3 * xy_to_index(x, y, layout)
                g, r, b = (round(255 * (c / 255) ** (1 / GAMMA)) for c in buf[i:i + 3])
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


class Keys:
    """Single key presses from the terminal, without waiting for Enter (--listen)."""

    def __init__(self):
        import termios
        import tty
        if not sys.stdin.isatty():
            sys.exit("--listen needs a terminal to read the space bar from")
        self._termios, self._fd = termios, sys.stdin.fileno()
        self._saved = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)

    def read(self):
        """Keys pressed since the last call."""
        import select
        keys = ""
        while select.select([sys.stdin], [], [], 0)[0]:
            keys += sys.stdin.read(1)
        return keys

    def close(self):
        self._termios.tcsetattr(self._fd, self._termios.TCSADRAIN, self._saved)


def rare_energy(rng):
    """A muon energy above the rare threshold (for --listen's r key)."""
    for _ in range(10000):
        e = muon_energy(rng)
        if e > HOT:
            return e
    return 1.5 * HOT


def main():
    p = argparse.ArgumentParser(description="Muon-ripple opacity test for a 16x16 NeoPixel panel on a Pi 5.")
    p.add_argument("--rate", type=float, default=0.4,
                   help="average drops per second, at random times (default 0.4 'gallery pace'; 1.7 = sea level)")
    p.add_argument("--scheme", choices=["rotate"] + SCHEME_ORDER + ["bloody", "pumpkin"]
                   + [f"pumpkin-{s}" for s in SCHEME_ORDER] + ["soccer"], default="rotate",
                   help="rotate = warm, cool, pride in turn (default); warm, cool or pride = only that "
                        "scheme's ripples; bloody = blood splats that fade to black; "
                        "pumpkin = orange jack-o'-lanterns; pumpkin-warm, "
                        "pumpkin-cool, pumpkin-pride = jack-o'-lanterns in that scheme's colours; "
                        "soccer = soccer balls")
    p.add_argument("--listen", action="store_true",
                   help="drop nothing on its own: space drops a muon, r a rare one")
    p.add_argument("--brightness", type=float, default=1.0, help="brightness 0..1 (default 1.0)")
    p.add_argument("--fps", type=float, default=FPS,
                   help=f"frames per second (default {FPS}; the panel can take about {PANEL_MAX_FPS})")
    p.add_argument("--duration", type=float, default=0, help="stop after this many seconds (default 0 = run until Ctrl+C)")
    p.add_argument("--pin", type=int, default=18, help="BCM GPIO number of the data line (default 18 = header pin 12)")
    p.add_argument("--max-amps", type=float, default=3.5,
                   help="panel current limit in A; frames are dimmed to stay under it (default 3.5, for a 5 V 4 A supply)")
    p.add_argument("--layout", choices=["serpentine", "progressive"], default="serpentine",
                   help="data-chain wiring of the matrix (default serpentine, as on Adafruit's 16x16)")
    p.add_argument("--seed", type=int, default=None, help="random seed, to repeat the same run of drops")
    p.add_argument("--gamma-test", nargs="?", const="red", choices=sorted(GAMMA_TEST_COLOURS), metavar="COLOUR",
                   help="show two snakes fading from 100 %% at the head to 0 at the tail, the top one "
                        "straight in drive levels, the bottom one through the gamma curve; COLOUR is "
                        "red (default), green, blue or white")
    p.add_argument("--preview", action="store_true", help="draw in the terminal instead of driving the panel")
    args = p.parse_args()

    if args.rate <= 0:
        p.error("--rate must be positive")
    if not 0 < args.brightness <= 1:
        p.error("--brightness must be above 0 and at most 1")
    if not 1 <= args.fps <= 1000:
        p.error("--fps must be between 1 and 1000")
    if args.duration < 0:
        p.error("--duration can't be negative")
    if args.max_amps <= N * N * MA_IDLE_PER_LED / 1000.0:
        p.error(f"--max-amps must be above the panel's idle draw ({N * N * MA_IDLE_PER_LED / 1000.0:.2f} A)")

    rng = random.Random(args.seed)
    out = TerminalPreview() if args.preview else Panel(args.pin)
    field = Ripples(rng, args.brightness, args.max_amps)
    keys = Keys() if args.listen else None
    if args.fps > PANEL_MAX_FPS:
        log(f"note: the panel takes about {1000 / PANEL_MAX_FPS:.0f} ms per frame, so above "
            f"{PANEL_MAX_FPS} fps frames will come out slower than asked", out)
    if keys:
        log("listening: space = drop a muon, r = a rare one, Ctrl+C = quit", out)

    # systemd / kill send SIGTERM; turn it into the same clean exit as Ctrl+C.
    def stop(signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)

    if args.gamma_test:
        frame = gamma_test_frame(args.gamma_test)
        level = args.brightness * power_scale(frame, args.brightness, args.max_amps)
        log(f"gamma test, {args.gamma_test}: top snake straight in drive levels, bottom through "
            f"the gamma {GAMMA}; head at {level:.0%}" + ("" if level >= args.brightness else " (power-limited)")
            + ". Ctrl+C to stop", out)
        start = time.monotonic()
        try:
            while not (args.duration and time.monotonic() - start >= args.duration):
                out.show(frame, level, args.layout)
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            out.off()
            log("panel off", out)
        return

    count = stripe = 0

    stepped = None                   # the t key's splat, while it has stops left

    def drop_one(now, energy, scheme=None, stops=()):
        nonlocal count, stripe
        if scheme is None:
            scheme = SCHEME_ORDER[count % len(SCHEME_ORDER)] if args.scheme == "rotate" else args.scheme
        drop = Drop(now, scheme, energy, stripe % len(PRIDE), stops)
        if scheme in ("pride", "pumpkin-pride"):
            stripe += 1
        field.add(drop)
        count += 1
        kind = "" if scheme in ("pumpkin", "soccer") else ("rare" if drop.hot else "typical")
        fit = f" | fitted to {drop.fit:.0%} for the power limit" if drop.fit < 1 else ""
        bright = "" if drop.splat else f" | brightness x{drop.amp:.2f}"   # a splat's colour is fixed
        log(f"drop {count:4d} | {scheme:13s} | {kind:7s} | {drop.e:5.1f} MeV{bright}{fit}", out)
        return drop

    start = time.monotonic()
    frames = 0
    try:
        next_drop = start            # the first drop lands straight away
        last_limit_log = -1.0
        while True:
            now = time.monotonic()
            if args.duration and now - start >= args.duration:
                break
            if keys:
                for k in keys.read():
                    if k == " ":
                        drop_one(now, muon_energy(rng))
                    elif k in "rR":
                        drop_one(now, rare_energy(rng))
                    elif k in "tT":
                        # Step a blood splat: held once landed, then out.
                        if stepped is not None and stepped.stops:
                            if stepped.held(now):
                                stepped.release(now)
                                log("  t: fading out", out)
                            else:
                                log("  t: still landing", out)
                        else:
                            stepped = drop_one(now, muon_energy(rng), "bloody", (BLOOD["wet"],))
                            log("  t: landed; t again to fade out", out)
            elif now >= next_drop:
                drop_one(now, muon_energy(rng))
                next_drop = now + rng.expovariate(args.rate)
            frame = field.frame(now)
            level = args.brightness * power_scale(frame, args.brightness, args.max_amps)
            # Always applied; only logged when it's a visible (1 %+) dip, at most once a second.
            if level < 0.99 * args.brightness and now - last_limit_log >= 1.0:
                log(f"  POWER-LIMITED: dimmed to {level:.0%} to stay under {args.max_amps} A", out)
                last_limit_log = now
            out.show(frame, level, args.layout)
            frames += 1
            time.sleep(max(0.0, 1.0 / args.fps - (time.monotonic() - now)))
    except KeyboardInterrupt:
        pass
    finally:
        if keys:
            keys.close()
        try:
            out.off()
            ran = time.monotonic() - start
            log(f"panel off | {frames} frames in {ran:.1f} s, {frames / max(ran, 1e-9):.1f} per second", out)
        except Exception as e:  # don't hide the error that got us here
            log(f"could not blank the panel: {e}", out)


if __name__ == "__main__":
    main()
