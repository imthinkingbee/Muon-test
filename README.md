# Muon-test: LED cover opacity test

`ring_test.py` cycles the muon detector's 16×16 NeoPixel panel through concentric-ring
patterns so a 3D-printed cover can be judged for opacity and diffusion:

- Do single LEDs show through as hotspots?
- Do neighbouring rings stay distinguishable, or do they blur together?
- How much light gets through at lower brightness?
- Does the expanding ripple still read clearly through the cover?

Colours and the ripple animation come from the **Muon Ripple** panel design:

| Scheme | Typical | Rare |
|---|---|---|
| warm | `#dfe9ff` | `#ffb04a` |
| cool | `#6fd8ff` | `#b996ff` |
| pride | one stripe per ring: `#ff3b3b` `#ff9a1f` `#ffe733` `#2fd16a` `#3d7bff` `#b05cff` | |

The design's fourth scheme, "bloody", is a splatter, not rings, so it's left out.

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

## Pi 5 setup (one time)

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
     echo 'SUBSYSTEM=="*-pio", GROUP="gpio", MODE="0660"' | sudo tee -a /etc/udev/rules.d/99-com.rules
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
source .venv/bin/activate
python3 ring_test.py
```

The script loops until **Ctrl+C**, which turns the panel off. Each configuration is printed
with its number, so you can write down how the cover looked for each one.

| Option | Default | What it does |
|---|---|---|
| `--hold SECONDS` | `8` | how long each configuration stays up |
| `--start N` | `1` | start at configuration *N* (see `--list`) |
| `--once` | off | run through the sequence once, then stop |
| `--list` | | print all 42 configurations and exit |
| `--max-amps A` | `3.5` | panel current limit (see below) |
| `--pin N` | `18` | BCM GPIO number of the data line |
| `--layout` | `serpentine` | `progressive` if your panel's rows all run the same way |
| `--preview` | off | draw the panel in the terminal instead of driving LEDs. Works on any computer. |

Examples:

```bash
python3 ring_test.py --list                 # see the sequence
python3 ring_test.py --hold 15              # more time to look at each configuration
python3 ring_test.py --start 37             # jump straight to the ripples
python3 ring_test.py --preview --hold 2     # try it out without the panel
```

## The sequence (42 configurations)

Static rings, each in warm, cool and pride, at 100 %, 50 % and 25 % brightness:

| # | Pattern | What it tests |
|---|---|---|
| 1–9 | thin rings, 1 on / 1 off | can the cover separate rings one LED apart? |
| 10–18 | thin rings, 1 on / 2 off | single-LED rings with wider gaps: hotspots |
| 19–27 | thick rings, 2 on / 2 off | two-LED rings: does each ring look even? |
| 28–36 | solid, every ring lit | overall uniformity and colour bleed between rings |
| 37–42 | expanding ripple, 100 % and 25 % | motion through the cover (Muon Ripple's speed, width and fade) |

Warm and cool rings alternate the typical and rare colours, so both are on screen together.

### Brightness and the power limit

At full white, 256 NeoPixels can draw around 15 A, and a 4 A supply can't deliver that. The
script estimates each frame's current conservatively (20 mA per colour channel at full,
1 mA idle per LED). If a frame would go over `--max-amps` (3.5 A, leaving headroom on a
4 A supply), it dims that frame just enough to fit, and the log says so:

```
[1/42] thin rings, 1 on / 1 off | warm | 100%  (adjacent rings separated by one dark ring)
  ~3.50 A  POWER-LIMITED: shown at 56% instead of 100%
```

So dense patterns at "100 %" actually run at the brightest level the supply can handle. Solid
warm/cool rings at 100 % and 50 % both come out around 27 %, so those two slots look the same.
The ripples stay under 1.5 A and are never dimmed. If you use a bigger supply, raise
`--max-amps` to about 90 % of its rating.

## Notes

- The rings are centred between the four middle LEDs and are mirror-symmetric, so they look
  the same whichever corner the data enters and whichever way the rows run.
- Adafruit's Pi 5 NeoPixel examples use `byteorder="BGR"`. The driver sends bytes in buffer
  order, so for standard GRB NeoPixels that swaps red and blue. Their rainbow demos hide it.
  This script writes GRB directly.
