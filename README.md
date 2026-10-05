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
| Bay DATA / S.Port (H1 pin 5), transmit | IO7 | U5 74LVC1G34 + R17 1k |
| Bay HB (H1 pin 2), output | IO8 | D6 (pull low only), R12 doubles as its pull-up |
| I2C SDA / SCL (J2, 10k pull-ups) | GPIO20 / GPIO21 (U0RXD / U0TXD) | |
| Breakout (J2) | IO1, IO3, IO10 | |
| USB D- / D+ | IO18 / IO19 | R4 / R3 33R |
| Strapping | IO2, IO8 (HB), IO9 pulled up 10k; JP1 BOOT bridges IO9 to GND | |

IO0 and IO6 are unused. UART0's pins carry I2C, so the console has to run over
USB-Serial/JTAG.

## Bay interface

The bay lines never connect straight to the ESP32.

- SIGNAL (PPM in) and DATA receive go through a BAT54WS Schottky with its
  cathode at the bay, the same scheme as the DIY Multiprotocol module (STM32
  board v1.0t, BAT48 diodes). The radio can only pull the line low; the high
  level comes from our 3V3 pull-ups (R14, R16), so a radio that drives 5 V
  never reaches the ESP32.
- HB (out) goes through a Schottky with its anode at the bay: the ESP32 can
  only pull it low, R15 (4.7k) pulls it high on the bay side.
- DATA transmit goes through U5, a 74LVC1G34 buffer (5.5 V tolerant, always on),
  and R17 (1k). The UART's idle level holds the line, so the same hardware
  works for CRSF (idle high) and inverted S.Port (idle low); which one is a
  firmware setting. When the radio transmits it overrides the 1k (about
  3.3 mA). Against a 10k pull-up on the radio side, an S.Port idle low sits at
  about 0.3 V (calculated, not measured).

DATA is half duplex on one wire, with separate receive and transmit pins
(IO5/IO7). The receive pin also sees the module's own transmitted bytes, so
firmware has to discard that echo. Inversion is done in the ESP32-C3's UART.
Use IO8 (HB) as an output only after boot: it is a strapping pin, which is
safe here because download mode needs USB, and USB and the bay can't be
connected at the same time.
