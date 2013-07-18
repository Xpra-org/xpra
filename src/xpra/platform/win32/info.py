# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

def get_sys_info():
    #TODO: pywin32 code here
    return  {}

def get_username():
    import getpass
    return getpass.getuser()

def get_name():
    import win32api        #@UnresolvedImport
    return win32api.GetUserName()
