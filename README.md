# Muon-test: LED cover opacity test

`ring_test.py` drops **muon ripples** into the centre of the muon detector's 16×16 NeoPixel
panel, animated exactly like the **Muon Ripple** artifact: a bright splash where the drop
lands, then a ring that spreads out and fades, like a drop in a lake. It's for judging a
3D-printed cover's opacity and diffusion with the real animation behind it:

- Do single LEDs show through as hotspots?
- Does the moving ring stay crisp, or smear into a glow?
- Do the dim tail of the ring and the fade-out still show through?

![ripples](docs/ripples.gif)

Every drop works the way it does in Muon Ripple:

- **Timing:** drops arrive at random times, 0.4 per second on average ("gallery pace").
  `--rate 1.7` gives the real sea-level muon rate.
- **Animation:** the ring spreads at 90 mm/s (9 LEDs per second), is 11 mm wide, and fades
  over about 1.6 s. It reaches the corners in about 1.2 s. The splash at the centre dies away
  in about 0.25 s.
- **Brightness and colour:** each drop gets a simulated muon energy. Most are 6–15 MeV, about
  9 MeV typical, and that sets how bright the drop is. About 7 % of drops are over 15.5 MeV
  and get the scheme's **rare** colour.

By default the colour scheme changes on **every drop**: warm → cool → pride → warm … To run
just one scheme, use `--scheme warm`, `--scheme cool` or `--scheme pride`.

| Scheme | Typical | Rare |
|---|---|---|
| warm | `#dfe9ff` | `#ffb04a` |
| cool | `#6fd8ff` | `#b996ff` |
| pride | the next stripe: `#ff3b3b` `#ff9a1f` `#ffe733` `#2fd16a` `#3d7bff` `#b05cff` | a full rainbow round the ring |

Pride ripples also throw off white glitter where the ring passes, as in the artifact. The
artifact's fourth scheme, "bloody", is a splatter, not a ripple, so it's left out.

### 🎃 Halloween: `--scheme pumpkin`

```bash
./quickstart.sh --scheme pumpkin
```

Every drop grows a **jack-o'-lantern** instead of a ripple. It starts as a small orange glow
at the centre, grows to fill the panel in 0.9 s, holds until 1.6 s, then fades out. Drops
keep the same random timing as the ripples. The pumpkin is drawn LED-for-LED on the 16×16
grid, so at full size every LED is cleanly lit (orange body, green stem) or dark (carved
eyes and grin).

![pumpkin](docs/pumpkin.gif)

- Only one pumpkin shows at a time. When a new one lands, the old one fades out in about
  0.1 s, so the new pumpkin never grows over the old face and fills it in.
- Each pumpkin's brightness still comes from its muon energy, but it's capped at 1×.
  Brighter than that, the red channel clips and the orange turns yellow. Most drops land
  at full brightness.
- At full size a pumpkin draws about 4 A, so on a 4 A supply it's shown at about 86 % and
  the log says `POWER-LIMITED` while it's held.

## Hardware

- Raspberry Pi 5
- Adafruit 16×16 NeoPixel matrix (WS2812B, GRB colour order, serpentine wiring)
- A separate **5 V 4 A** supply for the panel

| Panel wire | Connect to |
|---|---|
| DIN (data in) | Pi **GPIO18**, header **pin 12** |
| GND | 5 V supply **−** *and* a Pi GND pin (e.g. pin 6). The grounds **must** be shared. |
| 5V | 5 V supply **+**. **Not** the Pi's 5 V pin. |

Adafruit's recommended extras for a reliable panel:

- a 300–500 Ω resistor in series on the data line, close to the panel's DIN
- a 1000 µF capacitor across the panel's 5 V and GND
- a 74AHCT125 level shifter between GPIO18 and DIN. The Pi's data line is 3.3 V, while
  the panel at 5 V expects about 3.5 V as a logic high. It usually works without one,
  but if the panel flickers or shows wrong colours, add the level shifter first.

Power the Pi from its own USB-C supply.

## Quickstart

On the Pi, as your normal user (not `sudo`):

```bash
git clone https://github.com/imthinkingbee/Muon-test.git
cd Muon-test
./quickstart.sh
```

`quickstart.sh` checks and sets up everything below, then starts the test. It's safe to run
again: finished steps are skipped, so after the first time it goes straight to the test. It
asks before anything big, and uses `sudo` only for system changes.

1. Checks it's on a Raspberry Pi 5 with Python 3.11 or newer.
2. If `/dev/pio0` is missing, offers to update the OS, then asks you to reboot.
3. If you can't use `/dev/pio0`, adds a udev rule (`/etc/udev/rules.d/99-muon-pio.rules`) and
   puts you in the `gpio` group. You may need one reboot after this.
4. Creates the `.venv` virtual environment and installs the LED driver.
5. Runs `ring_test.py`.

