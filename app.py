#!/usr/bin/env python

import paho.mqtt.client as paho  # pip install paho-mqtt
import broadlink  # pip install broadlink
import os
import sys
import time
import json
import logging
import logging.config
import socket
import binascii

# get the data directory
DATA_DIR = os.getenv('DATA_DIR', os.path.dirname(os.path.abspath(__file__)))

# logging config
LOG_LEVEL = os.getenv('LOG_LEVEL', 'DEBUG')
LOG_FORMAT = os.getenv('LOG_FORMAT', '%(asctime)-15s %(levelname)-5s [%(module)s] %(message)s')

# read initial config files
APP_CONFIG = os.path.join(DATA_DIR, 'app.conf')

class Config(object):
    def __init__(self, filename):
        self.config = {}
        if os.path.exists(filename):
            exec(compile(open(filename, "rb").read(), filename, 'exec'), self.config)

    def get(self, key, default='MISSING_CONFIG'):
        # env var has precendence
        value = os.getenv(key.upper(), 'MISSING_ENV')
        if value == 'MISSING_ENV':
            # no env var, so check conf file
            value = self.config.get(key, default)
            if value == 'MISSING_CONFIG':
                logging.error("Configuration parameter '%s' should be specified" % key)
                sys.exit(2)
        return value

# initialise logging as early as possible
logging.basicConfig(stream=sys.stderr, level=LOG_LEVEL, format=LOG_FORMAT)

# load application config
try:
    cf = Config(APP_CONFIG)
except Exception as e:
    print("Failed to load application config from %s: %s" % (APP_CONFIG, e))
    sys.exit(2)

# noinspection PyUnusedLocal
def on_message(client, devices, msg):
    try:
        payload = json.loads(msg.payload)
    except Exception as e:
        logging.error('Failed to decode JSON payload (%s): %s' % (msg.payload, e))
        return

    device = None
    if 'host' in payload:
        host = payload['host']
        if host in devices:
            device = devices[host]

    if not device:
        logging.warning('No device found for message: %s' % (msg.payload))
        return

    if 'command' in payload:
        command = payload.get('command')
        action = payload.get('action', '')

        logging.debug('Command received for %s device at %s (MAC %s): %s -> %s' % (device.type, device.host[0], ':'.join(format(s, '02x') for s in device.mac), command, action))

        if device.type in ['RM2', 'RM4', 'RM4PRO', 'RMMINI', 'RM4MINI', 'RMMINIB', 'RMPRO']:
            file = os.path.join(DATA_DIR, 'commands', command)
            handy_file = os.path.join(file, action)

            try:
                if command == 'macro':
                    file = os.path.join(DATA_DIR, 'macros', action)
                    macro(device, file)
                elif action == '' or action == 'auto':
                    record_or_replay(device, file)
                elif action == 'autorf':
                    record_or_replay_rf(device, file)
                elif os.path.isfile(handy_file):
                    replay(device, handy_file)
                elif action == 'record':
                    record(device, file)
                elif action == 'recordrf':
                    record_rf(device, file)
                elif action == 'replay':
                    replay(device, file)
                elif action == 'macro':
                    file = os.path.join(DATA_DIR, 'macros', command)
                    macro(device, file)
                else:
                    logging.warning('Unrecognized MQTT message: %s' % (msg.payload))

            except Exception as e:
                logging.error('Error handling command %s: %s' % (command, e))
                return

# noinspection PyUnusedLocal
def on_connect(client, devices, flags, result_code):
    if result_code == 0:
        logging.info("MQTT connected")

        birth_topic = cf.get('mqtt_birth_topic', 'stat/broadlink/lwt')
        birth_payload = payload=cf.get('mqtt_birth_payload', '{"online":true}')
        mqttc.publish(birth_topic, birth_payload, qos=0, retain=True)

        cmnd_topic = cf.get('mqtt_command_topic', 'cmnd/broadlink')
        logging.debug("Subscribing to command topic %s" % cmnd_topic)
        client.subscribe(cmnd_topic)

    elif result_code == 1:
        logging.info("MQTT connection refused - unacceptable protocol version")
    elif result_code == 2:
        logging.info("MQTT connection refused - identifier rejected")
    elif result_code == 3:
        logging.info("MQTT connection refused - server unavailable")
    elif result_code == 4:
        logging.info("MQTT connection refused - bad user name or password")
    elif result_code == 5:
        logging.info("MQTT connection refused - not authorised")
    else:
        logging.warning("MQTT connection failed - result code %d" % (result_code))


# noinspection PyUnusedLocal
def on_disconnect(client, devices, result_code):
    if result_code == 0:
        logging.info("Clean disconnection from MQTT broker")
    else:
        logging.warning('MQTT connection lost, reconnect in 10s')
        time.sleep(10)


