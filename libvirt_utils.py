import libvirt
import re
import xml.etree.ElementTree as et

import log
import kvm_net_utils

libvirtError = libvirt.libvirtError
libvirt_domain_update_flags = libvirt.VIR_DOMAIN_AFFECT_LIVE | libvirt.VIR_DOMAIN_AFFECT_CONFIG

def libvirt_connect():
  """
  Establishes a libvirt connection and returns a handle or None.
  """
  try:
    return libvirt.open(None) # Uses LIBVIRT_DEFAULT_URI
  except libvirtError as error:
    log.FATAL("Failed to connect to libvirt: %s" % error)

def get_cvm_domain(conn):
  """
  Obtains a libvirt handle to the CVM domain, or None. This function presumes
  that there is only one domain named like .*-CVM on the host.
  """
  try:
    domains = conn.listAllDomains(0)
  except libvirtError as error:
    log.FATAL("Failed to list KVM domains: %s" % (error,))

  for domain in domains:
    try:
      name = domain.name()
    except libvirtError as error:
      log.ERROR("Failed to get KVM domain name: %s" % (error,))
      continue

    if re.match(".*-CVM", name):
      return domain

  log.FATAL("Could not find CVM domain")

def detach_device(domain, xml):
  try:
    domain.detachDeviceFlags(xml, libvirt_domain_update_flags)
  except libvirtError as ex:
    log.FATAL("Failed to detach %s : %s" % (xml, ex))

def attach_device(domain, xml):
  try:
    domain.attachDeviceFlags(xml, libvirt_domain_update_flags)
  except libvirtError as ex:
    log.FATAL("Failed to attach %s : %s" % (xml, ex))

def update_device_xml(domain, old_xml, new_xml):
  detach_device(domain, old_xml)
  attach_device(domain, new_xml)

def update_cvm_domain(domain, cfg):
  """
  Find network interface corresponding to eth_dev and add br_name, vlan_tag.
  Return True if successful, False otherwise.
  Ethernet devices are matched by mac addresses and no dependency is kept on
  ordering of devices.
  """
  log.INFO("Updating cvm xml file for network devices")

  cvm_interfaces = cfg["cvm_interfaces"]
  name_mac_map = {}
  for interface in cvm_interfaces:
    if interface["vswitch"] == "_internal_":
      continue
    out = kvm_net_utils.get_mac_address(interface["name"])
    mac_addr = out.strip()
    name_mac_map[interface["name"]] = mac_addr


  xmldesc = et.fromstring(domain.XMLDesc(0))

  for interface in cvm_interfaces:
    mac_addr = name_mac_map[interface["name"]]
    vlan_tag = interface["vlan"]
    if vlan_tag is not None and int(vlan_tag) >= 0 and int(vlan_tag) <= 4095:
      vlan_tag = str(vlan_tag)
    else:
      vlan_tag = None

    vswitch = interface["vswitch"]

    found = False
    for desc in xmldesc.findall("./devices/interface"):
      if ((desc.attrib["type"] == "bridge" and
           desc.find("./source").attrib["bridge"] in
           kvm_net_utils.VALID_VSWITCHES or
           (desc.attrib["type"] == "network" and
            desc.find("./source").attrib["network"] != "NTNX-Local-Network"))):

        old_xml = et.tostring(desc)

        if desc.find("./mac").attrib["address"] != mac_addr:
          continue

        found = True

        # Force interface type to be bridge.
        desc.attrib["type"] = "bridge"
        map(desc.remove, desc.findall("./source"))
        et.SubElement(desc, "source", {"bridge": vswitch})

        # Delete QEMU/libvirt assigned device names, let it pick a new one.
        map(desc.remove, desc.findall("./alias"))
        map(desc.remove, desc.findall("./target"))

        # Delete OVS related stuff such as UUIDs.
        map(desc.remove, desc.findall("./virtualport"))
        et.SubElement(desc, "virtualport", {"type": "openvswitch"})

        # Add vlan tagging.
        vlandesc = desc.find("./vlan")
        if vlan_tag and not vlandesc: # Add vlan tag.
          vlandesc = et.SubElement(desc, "vlan")
          et.SubElement(vlandesc, "tag", {"id": vlan_tag})
        elif not vlan_tag and vlandesc: # Remove vlan tag.
          desc.remove(vlandesc)
        elif (vlan_tag and vlandesc and
              vlandesc.find("./tag").attrib["id"] != vlan_tag): # Change tag.
          desc.remove(vlandesc)
          vlandesc = et.SubElement(desc, "vlan")
          et.SubElement(vlandesc, "tag", {"id": vlan_tag})

        new_xml = et.tostring(desc)

        log.INFO("Replacing external NIC %s in CVM" % interface["name"])
        update_device_xml(domain, old_xml, new_xml)

        log.INFO("CVM external NIC %s successfully updated" % interface["name"])
        break
    if not found:
      log.FATAL("Could not find external NIC in CVM XML descriptor")

  return True


def configure_cvm_interfaces(cfg):
  """
  Configures cvm interfaces in xml.
  Returns True if successful, Fatals otherwise.
  """

  log.INFO("Configuring cvm interfaces")
  conn = libvirt_connect()
  domain = get_cvm_domain(conn)
  update_cvm_domain(domain, cfg)
  conn.close()
  return True

def attach_passthru_device(domain, address):
  bus, slot, func = re.split("\.|:", address)
  xmldesc = et.fromstring(domain.XMLDesc(0))
  devices_desc = xmldesc.find("./devices")
  hostdev_desc = et.SubElement(devices_desc, "hostdev", {"mode": "subsystem",
                                                         "type": "pci",
                                                         "managed": "yes"})
  source_desc = et.SubElement(hostdev_desc, "source", {})
  et.SubElement(source_desc, "address", {"domain": "0x0000",
                                         "bus": "0x" + bus,
                                         "slot": "0x" + slot,
                                         "function": "0x" + func})
  et.SubElement(hostdev_desc, "rom", {"bar": "off"})
  attach_device(domain, et.tostring(hostdev_desc))

def get_host_device_xml(domain, address):
  bus, slot, func = re.split("\.|:", address)

  xmldesc = et.fromstring(domain.XMLDesc(0))
  for desc in xmldesc.findall("./devices/hostdev"):
    dev_xml = et.tostring(desc)
    src_address = desc.find("./source/address")
    if (src_address.attrib["domain"] == "0x0000" and
        src_address.attrib["bus"] == "0x%s" % bus and
        src_address.attrib["slot"] == "0x%s" % slot and
        src_address.attrib["function"] == "0x%s" % func):
      return desc, dev_xml
  return None, None
