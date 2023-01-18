"""
        This program is free software: you can redistribute it and/or modify
        it under the terms of the GNU General Public License as published by
        the Free Software Foundation, either version 3 of the License, or
        (at your option) any later version.

        This program is distributed in the hope that it will be useful,
        but WITHOUT ANY WARRANTY; without even the implied warranty of
        MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
        GNU General Public License for more details.

        You should have received a copy of the GNU General Public License
        along with this program.  If not, see <http://www.gnu.org/licenses/>.

Description
-----------
- Read Kamstrup MBUS device
- Parse data
"""

import threading
import time
import serial
import meterbus
import json

# Local imports
import config as cfg

# Logging
import __main__
import logging
import os

script = os.path.basename(__main__.__file__)
script = os.path.splitext(script)[0]
logger = logging.getLogger(script + "." + __name__)


class TaskReadHeatMeter(threading.Thread):
  def __init__(self, name, mbus_address, mbus_semaphore, t_readrate, t_mqtt, t_threads_stopper):
    logger.debug(f">> {name}")
    super().__init__()
    self.__name = name
    self.__mbus_address = mbus_address
    self.__mbus_semaphore = mbus_semaphore

    # determine when to read MBUS device
    self.__t_readrate = t_readrate

    # MQTT client
    self.__t_mqtt = t_mqtt

    # Signal when to stop
    self.__t_threads_stopper = t_threads_stopper

    # Maintain a dictionary of values to be publised to MQTT
    self.__json_values = dict()

    # Keep count of nr of reads since start of parser
    self.__counter = 0

    # Bookkeeping for throttling read rate
    #self.__lastreadtime = 0
    #self.__interval = 3600/cfg.READ_RATE

    logger.debug(f"<< {self.__name}")
    return

  def __del__(self):
    logger.debug(f">> {self.__name}")

  def __publish_telegram(self):
    """
    Publish self.__json_values to MQTT

    :return: None
    """
    logger.debug(f">> {self.__name}")

    # make resilient against double forward slashes in topic
    topic = cfg.MQTT_TOPIC_PREFIX + "/" + self.__name
    topic = topic.replace('//', '/')

    # Only when kamstrup device was connected, do publish values
    if self.__is_connected:
      message = json.dumps(self.__json_values, sort_keys=True, separators=(',', ':'))
      self.__t_mqtt.do_publish(topic, message, retain=False)

    self.__t_mqtt.do_publish(topic + "/counter", str(self.__counter), retain=False)

    # Indicate in MQTT whether kamstrup meter is connected (or not)
    status = "power on" if self.__is_connected else "power off"
    self.__t_mqtt.do_publish(topic + "/status", status, retain=True)

    logger.debug(f"<< {self.__name}")
    return

  def __read_mbus(self):
    """
    Read Kamstrup via MBUS
    Parse data

    :return: None
    """
    logger.debug(f">> {self.__name}")

    # Clear the dict where we store all Kamstrup meter values
    self.__json_values.clear()

    # Loop forever till threads are requested to stop
    while not self.__t_threads_stopper.is_set():
      # wait till trigger to read values (or time out and start from start)
      if not self.__t_readrate.wait(0.2):
        continue
      else:
        # Read all registers from Kamstrup Multical
        try:
          t = time.time()

          # get semaphore, as only one device can be read at same time via same MBUS
          self.__mbus_semaphore.acquire()
          logger.debug(f"{self.__name}: Acquired mbus semapahore after t = {round(time.time() - t, 2)} seconds")

          # Get timestamp and add to dict
          ts = self.__t_readrate.timestamp()
          self.__json_values["timestamp"] = ts

          # Read kamstrup via MBUS
          with serial.Serial(cfg.MBUS_PORT, cfg.MBUS_BAUDRATE, cfg.MBUS_BYTESIZE, cfg.MBUS_PARITY, cfg.MBUS_STOPBIT, timeout=0.5) as ser:
            meterbus.send_ping_frame(ser, self.__mbus_address)
            frame = meterbus.load(meterbus.recv_frame(ser, 1))
            assert isinstance(frame, meterbus.TelegramACK), "Meterbus did not return a meterbus.TelegramACK"

            meterbus.send_request_frame(ser, self.__mbus_address)
            frame = meterbus.load(meterbus.recv_frame(ser, meterbus.FRAME_DATA_LENGTH))
            assert isinstance(frame, meterbus.TelegramLong), "Meterbus did not return a meterbus.TelegramLong"

            # Convert telegram to JSON to a DICT
            kamstrup_json = frame.to_JSON()
            kamstrup_dict = json.loads(kamstrup_json)

        except Exception as e:
          logger.warning(f"{e}")

          # Flag that we are not connected to Kamstrup or not successfull in getting a telegram
          self.__is_connected = False

        else:
          # We are still connected to Kamstrup meter
          self.__is_connected = True

          # We did read values; increment counter
          self.__counter += 1

        finally:
          # Start parsing

          # Semaphore can be released
          self.__mbus_semaphore.release()
          self.__t_readrate.release(self.__name)

          if self.__is_connected:
            # Build a dict of key:value, for MQTT JSON
            # Do some rework on received values
            for record in kamstrup_dict['body']['records']:
              if record['function'] == "FunctionType.INSTANTANEOUS_VALUE":
                newvalue = str(record['type']).replace("VIFUnit.", "")
                record.update({'type': newvalue})

                if "tariff" in record:
                  # device = d; tariff = t
                  logger.debug(f"{self.__name}: RECORD: {record['type']}_d{record['device']}_t{record['tariff']} = {record['value']}")
                  self.__json_values[f"{record['type']}_d{record['device']}_t{record['tariff']}"] = record['value']
                else:
                  logger.debug(f"{self.__name}: RECORD: {record['type']} = {record['value']}")
                  self.__json_values[f"{record['type']}"] = record['value']

          self.__publish_telegram()

      # As __t_readrate is still set, and to prevent that we will read again the heat meter in current sequence;
      # wait till __t_readrate gets cleared; After __t_readrate is cleared, start from top
      while self.__t_readrate.is_set():
        logger.debug(f"{self.__name}: Wait till all tasks are done")
        time.sleep(0.2)

    logger.debug(f"<< {self.__name}")
    return

  def run(self):
    logger.debug(f">> {self.__name}")

    while not self.__t_threads_stopper.is_set():
      try:
        self.__read_mbus()

      except Exception as e:
        logger.error(f"{self.__name}: {e}")

        # Something unexpected happens, stop all threads
        self.__t_threads_stopper.set()

    logger.debug(f"<<")
    return