def record_or_replay(device, file):
    if os.path.isfile(file):
        replay(device, file)
    else:
        record(device, file)


def record_or_replay_rf(device, file):
    if os.path.isfile(file):
        replay(device, file)
    else:
        record_rf(device, file)


def record(device, file):
    logging.debug("Recording command to file " + file)
    # receive packet
    device.enter_learning()
    ir_packet = None
    attempt = 0
    while ir_packet is None and attempt < 8:
        attempt = attempt + 1
        time.sleep(5)
        try:
            ir_packet = device.check_data()
        except (broadlink.exceptions.ReadError, broadlink.exceptions.StorageError):
            continue
    if ir_packet is not None:
        # write to file
        directory = os.path.dirname(file)
        if not os.path.exists(directory):
            os.makedirs(directory)
        with open(file, 'wb') as f:
            f.write(binascii.hexlify(ir_packet))
        logging.debug("Done")
    else:
        logging.warning("No command received")


def record_rf(device, file):
    logging.debug("Recording RF command to file " + file)
    logging.debug("Learning RF Frequency, press and hold the button to learn...")

    device.sweep_frequency()
    timeout = 20

    while (not device.check_frequency()) and (timeout > 0):
        time.sleep(1)
        timeout -= 1

    if timeout <= 0:
        logging.warning("RF Frequency not found")
        device.cancel_sweep_frequency()
        return

    logging.debug("Found RF Frequency - 1 of 2!")
    time.sleep(5)
    logging.debug("To complete learning, single press the button you want to learn")

    # receive packet
    device.find_rf_packet()
    rf_packet = None
    attempt = 0
    while rf_packet is None and attempt < 6:
        time.sleep(5)
        rf_packet = device.check_data()
        attempt = attempt + 1
    if rf_packet is not None:
        # write to file
        directory = os.path.dirname(file)
        if not os.path.exists(directory):
            os.makedirs(directory)
        with open(file, 'wb') as f:
            f.write(binascii.hexlify(rf_packet))
        logging.debug("Done")
    else:
        logging.warning("No command received")


def replay(device, file):
    logging.debug("Replaying command from file " + file)
    with open(file, 'rb') as f:
        ir_packet = f.read()
    device.send_data(binascii.unhexlify(ir_packet.strip()))


def macro(device, file):
    logging.debug("Replaying macro from file " + file)
    with open(file, 'r') as f:
        for line in f:
            line = line.strip(' \n\r\t')
            if len(line) == 0 or line.startswith("#"):
                continue
            if line.startswith("pause "):
                pause = int(line[6:].strip())
                logging.debug("Pause for " + str(pause) + " milliseconds")
                time.sleep(pause / 1000.0)
            else:
                command_file = os.path.join(DATA_DIR, 'commands', line)
                replay(device, command_file)


def get_devices(cf):
    device_hosts = cf.get('device_hosts', '').split(',')
    devices = {}

    for host in device_hosts:
        if host != '':
            device = configure_device(broadlink.hello(host))
            devices[device.host[0]] = device

    return devices

def configure_device(device):
    device.auth()
    logging.debug('Found %s device at %s (MAC %s)' % (device.type, device.host[0], ':'.join(format(s, '02x') for s in device.mac)))
    return device


if __name__ == '__main__':
    logging.info("Scanning for Broadlink devices...")
    devices = get_devices(cf)

    if len(devices) == 0:
        logging.warning('No devices found, exiting')
        sys.exit(2)

    broker = cf.get('mqtt_broker', 'localhost')
    port  = int(cf.get('mqtt_port', 1883))
    clientid = cf.get('mqtt_clientid', 'broadlink')

    mqttc = paho.Client(clientid, clean_session=False, userdata=devices)

    mqttc.on_message = on_message
    mqttc.on_connect = on_connect
    mqttc.on_disconnect = on_disconnect

    will_topic = cf.get('mqtt_will_topic', 'stat/broadlink/lwt')
    will_payload = payload=cf.get('mqtt_will_payload', '{"online":false}')
    mqttc.will_set(will_topic, will_payload, qos=0, retain=True)

    if cf.get('mqtt_username', None):
        mqttc.username_pw_set(cf.get('mqtt_username'), cf.get('mqtt_password'))

    while True:
        logging.info('Attempting to connect to MQTT broker at %s:%d...' % (broker, port))
        try:
            mqttc.connect(broker, port, 60)
            mqttc.loop_forever()
        except socket.error:
            logging.warning("Failed to connect to MQTT broker, will try to reconnect in 5 seconds")
            time.sleep(5)
        except KeyboardInterrupt:
            sys.exit(0)
        except:
            logging.exception("Error")
