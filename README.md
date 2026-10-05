# heimdall-module

ESP32-C3 based module for the transmitter's JR module bay, part of the Heimdall Suite.

## Status

Hardware rev 2 (KiCad 10, `hardware/kicad/`): schematic reviewed and corrected,
board re-placed and re-routed from the first EasyEDA layout. Not built or tested
yet. The EasyEDA originals are kept in `hardware/easyeda-archive/`. No firmware yet.

## Pin assignment (rev 2)

| Function | ESP32-C3 GPIO | Via |
|---|---|---|
| Bay SIGNAL / PPM (H1 pin 1), input | IO4 | D3, R14 4.7k pull-up |
| Bay DATA / S.Port (H1 pin 5), receive | IO5 | D4, R16 4.7k pull-up |
| Bay DATA / S.Port (H1 pin 5), transmit | IO6 | D5 (pull low only) |
| Bay HB (H1 pin 2), output | IO7 | D6 (pull low only) |
| I2C SDA / SCL (J2, 10k pull-ups) | GPIO20 / GPIO21 (U0RXD / U0TXD) | |
| Breakout (J2) | IO1, IO3, IO10 | |
| USB D- / D+ | IO18 / IO19 | R4 / R3 33R |
| Strapping | IO2, IO8, IO9 pulled up 10k; JP1 BOOT bridges IO9 to GND | |

IO0 is unused. UART0's pins carry I2C, so the console has to run over
USB-Serial/JTAG.

## Bay interface

The bay lines never connect straight to the ESP32. Each one goes through a
BAT54WS Schottky diode, the same scheme as the DIY Multiprotocol module
(STM32 board v1.0t, BAT48 diodes):

- Toward the module (SIGNAL, DATA receive), the diode's cathode faces the bay.
  The radio can only pull the line low. The high level comes from our own 3V3
  pull-up (R14, R16), so a radio that drives 5 V never reaches the ESP32.
- Toward the radio (DATA transmit, HB), the diode's anode faces the bay. The
  ESP32 can only pull the line low. The high level comes from the pull-ups
  on the bay side: R17 (1.5k) on DATA, R15 (4.7k) on HB.

DATA is half duplex on one wire, with separate receive and transmit pins
(IO5/IO6). The receive pin also sees the module's own transmitted bytes, so
firmware has to discard that echo. R17 was chosen for fast enough rising edges
at 400 kbaud CRSF. This is calculated, not measured yet. Inversion, where a protocol needs it, is done in the
ESP32-C3's UART, not in hardware.
