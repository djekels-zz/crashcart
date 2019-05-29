#
# Copyright (c) 2015 Nutanix Inc. All rights reserved.
#
# Author: akshay@nutanix.com
#
# This module contains functions for configuring networks on kvm.
#
import os
import re
import time

from firstboot_utils import (
    run_cmd, run_cmd_new, run_cmd_on_svm)
from log import INFO, WARNING

VM_NETWORK_XML = """
<network connections='1'>
  <name>VM-Network</name>
  <forward mode='bridge'/>
  <bridge name='br0' />
  <virtualport type='openvswitch'/>
  <portgroup name='VM-Network' default='yes'>
  </portgroup>
</network>
"""

NTNX_LOCAL_NETWORK_XML = """
<network connections='1'>
  <name>NTNX-Local-Network</name>
  <bridge name='virbr0' stp='off' delay='0' />
  <ip address='192.168.5.1' netmask='255.255.255.0'>
  </ip>
</network>
"""

LIBVIRT_NETWORKS = {
  "VM-Network" : VM_NETWORK_XML,
  "NTNX-Local-Network" : NTNX_LOCAL_NETWORK_XML,
}

TEN_GIG_NIC_TYPES = frozenset(["ixgbe", "i40e"])

VALID_VSWITCHES = ["br0", "br1"]

# For full list of acceptable bond-modes, read
# http://openvswitch.org/support/dist-docs/ovs-vswitchd.conf.db.5.txt
# Here, we allow only what is tested in lab.
VALID_BOND_MODES = ["active-backup", "balance-tcp", "balance-slb"]
DEFAULT_BOND_MODE = "active-backup"
DEFAULT_UPLINKS = ["igb", "ixgbe", "i40e", "mlx4_core", "mlx5_core"]

def get_supported_speeds(intf):
  """
  Find the supported speeds for an interface.

  Args:
    intf: Name of the interface.

  Returns:
    List of supported speeds in Gbps. If unable to figure out the speed,
    empty list is returned.
  """
  speeds = []
  out, _, ret = run_cmd_new(["ethtool", intf], fatal=False)
  if ret:
    return speeds

  regex = re.compile(r"Supported link modes:((\s+\d+.+\n)+)")
  match = regex.search(out)
  if match:
    modes_str = match.group(1)
    for t in modes_str.strip().split("\n"):
      speed_list = re.findall(r'\d+', t)
      if speed_list:
        speeds.append(int(speed_list[0]))
  return speeds

def get_max_supported_speed(intf):
  """
  Find the maximum supported speed for an interface.

  Args:
    intf: Name of the interface.

  Returns:
    Maximum speed supported by the interface. If speed cannot be determined,
    -1 is returned.
  """
  supported_speeds = get_supported_speeds(intf)
  if supported_speeds:
    return max(supported_speeds)
  return -1

def get_netdevs(passthru_nics=[]):
  """
  Returns a list of NIC. Returns tuple:
  (name, mac, driver, pci_addr)

  Args:
    passthru_nics : List of bus address of passthru nics
  """
  results = []
  base = "/sys/class/net"
  for netdev in os.listdir(base):
    # Determine the absolute path, and filter out non-PCI devices
    path = os.path.realpath(os.path.join(base, netdev))
    if not path.startswith("/sys/devices/pci"):
      continue
    pci_addr = os.path.dirname(os.path.dirname(path))
    pci_addr = pci_addr.split("/")[-1]

    bus_addr = os.path.basename(os.path.dirname(os.path.dirname(path)))
    bus_addr = bus_addr[(bus_addr.find(":") + 1):]
    if bus_addr in passthru_nics:
      continue

    addr = open(os.path.join(path, "address")).read().strip()
    driver = os.path.basename(
        os.path.realpath(os.path.join(path, "device", "driver")))
    max_speed = get_max_supported_speed(netdev)
    results.append((netdev, addr.lower(), driver, str(pci_addr), max_speed))
  return results

def nic_supports_speeds(intf, speeds):
  """
  Detects whether an interface supports any of the given list of speeds.

  Args:
    intf: Name of the interface.
    speeds: List of speeds in Mbps.

  Returns:
    True if the interface supports any of the given list of speeds.
    False otherwise.
  """
  if not speeds:
    return False
  supported_speeds = get_supported_speeds(intf)
  if not supported_speeds:
    return False
  for s in speeds:
    if int(s) in supported_speeds:
      return True
  return False

