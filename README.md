# Kamstrup Multical MQTT
MQTT client/parser for Kamstrup Multical family of heat/energy meters.
- Tested with Kamstrup Multical 303 (in active heating system) 
- Tested with Kamstrup Multical 601 (not mounted in heating system, 0 flow, 0 power)
- Not all registers are implemented (eg the MAX value registers are ignored)
- Supports multiple Kamstrup meters on one single MBUS (Meterbus)
- Note: MBUS/Meterbus is not the same as MODBUS; You do need a MBUS adapter, MODBUS adapter will not work
- Timestamps (used for influxdb) are generated with 1sec accuracy
- All connected meters are read in a single sequential burst

## Coding:
- MQTT JSON key coding: d=device; t=tarif (used in Multical 601)

## Usage:
* Copy `systemd/kamstrup-mqtt.service` to `/etc/systemd/system`
* Adapt path in `kamstrup-mqtt.service` to your install location (default: `/opt/iot/kamstrup`)
* Copy `config.rename.py` to `config.py` and adapt for your configuration (minimal: mqtt ip, username, password)
* `sudo systemctl enable kamstrup-mqtt`
* `sudo systemctl start kamstrup-mqtt`

Use
http://mqtt-explorer.com/
to test & inspect MQTT messages

## Requirements
* paho-mqtt
* meterbus
* pyserial
* python 3.x

Tested under Linux; there is no reason why it does not work under Windows.

## InfluxDB
* Use `telegraf-kamstrup-powermeters.conf` as Telegraf configuration file to get kamstrup MQTT data into InfluxDB

## Licence
GPL v3

## Versions
1.0.0
* Initial version

