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

"""

import threading
import time

# Local imports
import config as cfg

# Logging
import __main__
import logging
import os

script = os.path.basename(__main__.__file__)
script = os.path.splitext(script)[0]
logger = logging.getLogger(script + "." + __name__)


# somehow inheriting threading.Event does not work
# class ReadRateTimer(threading.Thread, threading.Event):
class ReadRateTimer(threading.Thread):
  """
  - Set a trigger based on read_rate (rate per hour, 3600 is every second)
  - Clear trigger when all subscribed (nrof_threads) have cleared trigger

  """
  def __init__(self, read_rate, nrof_threads, t_threads_stopper):
    logger.debug(f">> read_rate = {read_rate};  nrof threads = {nrof_threads}")
    super().__init__()

    # number of threads which needs to be synchronized with ReadRateTimer
    self.__nrof_threads = nrof_threads
    self.__t_threads_stopper = t_threads_stopper
    self.__t_event = threading.Event()

    # Bookkeeping for throttling read rate
    self.__lastreadtime = 0
    self.__interval = 3600/read_rate

    # Measure time between Set and Release
    self.__triggertime = 0

    # ReadRateTimer flag will be set when timer has shot
    self.__set_counter = 0

    # timestamp for MQTT
    self.__ts = 0

    logger.debug("<<")
    return

  # threading.Event methods
  def wait(self, timeout=None):
    return self.__t_event.wait(timeout)

  def is_set(self):
    return self.__t_event.is_set()

  def release(self, name):
    logger.debug(f">> name = {name}; set_counter = {self.__set_counter}")

    if self.__set_counter <= 0:
      logger.error(f"set_counter <= 0; this should not happen")
    else:
      # decrement counter
      self.__set_counter += -1

    logger.debug(f"Updated set_counter = {self.__set_counter}")

    if self.__set_counter == 0:
      self.__t_event.clear()
      logger.info(f"Read time elapsed = {round(time.time() - self.__triggertime, 2)} seconds")

  def timestamp(self):
    logger.debug(">>")

    if cfg.SYNC_TIMESTAMP:
      # all worker thread gets same timestamp
      return self.__ts
    else:
      # every worker thread gets its own timestamp
      return int(time.time())

  def run(self):
    """
      - Exit when __stopper is set
      - Wait till read_rate delay has been exceeded

    :return:
    """
    logger.debug(">>")

    while not self.__t_threads_stopper.is_set():
      # Wait based on READ_RATE
      while not self.__t_threads_stopper.is_set() and not self.__t_event.is_set():
        t_elapsed = int(time.time()) - self.__lastreadtime

        if t_elapsed > self.__interval:
          logger.debug(f"Read Rate has exceeded wait threshold")
          # Read Rate has exceeded wait threshold;
          # Store current time for next wait cycle
          self.__lastreadtime = int(time.time())

          # Store epoch, MQTT timestamp for all threads
          self.__ts = int(time.time())

          # reset tracking counter to subscribed threads
          self.__set_counter = self.__nrof_threads

          # Set status (timer has shot)
          logger.debug(f"Flag set")
          self.__triggertime = time.time()
          self.__t_event.set()

          # Break from inner while loop
          break

        else:
          # if all threads have executed their task, clear flag
          if self.__set_counter == 0:

            # Reset status
            # This can be done without if statement, but that will pollute the debug messages
            if self.is_set():
              self.__t_event.clear()
              logger.info(f"Read time elapsed = {round(time.time() - self.__triggertime, 2)} seconds")
          else:
            # wait a bit
            time.sleep(0.2)
            logger.debug(f"Wait to satisfy READ_RATE")

    logger.debug("<<")
    return