def get_vswitch_links(vs, nics):
  """
  Figures out the uplinks in a vswitch.

  Args:
    vs: Vswitch dictionary from first boot config.
    nics: List of nics to be considered for the vswitch with nic details.

  Returns:
    Tuple containing the list of uplink devs and remaining nics.
  """
  uplink_devs = []
  vs_uplinks = vs.get("uplinks", []) or DEFAULT_UPLINKS
  uplink_speeds = vs.get("uplink_speeds", [])
  for uplink in vs_uplinks:
    # Uplink can be specified by name, address or driver
    remaining_nics = []
    for dev, addr, driver, pci_addr, max_speed in nics:
      if dev == uplink or addr == uplink.lower() or driver == uplink:
        if uplink_speeds:
          # If uplink speeds are provided, add only nics with those speeds.
          if nic_supports_speeds(dev, uplink_speeds):
            uplink_devs.append(dev)
          else:
            remaining_nics.append((dev, addr, driver, pci_addr, max_speed))
        else:
          uplink_devs.append(dev)
      else:
        remaining_nics.append((dev, addr, driver, pci_addr, max_speed))
    nics = remaining_nics
  return uplink_devs, remaining_nics

def is_interface_up(intf):
  out = run_cmd(["ifconfig", intf], fatal=False)
  if "UP" in out:
    return True
  return False

