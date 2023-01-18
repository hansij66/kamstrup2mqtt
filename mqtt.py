"""
  Send MQTT messages

  Buffer messages if mqtt server is not available

  https://github.com/eclipse/paho.mqtt.python/blob/master/src/paho/mqtt/client.py
  https://www.eclipse.org/paho/index.php?page=clients/python/index.php


  v1.0.0: initial version
  v1.0.1: add last will
  V1.1.0: 31-7-2022: Add subscribing to MQTT server
  v1.1.3: on_disconnect rc=1 (out of memory) stop program
  v1.1.4: Add test for subscribing; whether message queue is set
  V1.1.5: Fix MQTT_ERR_NOMEM


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



"""

__version__ = "1.1.5"
__author__ = "Hans IJntema"
__license__ = "GPLv3"

import time
import threading
import socket
import queue
import paho.mqtt.client as paho

# Logging
import __main__
import logging
import os
script = os.path.basename(__main__.__file__)
script = os.path.splitext(script)[0]
logger = logging.getLogger(script + "." + __name__)

# Error values
MQTT_ERR_AGAIN = -1
MQTT_ERR_SUCCESS = 0

# MQTT_ERR_NOMEM is not very accurate; is often similar to MQTT_ERR_CONN_LOST
# eg stopping Mosquitto server generates a MQTT_ERR_NOMEM
# However, there are cases that client freezes for ethernity after a MQTT_ERR_NOMEM
# Implement a recover? With timeout? Try to reconnect?
MQTT_ERR_NOMEM = 1
MQTT_ERR_PROTOCOL = 2
MQTT_ERR_INVAL = 3
MQTT_ERR_NO_CONN = 4
MQTT_ERR_CONN_REFUSED = 5
MQTT_ERR_NOT_FOUND = 6
MQTT_ERR_CONN_LOST = 7
MQTT_ERR_TLS = 8
MQTT_ERR_PAYLOAD_SIZE = 9
MQTT_ERR_NOT_SUPPORTED = 10
MQTT_ERR_AUTH = 11
MQTT_ERR_ACL_DENIED = 12
MQTT_ERR_UNKNOWN = 13
MQTT_ERR_ERRNO = 14
MQTT_ERR_QUEUE_SIZE = 15

rc_dict = {
            MQTT_ERR_SUCCESS: "Success.",
            MQTT_ERR_NOMEM: "Out of memory.",
            MQTT_ERR_PROTOCOL: "A network protocol error occurred when communicating with the broker.",
            MQTT_ERR_INVAL: "Invalid function arguments provided.",
            MQTT_ERR_NO_CONN: "The client is not currently connected.",
            MQTT_ERR_CONN_REFUSED: "The connection was refused.",
            MQTT_ERR_NOT_FOUND: "Message not found (internal error).",
            MQTT_ERR_CONN_LOST: "The connection was lost.",
            MQTT_ERR_TLS: "A TLS error occurred.",
            MQTT_ERR_PAYLOAD_SIZE: "Payload too large.",
            MQTT_ERR_NOT_SUPPORTED: "This feature is not supported.",
            MQTT_ERR_AUTH: "Authorisation failed.",
            MQTT_ERR_ACL_DENIED: "Access denied by ACL.",
            MQTT_ERR_UNKNOWN: "Unknown error.",
            MQTT_ERR_ERRNO: "Error defined by errno."
           }

connack_dict = {
  0: "Connection Accepted.",
  1: "Connection Refused: unacceptable protocol version.",
  2: "Connection Refused: identifier rejected.",
  3: "Connection Refused: broker unavailable.",
  4: "Connection Refused: bad user name or password.",
  5: "Connection Refused: not authorised.",
  6: "Connection Refused: unknown reason.",
  7: "Connection Refused: unknown reason."
}


