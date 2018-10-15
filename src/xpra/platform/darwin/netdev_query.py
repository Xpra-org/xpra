# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from SystemConfiguration import (
    SCNetworkInterfaceCopyAll,                      #@UnresolvedImport
    SCNetworkInterfaceGetBSDName,                   #@UnresolvedImport
    SCNetworkInterfaceGetHardwareAddressString,     #@UnresolvedImport
    SCNetworkInterfaceGetInterfaceType,             #@UnresolvedImport
    SCNetworkInterfaceGetSupportedProtocolTypes,    #@UnresolvedImport
    )


def get_interface_info(_fd, iface):
    r = SCNetworkInterfaceCopyAll()
    if iface:
        for scnetworkinterface in r:
            if str(SCNetworkInterfaceGetBSDName(scnetworkinterface))==iface:
                return do_get_interface_info(scnetworkinterface)
    elif len(r)==1:
        return do_get_interface_info(r[0])
    return {}

def do_get_interface_info(scnetworkinterface):
    info = {}
    bsdname = SCNetworkInterfaceGetBSDName(scnetworkinterface)
    if bsdname:
        info["name"] = str(bsdname)
    hw = SCNetworkInterfaceGetHardwareAddressString(scnetworkinterface)
    if hw:
        info["hardware-address"] = str(hw)
    t = SCNetworkInterfaceGetInterfaceType(scnetworkinterface)
    if t:
        info["adapter-type"] = str(t)
    #SCNetworkInterfaceGetLocalizedDisplayName
    p = SCNetworkInterfaceGetSupportedProtocolTypes(scnetworkinterface)
    if p:
        info["protocols"] = tuple(str(x) for x in p)
    return info


def main():
    r = SCNetworkInterfaceCopyAll()
    print("%i interfaces:" % len(r))
    for scnetworkinterface in r:
        info = do_get_interface_info(scnetworkinterface)
        print(info)


if __name__ == "__main__":
    main()
