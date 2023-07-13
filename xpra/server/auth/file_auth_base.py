# This file is part of Xpra.
# Copyright (C) 2013-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from typing import Union, Optional, Tuple

from xpra.net.digest import get_salt, choose_digest
from xpra.server.auth.sys_auth_base import SysAuthenticator
from xpra.log import Logger

log = Logger("auth")


def stat_filetime(full_path) -> float:
    try:
        v = os.stat(full_path).st_mtime
        log("mtime(%s)=%s", full_path, v)
        return v
    except Exception as e:
        log.error(f"Error accessing time of file {full_path!r}")
        log.estr(e)
        return 0


class FileAuthenticatorBase(SysAuthenticator):
    def __init__(self, **kwargs):
        password_file = kwargs.pop("filename", None)
        log("FileAuthenticatorBase password_file=%s", password_file)
        if not password_file:
            log.warn("Warning: %r authentication module is missing the 'filename' option", self)
            log.warn(" all authentication attempts will fail")
        elif not os.path.isabs(password_file):
            exec_cwd = kwargs.get("exec_cwd", os.getcwd())
            password_file = os.path.join(exec_cwd, password_file)
        log("FileAuthenticatorBase filename=%s", password_file)
        super().__init__(**kwargs)
        self.salt : Union[bytes,bool,None] = None
        self.digest : str = ""
        self.challenge_sent = False
        self.password_filename = password_file
        self.password_filedata = None
        self.password_filetime = 0.0
        self.authenticate_check = self.authenticate_hmac

    def requires_challenge(self) -> bool:
        return True

    def get_challenge(self, digests) -> Optional[Tuple[bytes,str]]:
        if self.salt is not None:
            log.error("challenge already sent!")
            if self.salt is not False:
                self.salt = False
            return None
        self.salt = get_salt()
        self.digest = choose_digest(digests)
        self.challenge_sent = True
        return self.salt, self.digest

    def get_password(self) -> str:
        file_data = self.load_password_file()
        if not file_data:
            return ""
        return file_data

    def parse_filedata(self, data:str):
        raise NotImplementedError()

    def load_password_file(self):
        if not self.password_filename:
            return None
        full_path = os.path.abspath(self.password_filename)
        if not os.path.exists(self.password_filename):
            log.error("Error: password file '%s' is missing", full_path)
            self.password_filedata = None
        else:
            ptime = self.stat_password_filetime()
            if self.password_filedata is None or ptime!=self.password_filetime:
                self.password_filetime = 0
                self.password_filedata = b""
                try:
                    with open(self.password_filename, mode="r") as f:
                        data = f.read()
                    log(f"loaded {len(data)} bytes from {self.password_filename!r}")
                    self.password_filedata = self.parse_filedata(data)
                    self.password_filetime = ptime
                except Exception as e:
                    log.error("Error reading password data from '%s':", self.password_filename, exc_info=True)
                    log.estr(e)
                    self.password_filedata = None
        return self.password_filedata

    def stat_password_filetime(self) -> float:
        full_path = os.path.abspath(self.password_filename or "")
        return stat_filetime(full_path)