class mqttclient(threading.Thread):
  def __init__(self, mqtt_broker, mqtt_port, mqtt_client_id, mqtt_rate, mqtt_qos, username, password, mqtt_stopper, worker_threads_stopper):
    """

    Args:
      :param str mqtt_broker: ip or dns
      :param int mqtt_port:
      :param str mqtt_client_id:
      :param int mqtt_rate:
      :param int mqtt_qos: MQTT QoS 0,1,2
      :param str username:
      :param str password:
      :param threading.Event() mqtt_stopper: indicate to stop the mqtt thread; typically as last thread in main loop to flush out all mqtt messages
      :param threading.Event() worker_threads_stopper: stopper event for other worker threads; typically the worker threads are
             stopped in the main loop before the mqtt thread;but mqtt thread can also set this in case of failure

      TODO REMOVE worker_threads_stopper, as it is always set when mqtt_stopper is set
      (is that possible?)

    Returns:
      None
    """

    logger.debug(f">>")
    super().__init__()

    self.__mqtt_broker = mqtt_broker
    self.__mqtt_port = mqtt_port
    # self.__mqtt_client_id = mqtt_client_id

    self.__mqtt_stopper = mqtt_stopper
    self.__worker_threads_stopper = worker_threads_stopper
    self.__mqtt = paho.Client(mqtt_client_id)
    self.__run = False

    # Todo parameterize
    self.__keepalive = 500
    self.__qos = mqtt_qos
    self.__maxqueuesize = 10000

    # MQTT client tries to force a reconnection if
    # Client remains disconnected for more than MQTT_CONNECTION_TIMEOUT seconds
    self.__MQTT_CONNECTION_TIMEOUT = 60

    if mqtt_rate == 0:
      self.__mqtt_delay = 0
    else:
      self.__mqtt_delay = float(1.0 / mqtt_rate)

    # Call back functions
    self.__mqtt.on_connect = self.__on_connect
    self.__mqtt.on_disconnect = self.__on_disconnect
    self.__mqtt.on_message = self.__on_message

    # Uncomment if needed for debugging
#    self.__mqtt.on_publish = self.__on_publish
#    self.__mqtt.on_log = self.__on_log
    self.__mqtt.on_subscribe = self.__on_subscribe
    self.__mqtt.on_unsubscribe = self.__on_unsubscribe

    # Not yet implemented
    # self.__mqtt.on_unsubscribe = self.__on_unsubscribe

    # Managed via __set_connected_flag()
    # Keeps track of connected status
    self.__connected_flag = False

    # Keep track how long client is disconnected
    # When threshold is exceeded, try to recover
    # In some cases, a MQTT_ERR_NOMEM is not recovered automatically
    self.__disconnect_start_time = 0

    # Maintain a mqtt message count
    self.__mqtt_counter = 0

    # PAHO does implement a queue message for qos > 0
    # This client has its own queue for *stupid* reasons (as I originally did not realize that PAHO has a queue)
    # - To allow for throttling of MQTT messages (but maybe this can be implemented via the call-back functions
    # - Initially, I did not realize that PAHO has a queue mechanism
    # - Too lazy to remove.....
    self.__queue = queue.Queue(maxsize=self.__maxqueuesize)
    self.__mqtt.username_pw_set(username, password)

    self.__status_topic = None
    self.__status_payload = None
    self.__status_retain = None

    # For processing subscribed messages
    self.__message_trigger = None
    self.__subscribed_queue = None

  def __del__(self):
    logger.info(f">>")

  def __internet_on(self):
    """
      Test if there is connectivity with the MQTT broker

    Returns:
      return: connectivity status (True, False)
      rtype: bool
    """
    logger.debug(f">>")

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
      # Format: s.connect((HOST, PORT))
      s.connect((f"{self.__mqtt_broker}", int(self.__mqtt_port)))
      s.shutdown(socket.SHUT_RDWR)
      logger.debug(f"Internet connectivity to MQTT broker {self.__mqtt_broker} at port {self.__mqtt_port} available")
      return True
    except Exception as e:
      logger.info(f"Internet connectivity to MQTT broker {self.__mqtt_broker} at port {self.__mqtt_port} NOT yet available; Exception {e}")
      return False


  def __set_connected_flag(self, flag=True):
    logger.debug(f">> flag={flag}; current __connected_flag={self.__connected_flag}")

    # if flag == False and __connected_flag == True; start trigger
    if not flag and self.__connected_flag:
      self.__disconnect_start_time = int(time.time())
      logger.debug("Disconnect TIMER started")

    self.__connected_flag = flag
    return

  def __on_connect(self, client, userdata, flags, rc):
    """
    Callback: when the client receives a CONNACK response from the broker.

    Args:
      :param ? client: the client instance for this callback
      :param ? userdata: the private user data as set in Client()
      :param dict flags: response flags sent by the broker
      :param int rc: the connection result --> connack_dict

    Returns:
      None
    """
    logger.debug(f">>")
    if rc == 0:
      logger.debug(f"Connected: client={client}; userdata={userdata}; flags={flags}; rc={rc}: {connack_dict[rc]}")
      self.__set_connected_flag(True)
      self.__set_status()

      # TODO
      # Add subscribing, in case connection was lost

    else:
      logger.error(f"userdata={userdata}; flags={flags}; rc={rc}: {connack_dict[rc]}")
      self.__set_connected_flag(False)

  def __on_disconnect(self, client, userdata, rc):
    """
    Callback: called when the client disconnects from the broker.

    Args:
      :param ? client: the client instance for this callback
      :param ? userdata: the private user data as set in Client()
      :param int rc: the disconnection result --> rc_dict

    Returns:
      None
    """
    logger.info(f"(Un)expected disconnect, userdata = {userdata}; rc = {rc}: {rc_dict[rc]}")
    self.__set_connected_flag(False)

    return

