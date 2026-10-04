# heimdall-module

ESP32-C3 based module for the transmitter's JR module bay, part of the Heimdall Suite.

## Status

Hardware rev 2 (KiCad 10, `hardware/kicad/`): schematic reviewed and corrected,
board re-placed and re-routed from the first EasyEDA layout. Not built or tested
yet. The EasyEDA originals are kept in `hardware/easyeda-archive/`. No firmware yet.

## Pin assignment (rev 2)

| Function | ESP32-C3 GPIO | Via |
|---|---|---|
| Bay SIGNAL (H1 pin 1) | IO4 | R5 220R |
| Bay HB (H1 pin 2) | IO6 | R7 220R |
| Bay DATA (H1 pin 5) | IO5 | R6 220R |
| I2C SDA / SCL (J2, 10k pull-ups) | GPIO20 / GPIO21 (U0RXD / U0TXD) | |
| Breakout (J2) | IO3, IO7, IO10 | |
| USB D- / D+ | IO18 / IO19 | R4 / R3 33R |
| Strapping | IO2, IO8, IO9 pulled up 10k; JP1 BOOT bridges IO9 to GND | |

IO0 and IO1 are unused. UART0's pins carry I2C, so the console has to run over
USB-Serial/JTAG.
