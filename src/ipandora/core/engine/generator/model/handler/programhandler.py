# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : programhandler.py
@Time  : 2024-06-06
"""
import os
import requests
from SSHLibrary.library import SSHLibrary
from ipandora.core.schedule.runtime import Runtime
from ipandora.utils.log import logger
from ipandora.utils.error import DataError
from ipandora.utils.pathutils import PathUtils


class ProgramHandler(object):
    def __init__(self):
        self.host = Runtime.Remote.host
        self.username = Runtime.Remote.username
        self.password = Runtime.Remote.password
        self.dest_dir = Runtime.Remote.directory
        self.port = Runtime.Remote.port
        self.zentao_user = ''
        self.zentao_password = ''
        self.session = requests.session()
        self.session.headers = {"Cookie": str(Runtime.Remote.cookies)}
        self.ssh = SSHLibrary()
        self.connect_to_remote_server()

    def transfer_program(self, url: str, remote_file: str, host: str = ''):
        """
        Transfer program from zentao to service
        :param url:
        :param remote_file:
        :param host:
        :return:
        """
        logger.info("Start to transfer program from zentao to service.")
        _local_file_path = self.download_program_from_zentao(url, os.path.basename(remote_file))
        dest_dir = PathUtils.join_paths_ignore_duplicates(self.dest_dir,
                                                          os.path.dirname(remote_file))
        self.put_program_to_service(_local_file_path, host, dest_dir)

    def download_program_from_zentao(self, url: str, local_filename: str, local_dir: str = '/tmp'):
        """
        Download program from zentao
        :param url:
        :param local_filename:
        :param local_dir:
        :return:
        """
        # Send HTTP GET Request
        logger.info("Start to download program from zentao.")
        # headers = {"Cookie": str(GTRuntime.Remote.cookies)}
        response = self.session.get(url)
        if '<html>' in response.text:
            raise DataError("The cookie of Zentao has expired")
        _file_path = os.path.join(local_dir, local_filename)
        # Create file
        with open(_file_path, 'wb') as _file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:  # 忽略空块
                    _file.write(chunk)
        logger.info("Download program from zentao success!!!")
        return _file_path

    def put_program_to_service(self, local_file_path, host = '', dest_dir = ''):
        """
        Put program to service
        :param local_file_path:
        :param host:
        :param dest_dir:
        :return:
        """
        self.host = host if host else self.host
        dest_dir = dest_dir if dest_dir else self.dest_dir
        if not dest_dir.endswith('/'):
            dest_dir += '/'
        logger.info(f"Start to put program to service. "
                    f"<Host: {self.host}, Local_File: {local_file_path}, Dest_Dir: {dest_dir}>")
        if self.host == 'localhost':
            logger.info("start to copy with <cp> command.")
            os.system(f'echo {self.password} | sudo -S -s')
            cmd_cp = f"cp {local_file_path} {dest_dir}"
            logger.info(f"Execute command <{cmd_cp}>")
            os.system(cmd_cp)
        else:
            logger.info("start to put file with SSH.")
            self._upload_file_to_remote(local_file_path, dest_dir)
        logger.info("Put file success!!!")

    def _upload_file_to_remote(self, local_file_path: str, dest_dir) -> None:
        """
        Upload file to remote with ssh
        :param local_file_path:
        :return:
        """
        try:
            # ssh.open_connection(self.host, port=self.port)
            # ssh.login(self.username, self.password)
            self.ssh.put_file(local_file_path, dest_dir)
        except Exception as e:
            _msg = f"Failed to upload file to {self.host}:{dest_dir} due to {str(e)}"
            logger.error(_msg)
            raise _msg

    def download_program_from_service(self, remote_file_path: str, local_dir: str = '/tmp') -> str:
        """
        Download file from remote service with ssh
        :param remote_file_path:
        :param local_dir:
        :return:
        """
        logger.info(f"Start to download file from remote service. <Host: {self.host}>")
        local_file_path = os.path.join(local_dir, os.path.basename(remote_file_path))
        if self.file_exists(local_file_path):
            logger.info(f"File already exists locally. Skipping download: {local_file_path}")
            return local_file_path
        # ssh = SSHLibrary()
        try:
            # self.ssh.open_connection(self.host, port=self.port)
            # self.ssh.login(self.username, self.password)
            self.ssh.get_file(remote_file_path, local_file_path)
        except Exception as e:
            _msg = f"Failed to download file from {self.host}:{remote_file_path} due to {str(e)}"
            logger.error(_msg)
            raise _msg
        logger.info(f"Download file success!!! <File: {local_file_path}>")
        return local_file_path

    @staticmethod
    def file_exists(local_file_path: str) -> bool:
        """
        Check if the file already exists in the local directory
        :param local_file_path:
        :return: True if file exists, False otherwise
        """
        return os.path.isfile(local_file_path)

    def connect_to_remote_server(self):
        try:
            self.ssh.open_connection(self.host, port=self.port)
            self.ssh.login(self.username, self.password)
        except Exception as e:
            _msg = f"Login remote file server fail {self.host}, due to {str(e)}"
            logger.error(_msg)
            raise _msg

    def disconnect_remote_server(self):
        try:
            self.ssh.close_connection()
        except Exception as e:
            _msg = f"Disconnect remote file server fail {self.host}, due to {str(e)}"
            logger.error(_msg)


if __name__ == '__main__':
    _link = 'http://zentao.i5cnc.com/file-download-571.html'
    # _local_file_path = '/Users/shaofeng/Downloads/test.txt'
    _prog_handler = ProgramHandler()
    resp = _prog_handler.download_program_from_zentao(_link, 'test.txt', 'i5program')
    print(resp)


