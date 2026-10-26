#!/usr/bin/env bash
# One-command setup + run for the LED cover opacity test on a Raspberry Pi 5.
#
#   ./quickstart.sh                 set up anything missing, then run the test
#   ./quickstart.sh --hold 15       anything after the script name goes to ring_test.py
#   ./quickstart.sh --setup-only    set up, don't run
#
# Safe to run again: each step is skipped once it's done. It asks before
# anything big (OS upgrade, reboot) and uses sudo only for system changes.

set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

VENV=.venv
UDEV_RULE=/etc/udev/rules.d/99-muon-pio.rules
PIO=/dev/pio0

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
ok()   { printf '    ok: %s\n' "$*"; }
die()  { printf '\n\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }
ask() {  # y/N question on the terminal; "no" when there's no terminal to ask on
    local reply
    if ! { exec 3</dev/tty; } 2>/dev/null; then
        echo "    ($1 No terminal to answer on, so: no.)"
        return 1
    fi
    read -r -p "    $1 [y/N] " reply <&3 || reply=
    exec 3<&-
    [[ $reply =~ ^[Yy]$ ]]
}

setup_only=0
if [[ ${1:-} == --setup-only ]]; then
    setup_only=1
    shift
fi

if (( EUID == 0 )); then
    die "Run this as your normal user, not with sudo (it asks for sudo itself when needed)."
fi

# ---- 1. right hardware -----------------------------------------------------------
say "Checking this is a Raspberry Pi 5"
model=$(tr -d '\0' 2>/dev/null </proc/device-tree/model || true)
if [[ $model != *"Raspberry Pi 5"* ]]; then
    die "This needs a Raspberry Pi 5 (found: '${model:-unknown}').
       To see the patterns on any other computer, run:  python3 ring_test.py --preview"
fi
ok "$model"

# ---- 2. Python 3.11+ with venv ---------------------------------------------------
say "Checking Python"
command -v python3 >/dev/null || die "python3 not found. Install it with:  sudo apt install python3"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' \
    || die "Python 3.11 or newer is needed (found $(python3 -V 2>&1)). Use Raspberry Pi OS Bookworm or later."
ok "$(python3 -V)"
if ! python3 -c 'import venv, ensurepip' 2>/dev/null; then
    echo "    python3-venv is missing; installing it (needs sudo)"
    sudo apt-get update
    sudo apt-get install -y python3-venv
fi

# ---- 3. PIO device (kernel/firmware support for the Pi 5 LED driver) -------------
say "Checking for $PIO (Pi 5 PIO support)"
if [[ ! -e $PIO ]]; then
    echo "    $PIO is missing, so the OS is too old for the Pi 5 NeoPixel driver."
    echo "    Fix: update the OS and reboot (this can take a while)."
    if ask "Run 'sudo apt update && sudo apt full-upgrade -y' now?"; then
        sudo apt-get update
        sudo apt-get full-upgrade -y
        echo
        echo "    Update done. Reboot, then run ./quickstart.sh again."
        if ask "Reboot now?"; then sudo reboot; fi
        exit 0
    fi
    die "$PIO is still missing. Update the OS, reboot, and run ./quickstart.sh again."
fi
ok "$PIO exists"

# ---- 4. permission to use the PIO device without sudo ----------------------------
say "Checking permission to use $PIO"
if [[ -r $PIO && -w $PIO ]]; then
    ok "you can use $PIO"
else
    if [[ ! -f $UDEV_RULE ]]; then
        echo "    Adding a udev rule so the 'gpio' group can use $PIO (needs sudo)"
        echo 'SUBSYSTEM=="*-pio", GROUP="gpio", MODE="0660"' | sudo tee "$UDEV_RULE" >/dev/null
        sudo udevadm control --reload-rules
        sudo udevadm trigger
        sudo udevadm settle || true
    fi
    if [[ " $(id -nG) " != *" gpio "* ]]; then
        echo "    Adding $(id -un) to the 'gpio' group (needs sudo)"
        sudo usermod -aG gpio "$(id -un)"
        echo
        echo "    Group changes take effect after you log in again. Reboot, then run ./quickstart.sh again."
        if ask "Reboot now?"; then sudo reboot; fi
        exit 0
    fi
    if [[ -r $PIO && -w $PIO ]]; then
        ok "you can use $PIO"
    else
        echo
        echo "    The rule is in place, but it only applies after a reboot. Reboot, then run ./quickstart.sh again."
        if ask "Reboot now?"; then sudo reboot; fi
        exit 0
    fi
fi

# ---- 5. virtual environment + LED driver -----------------------------------------
say "Setting up the Python environment ($VENV)"
if [[ ! -x $VENV/bin/python ]]; then
    python3 -m venv "$VENV"
    ok "created $VENV"
fi
if "$VENV/bin/python" -c 'import adafruit_raspberry_pi5_neopixel_write' 2>/dev/null; then
    ok "LED driver already installed"
else
    "$VENV/bin/python" -m pip install -r requirements.txt \
        || die "pip couldn't install the LED driver. Check the Pi's internet connection and try again."
    "$VENV/bin/python" -c 'import adafruit_raspberry_pi5_neopixel_write' \
        || die "The LED driver installed but won't import. See the pip output above."
    ok "LED driver installed"
fi

# ---- 6. run ----------------------------------------------------------------------
if (( setup_only )); then
    say "Setup complete. Run the test with:  ./quickstart.sh"
    exit 0
fi

say "Starting the ring test (Ctrl+C to stop and turn the panel off)"
echo "    Check first: panel on its own 5 V supply, grounds shared, data on GPIO18 (pin 12)."
exec "$VENV/bin/python" ring_test.py "$@"
