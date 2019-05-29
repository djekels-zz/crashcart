# Copyright (c) 2015 Nutanix Inc. All rights reserved.
#
# Author: akshay@nutanix.com
#
# Crash Cart UI for configuring network.
#
import abc
import curses
import glob
import os
import re
import string
import sys
import time

from subprocess import Popen, PIPE
from traceback import format_exc

import crash_utils
import firstboot_utils

from crash_gui_widgets import *
from gui_widgets import *

DISABLE_MANAGEMENT_CHOICES = True

class NetworkParams(object):
  def __init__(self):
    self.separate_network = False

    # Storage Network.
    self.storage_eth_devs = []
    self.storage_vlan_tag = None
    self.storage_cvm_ip = None
    self.storage_hyp_ip = None
    self.storage_netmask = None
    self.storage_gateway = None

    # Management Network.
    self.mgmt_vlan_tag = None
    self.mgmt_cvm_ip = None
    self.mgmt_hyp_ip = None
    self.mgmt_netmask = None
    self.mgmt_gateway = None
    self.diff_interfaces_mgmt_network = False
    self.mgmt_eth_devs = []

class GuiParams(object):
  """
  Class for values of parameters chosen by user.
  """
  def __init__(self):
    NETWORK_CHOICES = ["Single Storage + Management Network",
                       "Separate Storage and Management Network"]
    self.network_choice = [ (choice, choice) for choice in NETWORK_CHOICES]
    self.network_params = NetworkParams()

gp = GuiParams()

def get_nic_info_table(nic_info):
  """
  Returns array of text
  """

  adj_dict = [7, 15, 18, 15, 15]

  table = []
  headers = ["Name", "Description", "Mac Address", "Max Speed", "Link"]

  table.append(generate_row_text(headers, adj_dict))

  for info in nic_info:
    row_entries = [info.dev, info.model, info.mac_addr,
                   info.speed, info.link]
    table.append(generate_row_text(row_entries, adj_dict))
  return table

class Gui(object):
  __metaclass__ = abc.ABCMeta

  def __init__(self):
    self.is_first = True
    self.window = None
    self.handler = None

  @abc.abstractmethod
  def interactive_ui(self, stdscr):
    pass

  @abc.abstractmethod
  def get_params(self):
    pass

