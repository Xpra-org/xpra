# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

import os
import sys
from typing import Callable, Any

from xpra.os_util import gi_import
from xpra.util.env import envint, envbool
from xpra.log import Logger

log = Logger("network")

NM_API = envbool("XPRA_NM_API", True)

ETHERNET_JITTER: int = envint("XPRA_LOCAL_JITTER", 0)
WAN_JITTER: int = envint("XPRA_WAN_JITTER", 20)
ADSL_JITTER: int = envint("XPRA_WAN_JITTER", 20)
WIRELESS_JITTER: int = envint("XPRA_WIRELESS_JITTER", 1000)

WIFI_LIMIT: int = envint("XPRA_WIFI_LIMIT", 10 * 1000 * 1000)
ADSL_LIMIT: int = envint("XPRA_WIFI_LIMIT", 1000 * 1000)


def get_NM_adapter_type(device_name, ignore_inactive=True) -> str:
    if not NM_API:
        return ""
    if not any(sys.modules.get(f"gi.repository.{mod}") for mod in ("GLib", "Gtk")):
        log("get_NM_adapter_type() no main loop")
        return ""
    try:
        NM = gi_import("NM")
    except (ImportError, ValueError):
        log("get_NM_adapter_type() no network-manager bindings")
        return ""
    try:
        nmclient = NM.Client.new(None)
    except Exception as e:
        log("NM.Client.new(None)", exc_info=True)
        log.warn("Warning: failed to query network manager")
        log.warn(" %s", e)
        return ""
    if device_name:
        nmdevice = nmclient.get_device_by_iface(device_name)
    else:
        connection = nmclient.get_primary_connection()
        if not connection:
            return ""
        try:
            nmdevice = connection.get_controller()
        except AttributeError:
            nmdevice = connection.get_master()
    if not nmdevice or isinstance(nmdevice, int):
        return ""
    log(f"NM device {device_name!r}: {nmdevice.get_vendor()} {nmdevice.get_product()}")
    nmstate = nmdevice.get_state()
    log(f"NM state({device_name})={nmstate}")
    inactive = nmdevice.get_state() != NM.DeviceState.ACTIVATED
    if ignore_inactive and inactive:
        log.info(f"ignoring {device_name}: {nmstate.value_name}")
        return ""
    adapter_type = nmdevice.get_device_type().value_name
    if adapter_type.startswith("NM_DEVICE_TYPE_"):
        adapter_type = adapter_type[len("NM_DEVICE_TYPE_"):]
    log(f"NM device-type({device_name})={adapter_type}")
    return adapter_type


def get_device_value(coptions: dict, device_info: dict, attr: str, conv: Callable = str, default_value: Any = ""):
    # first try an env var:
    v = os.environ.get("XPRA_NETWORK_%s" % attr.upper().replace("-", "_"))
    # next try device options (ie: from connection URI)
    if v is None:
        v = coptions.get("socket.%s" % attr)
    # last: the OS may know:
    if v is None:
        v = device_info.get(attr)
    if v is not None:
        try:
            return conv(v)
        except (ValueError, TypeError) as e:
            log("get_device_value%s", (coptions, device_info, attr, conv, default_value), exc_info=True)
            log.warn("Warning: invalid value for network attribute '%s'", attr)
            log.warn(" %r: %s", v, e)
    return default_value


def guess_adapter_type(name: str) -> str:
    dnl = name.lower()
    if dnl.startswith("wlan") or dnl.startswith("wlp") or any(dnl.find(x) >= 0 for x in (
            "wireless", "wlan", "80211", "modem"
    )):
        return "wireless"
    if dnl == "lo" or dnl.find("loopback") >= 0 or dnl.startswith("local"):
        return "loopback"
    if any(dnl.find(x) >= 0 for x in ("fiber", "1394", "infiniband", "tun", "tap", "vlan")):
        return "local"
    if any(dnl.find(x) >= 0 for x in ("ether", "local", "fiber", "1394", "infiniband", "veth")):
        return "ethernet"
    if dnl.find("wan") >= 0:
        return "wan"
    return ""


def jitter_for_adapter_type(adapter_type: str) -> int:
    if not adapter_type:
        return -1
    at = adapter_type.lower()

    def anyfind(*args) -> bool:
        return any(at.find(str(x)) >= 0 for x in args)

    if anyfind("loopback"):
        return 0
    if anyfind("ether", "local", "fiber", "1394", "infiniband"):
        return ETHERNET_JITTER
    if at.find("wan") >= 0:
        return WAN_JITTER
    if anyfind("wireless", "wifi", "wimax", "modem", "mesh"):
        return WIRELESS_JITTER
    return -1


def guess_bandwidth_limit(adapter_type: str) -> int:
    at = adapter_type.lower()

    def anyfind(*args) -> bool:
        return any(at.find(str(x)) >= 0 for x in args)

    if anyfind("wireless", "wifi", "wimax", "modem"):
        return WIFI_LIMIT
    if anyfind("adsl", "ppp"):
        return ADSL_LIMIT
    return 0
