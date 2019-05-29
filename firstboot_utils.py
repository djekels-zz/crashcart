#!/usr/bin/env python
#
# Copyright (c) 2014 Nutanix Inc. All rights reserved.
#
# Author: bfinn@nutanix.com
#
# This module provides system utilities common to ESX and KVM firstboot.

import errno
import os
import re
import shutil
import subprocess
import time
import threading

from log import INFO, FATAL, ERROR

# Constants to represent state of the system.
ONE_NODE_INSTALL_SUCCESS = "one_node_install_success"

SVM_SSH_KEY_PATH = None
SSH_PATH = None
SCP_PATH = None

def initialize_ssh_keys(svm_ssh_key_path, ssh_path, scp_path):
  global SVM_SSH_KEY_PATH
  global SSH_PATH
  global SCP_PATH
  SVM_SSH_KEY_PATH = svm_ssh_key_path
  SSH_PATH = ssh_path
  SCP_PATH = scp_path


def run_cmd(cmd_array, retry=False, fatal=True, timeout=None, quiet=False):
  """
  Runs a system command specified in the cmd_params array. The function
  exits if the execution of the command fails. If retry is set,
  a retry of the command is carried out until success.

  NOTE: This method is deprecated, please use run_cmd_new for any new code.
  """
  if retry:
    attempts = 5
  else:
    attempts = 1
  stdout, stderr, return_code = run_cmd_new(
    cmd_array=cmd_array, attempts=attempts, fatal=fatal, timeout=timeout,
    quiet=quiet)
  return stdout


