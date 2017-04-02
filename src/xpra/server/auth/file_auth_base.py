# This file is part of Xpra.
# Copyright (C) 2013-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#authentication from a file containing just the password

import os.path

from xpra.net.crypto import get_salt, choose_digest
from xpra.os_util import strtobytes
from xpra.server.auth.sys_auth_base import SysAuthenticator
from xpra.log import Logger
log = Logger("auth")


#legacy interface: this is to inject the "--password-file=" option
#this is shared by all instances
password_file = None
def init(opts):
    global password_file
    password_file = opts.password_file


class FileAuthenticatorBase(SysAuthenticator):
    def __init__(self, username, **kwargs):
        SysAuthenticator.__init__(self, username)
        filename = kwargs.get("filename", password_file)
        if filename and not os.path.isabs(filename):
            exec_cwd = kwargs.get("exec_cwd", os.getcwd())
            filename = os.path.join(exec_cwd, filename)
        self.password_filename = filename
        self.password_filedata = None
        self.password_filetime = None
        self.authenticate = self.authenticate_hmac

    def requires_challenge(self):
        return True

    def get_challenge(self, digests):
        if self.salt is not None:
            log.error("challenge already sent!")
            if self.salt is not False:
                self.salt = False
            return None
        self.salt = get_salt()
        self.digest = choose_digest(digests)
        if not self.digest:
            return None
        return self.salt, self.digest

    def get_password(self):
        file_data = self.load_password_file()
        if file_data is None:
            return None
        return strtobytes(file_data)

    def parse_filedata(self, data):
        return data

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
                self.password_filetime = None
                self.password_filedata = None
                try:
                    with open(self.password_filename, mode='rb') as f:
                        data = f.read()
                    log("loaded %s bytes from '%s'", len(data), self.password_filename)
                    self.password_filedata = self.parse_filedata(data)
                    self.password_filetime = ptime
                except Exception as e:
                    log.error("Error reading password data from '%s':", self.password_filename, exc_info=True)
                    log.error(" %s", e)
                    self.password_filedata = None
        return self.password_filedata

    def stat_password_filetime(self):
        try:
            full_path = os.path.abspath(self.password_filename)
            v = os.stat(full_path).st_mtime
            log("mtime(%s)=%s", full_path, v)
            return v
        except Exception as e:
            log.error("Error accessing time of password file '%s'", full_path)
            log.error(" %s", e)
            return 0
