"""
  Rename to config.py

  Configure:
  - MQTT client
  - Kamstrup MBus devices
  - Debug level

"""

import serial

# [ LOGLEVELS ]
# DEBUG, INFO, WARNING, ERROR, CRITICAL
loglevel = "INFO"

# NROF parameter reads from power meter per hour (60 equals every minute)
# If rate is too high for numer of devices connected, parser might "collapse"
# No safety checks build in for too high read_rate
# You have to balance nrof devices, baud-rate and READ_RATE
# With a baud-rate of 2400, reading one device takes about 1.3 seconds
READ_RATE = 60  # Every minute


# [ MQTT Parameters ]
# Using local dns names was not always reliable with PAHO
MQTT_BROKER = "192.168.1.1"
MQTT_PORT = 1883
MQTT_CLIENT_UNIQ = 'mqtt-kamstrup'
MQTT_QOS = 1
MQTT_USERNAME = "username"
MQTT_PASSWORD = "secret"

# Max nrof MQTT messages per second
# Set to 0 for unlimited rate
MQTT_RATE = 100
MQTT_TOPIC_PREFIX = "kamstrup"

# [ MBUS/meterbus ]
# Depends on your MBUS USB dongle
# Assumption is there is only one MBUS bus with optionally multiple Kamstrup Multicals
# All devices need to have same serial settings
# https://pyserial.readthedocs.io/en/latest/pyserial_api.html#constants
MBUS_PORT = "/dev/tty-mbus"
MBUS_BAUDRATE = 2400
MBUS_BYTESIZE = serial.EIGHTBITS
MBUS_PARITY = serial.PARITY_EVEN
MBUS_STOPBIT = serial.STOPBITS_ONE

# [ Kamstrup MBUS device(s) ]
# Address 254 also works if only one device is connected
# Address 254 = broadcast address (only use when single device is connected)
# Use tools/mbus-serial-scan.py /dev/tty-<yourmbus dongle> to find your mbus address
MBUS_KAMSTRUP_DEVICES = [
#{'name': 'MC601', 'mbus_address': 3},
{'name': 'MC303', 'mbus_address': 11}
]

# INFLUXDB
# All kamstrup meters are read in a single sequential burst (determined by READ_RATE)
# Generate same time stamp for all meters read in one sequential burst
# Drawback: if you have multiple devices, timestamp might deviate a bit from actual time measurement is done
# Advantage: all measurements in one sequence will get same timestamp for influxdb
# Reading burst for the 2 power meters used in this example takes about 2 seconds
# Timestamp is with 1sec accuracy; if you need more, adapt code a bit
SYNC_TIMESTAMP = True
