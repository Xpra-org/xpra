# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.client.base.stub import StubClientSubsystem
from xpra.exit_codes import ExitCode, ExitValue
from xpra.log import Logger
from xpra.os_util import LINUX
from xpra.scripts.config import InitExit

log = Logger("landlock")


class LandLock(StubClientSubsystem):
    """Own the client's process-wide filesystem confinement and startup state."""
    __slots__ = ("abi", "enforced", "mode", "download_path", "write_paths", "auth_paths",
                 "temp_dir", "temp_dir_owner")
    PREFIX = "landlock"

    def __init__(self, client=None):
        super().__init__(client)
        self.mode = "no"
        self.download_path = ""
        self.write_paths: tuple[str, ...] = ()
        self.auth_paths: tuple[str, ...] = ()
        self.abi = 0
        self.enforced = False
        self.temp_dir = ""
        self.temp_dir_owner = 0

    def init(self, opts) -> None:
        self.mode = opts.landlock or "no"
        self.download_path = opts.download_path
        if LINUX and self.mode != "no":
            try:
                from xpra.platform.posix.security import get_landlock_auth_paths, get_landlock_mmap_paths
                self.auth_paths = get_landlock_auth_paths(opts)
                self.write_paths = (self.download_path,) + get_landlock_mmap_paths(opts.mmap or "")
            except (ImportError, OSError, ValueError) as e:
                raise InitExit(ExitCode.FAILURE, f"failed to initialize client Landlock: {e}") from None

    def run(self) -> ExitValue:
        # Listen mode has no outbound connection setup to enforce the policy.
        self.setup_connection(None)
        return ExitCode.OK

    def setup_connection(self, _conn) -> None:
        """Confine once, before any Xpra protocol processing starts."""
        if not LINUX or self.mode == "no" or self.enforced:
            return
        try:
            from xpra.platform.posix.security import enforce_landlock
            socket_dirs = []
            if listener := self.get_subsystem("listener"):
                socket_dirs += [os.path.dirname(sock.address) for sock in listener.sockets
                                if sock.socktype == "socket" and not sock.address.startswith("@")]
            read_paths = list(self.auth_paths)
            required_paths = list(self.auth_paths)
            socket_paths = []
            if self.mode == "strict":
                from xpra.platform.posix.security import get_connection_landlock_auth_paths, prepare_landlock_temp_dir
                desc = self.client.display_desc if self.client is not None else {}
                optional, required = get_connection_landlock_auth_paths(desc)
                read_paths += optional + required
                required_paths += required
                if desc.get("type") == "socket":
                    from xpra.scripts.picker import get_sockpath
                    socket_paths.append(get_sockpath(desc, 0))
                self.temp_dir, self.temp_dir_owner = prepare_landlock_temp_dir(self.download_path)
            self.abi = enforce_landlock(self.mode, self.write_paths, read_paths=read_paths,
                                        required_paths=required_paths, socket_paths=socket_paths, socket_dirs=socket_dirs,
                                        temp_dir=self.temp_dir, allow_socket_creation=self.mode == "default")
            # File transfers resolve this environment variable, rather than opts.
            os.environ["XPRA_DOWNLOAD_DIR"] = self.download_path
            self.enforced = True
        except (ImportError, OSError, ValueError) as e:
            with log.trap_error("Error cleaning up after failed Landlock enforcement"):
                self.late_cleanup()
            raise InitExit(ExitCode.FAILURE, f"failed to restrict the client process with Landlock: {e}") from None

    def get_info(self) -> dict:
        return {LandLock.PREFIX: {
            "mode": self.mode, "enforced": self.enforced, "abi": self.abi,
            "temp-dir": self.temp_dir,
        }}

    def late_cleanup(self) -> None:
        if self.temp_dir:
            from xpra.platform.posix.security import cleanup_landlock_temp_dir
            cleanup_landlock_temp_dir(self.temp_dir, self.temp_dir_owner)
            self.temp_dir = ""
            self.temp_dir_owner = 0
