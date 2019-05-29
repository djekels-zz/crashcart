#
# Copyright (c) 2013 Nutanix Inc. All rights reserved.
#
# Author: thomas@nutanix.com
#
# Installer log library.
#

import logging
import os
import sys
import threading
import socket

try:
  # Py3 for ESXi 6.5.
  from urllib.parse import quote
  from urllib.request import urlopen, Request
  from urllib.error import URLError
except ImportError:
  # Py2 for phoenix and others.
  from urllib import quote
  from urllib2 import urlopen, Request, URLError

monitoring_url_root = None
monitoring_log_offset = 0
monitoring_offset_lock = threading.Lock()
monitoring_url_timeout_secs = 5
monitoring_url_retry_count = 5

FATAL_CALLBACK = None
FATAL_CALLBACK_ARGS = None


FATAL_LEVEL = 60
logging.addLevelName(FATAL_LEVEL, "FATAL")

logger = logging.getLogger("phoenix")
logger.setLevel(logging.DEBUG)

# ttyout handler definition.
ttyout_handler = logging.StreamHandler()
ttyout_handler.setLevel(logging.INFO)
ttyout_formatter = logging.Formatter(fmt="%(levelname)s %(message)s")
ttyout_handler.setFormatter(ttyout_formatter)
logger.addHandler(ttyout_handler)

# file handler definition.
file_handler = None


def disable_ttyout_handler():
  logger.removeHandler(ttyout_handler)


def enable_ttyout_handler():
  logger.addHandler(ttyout_handler)


def _fatal(msg):
  global FATAL_CALLBACK
  logger.log(FATAL_LEVEL, msg)
  if FATAL_CALLBACK:
    # Prevent infinite recursion if FATAL_CALLBACK calls FATAL.
    fatal_callback = FATAL_CALLBACK
    FATAL_CALLBACK = None
    fatal_callback(*FATAL_CALLBACK_ARGS)
  sys.exit(1)


def set_log_file(log_file="installer.log"):
  global file_handler
  logger.removeHandler(file_handler)
  file_handler = logging.FileHandler(log_file, delay=True)
  file_handler.setLevel(logging.DEBUG)
  file_formatter = logging.Formatter(
      fmt="%(asctime)s %(levelname)s  %(message)s")

  file_handler.setFormatter(file_formatter)
  logger.addHandler(file_handler)


def set_log_offset(new_offset):
  global monitoring_log_offset
  monitoring_log_offset = new_offset


def get_log_offset():
  global monitoring_log_offset
  return monitoring_log_offset


def set_monitoring_url_root(root):
  global monitoring_url_root
  monitoring_url_root = root


def get_monitoring_url_timeout_secs():
  return monitoring_url_timeout_secs


def set_monitoring_url_timeout_secs(timeout_secs):
  global monitoring_url_timeout_secs
  monitoring_url_timeout_secs = timeout_secs


def get_monitoring_url_retry_count():
  return monitoring_url_retry_count


def set_monitoring_url_retry_count(count):
  global monitoring_url_retry_count
  monitoring_url_retry_count = count


def set_log_fatal_callback(fatal_callback, arguments=()):
  # NOTE: arguments can only contain regular args and not kwargs.
  global FATAL_CALLBACK, FATAL_CALLBACK_ARGS
  FATAL_CALLBACK = fatal_callback
  FATAL_CALLBACK_ARGS = arguments

def monitoring_callback(step, message=None, retries=None, timeout=None):
  """
  Sends a message to monitoring server if set.
  Returns:
    None if monitoring server is not set.
    True if posted successfully.
    False, otherwise.
  """
  global monitoring_log_offset
  if not monitoring_url_root:
    return None

  retries = retries or monitoring_url_retry_count
  timeout = timeout or monitoring_url_timeout_secs

  if not message:
    message = ""
  else:
    message += "\n"

  # Update offset under lock.
  with monitoring_offset_lock:
    old_offset = monitoring_log_offset
    monitoring_log_offset += len(message)

  headers = {
      'Content-Type': 'application/text; charset=utf-8'
  }

  url = "%s&step=%s&offset=%d" % (monitoring_url_root, quote(step), old_offset)
  req = Request(url, message.encode(), headers)

  while retries > 0:
    try:
      result = urlopen(req, timeout=timeout)
      if result.getcode() != 200:
        logger.error("failed to post message to " + url)
        return False # Fatal error. No retry.
      return True # Request was successful.
    except (URLError, socket.timeout) as e:
      retries -= 1

  logger.error("error posting message to " + url)
  return False


def DEBUG(msg):
  monitoring_callback("debug", msg)
  logger.debug(msg)


def INFO(msg):
  monitoring_callback("info", msg)
  logger.info(msg)


def ERROR(msg):
  monitoring_callback("error", msg)
  logger.error(msg)


def WARNING(msg):
  monitoring_callback("warning", msg)
  logger.warning(msg)


def FATAL(msg):
  # Put a failire maker incase there is a retry to clear resources
  try:
    if not os.path.isdir("/tmp"):
      os.makedirs('/tmp')
    with open("/tmp/fatal_marker", "w+") as f:
      pass
  except:
    pass
  monitoring_callback("fatal", msg)
  _fatal(msg)

# set a default log file on import.
set_log_file()

__all__ = ["INFO", "ERROR", "FATAL", "WARNING", "set_monitoring_url_root",
            "set_monitoring_url_timeout_secs", "get_monitoring_url_retry_count",
            "set_monitoring_url_retry_count", "get_monitoring_url_timeout_secs",
            "monitoring_callback", "set_log_file", "set_log_offset",
            "set_log_fatal_callback", "DEBUG", "get_log_offset"]