class NetworkConfigGui(Gui):
  def __init__(self):
    super(NetworkConfigGui, self).__init__()

  def init_header(self, window, stdscr):
    y = 1; x_default = 10
    max_y, max_x = stdscr.getmaxyx()

    window.bkgdset(' ', curses.color_pair(2))
    window.clear()
    window.border()
    window.keypad(1)

    msg = "<< Nutanix Network Configuration >>"
    x_temp = (max_x/2 - len(msg)/2) or x_default
    window.addnstr(y, x_temp, msg, 50, curses.color_pair(1))

  def init_ui(self, stdscr):
    curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_RED)

    stdscr.bkgdset(' ', curses.color_pair(1))
    stdscr.clear()
    stdscr.border()

    max_y, max_x = stdscr.getmaxyx()
    self.window = stdscr.subwin(max_y-2, max_x-4, 1, 2)
    self.handler = ElementHandler(self.window)

  def show_network_card_details(self, window, handler, y, x, max_y):
    """
    Shows network card details.
    Returns y,x for end.
    """
    y += 2
    x_temp = x+2

    table = get_nic_info_table(
      crash_utils.get_ethernet_devices_details().values())

    max_width = min(len(max(table, key=len)) + 3, 79)
    max_height = min(max_y - 5 - y, 8)
    device_info = TextViewBlock(window, y, x, None, table,
                                     "Network card details",
                                     max_width + 3, max_height)
    handler.add(device_info)
    y += max_height
    return y,x

  def load_storage_page(self, stdscr):
    """
    Load all storage network options.
    Page has to fit in  80x25 in worst case.
    """
    max_y, max_x = stdscr.getmaxyx()
    y = 1; x = 5
    x_adj = 25; x_default = 10

    # Checkbox for to ask user if separate management and storage networks
    # are required.
    # TODO: Remove condition when support for management network is ready.
    if not DISABLE_MANAGEMENT_CHOICES:
      y += 2
      msg = "Separate management and storage networks?"
      msg += ":"
      x_temp = len(msg) + 1
      self.window.addnstr(y, x, msg, x_temp+1)
      self.separate_network =  CheckBox(self.window, y, x + x_temp,
                                        "", False)
      self.handlers.add(self.separate_network)

    y += 2
    msg = "<< Storage Network Configuration >>"
    x_temp = (max_x/2 - len(msg)/2) or x_default
    self.window.addnstr(y, x_temp, msg, 50, curses.color_pair(1))
    self.eth_devs = crash_utils.detect_ethernet_devices()
    self.storage_dev_box = {}

    y += 1
    msg = "Choose Ethernet Devices".ljust(x_adj)
    msg += ":"
    self.window.addnstr(y, x, msg, x_adj+1)

    x_temp = x + len(msg) + 1
    # Show only 4 devices in single line.
    # Show remaining devices on next line.
    for index, dev in enumerate(self.eth_devs):
      if index != 0 and index % 4 == 0:
        x_temp = x + len(msg) + 1
        y += 2
      self.storage_dev_box[dev] = CheckBox(self.window, y, x_temp,
                                           dev, False)
      x_temp += 10

      self.handler.add(self.storage_dev_box[dev])


    y += 2
    x_temp = x
    msg = "Vlan tag".ljust(x_adj)
    msg += ":"
    self.storage_vlan_tag = TextEditor(self.window, y, x_temp, msg, "", 15)
    self.handler.add(self.storage_vlan_tag)

    y += 1
    msg = "VSwitch MTU".ljust(x_adj)
    msg += ":"
    self.vswitch_mtu = TextEditor(self.window, y, x_temp, msg, "1500", 15)
    self.handler.add(self.vswitch_mtu)

    y += 1
    msg = "Netmask".ljust(x_adj)
    msg += ":"
    self.storage_netmask = TextEditor(self.window, y, x_temp, msg, "", 15)
    self.handler.add(self.storage_netmask)

    y += 1
    msg = "Gateway".ljust(x_adj)
    msg += ":"
    self.storage_gateway = TextEditor(self.window, y, x_temp, msg, "", 15)
    self.handler.add(self.storage_gateway)

    y += 1
    msg = "Controller VM IP".ljust(x_adj)
    msg += ":"
    self.storage_cvm_ip = TextEditor(self.window, y, x_temp, msg, "", 15)
    self.handler.add(self.storage_cvm_ip)


    y += 1
    msg = "Hypervisor IP".ljust(x_adj)
    msg += ":"
    self.storage_hyp_ip = TextEditor(self.window, y, x_temp, msg, "", 15)
    self.handler.add(self.storage_hyp_ip)


    self.eth_devs = crash_utils.detect_ethernet_devices()

    y,x = self.show_network_card_details(self.window, self.handler,
                                         y, x, max_y)

    # Done and cancel buttons.
    # Text of done changes depending on network choice.

    y += 1
    self.next_button = CrashCartButton(self.window, y, x, "Done",
                                       lambda e:ElementHandler.NEXT)
    self.handler.add(self.next_button)
    self.cancel_button = CrashCartButton(self.window, y, x+10, "Cancel",
                                         lambda e:ElementHandler.EXIT)
    self.handler.add(self.cancel_button)
    stdscr.refresh()


    # TODO: Remove this condition when support for management network is ready.
    if not DISABLE_MANAGEMENT_CHOICES:
      self.separate_network.update_if_unchecked = []
      self.separate_network.update_if_unchecked.append(self.next_button)

  def load_management_page(self, stdscr):
    """
    Load all management network options.
    Page has to fit in  80x25 in worst case.
    """
    max_y, max_x = stdscr.getmaxyx()
    y = 1; x = 5
    x_adj = 30; x_default = 5

    # Management Network UI.
    y += 2
    msg = "<< Management Network Configuration >>"
    x_temp = (max_x/2 - len(msg)/2) or x_default
    self.window.addnstr(y, x_temp, msg, 50, curses.color_pair(1))

    self.mgmt_dev_box = {}

    y += 2
    msg = "Separate interfaces for management network? "
    msg += ":"
    x_temp = len(msg) + 1
    self.management_choice_box = CheckBox(self.window, y, x + x_temp, "",
                                          False)

    self.window.addnstr(y, x, msg, x_temp)
    self.handler.add(self.management_choice_box)

    y += 2
    msg = "Choose Ethernet Devices".ljust(x_adj)
    msg += ":"

    self.window.addnstr(y, x, msg, x_adj + 1)

    x_temp = x + len(msg) + 1
    for dev in self.eth_devs:
      if dev in self.storage_dev_box and self.storage_dev_box[dev].selected:
        continue
      self.mgmt_dev_box[dev] = CheckBox(self.window, y, x_temp, dev,
                                              False, False)
      x_temp += 10
      self.handler.add(self.mgmt_dev_box[dev])

    y += 2
    x_temp = x
    msg = "Vlan tag".ljust(x_adj)
    msg += ":"
    self.mgmt_vlan_tag = TextEditor(self.window, y, x_temp, msg, "", 15)
    self.handler.add(self.mgmt_vlan_tag)

    y += 1
    msg = "Netmask".ljust(x_adj)
    msg += ":"
    self.mgmt_netmask = TextEditor(self.window, y, x_temp, msg, "", 15)
    self.handler.add(self.mgmt_netmask)

    y += 1
    msg = "Gateway".ljust(x_adj)
    msg += ":"
    self.mgmt_gateway = TextEditor(self.window, y, x_temp, msg, "", 15)
    self.handler.add(self.mgmt_gateway)

    y += 1
    msg = "Controller VM IP".ljust(x_adj)
    msg += ":"
    self.mgmt_cvm_ip = TextEditor(self.window, y, x_temp, msg, "", 15)
    self.handler.add(self.mgmt_cvm_ip)


    y += 1
    msg = "Hypervisor IP".ljust(x_adj)
    msg += ":"
    self.mgmt_hyp_ip = TextEditor(self.window, y, x_temp, msg, "", 15)
    self.handler.add(self.mgmt_hyp_ip)

    y,x = self.show_network_card_details(self.window, self.handler,
                                         y, x , max_y)
    # Done and cancel buttons.
    y += 2
    self.done_button = CrashCartButton(self.window, y, x, "Done",
                                       lambda e:ElementHandler.EXIT)
    self.handler.add(self.done_button)

    self.cancel_button = CrashCartButton(self.window, y, x+10, "Cancel",
                                         lambda e:ElementHandler.EXIT)
    self.handler.add(self.cancel_button)

    self.management_choice_box.disable_if_unchecked = []

    self.management_choice_box.disable_if_unchecked.extend(
      self.mgmt_dev_box.values())

    stdscr.refresh()

  def interactive_ui(self, stdscr):

    if self.is_first:
      self.init_ui(stdscr)
      self.is_first = False

    self.init_header(self.window, stdscr)
    self.load_storage_page(stdscr)
    self.handler.elements[0].set_focus(True)
    ret = self.handler.process()

    # TODO: Remove this condition when support for management network is ready.
    if not DISABLE_MANAGEMENT_CHOICES:
      if ret == NEXT:
        self.init_header(self.window, stdscr)
        self.load_management_page(stdscr)
        self.handler.elements[0].set_focus(True)
        ret = self.handler.process()

    return ret

  def get_params(self):
    config_json = {}
    vswitches_list = []
    host_interfaces_list = []
    cvm_interfaces_list = []

    # Populate information for storage network.
    # This is required irrespective of single or separate network.
    # Vswitch info.
    if getattr(self, "storage_dev_box", None):
      vswitch_conf = {}
      vswitch_conf["name"] = "br0"
      vswitch_conf["bond_mode"] = "active-passive"
      vswitch_conf["uplinks"] = [dev for dev in self.storage_dev_box
                                 if self.storage_dev_box[dev].selected]
      vswitch_conf["mtu"] = self.vswitch_mtu.get_displayed_text()
      vswitches_list.append(vswitch_conf)

      # Host interface info.
      host_interfaces_conf = {}
      host_interfaces_conf["name"] = "br0"
      host_interfaces_conf["vswitch"] = "br0"
      host_interfaces_conf["vlan"] = convert_to_int(
          self.storage_vlan_tag.get_displayed_text())
      host_interfaces_conf["ip"] = self.storage_hyp_ip.get_displayed_text()
      host_interfaces_conf["netmask"] = self.storage_netmask.get_displayed_text()
      host_interfaces_conf["gateway"] = self.storage_gateway.get_displayed_text()

      host_interfaces_list.append(host_interfaces_conf)

      # CVM interface info.
      cvm_interfaces_conf = {}
      cvm_interfaces_conf["name"] = "eth0"
      cvm_interfaces_conf["vswitch"] = "br0"
      cvm_interfaces_conf["vlan"] = convert_to_int(
          self.storage_vlan_tag.get_displayed_text())
      cvm_interfaces_conf["ip"] = self.storage_cvm_ip.get_displayed_text()
      cvm_interfaces_conf["netmask"] = self.storage_netmask.get_displayed_text()
      cvm_interfaces_conf["gateway"] = self.storage_gateway.get_displayed_text()

      cvm_interfaces_list.append(cvm_interfaces_conf)

    # User selected a separate management network.

    # TODO: Remove this condition when support for management network is ready.
    if not DISABLE_MANAGEMENT_CHOICES and self.separate_network.selected:
      # User chose same interfaces for storage and management.
      if not self.management_choice_box.selected:
        # A separate subinterface has to be created on br0.
        host_interfaces_conf = {}
        host_interfaces_conf["name"] = "br0_mgmt"
        host_interfaces_conf["vswitch"] = "br0"
        host_interfaces_conf["vlan"] = convert_to_int(
            self.mgmt_vlan_tag.get_displayed_text())
        host_interfaces_conf["ip"] = self.mgmt_hyp_ip.get_displayed_text()
        host_interfaces_conf["netmask"] = self.mgmt_netmask.get_displayed_text()
        host_interfaces_conf["gateway"] = self.mgmt_gateway.get_displayed_text()

        host_interfaces_list.append(host_interfaces_conf)

        # Configure eth2 of cvm.
        cvm_interfaces_conf = {}
        cvm_interfaces_conf["name"] = "eth2"
        cvm_interfaces_conf["vswitch"] = "br0"
        cvm_interfaces_conf["vlan"] = convert_to_int(
            self.mgmt_vlan_tag.get_displayed_text())
        cvm_interfaces_conf["ip"] = self.mgmt_cvm_ip.get_displayed_text()
        cvm_interfaces_conf["netmask"] = self.mgmt_netmask.get_displayed_text()
        cvm_interfaces_conf["gateway"] = self.mgmt_gateway.get_displayed_text()

        cvm_interfaces_list.append(cvm_interfaces_conf)

      # User chose different interfaces for storage and management.
      else:
        # Create new vswitch.
        vswitch_conf = {}
        vswitch_conf["name"] = "br1"
        vswitch_conf["bond_mode"] = "active-passive"
        vswitch_conf["uplinks"] = [dev for dev in self.mgmt_dev_box
                                   if self.mgmt_dev_box[dev].selected]
        vswitches_list.append(vswitch_conf)


        # A separate subinterface has to be created on br0.
        host_interfaces_conf = {}
        host_interfaces_conf["name"] = "br1"
        host_interfaces_conf["vswitch"] = "br1"
        host_interfaces_conf["vlan"] = convert_to_int(
            self.mgmt_vlan_tag.get_displayed_text())
        host_interfaces_conf["ip"] = self.mgmt_hyp_ip.get_displayed_text()
        host_interfaces_conf["netmask"] = self.mgmt_netmask.get_displayed_text()
        host_interfaces_conf["gateway"] = self.mgmt_gateway.get_displayed_text()

        host_interfaces_list.append(host_interfaces_conf)

        # Configure eth2 of cvm.
        cvm_interfaces_conf = {}
        cvm_interfaces_conf["name"] = "eth2"
        cvm_interfaces_conf["vswitch"] = "br1"
        cvm_interfaces_conf["vlan"] = convert_to_int(
            self.mgmt_vlan_tag.get_displayed_text())
        cvm_interfaces_conf["ip"] = self.mgmt_cvm_ip.get_displayed_text()
        cvm_interfaces_conf["netmask"] = self.mgmt_netmask.get_displayed_text()
        cvm_interfaces_conf["gateway"] = self.mgmt_gateway.get_displayed_text()

        cvm_interfaces_list.append(cvm_interfaces_conf)

    # Fill json.
    config_json["vswitches"] = vswitches_list
    config_json["host_interfaces"] = host_interfaces_list
    config_json["cvm_interfaces"] = cvm_interfaces_list

    return config_json

