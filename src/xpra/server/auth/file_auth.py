# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#use authentication from a file with the following format:
#1) either a single password with no "|" characters, which will be used for all usernames
#2) a list of entries of the form:
# username|password|uid|gid|displays|env_options|session_options
#

import os.path
import sys
import hmac

from xpra.os_util import get_hex_uuid
from xpra.util import xor
from xpra.dotxpra import DotXpra
from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_AUTH_DEBUG")


password_file = None
socket_dir = None
def init(opts):
    global password_file, socket_dir
    password_file = opts.password_file
    socket_dir = opts.socket_dir


def parseOptions(s):
    return {}


auth_data = None
auth_data_time = None
def load_auth_file():
    global auth_data, auth_data_time, password_file, socket_dir
    if not os.path.exists(password_file):
        log.error("password file is missing: %s", password_file)
        auth_data = None
        return auth_data
    ptime = 0
    try:
        ptime = os.stat(password_file).st_mtime
    except Exception, e:
        log.error("error accessing password file time: %s", e)
    if auth_data is None or ptime!=auth_data_time:
        auth_data = {}
        auth_data_time = ptime
        f = None
        try:
            try:
                f = open(password_file, mode='rb')
                data = f.read()
            finally:
                if f:
                    f.close()
        except Exception, e:
            log.error("error loading %s: %s", password_file, e)
            data = ""
        i = 0
        for line in data.splitlines():
            i += 1
            line = line.strip()
            if len(line)==0 or line.startswith("#"):
                continue
            debug("line %s: %s", i, line)
            if line.find("|")<0:
                #assume old style file with just the password
                #get all the displays for the current user:
                sockdir = DotXpra(socket_dir)
                results = sockdir.sockets()
                displays = [display for state, display in results if state==DotXpra.LIVE]
                auth_data[""] = line, os.getuid(), os.getgid(), displays, {}, {}
                debug("Warning: assuming this is a single password for all users")
                continue
            ldata = line.split("|")
            debug("found %s fields at line %s", len(ldata), i)
            if len(ldata)<4:
                log.warn("skipped line %s of %s: not enough fields", i, password_file)
                continue
            #parse fields:
            username = ldata[0]
            password = ldata[1]
            def getsysid(s, default_value):
                if not s:
                    return default_value
                try:
                    return int(s)
                except:
                    return default_value
            uid = getsysid(ldata[2], os.getuid())
            gid = getsysid(ldata[3], os.getgid())
            displays = ldata[4].split(",")
            env_options = {}
            session_options = {}
            if len(ldata)>=6:
                env_options = parseOptions(ldata[5])
            if len(ldata)>=7:
                session_options = parseOptions(ldata[6])
            auth_data[username] = password, uid, gid, displays, env_options, session_options
    debug("loaded auth data from file %s: %s", password_file, auth_data)
    return auth_data


class Authenticator(object):
    def __init__(self, username):
        self.username = username
        self.salt = None
        self.sessions = None

    def get_challenge(self):
        if self.salt is not None:
            log.error("challenge already sent!")
            return None
        self.salt = get_hex_uuid()
        #this authenticator can use the safer "hmac" digest:
        return self.salt, "hmac"

    def get_entry(self):
        ad = load_auth_file()
        if ad is None:
            return None
        username = self.username
        if username not in ad:
            #maybe this is an old style file with just the password?
            if len(ad)==1 and ad.keys()[0]=="":
                #then ignore the username
                username = ""
            else:
                return None
        return ad[username]

    def get_password(self):
        entry = self.get_entry()
        if entry is None:
            return None
        return entry[0]

    def authenticate(self, challenge_response, client_salt):
        global password_file
        if not self.salt:
            log.error("illegal challenge response received - salt cleared or unset")
            return None
        #ensure this salt does not get re-used:
        if client_salt is None:
            salt = self.salt
        else:
            salt = xor(self.salt, client_salt)
        self.salt = None
        entry = self.get_entry()
        if entry is None:
            log.error("usename %s does not exist in %s", self.username, password_file)
            return None
        fpassword, uid, gid, displays, env_options, session_options = entry
        verify = hmac.HMAC(fpassword, salt).hexdigest()
        debug("authenticate(%s) password=%s, salt=%s, hash=%s", challenge_response, fpassword, salt, verify)
        if verify!=challenge_response:
            debug("expected '%s' but got '%s'", verify, challenge_response)
            log.error("hmac password challenge for %s does not match", self.username)
            return False
        self.sessions = uid, gid, displays, env_options, session_options
        return True

    def get_sessions(self):
        return self.sessions

    def __str__(self):
        return "Password File Authenticator"



def main(args):
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
