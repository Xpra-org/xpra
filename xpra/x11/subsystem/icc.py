# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.server.source.display import DisplayConnection
from xpra.util.colourspace import Colourspace, SRGB
from xpra.util.env import envbool
from xpra.util.str_fn import hexstr
from xpra.util.objects import typedict
from xpra.server.subsystem.stub import StubSubsystem
from xpra.log import Logger

log = Logger("screen")

# legacy: push the client's ICC profile onto the vfb root window.
# this makes the session's contents depend on whichever client is connected,
# which cannot work with more than one client, with shadow / record,
# or with a client whose monitors don't all share the same profile.
# the session now declares its own colourspace instead, and the client is expected to convert.
SYNC_ICC: bool = envbool("XPRA_SYNC_ICC", False)


def get_icc_profile_data(colourspace: Colourspace) -> bytes:
    """
    The ICC profile matching a colourspace, generated using `littlecms` via pillow.
    Returns an empty value if pillow is not available,
    or if we don't know how to generate a profile for this colourspace.
    """
    if colourspace != SRGB:
        return b""
    try:
        from PIL import ImageCms
        profile = ImageCms.createProfile("sRGB")
        return ImageCms.ImageCmsProfile(profile).tobytes()
    except ImportError as e:
        log("get_icc_profile_data(%s)", colourspace, exc_info=True)
        log("cannot generate an ICC profile: %s", e)
    except Exception as e:
        log("get_icc_profile_data(%s)", colourspace, exc_info=True)
        log.warn("Warning: failed to generate the %s ICC profile", colourspace)
        log.warn(" %s", e)
    return b""


class ICCServer(StubSubsystem):
    __slots__ = ("icc_profile", "colourspace")
    PREFIX = "icc"

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
        self.icc_profile = b""
        # the colourspace the session renders into:
        # a virtual framebuffer has no colourimetry of its own, so this is sRGB
        self.colourspace: Colourspace = SRGB

    def setup(self) -> None:
        self.server.connect("last-client-exited", self._on_last_client_exited)
        from xpra.x11.bindings.core import X11CoreBindings
        from xpra.x11.error import xsync
        with xsync:
            # pre-intern the root window properties we set later on:
            X11CoreBindings().intern_atoms(("_ICC_PROFILE", "_ICC_PROFILE_IN_X_VERSION"))
        if not SYNC_ICC:
            # the session colourspace never changes, so this only has to be done once:
            self.set_session_icc_profile()

    def add_new_client(self, ss, caps: typedict) -> None:
        self.set_icc_profile()

    def get_caps(self, _source) -> dict[str, Any]:
        # `ServerCore.get_caps` merges subsystem capabilities into a flat dictionary,
        # so the namespacing has to be explicit here:
        return {"colourspace": self.colourspace.to_dict()}

    # TODO: should use its own packet rather than getting called by `DisplayManager`:
    def process_icc(self, ss, iccdata: dict[str, Any]):
        if iccdata:
            iccd = typedict(iccdata)
            ss.icc = iccd.get("global", ss.icc)
            ss.display_icc = iccd.get("display", ss.display_icc)
            self.set_icc_profile()

    def _on_last_client_exited(self, *_args) -> None:
        if SYNC_ICC:
            # the profile we had applied belonged to the client that just left:
            self.reset_icc_profile()

    def get_info(self, _proto) -> dict[str, Any]:
        return {"icc": self.get_icc_info()}

    def get_icc_info(self) -> dict[str, Any]:
        icc_info: dict[str, Any] = {
            "sync": SYNC_ICC,
            "colourspace": self.colourspace.to_dict(),
        }
        if self.icc_profile:
            icc_info["profile"] = hexstr(self.icc_profile)
        return icc_info

    def set_session_icc_profile(self) -> None:
        """
        Advertise the session's own colourspace on the root window,
        so that colour managed applications know what they are rendering into.
        """
        data = get_icc_profile_data(self.colourspace)
        if not data:
            # an unset `_ICC_PROFILE` already means sRGB to every client,
            # so there is nothing to do if we cannot generate the profile:
            log("no ICC profile data available for %s", self.colourspace)
            return
        log("set_session_icc_profile() %s: %i bytes", self.colourspace, len(data))
        self.icc_profile = data
        self.set_root_icc_profile(data)

    def set_root_icc_profile(self, data: bytes) -> None:
        from xpra.x11.xroot_props import root_set, root_array_set
        root_array_set("_ICC_PROFILE", "u32", data)
        root_set("_ICC_PROFILE_IN_X_VERSION", "u32", 0 * 100 + 4)  # 0.4 -> 0*100+4*1

    def set_icc_profile(self) -> None:
        if not SYNC_ICC:
            return
        display_clients = self.get_sources_by_type(DisplayConnection)
        if len(display_clients) != 1:
            log("%i display clients, resetting ICC profile to default", len(display_clients))
            self.reset_icc_profile()
            return
        icc_client = display_clients[0]
        icc = typedict(icc_client.icc)
        for x in ("data", "icc-data", "icc-profile"):
            data = icc.bytesget(x)
            if data:
                log("set_icc_profile() icc data for %s: %s (%i bytes)", icc_client, hexstr(data), len(data))
                log("overriding the session colourspace %s with the client's profile", self.colourspace)
                self.icc_profile = data
                self.set_root_icc_profile(data)
                return
        log("no icc data found in %s", icc)
        self.reset_icc_profile()

    def reset_icc_profile(self) -> None:
        log("reset_icc_profile()")
        from xpra.x11.xroot_props import root_del
        root_del("_ICC_PROFILE")
        root_del("_ICC_PROFILE_IN_X_VERSION")
        self.icc_profile = b""
