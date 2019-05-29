#!/usr/bin/python
#
# Copyright (c) 2018 Nutanix Inc. All rights reserved.
#
# Author: sadhana.kannan@nutanix.com
#
# Contains common functions used by crashcart
import json
import os

import firstboot_utils as utils
import netUtil

from log import ERROR, FATAL

HW_CONFIG_PATH = "/root/nutanix-network-crashcart/hardware_config.json"

SVM_SSH_KEY_PATH = "/root/nutanix-network-crashcart/nutanix"
SSH_PATH = "/usr/bin/ssh"
SCP_PATH = "/usr/bin/scp"

def check_if_in_cluster(fatal=False):
  """
  Check if node is in a cluster
  """
  cmd = "ls /tmp/svm_boot_succeeded"
  _, _, ret = utils.run_cmd_on_svm(cmd, dest_host="nutanix@192.168.5.254",
                                     attempts=3, retry_wait=1,
                                     fatal=False)
  if ret:
     # Check if ssh into svm ?
     #  - If no, then node is in cluster as user would have changed
     #    default username/passwd
     #  - If yes, then node is not in cluster
    return True
  return False

def get_rdma_nics(hw_layout=None):
  """
  Returns the bus_address for rdma nics from hardware_config.json
  """
  if not hw_layout:
    hw_layout = get_hardware_layout()
    if not hw_layout:
      FATAL("Unable to find hardware_config.json")
  rdma_nics = []
  for nic in hw_layout["node"].get("network_adapters", []):
    if "rdma" in nic.get("features", []):
      rdma_nics.append(nic["address"])
  if rdma_nics:
    return utils.get_pci_bus_addresses(rdma_nics, "kvm")
  return []

def get_hardware_layout():
  hw_layout = None
  with open(HW_CONFIG_PATH, "r") as fp:
    hw_layout = json.load(fp)
  return hw_layout

class NicInfo(object):
  def __init__(self, netdev):
    self.dev = netdev
    self.mac_addr = netUtil.get_mac_addr(self.dev)
    self.link, self.speed = get_nic_link_status_and_speed(self.dev)
    self.model, self.pci_id, self.bus_addr = get_nic_model_and_pci_info(self.dev)

def detect_ethernet_devices():
  """
  Return ethernet devices in sorted order.
  """
  results = []
  base = "/sys/class/net"
  for netdev in os.listdir(base):
    # Determine the absolute path, and filter out non-PCI devices
    path = os.path.realpath(os.path.join(base, netdev))
    if not path.startswith("/sys/devices/pci"):
      continue
    driver = os.path.basename(os.path.realpath(os.path.join(path,
                                                            "device",
                                                            "driver")))
    if driver != "cdc_ether":
      results.append(netdev)

  return sorted(results)

def get_nic_link_status_and_speed(netdev):
  """
  Returns the link status and speed on NIC.
  """
  cmd = ["/sbin/ethtool", netdev]
  out, _, _ = utils.run_cmd_new(cmd, fatal=False)
  if not out:
    ERROR("No output for cmd %s" % cmd)
    return None, None
  try:
    for line in out.splitlines():
      line = line.strip()
      if line.startswith("Link detected"):
        link = line.split(":")[1].strip()
      if line.startswith("Speed"):
        speed = line.split(":")[1].strip()
    return link, speed
  except Exception as e:
    ERROR("Exception %s" % e)
    return None, None

def get_nic_model_and_pci_info(netdev):
  """
  Returns nic model and pci_id and pci_slot
  """
  file_name = "/sys/class/net/%s/device/uevent" % netdev
  try:
    pci_slot = None
    pci_id = None
    with open(file_name) as fd:
      for line in fd.read().splitlines():
        if line.startswith("PCI_SLOT_NAME"):
          pci_slot = line.split("=")[1].strip()
        if line.startswith("PCI_ID"):
          pci_id = line.split("=")[1].strip()
  except Exception as e:
    FATAL("Failed to read %s" % file_name)
  model = "Unknown"
  cmd = ["lspci", "-mmvv", "-s", pci_slot]
  output, _, _ = utils.run_cmd_new(cmd)
  for line in output.splitlines():
    if line.startswith("Device"):
      model = line.strip().split()[1]
      break
  # pci_slot contains domain, eg: 0000:88:6.0
  bus_addr = pci_slot[5:]
  return model, pci_id, bus_addr

def get_ethernet_devices_details(bus_addr_list=None):
  """
  Returns a dict "device_name" : (description, speed, link) if successful,
  Fatals otherwise.
  """
  eth_devs = detect_ethernet_devices()
  if bus_addr_list:
    eth_devs = [netUtil.get_netdev_from_bus_addr(x) for x in bus_addr_list]

  eth_devs = sorted(eth_devs, reverse=True)

  output = {}
  for dev in eth_devs:
    output[dev] = NicInfo(dev)

  return output

def fix_passthru_nics(rdma_netdevs):
  """
  Since only nic_passthru is supported,
  returns all nics to be passed through to pass through rdma_netdevs
  Args:
    rdma_netdevs (list): List of intf names selected
  """
  out = set(rdma_netdevs)
  rdma_capable_nics = get_rdma_nics()

  for netdev in rdma_netdevs:
    nic_info = NicInfo(netdev)
    index = rdma_capable_nics.index(nic_info.bus_addr)
    other_index = index + 1 if index%2 == 0 else index - 1
    out.add(netUtil.get_netdev_from_bus_addr(
      rdma_capable_nics[other_index]))

  return list(out)