def configure_ovs(cfg, passthru_nics=None, arch="x86_64"):
  passthru_nics = passthru_nics or []
  run_cmd(["/sbin/restorecon", "-R", "/etc/sysconfig/network-scripts"])

  #### First, create the vswitches ####
  nics = get_netdevs(passthru_nics=passthru_nics)

  # Removing usb ethernet nics from eligible nics
  nics = filter(lambda nic: nic[2] != "cdc_ether", nics)
  # Sort nics based on max speed.
  nics = sorted(nics, key=lambda x: x[4], reverse=True)

  original_nics = [nic[0] for nic in nics]
  vswitches = cfg["vswitches"]

  # If vswitches is not specified, populate from old fields for
  # backwards compatibility
  if not vswitches:
    br0 = {"name": "br0", "uplinks": [], "bond-mode": DEFAULT_BOND_MODE}
    vswitches = [br0]

  # Populate empty br0 uplinks.
  if len(vswitches) == 1 and not vswitches[0].get("uplinks", []):
    br0 = vswitches[0]
    if cfg["use_ten_gig_only"]:
      nics = filter(lambda nic: nic[2] in TEN_GIG_NIC_TYPES, nics)
    br0["uplinks"] = [nic[0] for nic in nics]

  vswitch_uplinks = {}

  for vs in vswitches:
    name = vs["name"]
    vs["uplink_speeds"] = [int(speed) for speed in vs.get("uplink_speeds", [])]
    uplink_speeds = vs["uplink_speeds"]
    if not nics:
      raise StandardError("No nic available to use with vswitch %s" % name)
    uplink_devs, rem_nics = get_vswitch_links(vs, nics)

    if not uplink_devs:
      if uplink_speeds:
        # ENG-103044: Foundation couldn't find any uplink with the given
        # speeds. Fallback to the nic with highest speed.
        max_speed = nics[0][4]
        if max_speed not in uplink_speeds:
          INFO("No nics with speed in %s were found. Using nics "
               "with highest available speed %d"
               % (uplink_speeds, max_speed))
          vs["uplink_speeds"].append(max_speed)
          uplink_devs, rem_nics = get_vswitch_links(vs, nics)

    if not uplink_devs:
      raise StandardError("Could not find any uplinks which could be added "
                          "to vswitch %s" % name)
    vswitch_uplinks[name] = uplink_devs
    nics = rem_nics

    cmds = ["add-br " + name]
    INFO("Adding %s to the list of uplinks for vswitch %s"
         % (uplink_devs, name))

    # Set MTU properly for each uplink, then reload each interface
    for dev in uplink_devs:
      with open("/etc/sysconfig/network-scripts/ifcfg-" + dev, "a") as ifcfg:
        ifcfg.write('MTU=%d\n' % vs.get("mtu", 1500))
      if arch == "x86_64" or is_interface_up(dev):
        run_cmd(["/sbin/ifdown", dev], fatal=False)
        run_cmd(["/sbin/ifup", dev], fatal=False)

    # Build OVS transaction, then execute all commands for this vswitch in a
    # single transaction.
    if len(uplink_devs) > 1:
      cmds.append("add-bond %s %s-up %s" % (name, name, " ".join(uplink_devs)))
    elif len(uplink_devs) == 1:
      cmds.append("add-port %s %s" % (name, uplink_devs[0]))
    elif len(uplink_devs) == 0:
      # If no desired uplink_devs are found then default to using all NICs in
      # the bond.
      cmds.append("add-bond %s %s-up %s" %
                  (name, name,
                   " ".join(original_nics)))

    uname_r = run_cmd(["uname", "-r"])
    if uname_r.startswith("2.6."):
      for dev in uplink_devs:
        cmds.append("set interface %s other-config:enable-vlan-splinters=true" %
                    (dev,))
    # Set LACP.
    if vs.get("lacp", None):
      cmds.append("set port %s-up lacp=%s" % (name, vs["lacp"]))

    # Set bond mode.
    if len(uplink_devs) != 1 and "bond-mode" in vs:
      bond_mode = vs["bond-mode"]
      if bond_mode in VALID_BOND_MODES:
        cmds.append("set port %s-up bond_mode=%s" % (name, bond_mode))
      else:
        WARNING("invalid bond-mode(%s), ignored" % bond_mode)
    # Set other configs.
    if vs.get("other_config", None):
      for other_config in vs["other_config"]:
        cmds.append("set port %s-up other_config:%s" % (name, other_config))
    run_cmd(["ovs-vsctl " + " -- ".join(cmds)])

  #### Second, configure the internal interfaces ####

  host_interfaces = cfg["host_interfaces"]
  # Backwards compatibility
  if not host_interfaces:
    host_interfaces = [{"name": "br0", "vswitch": "br0"}]
    host_interfaces[0]["vlan"] = cfg.get("cvm_vlan_id")

  for iface in host_interfaces:
    cmds = []
    name = iface["name"]
    vswitch = iface["vswitch"]
    vlan = iface.get("vlan")
    # If the interface name is not the same as the vswitch, then the
    # internal port needs to be explicitly created.
    if name != vswitch:
      cmds.append("add-port %s %s" % (vswitch, name))
      cmds.append("set interface %s type=internal" % name)
    if vlan >= 0:
      cmds.append("set port %s tag=%d" % (name, int(vlan)))
    if cmds:
      run_cmd(["ovs-vsctl " + " -- ".join(cmds)])

    # Add dependent interfaces to OVSREQUIRES
    with open("/etc/sysconfig/network-scripts/ifcfg-" + name, "a") as ifcfg:
      uplinks = vswitch_uplinks[vswitch]
      if arch == "ppc64le":
        uplinks = [uplink for uplink in uplinks if is_interface_up(uplink)]
      ifcfg.write('OVSREQUIRES="%s"\n' % " ".join(uplinks))

  # Sleep for 5 seconds, then reload all host_interfaces.
  time.sleep(5)  # For the uplinks to come up.
  for iface in host_interfaces:
    run_cmd(["/sbin/ifdown", iface["name"]], fatal=False)
    run_cmd(["/sbin/ifup", iface["name"]], fatal=False)
  run_cmd(["service", "network", "restart"], fatal=False)

  # ENG-57953 Fix arp table for bad switches.
  # This is similar to what livecd.sh does to make things work for phoenix.
  for iface in host_interfaces:
    iface_name = iface["name"]
    interface_config = parse_interface_config(iface_name)
    if (interface_config and
        interface_config.get("BOOTPROTO", "").lower() is not "dhcp" and
        interface_config.get("IPADDR") and
        interface_config.get("NETMASK")):

      ip = interface_config["IPADDR"]

      # Update switch ARP table.
      run_cmd(["arping -A -I %s %s -c 1" % (iface_name, ip)], fatal=False)
      run_cmd(["sleep 2"], fatal=False)
      run_cmd(["arping -U -I %s %s -c 1" % (iface_name, ip)], fatal=False)

      # Broadcast ping. Seems to help with broken switches.
      netmask = interface_config["NETMASK"]
      out = run_cmd(["ipcalc -b %s %s" % (ip, netmask)], fatal=False)

      if out and out.strip():
        try:
          # out looks like BROADCASTIP=some_ip.
          broadcast_ip = out.strip().split("=")[1]
          run_cmd(["ping -b -c 1 %s -W 1" % broadcast_ip], fatal=False)
        except IndexError:
          pass


