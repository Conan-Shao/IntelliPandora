# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : systeminfo.py
@Time  : 2024-04-24
"""
import platform
import socket
import psutil
import os
import getpass
from ipandora.utils.log import logger


class SystemInfo(object):
    def __init__(self):
        pass

    @property
    def user(self):
        return getpass.getuser()

    @property
    def host(self):
        return self.get_host()

    @property
    def host_name(self):
        return self.get_host_name()

    @property
    def os_name(self):
        return platform.system()

    @property
    def os_version(self):
        return platform.version()

    @property
    def os_detail(self):
        return platform.platform()

    @property
    def pid(self):
        """
        return current process id
        :return:
        """
        return self.get_current_pid()

    @property
    def ppid(self):
        """
        return current process parent id
        :return:
        """
        return self.get_parent_pid()

    @staticmethod
    def get_memory_info():
        return psutil.virtual_memory()

    @staticmethod
    def get_host_name():
        return socket.gethostname()

    @staticmethod
    def get_host():
        interfaces = psutil.net_if_addrs()
        for interface_name, interface_addresses in interfaces.items():
            for address in interface_addresses:
                # get address which family is "AddressFamily.AF_INET: 2" and ignore "
                if ((str(address.family) == 'AddressFamily.AF_INET' or str(address.family) == '2')
                        and address.address != '127.0.0.1'):
                    return address.address
        raise Exception('No suitable internal IP found, please check the ip configuration')

    @staticmethod
    def get_current_pid():
        return os.getpid()

    @staticmethod
    def get_parent_pid():
        return os.getppid()

    @staticmethod
    def get_pids_by_name(name='python', include='', exclude=''):
        """
        get pids by process name
        :param name:
        :param include: the value in cmdline
        :param exclude: the value not in cmdline
        :return:
        """
        result = []
        for proc in psutil.process_iter(attrs=['pid', 'name', 'cmdline']):
            if name.lower() in proc.name().lower():
                cmdline = proc.cmdline()
                if (include and include in cmdline) and (exclude and exclude not in cmdline):
                    result.append(proc.pid)
        return result

    @staticmethod
    def kill_process(pid):
        try:
            # get pid object
            process = psutil.Process(pid)
            process.terminate()
            process.wait()
            logger.info(f"Process {pid} has been terminated.")
        except psutil.NoSuchProcess:
            logger.warning(f"No process found with PID {pid}.")
        except psutil.AccessDenied:
            logger.warning(f"Permission denied to terminate process {pid}.")
        except Exception as e:
            logger.warning(f"Error terminating process {pid}: {e}")


if __name__ == '__main__':
    print(SystemInfo().get_host())
    print(SystemInfo().user)
    # pids = (SystemInfo().get_pids_by_name('python', 'remote', 'stop'))
    # for p in pids:
    #     SystemInfo().kill_process(p)