#    if rc == 0:
#      logger.debug(f"Disconnected")
#    elif rc == 1:
#      logger.error(f"Unexpected disconnect - TERMINATE, rc = {rc}, {rc_dict[rc]}")
#      self.__worker_threads_stopper.set()
#    else:
#      logger.error(f"Unexpected disconnect, rc = {rc}, {rc_dict[rc]}")

  def __on_message(self, client, userdata, message):
    """
    :param client:
    :param userdata:
    :param message: Queue()
    :return:
    """
    logger.debug(f">> message = {message.topic}  {message.payload}")

    self.__subscribed_queue.put(message)

    # set event that message has been received
    if self.__message_trigger != None:
      self.__message_trigger.set()

  def __on_publish(self, client, userdata, mid):
    """
    Callback: when a message that was to be sent using the publish() call has completed transmission to the broker.

    Args:
      :param ? client: the client instance for this callback
      :param ? userdata: the private user data as set in Client()
      :param ? mid: matches the mid variable returned from the corresponding publish()

    Returns:
      None
    """
    logger.debug(f"userdata={userdata}; mid={mid}")
    return None

  def __on_subscribe(self, client, obj, mid, granted_qos):
    """
    :param client:
    :param obj:
    :param mid:
    :param granted_qos:
    :return:
    """
    logger.debug(f">> Subscribed: {mid} {granted_qos}")

  def __on_unsubscribe(self, client, obj, mid):
    """
    :param client:
    :param obj:
    :param mid:
    :return:
    """
    logger.debug(f">> Unsubscribed: {mid}")

  def __on_log(self, client, obj, level, buf):
    """
    Callback: when the client has log information.

    Args:
      :param ? client:
      :param ? obj:
      :param ? level: severity of the message
      :param ? buf: message

    Returns:
      None
    """
    logger.debug(f"obj={obj}; level={level}; buf={buf}")

  def __set_status(self):
    """
    Publish MQTT status message
    :return: None
    """
    logger.debug(">>")

    if self.__status_topic is not None:
      self.do_publish(self.__status_topic, self.__status_payload, self.__status_retain)

    return

  def set_status(self, topic, payload=None, retain=False):
    """
    Set status
    Will store status & resend on a reconnect

    :param str topic:
    :param str payload:
    :param bool retain:
    :return: None
    """
    logger.debug(">>")
    self.__status_topic = topic
    self.__status_payload = payload
    self.__status_retain = retain
    self.__set_status()

  def will_set(self, topic, payload=None, qos=0, retain=False):
    """
    Set last will/testament
    It is advised to call before self.run() is called

    :param str topic:
    :param str payload:
    :param int qos:
    :param bool retain:
    :return: None
    """
    logger.debug(f">>")

    if self.__run:
      logger.warning(f"Last Will/testament is set after run() is called. Not advised per documentation")

    self.__mqtt.will_set(topic, payload, qos, retain)

  def do_publish(self, topic, message, retain=False):
    """
    Publish topic & message to MQTT broker
    (by storing topic & message in message queue)

    Args:
      :param str topic: MQTT topic
      :param str message: MQTT message
      :param bool retain: retained flag MQTT message

    Returns:
      None
    """
    logger.debug(f">> TOPIC={topic}; MESSAGE={message}")

    # Queue is used to allow for throttling of MQTT messages
    self.__queue.put((topic, message, retain))
    logger.debug(f"{self.__queue.qsize()} MQTT messages are queued")

  def __do_mqtt(self):
    """
    Read message queue and send to mqtt broker

    Returns:
      None
    """
    logger.debug(">>")

    # Check connectivity
    if not self.__connected_flag:
      logger.warning(f"No connection with MQTT Broker; {self.__queue.qsize()} messages queued")
      return None

    logger.info(f"Connection with MQTT Broker; {self.__queue.qsize()} messages queued")

    while not self.__mqtt_stopper.is_set() and self.__connected_flag:

      # queue.get is set to blocking, with timeout of 1sec, to have a
      # regular check on stopper
      try:
        (topic, message, retainflag) = self.__queue.get(block=True, timeout=1)
        logger.debug(f"Received from Queue: TOPIC={topic} MESSAGE={message};...{self.__queue.qsize()} message(s) left in queued")
      except queue.Empty:
        continue
        #return None

      try:
        mqttmessageinfo = self.__mqtt.publish(topic, message, qos=self.__qos, retain=retainflag)
        self.__mqtt_counter += 1

        if mqttmessageinfo.rc != MQTT_ERR_SUCCESS:
          logger.warning(f"MQTT publish was not successfull, rc = {mqttmessageinfo.rc}: {rc_dict[mqttmessageinfo.rc]}")
      except ValueError:
        logger.warning("")

      """
      Returns a MQTTMessageInfo which expose the following attributes and methods:

      - rc, the result of the publishing. It could be MQTT_ERR_SUCCESS to indicate success, 
      MQTT_ERR_NO_CONN if the client is not currently connected, 
      or MQTT_ERR_QUEUE_SIZE when max_queued_messages_set is used to indicate that message is neither queued nor sent.
      
      - mid is the message ID for the publish request. 
      The mid value can be used to track the publish request by checking against the mid argument in the on_publish() callback 
      if it is defined. wait_for_publish may be easier depending on your use-case.
      
      - wait_for_publish() will block until the message is published. 
      It will raise ValueError if the message is not queued (rc == MQTT_ERR_QUEUE_SIZE).
      
      - is_published returns True if the message has been published. 
      It will raise ValueError if the message is not queued (rc == MQTT_ERR_QUEUE_SIZE).
      
      A ValueError will be raised if topic is None, has zero length or is invalid (contains a wildcard), 
      if qos is not one of 0, 1 or 2, or if the length of the payload is greater than 268435455 bytes.
      """

      # Throttle mqtt rate
      if self.__mqtt_delay > 0.0:
        logger.debug(f"THROTTLE with {self.__mqtt_delay}")
        time.sleep(self.__mqtt_delay)

    # stopper is set...
    if self.__mqtt_stopper.is_set():
      logger.info(f"Shutting down MQTT Client... {self.__mqtt_counter} MQTT messages have been published")

    return

  def set_message_trigger(self, subscribed_queue, trigger=None):
    """
    Call before subscribing
    The received messages are stored in a queue
    If a message is received, trigger event will be set

    :param subscribed_queue: Queue() - as received by on_message (topic, payload,..)
    :param trigger: threading.Event(); OPTIONAL: to indicate that message has been received
    :return:
    """

    self.__message_trigger = trigger
    self.__subscribed_queue = subscribed_queue
    return

  def subscribe(self, topic):
    logger.debug(f">> topic = {topic}")

    if self.__subscribed_queue is None:
      logger.error(f"Subscription message queue has not been set --> call set_message_trigger")
      return

    # Subscribing will not work if client is not connected
    # Wait till there is a connection
    while not self.__connected_flag and not self.__mqtt_stopper.is_set():
      logger.warning(f"No connection with MQTT Broker; cannot subscribe...wait for connection")
      time.sleep(0.1)

    # TODO...store subscriptions, and subscribe again in on_connect (in case connection was lost)
    # https://www.eclipse.org/paho/index.php?page=clients/python/docs/index.php
    self.__mqtt.subscribe(topic, self.__qos)

  def unsubscribe(self, topic):
    logger.debug(f">> topic = {topic}")
    self.__mqtt.unsubscribe(topic)

  def run(self):
    logger.info(f"Broker = {self.__mqtt_broker}>>")
    self.__run = True

    # Wait till there is network connectivity to mqtt broker
    # Start with a small delay and incrementally (+20%) make larger
    delay = 0.1
    while not self.__internet_on():
      time.sleep(delay)
      delay = delay * 1.2

      # Timeout after 60min
      if delay > 3600:
        logger.error(f"No internet connection - EXIT")
        self.__mqtt_stopper.set()
        self.__worker_threads_stopper.set()
        return

    try:
      self.__mqtt.connect_async(self.__mqtt_broker, self.__mqtt_port, self.__keepalive)

    except Exception as e:
      logger.exception(f"Exception {format(e)}")
      self.__mqtt.disconnect()
      self.__mqtt_stopper.set()
      self.__worker_threads_stopper.set()
      return

    else:
      logger.info(f"start mqtt loop...")
      self.__mqtt.loop_start()
      logger.debug(f"mqtt loop started...")

    # Start infinite loop which sends queued messages every second
    while not self.__mqtt_stopper.is_set():
      self.__do_mqtt()

      # Check connection status
      # If disconnected time exceeds threshold
      # then reconnect
      if not self.__connected_flag:
        disconnect_time = int(time.time()) - self.__disconnect_start_time
        logger.debug(f"Disconnect TIMER = {disconnect_time}")
        if disconnect_time > self.__MQTT_CONNECTION_TIMEOUT:
          try:
            self.__mqtt.reconnect()
          except Exception as e:
            logger.exception(f"Exception {format(e)}")

            # reconnect failed....reset disconnect time, and retry after self.__MQTT_CONNECTION_TIMEOUT
            self.__disconnect_start_time = int(time.time())

      time.sleep(0.1)

    # Close mqtt broker
    logger.debug(f"Close down MQTT client & connection to broker")
    self.__mqtt.loop_stop()
    self.__mqtt.disconnect()
    self.__mqtt_stopper.set()
    self.__worker_threads_stopper.set()
    logger.info(f"<<")
