# ADS1299 16ch Native GUI Notes

This source tree is based on OpenBCI GUI `v5.2.2` with a local ADS1299 TCP data source added.

## Run From Processing

Use Processing `3.5.4` or `3.5.3`.

1. Open `OpenBCI_GUI/OpenBCI_GUI.pde`.
2. Run the sketch.
3. In `DATA SOURCE`, choose `ADS1299 16ch (WiFi TCP)`.
4. Keep `LISTEN PORT` at `1234`, or choose another free TCP port.
5. Choose the board sample rate: `250Hz`, `500Hz`, or `1000Hz`.
6. Click `START SESSION`, then start the data stream from the top navigation.

The GUI listens on `0.0.0.0:<LISTEN PORT>`. The ADS1299 board must be configured to connect to this computer.

## Board WiFi STA Config

Use the board serial config mode and send one command per line:

```text
AT+NAME=your_2G_wifi_ssid
AT+PSWD=your_wifi_password
AT+IP=your_computer_ipv4
AT+PORT=1234
AT+SETOVER
```

The port must match the GUI `LISTEN PORT`. The selected GUI sample rate should match the rate encoded by the incoming board frames.

## Local Fake Sender

After starting an ADS1299 GUI session, run:

```powershell
python tools\ads129x_fake_sender.py --host 127.0.0.1 --port 1234 --rate 250 --duration 30
```

Useful fault-injection options:

```powershell
python tools\ads129x_fake_sender.py --host 127.0.0.1 --port 1234 --rate 250 --sequence-gap-after 20
python tools\ads129x_fake_sender.py --host 127.0.0.1 --port 1234 --rate 250 --bad-checksum-every 10
```

## Data Layout

The native ADS1299 board exposes 21 rows:

- `0`: sample index
- `1-16`: ADS1299 channels in microvolts
- `17`: battery
- `18`: lead status
- `19`: timestamp seconds
- `20`: marker

OpenBCI CSV output uses these channel names and includes the formatted timestamp column added by the standard GUI writer.