class RdmaConfigGui(Gui):
  def __init__(self):
    super(RdmaConfigGui, self).__init__()

    self.rdma_capable_bus_addrs = crash_utils.get_rdma_nics()

    self.rdma_nics_info = crash_utils.get_ethernet_devices_details(self.rdma_capable_bus_addrs)

  def init_header(self, window, stdscr):
    y = 1; x_default = 10
    _, max_x = stdscr.getmaxyx()

    window.bkgdset(' ', curses.color_pair(2))
    window.clear()
    window.border()
    window.keypad(1)

    msg = "<< Nutanix Rdma Configuration >>"
    x_temp = (max_x/2 - len(msg)/2) or x_default
    window.addnstr(y, x_temp, msg, 50, curses.color_pair(1))

  def init_ui(self, stdscr):
    curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_RED)

    stdscr.bkgdset(' ', curses.color_pair(1))
    stdscr.clear()
    stdscr.border()

    max_y, max_x = stdscr.getmaxyx()
    self.window = stdscr.subwin(max_y-2, max_x-4, 1, 2)
    self.handler = ElementHandler(self.window)

  def show_rdma_details(self, window, handler, y, x, max_y, eths=[]):
    y += 2
    x_temp = x+2

    info_map = [self.rdma_nics_info[eth] for eth in eths]

    table = get_nic_info_table(info_map or self.rdma_nics_info.values())

    max_width = min(len(max(table, key=len)) + 3 , 79)
    max_height = min (max_y - 5 - y, 8)
    self.rdma_info_table = TextViewBlock(window, y, x, None, table,
                                         "RDMA NIC details",
                                         max_width + 3, max_height)
    handler.add(self.rdma_info_table)
    y += max_height
    return y, x

  def load_rdma_page(self, stdscr):
    # Initialize window.
    max_y, max_x = stdscr.getmaxyx()
    self.window = stdscr.subwin(max_y-2, max_x-4, 1, 2)
    self.init_header(self.window, stdscr)
    self.handler = ElementHandler(self.window)

    # Title of page
    y = 1; x = 5
    x_adj = 30; x_default = 10
    y += 2
    msg = "<< RDMA Network Configuration >>"
    x_temp = (max_x/2 - len(msg)/2) or x_default
    self.window.addnstr(y, x_temp, msg, 50, curses.color_pair(1))
    self.rdma_dev_box = {}

    # Description
    y += 1
    msg = "Choose RDMA NIC to Passthrough".ljust(x_adj)
    msg += ":"
    self.window.addnstr(y, x, msg, x_adj+1)

    x_temp = x + len(msg) + 1
    # Show only 4 devices in single line.
    # Show remaining devices on next line.
    for index, dev in enumerate(sorted(self.rdma_nics_info.keys())):
      if index != 0 and index % 4 == 0:
        x_temp = x + len(msg) + 1
        y += 2
      self.rdma_dev_box[dev] = CheckBox(self.window, y, x_temp,
                                        dev, False)
      x_temp += 10

      self.handler.add(self.rdma_dev_box[dev])

    y, x = self.show_rdma_details(self.window, self.handler,
                                 y, x, max_y)

    y += 1

    self.next_button = CrashCartButton(self.window, y, x, "Next",
                                       lambda e: ElementHandler.NEXT)
    self.handler.add(self.next_button)

    self.cancel_button = CrashCartButton(self.window, y, x+10, "Cancel",
                                         lambda e: ElementHandler.EXIT)
    self.handler.add(self.cancel_button)
    stdscr.refresh()

  def load_rdma_confirmation_page(self, stdscr):
    # Initialize window.
    max_y, max_x = stdscr.getmaxyx()
    self.window = stdscr.subwin(max_y-2, max_x-4, 1, 2)
    self.init_header(self.window, stdscr)
    self.handler = ElementHandler(self.window)

    # Title of page
    y = 1; x = 5
    x_adj = 30; x_default = 10
    y += 2
    msg = "<< RDMA Network Configuration >>"
    x_temp = (max_x/2 - len(msg)/2) or x_default
    self.window.addnstr(y, x_temp, msg, 50, curses.color_pair(1))

    # Description
    y += 1
    msg = "The following nics will be passed through".ljust(43)
    msg += ":"
    self.window.addnstr(y, x, msg, 44)

    selected_nics = self.get_selected_rdma_nics()
    passthru_nics = crash_utils.fix_passthru_nics(selected_nics)

    y,x = self.show_rdma_details(self.window, self.handler,
                                 y, x, max_y, passthru_nics)

    y += 1
    self.next_button = CrashCartButton(self.window, y, x, "Ok",
                                       lambda e:ElementHandler.EXIT)
    self.handler.add(self.next_button)

    self.cancel_button = CrashCartButton(self.window, y, x+10, "Cancel",
                                         lambda e:ElementHandler.EXIT)
    self.handler.add(self.cancel_button)
    stdscr.refresh()

  def interactive_ui(self, stdscr):
    if self.is_first:
      self.init_ui(stdscr)
      self.is_first = False

    self.init_header(self.window, stdscr)
    self.load_rdma_page(stdscr)
    self.handler.elements[0].set_focus(True)
    ret = self.handler.process()

    if ret == NEXT:
      self.init_header(self.window, stdscr)
      self.load_rdma_confirmation_page(stdscr)
      self.handler.elements[0].set_focus(True)
      ret = self.handler.process()

    return ret

  def get_selected_rdma_nics(self):
    if getattr(self, "rdma_dev_box", None):
      return [dev for dev in self.rdma_dev_box
              if self.rdma_dev_box[dev].selected]
    return []

  def get_params(self):
    config_json = {}
    rdma_nic_list = []
    for netdev in self.get_selected_rdma_nics():
      nic_config = {}
      nic_info = self.rdma_nics_info[netdev]
      nic_config["name"] = netdev
      nic_config["mac_addr"] = nic_info.mac_addr
      nic_config["bus_addr"] = nic_info.bus_addr
      rdma_nic_list.append(nic_config)

    config_json["rdma_nic_list"] = rdma_nic_list
    return config_json

def convert_to_int(number):
  try:
    return int(number)
  except Exception as e:
    return None

def run_gui(gui_obj):
  while True:
    if not isinstance(gui_obj, Gui):
      raise StandardError("Invalid Gui")

    try:
      is_save = curses.wrapper(gui_obj.interactive_ui)
    except curses.error, e:
      if e.args[0].count("str() returned ERR") > 0:
        print "Terminal screen is not large enough to run the installation " \
              "script. Please resize the terminal and rerun the script."
        sys.exit(1)
      raise e
    if not is_save:
      sys.exit(2)

    if is_save == CANCEL:
      return is_save, None

    try:
      params = gui_obj.get_params()
      return is_save, params
    except Exception as e:
      raw_input ("Press 'enter' to continue %s" % e )