def run_cmd_new(cmd_array, attempts=1, retry_wait=5, fatal=True, timeout=None,
                quiet=False):
  """
  Runs a system command specified in the cmd_params array.

  Args:
    cmd_array: shell command represented as array. e.g. ["ls", "-l"]
    attempts: Number of attempts of the command.
    retry_wait: time (in seconds) to wait before retrying.
    fatal: Method exists with FATAL if True.
    timeout: time in seconds to wait for a command to complete.
    quiet: If True doesn't print INFO messages.

  NOTE:
    Since, we are running our subprocess with shell=True timeout will
    actually kill the shell. This in most cases would kill the actual process
    also but in some cases the process may chose to ignore that the shell sent
    it a kill signal. One way to fix this is to not use shell=True and
    refactor all our code to be not dependent on shell being present.

  Returns:
    (stdout, stderr, return_code), exits with FATAL if fatal=True
  """

  cmd_array = [" ".join(cmd_array)]
  if not quiet:
    INFO("Running cmd %s" % cmd_array)

  stdout = ""
  stderr = ""
  return_code = 0

  for _ in range(attempts):
    process = subprocess.Popen(cmd_array, shell=True, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    process.timed_out = False

    def kill_process():
      ERROR("Killing timed out process %s" % process.pid)
      process.timed_out = True
      try:
        process.kill()
      except OSError as e:
        # There is a small window in which process can die while thread is
        # trying to send kill signal.
        if e.errno == errno.ESRCH:
          pass
        else:
          raise

    timer = threading.Timer(timeout, kill_process)
    timer.start()
    stdout, stderr = process.communicate()
    stdout = stdout.decode('utf-8', 'ignore')
    stderr = stderr.decode('utf-8', 'ignore')
    return_code = process.returncode
    timer.cancel()
    if not return_code:
      return stdout.strip(), stderr.strip(), return_code
    else:
      if process.timed_out:
        if not quiet:
          INFO("Execution of command %s failed to finish within %s seconds, "
                "exit code: %s, stdout: %s, stderr: %s" %
                (cmd_array, timeout, return_code, stdout, stderr))
      else:
        if not quiet:
          INFO("Execution of command %s failed, exit code: %s, stdout: %s, "
                "stderr: %s" % (cmd_array, return_code, stdout, stderr))
      time.sleep(retry_wait)
  else:
    if fatal:
      FATAL("Execution of command %s failed, exit code: %s, stdout: %s, "
            "stderr: %s" % (cmd_array, return_code, stdout, stderr))
    else:
      return stdout.strip(), stderr.strip(), return_code


def run_cmd_on_svm(cmd=None, dest_host="nutanix@192.168.5.2", attempts=5,
                   retry_wait=5, fatal=True, timeout=None, quiet=False):
  """
  This function will run a command on the SVM
  """
  if not quiet:
    INFO("Run ssh cmd on SVM")
  ssh_key_path = SVM_SSH_KEY_PATH
  return run_cmd_on_server(
    cmd=cmd, dest_host=dest_host, ssh_key_path=ssh_key_path, fatal=fatal,
    attempts=attempts, retry_wait=retry_wait, timeout=timeout, quiet=quiet)


def run_cmd_on_server(cmd, dest_host, ssh_key_path=None,
                      attempts=1, retry_wait=5, fatal=True, timeout=None,
                      quiet=False):
  """
  This function will run a command on the specified server
  """
  if not ssh_key_path:
    ssh_key_path = SVM_SSH_KEY_PATH

  common_args = ["-i", ssh_key_path,
                 "-o", "StrictHostKeyChecking=no",
                 "-o", "NumberOfPasswordPrompts=0",
                 "-o", "UserKnownHostsFile=/dev/null"]

  # SSH
  cmd_array = [SSH_PATH] + common_args + [dest_host, '"%s"' % cmd]
  return run_cmd_new(cmd_array=cmd_array, attempts=attempts,
                     retry_wait=retry_wait, fatal=fatal, timeout=timeout,
                     quiet=quiet)


def scp_files_to_svm(src_path, dest_path, dest_host="nutanix@192.168.5.2",
                     retry=True, fatal=True):
  """
  This function will SCP files to the SVM
  """
  INFO("SCP files to SVM")
  ssh_key_path = SVM_SSH_KEY_PATH
  scp_files_to_server(src_path, dest_path, dest_host, retry, ssh_key_path,
                      fatal)


def scp_files_to_server(src_path, dest_path, dest_host=None, retry=True,
                        ssh_key_path=None, fatal=True):
  """
  This function will SCP files to the specified server
  """
  if not ssh_key_path:
    ssh_key_path = SVM_SSH_KEY_PATH

  common_args = ["-i", ssh_key_path,
                 "-o", "StrictHostKeyChecking=no",
                 "-o", "NumberOfPasswordPrompts=0",
                 "-o", "UserKnownHostsFile=/dev/null"]

  run_cmd([SCP_PATH] + common_args +
            [src_path, "%s:%s" % (dest_host, dest_path)],
            retry=retry, fatal=fatal)


def get_pci_bus_addresses(pci_addresses, hyp_type):
  """
  Returns the pci bus addresses corresponding to the pci addresses provided.
  Args:
    pci_addresses: List of addresses where each address is of the form
        <vendor_id>:<device_id>:<index>. The index uniquely identifies the pci
        bus corresponding to the vendor id and device id.
    hyp_type: Hypervisor for which the bus addresses needs to be obtained.

  Returns:
    List of pci bus addresses. For AHV, the bus address lacks the domain
    prefix. For ESX, the domain prefix will be part of the address.
  """
  if not pci_addresses or hyp_type not in ["kvm", "esx"]:
    return []
  out = run_cmd(["lspci", "-n"])
  # pci_addresses will be a list of the form ["15b3:1007:1", "15b3:1009:0"].
  pci_ids = [":".join(pci_id.split(":")[0:2]) for pci_id in (
      pci_addresses)]
  pci_devices = []
  for line in out.splitlines():
    if hyp_type == "kvm":
      dev_parts = line.split()
      addr = dev_parts[0]
      pci_id = dev_parts[2]
      vendor_id, device_id = [d.lower() for d in pci_id.split(":")]
    elif hyp_type == "esx":
      match = re.search(r"(\w+:\w+:\w+.\w+) .+? (\w{4}:\w{4}).*", line)
      if match:
        addr = match.group(1)
        pci_id = match.group(2)
        vendor_id, device_id = pci_id.split(":")
      else:
        continue

    if pci_id in pci_ids:
      pci_devices.append([addr, vendor_id, device_id])

  def _pci_search(vendor_id, device_id):
    bus_list = []
    for dev in pci_devices:
      addr, v_id, d_id = dev
      if vendor_id != v_id or device_id != d_id:
        continue
      bus_list.append(addr)
    return bus_list

  bus_addr_list = []
  for dev in pci_addresses:
    vendor_id, device_id, index = dev.split(":")
    bus_list = _pci_search(vendor_id, device_id)
    bus_addr_list.append(bus_list[int(index)])
  return bus_addr_list


def configure_ptagent(ptagent_config_file):
  """

  Args:
    ptagent_config_file(str): path to the config file.

  Returns:
    None
  """
  with open(ptagent_config_file) as fp:
    lines = fp.readlines()

  configs = {"rest_ip": "0.0.0.0:8086",
             "rest_auth": "disabled",
             "monitor_restarts_on_exit": "enabled"}
  # esx config apparently has empty lines
  lines = [line for line in lines if line.strip()]

  for key in configs:
    new_lines = lines[:]
    for i, line in enumerate(lines):
      if key in line:
        new_lines.pop(i)
        new_line = "%s=%s\n" % (key, configs[key])
        new_lines.insert(i, new_line)
        break
    else:
      new_lines.append("%s=%s\n" % (key, configs[key]))
    lines = new_lines[:]

  with open(ptagent_config_file, "w") as fp:
    fp.writelines(lines)

def copy_cvm_logs_to_hypervisor(copy_to):
  """
  This function will copy available cvm boot logs from CVM to Hypervisor.
  Args:
    copy_to(str): Folder to copy the cvm boot logs.

  Returns:
    None
  """
  if os.path.exists(copy_to):
    shutil.rmtree(copy_to)
  os.makedirs(copy_to)
  cvm_boot_logs = ["/tmp/config_home_dir.log", "/tmp/rc.nutanix.log",
      "/tmp/startd.log", "/usr/local/nutanix/bootstrap/log/gen2_svm_boot.log",
      "/home/nutanix/data/logs/genesis.out"]
  INFO("Copying cvm boot logs to hypervisor.")
  for log in cvm_boot_logs:
    out, err, ret = run_cmd_on_svm(cmd="sudo cat %s" % log, attempts=3,
        fatal=False)
    if not ret:
      log = log[log.rfind("/")+1:]
      file_path = os.path.join(copy_to, log)
      INFO("Copying log file %s to hypervisor." % log)
      with open(file_path, "w") as fd:
        fd.write(out)
    else:
      INFO("Failed to read log file %s on CVM." % log)

__all__ = ["initialize_ssh_keys", "run_cmd", "run_cmd_new", "run_cmd_on_svm",
           "scp_files_to_svm", "get_pci_bus_addresses",
           "ONE_NODE_INSTALL_SUCCESS", "configure_ptagent",
           "copy_cvm_logs_to_hypervisor"]
