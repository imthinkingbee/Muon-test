# Muon-test: LED cover opacity test

`ring_test.py` lights the muon detector's 16×16 NeoPixel panel **one concentric ring at a
time**, stepping from the centre out to the corners every **0.75 s**, so a 3D-printed cover
can be judged for opacity and diffusion:

- Do single LEDs show through as hotspots?
- How far does one ring's light spread under the cover?
- Does one lit ring still read as one clean ring?

Colours come from the **Muon Ripple** panel design:

| Scheme | Typical | Rare |
|---|---|---|
| warm | `#dfe9ff` | `#ffb04a` |
| cool | `#6fd8ff` | `#b996ff` |
| pride | one stripe per ring: `#ff3b3b` `#ff9a1f` `#ffe733` `#2fd16a` `#3d7bff` `#b05cff` | |

Warm and cool rings alternate the typical and rare colours from one ring to the next. The
design's fourth scheme, "bloody", is a splatter, not rings, so it's left out.

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

Anything after `./quickstart.sh` is passed to the test, e.g. `./quickstart.sh --hold 2` or
`./quickstart.sh --start 23`. Use `./quickstart.sh --setup-only` to set up without running.

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

The script loops until **Ctrl+C**, which turns the panel off. Each step is printed with its
number, so you can write down how the cover looked for each ring.

| Option | Default | What it does |
|---|---|---|
| `--hold SECONDS` | `0.75` | how long each ring stays lit |
| `--brightness B` | `1.0` | brightness from 0 to 1 (e.g. `0.25`) |
| `--start N` | `1` | start at step *N* (see `--list`) |
| `--once` | off | run through the sequence once, then stop |
| `--list` | | print all 33 steps and exit |
| `--max-amps A` | `3.5` | panel current limit (see below) |
| `--pin N` | `18` | BCM GPIO number of the data line |
| `--layout` | `serpentine` | `progressive` if your panel's rows all run the same way |
| `--preview` | off | draw the panel in the terminal instead of driving LEDs. Works on any computer. |

Examples:

```bash
python3 ring_test.py --list                 # see the sequence
python3 ring_test.py --hold 3               # more time to look at each ring
python3 ring_test.py --start 23             # jump straight to the pride sweep
python3 ring_test.py --brightness 0.25      # dimmer, to see when light stops getting through
python3 ring_test.py --preview              # try it out without the panel
```

## The sequence (33 steps, about 25 s per loop)

One ring lit at a time, centre outwards, one full sweep per colour scheme:

| # | Scheme |
|---|---|
| 1–11 | warm, rings 0 → 10 |
| 12–22 | cool, rings 0 → 10 |
| 23–33 | pride, rings 0 → 10 |

Ring 0 is the middle 4 LEDs. The rings grow outwards, and rings 8–10 are cut off by the
panel's square edge, so they show up as arcs near the corners. Ring 10 is just the 4 corner
LEDs.

| Ring | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| LEDs | 4 | 8 | 20 | 20 | 28 | 32 | 44 | 52 | 24 | 20 | 4 |

The timing is held on a fixed schedule, so each ring really gets 0.75 s however long the
frame took to send.

### Brightness and the power limit

At full white, 256 NeoPixels can draw around 15 A, and a 4 A supply can't deliver that. The
script estimates each frame's current conservatively (20 mA per colour channel at full,
1 mA idle per LED), and if a frame would go over `--max-amps` (3.5 A, leaving headroom on a
4 A supply) it dims that frame just enough to fit and logs `POWER-LIMITED`.

With one ring at a time this never actually triggers. The biggest ring (ring 7, 52 LEDs)
comes to about 2.7 A at full brightness. The limit is there as a safety net. If you use a
bigger supply, raise `--max-amps` to about 90 % of its rating.

## Notes

- The rings are centred between the four middle LEDs and are mirror-symmetric, so they look
  the same whichever corner the data enters and whichever way the rows run.
- Adafruit's Pi 5 NeoPixel examples use `byteorder="BGR"`. The driver sends bytes in buffer
  order, so for standard GRB NeoPixels that swaps red and blue. Their rainbow demos hide it.
  This script writes GRB directly.
