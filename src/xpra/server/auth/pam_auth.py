# This file is part of Xpra.
# Copyright (C) 2013, 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from xpra.server.auth.sys_auth_base import SysAuthenticator, init, log
from xpra.util import csv
assert init and log #tests will disable logging from here


check = None
#choice of two pam modules we can use
try:
    import PAM                        #@UnresolvedImport
    PAM_SERVICE = 'login'
    PAM_PASSWORD = "password"

    try:
        PAM_PROMPT_ERROR_MSG = PAM.PAM_PROMPT_ERROR_MSG         #@UndefinedVariable
    except:
        try:
            PAM_PROMPT_ERROR_MSG = PAM.PAM_ERROR_MSG
        except:
            PAM_PROMPT_ERROR_MSG = None
    try:
        PAM_PROMPT_TEXT_INFO = PAM.PAM_PROMPT_TEXT_INFO         #@UndefinedVariable
    except:
        try:
            PAM_PROMPT_TEXT_INFO = PAM.PAM_TEXT_INFO
        except:
            PAM_PROMPT_TEXT_INFO = None


    class PAM_conv:
        def __init__(self, password):
            self.password = password

        def pam_conv_password(self, auth, query_list, *args):
            try:
                resp = []
                for i in range(len(query_list)):
                    query, pam_type = query_list[i]
                    if pam_type == PAM.PAM_PROMPT_ECHO_ON or pam_type == PAM.PAM_PROMPT_ECHO_OFF:
                        resp.append((self.password, 0))
                    elif pam_type == PAM_PROMPT_ERROR_MSG or pam_type == PAM_PROMPT_TEXT_INFO:
                        log("pam_conf_password: ERROR/INFO: '%s'", query)
                        resp.append(('', 0))
                    else:
                        log.error("pam_conf_password unknown type: '%s'", pam_type)
            except Exception as e:
                log.error("pam_conv_password error: %s", e)
            return    resp

    def check(username, password):
        log("PAM check(%s, [..])", username)
        auth = PAM.pam()
        auth.start(PAM_SERVICE)
        auth.set_item(PAM.PAM_USER, username)
        conv = PAM_conv(password)
        auth.set_item(PAM.PAM_CONV, conv.pam_conv_password)
        try:
            auth.authenticate()
            return    True
            #auth.acct_mgmt()
        except PAM.error as resp:
            log.error("PAM.authenticate() error: %s", resp)
            return    False
        except Exception as e:
            log.error("PAM.authenticate() internal error: %s", e)
            return    False
except Exception as e:
    log("PAM module not available: %s", e)

try:
    from xpra.server.auth import pam
    assert pam
    def check(username, password):
        log("pam check(%s, [..])", username)
        return pam.authenticate(username, password)
except:
    log("pam module not available: %s", e)


if check is None:
    raise ImportError("cannot use pam_auth without a pam python module")


class Authenticator(SysAuthenticator):

    def check(self, password):
        if self.pw is None:
            return False
        return check(self.username, password)

    def get_challenge(self, digests):
        if "xor" not in digests:
            raise Exception("pam authenticator requires the 'xor' digest, not %s" % csv(digests))
        return SysAuthenticator.get_challenge(self, ["xor"])

    def __repr__(self):
        return "PAM"


def main(args):
    if len(args)!=3:
        print("invalid number of arguments")
        print("usage:")
        print("%s username password" % (args[0],))
        return 1
    a = Authenticator(args[1])
    if a.check(args[2]):
        print("success")
        return 0
    else:
        print("failed")
        return -1

if __name__ == "__main__":
    sys.exit(main(sys.argv))
