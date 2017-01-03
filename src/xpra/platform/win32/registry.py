# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import ctypes

def RegOpenKeyEx(key, subkey, opt, sam):
    result = ctypes.c_uint(0)
    ctypes.windll.advapi32.RegOpenKeyExA(key, subkey, opt, sam, ctypes.byref(result))
    return result.value

def RegQueryValueEx( hkey, valuename, max_len=1024):
    data_type = ctypes.c_uint(0)
    data_len = ctypes.c_uint(max_len)
    data = ctypes.create_string_buffer(max_len+1)
    ctypes.windll.advapi32.RegQueryValueExA(hkey, valuename, 0, ctypes.byref(data_type), data, ctypes.byref(data_len))
    return data.value
            
RegCloseKey = ctypes.windll.advapi32.RegCloseKey

def get_registry_value(key, reg_path, entry):
    hKey = RegOpenKeyEx(key, reg_path)
    value, _ = RegQueryValueEx(hKey, entry)
    RegCloseKey(hKey)
    return value