If it stops and says reboot, reboot and run `./quickstart.sh` again.

Anything after `./quickstart.sh` is passed to the test, e.g. `./quickstart.sh --rate 1.7` or
`./quickstart.sh --brightness 0.25`. Use `./quickstart.sh --setup-only` to set up without running.

## Pi 5 setup by hand (what quickstart.sh does)

The Pi 5 can't use the old `rpi_ws281x` NeoPixel driver. This script uses Adafruit's Pi 5
driver instead, which drives the LEDs with the RP1 chip's PIO block.

1. Update the OS so the kernel and firmware have PIO support:
   ```bash
   sudo apt update && sudo apt full-upgrade -y
   sudo reboot
   ```
2. Check that the PIO device exists:
   ```bash
   ls -l /dev/pio0
   ```
   - If it's **not found**, the firmware or kernel is too old. Update again (step 1).
   - If it's owned by `root root`, let the `gpio` group use it, so the script doesn't need `sudo`:
     ```bash
     echo 'SUBSYSTEM=="*-pio", GROUP="gpio", MODE="0660"' | sudo tee /etc/udev/rules.d/99-muon-pio.rules
     sudo reboot
     ```
     Your user must be in the `gpio` group (the default user is). Check with `groups`.
3. Get the code and install the driver in a virtual environment. Raspberry Pi OS won't let
   you `pip install` into the system Python.
   ```bash
   git clone https://github.com/imthinkingbee/Muon-test.git
   cd Muon-test
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

## Running

```bash
cd Muon-test
./quickstart.sh
```

or, after setup, directly:

```bash
cd Muon-test
source .venv/bin/activate
python3 ring_test.py
```

The script runs until **Ctrl+C**, which turns the panel off. Each drop is logged as it lands,
so you can match what you saw through the cover to the drop:

```
drop    1 | warm    | typical |   9.0 MeV | brightness x1.16
drop    2 | cool    | typical |   6.8 MeV | brightness x0.88
drop    3 | pride   | rare    |  17.2 MeV | brightness x1.60
```

| Option | Default | What it does |
|---|---|---|
| `--scheme S` | `rotate` | `rotate` = warm, cool, pride in turn. `warm`, `cool` or `pride` = only that scheme's ripples. `pumpkin` = only jack-o'-lanterns. |
| `--rate R` | `0.4` | average drops per second, at random times. `1.7` = sea level. |
| `--brightness B` | `1.0` | overall brightness from 0 to 1 (e.g. `0.25`) |
| `--duration S` | `0` | stop after *S* seconds (`0` = run until Ctrl+C) |
| `--seed N` | random | repeat exactly the same run of drops (handy for comparing two covers) |
| `--max-amps A` | `3.5` | panel current limit (see below) |
| `--pin N` | `18` | BCM GPIO number of the data line |
| `--layout` | `serpentine` | `progressive` if your panel's rows all run the same way |
| `--preview` | off | draw the panel in the terminal instead of driving LEDs. Works on any computer. |

Examples:

```bash
python3 ring_test.py --rate 1.7             # real sea-level muon rate
python3 ring_test.py --scheme cool          # only cool ripples (also: warm, pride)
python3 ring_test.py --scheme pumpkin       # jack-o'-lanterns 🎃
python3 ring_test.py --brightness 0.25      # dimmer, to see when light stops getting through
python3 ring_test.py --seed 42              # same drops every time: swap covers and compare
python3 ring_test.py --preview              # try it out without the panel
```

### Brightness and the power limit

At full white, 256 NeoPixels can draw around 15 A, and a 4 A supply can't deliver that. The
script estimates each frame's current conservatively (20 mA per colour channel at full,
1 mA idle per LED), and if a frame would go over `--max-amps` (3.5 A, leaving headroom on a
4 A supply) it dims that frame just enough to fit and logs `POWER-LIMITED` (at most once a
second).

- At the default 0.4 drops/s this almost never happens: under 1 % of frames, when two bright
  drops overlap, and only briefly.
- At `--rate 1.7`, drops overlap more and about 1 frame in 7 gets dimmed a little.
- With `--scheme pumpkin`, every pumpkin is dimmed to about 86 % while it's at full size
  (about a quarter of the time). It never goes lower than that.

If you use a bigger supply, raise `--max-amps` to about 90 % of its rating.

## Notes

- The ripples land between the four middle LEDs and spread symmetrically, so they look the
  same whichever corner the data enters and whichever way the rows run. (In the artifact, a
  drop lands wherever the muon hit. Here every drop lands in the centre.)
- Frames are sent at about 50 per second, and each one takes a few milliseconds to work out.
- Adafruit's Pi 5 NeoPixel examples use `byteorder="BGR"`. The driver sends bytes in buffer
  order, so for standard GRB NeoPixels that swaps red and blue. Their rainbow demos hide it.
  This script writes GRB directly.