def parse_interface_config(interface):
  interface_config = {}

  interface_config_file = "/etc/sysconfig/network-scripts/ifcfg-%s" % interface
  if not os.path.exists(interface_config_file):
    return interface_config

  with open(interface_config_file) as fp:
    config = fp.read()
    for line in config.strip().splitlines():
      if line.startswith("#"):
        continue
      try:
        key, value = line.strip().split("=")
        interface_config[key] = value
      except ValueError:
        pass
  return interface_config

def undefine_libvirt_network(name, destroy=True, fatal=False):
  out = run_cmd(["virsh", "net-list", "--all"])
  if name in out:
    if destroy:
      run_cmd(["virsh", "net-destroy", name], fatal=fatal)
    run_cmd(["virsh", "net-undefine", name], fatal=fatal)

def create_libvirt_networks():
  # Delete "default" network installed by libvirt.
  undefine_libvirt_network("default")

  for net, xml in LIBVIRT_NETWORKS.items():
    undefine_libvirt_network(net)
    xmlpath = "/root/net-%s.xml" % net
    open(xmlpath, "w").write(xml)
    run_cmd(["virsh net-define %s" % xmlpath])
    run_cmd(["virsh net-start %s" % net])
    run_cmd(["virsh net-autostart %s" % net])

def delete_all_vswitches():
  """
  Delete vswitches created by Nutanix.
  Returns True if successful, Fatals otherwise.
  """
  # Get a list of bridges.
  cmd = ["ovs-vsctl list-br"]
  out = run_cmd(cmd)

  current_bridges = [ br.strip() for br in out.splitlines()]

  # Create a bridge if does not already exist.
  for br in VALID_VSWITCHES:
    if br in current_bridges:
      cmd = ["ovs-vsctl del-br %s" % br]
      out = run_cmd(cmd)

      ifcfgfile = "/etc/sysconfig/network-scripts/ifcfg-%s" % br
      cmd = ["rm -f %s" % ifcfgfile]
      out = run_cmd(cmd)

  return True

def get_mac_address(interface):
  """
  Get mac address of interface from cvm.
  Returns address if successful, None otherwise.
  """
  file_name = "/sys/class/net/%s/address" % interface

  cmd = "sudo cat %s" % file_name
  out, _, _ = run_cmd_on_svm(cmd, dest_host="nutanix@192.168.5.254")
  return out

def modify_active_slave_in_ovs_bond(target_ip, bond_name="br0-up",
                                    arch="x86_64"):
  """
  Modifies OVS bond to set active nic as the one which can reach a target
  ip.
  Args:
    target_ip: IP address to ping in order to verify connectivity.

  Raises:
    StandardError if no nic which can reach target ip is found.

  Return:
    None
  """
  out, _, _ = run_cmd_new(["ovs-appctl", "bond/list"])
  # Output will be of the following form:
  # bond    type    recircID    slaves
  # br0-up    active-backup    0    eth1, eth0
  intfs = []
  for line in out.splitlines():
    words = line.split()
    if words[0] != bond_name:
      continue
    for i in range(3, len(words)):
      words[i] = words[i].strip().replace(",", "")
      if arch == "x86_64" or is_interface_up(words[i]):
        speed_file = "/sys/class/net/%s/speed" % words[i]
        speed = int(open(speed_file).read().strip())
        intfs.append((words[i], speed))
    break

  # Sort the nics according to speed and test connectivity.
  intfs = sorted(intfs, key=lambda x:x[1], reverse=True)
  active_nic = None
  for intf in intfs:
    if intf[1] > 0:
      _, _, ret = run_cmd_new(["ovs-appctl", "bond/set-active-slave",
                              bond_name, intf[0]], fatal=False)
      if ret:
        INFO("Failed to set %s as the active slave in bond %s"
             % (intf[0], bond_name))
        continue
      _, _, ret = run_cmd_new(["ping", "-c", "1", target_ip],
                              timeout=60, attempts=5, fatal=False)
      if not ret:
        INFO("Using %s as the active slave in bond %s" % (intf[0], bond_name))
        active_nic = intf[0]
        break

  if not active_nic:
    raise StandardError("Could not find any interface which could reach "
                        "target ip %s" % target_ip)
