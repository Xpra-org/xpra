# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import json
import shlex
import os.path
from subprocess import Popen, PIPE
from typing import Any

from xpra.util.env import envbool, shellsub, osexpand
from xpra.os_util import OSX, POSIX
from xpra.util.io import umask_context, which, get_util_logger
from xpra.platform.dotxpra import norm_makepath
from xpra.platform.paths import get_python_exec_command
from xpra.scripts.config import InitException, FALSE_OPTIONS

UINPUT_UUID_LEN: int = 12


# pylint: disable=import-outside-toplevel


def get_logger():
    from xpra.log import Logger
    return Logger("server", "util")


def source_env(source=()) -> dict[str, str]:
    log = get_logger()
    log("source_env(%s)", source)
    env = {}
    for f in source:
        if not f or f.lower() in FALSE_OPTIONS:
            continue
        try:
            es = env_from_sourcing(f)
            log("source_env %s=%s", f, es)
            env.update(es)
        except Exception as e:
            log(f"env_from_sourcing({f})", exc_info=True)
            log.error(f"Error sourcing {f!r}: {e}")
    log("source_env(%s)=%s", source, env)
    return env


def decode_dict(out: str) -> dict[str, str]:
    env = {}
    for line in out.splitlines():
        parts = line.split("=", 1)
        if len(parts) == 2:
            env[parts[0]] = parts[1]
    return env


def decode_json(out):
    return json.loads(out)


# credit: https://stackoverflow.com/a/47080959/428751
# returns a dictionary of the environment variables resulting from sourcing a file
def env_from_sourcing(file_to_source_path: str, include_unexported_variables: bool = False) -> dict[str, str]:
    from xpra.log import Logger
    log = Logger("exec")
    cmd: list[str] = shlex.split(file_to_source_path)

    def abscmd(s: str) -> str:
        if os.path.isabs(s):
            return s
        c = which(s)
        if not c:
            log.error(f"Error: cannot find command {s!r} to execute")
            log.error(f" for sourcing {file_to_source_path!r}")
            return s
        if os.path.isabs(c):
            return c
        return os.path.abspath(c)

    filename = abscmd(cmd[0])
    cmd[0] = filename
    # figure out if this is a script to source,
    # or if we're meant to execute it directly
    try:
        with open(filename, "rb") as f:
            first_line = f.readline()
    except OSError as e:
        log.error(f"Error: failed to read from {filename!r}")
        log.estr(e)
        first_line = b""
    else:
        log(f"first line of {filename!r}: {first_line!r}")
    if first_line.startswith(b"\x7fELF") or b"\x00" in first_line:
        decode = decode_dict
    else:
        source = "set -a && " if include_unexported_variables else ""
        source += f". {filename}"
        # ie: this is "python3.9 -c" on Posix
        # (but our 'Python_exec_cmd.exe' wrapper on MS Windows):
        python_cmd = " ".join(get_python_exec_command())
        dump = f'{python_cmd} "import os, json;print(json.dumps(dict(os.environ)))"'
        sh = which("bash") or "/bin/sh"
        cmd = [sh, "-c", f"{source} 1>&2 && {dump}"]
        decode = decode_json
    out = err = b""
    proc = None
    try:
        log("env_from_sourcing%s cmd=%s", (filename, include_unexported_variables), cmd)
        proc = Popen(cmd, stdout=PIPE, stderr=PIPE)
        out, err = proc.communicate()
        if proc.returncode != 0:
            log.error(f"Error {proc.returncode} running source script {filename!r}")
    except OSError as e:
        log("env_from_sourcing%s", (filename, include_unexported_variables), exc_info=True)
        log(f" stdout={out!r} ({type(out)})")
        log(f" stderr={err!r} ({type(err)})")
        log.error(f"Error running source script {file_to_source_path!r}")
        if proc and proc.returncode is not None:  # NOSONAR @SuppressWarnings("python:S5727")
            log.error(f" exit code: {proc.returncode}")
        log.error(f" {e}")
        return {}
    log(f"stdout({filename})={out!r}")
    log(f"stderr({filename})={err!r}")

    def proc_str(b: bytes, fdname="stdout") -> str:
        try:
            return (b or b"").decode()
        except UnicodeDecodeError:
            log.error(f"Error decoding {fdname} from {filename!r}", exc_info=True)
        return ""

    env: dict[str, str] = {}
    env.update(decode(proc_str(out, "stdout")))
    env.update(decode_dict(proc_str(err, "stderr")))
    log("env_from_sourcing%s=%s", (file_to_source_path, include_unexported_variables), env)
    # ensure we never expose empty keys:
    # (see ticket #4485)
    return dict(filter(lambda item: bool(item[0]), env.items()))


def sh_quotemeta(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def xpra_env_shell_script(socket_dir: str, env: dict[str, str]) -> str:
    script = ["#!/bin/sh", ""]
    for var, value in env.items():
        if var in ("PATH", "LD_LIBRARY_PATH", "PYTHONPATH"):
            # prevent those paths from accumulating the same values multiple times,
            # only keep the first one:
            pathsep = os.pathsep
            pval = value.split(pathsep)  # ie: ["/usr/bin", "/usr/local/bin", "/usr/bin"]
            seen = set()
            value = pathsep.join(x for x in pval if not (x in seen or seen.add(x)))  # type: ignore[func-returns-value]
            qval = sh_quotemeta(value) + f':"${var}"'
        elif var in (
                # whitelist:
                "XDG_MENU_PREFIX", "XDG_RUNTIME_DIR",
                "XAUTHORITY",
                "HOSTNAME", "HOME", "USERNAME", "USER",
                "SSH_ASKPASS",
        ):
            qval = sh_quotemeta(value)
        else:
            continue
        script.append(f"{var}={qval}; export {var}")
    # XPRA_SOCKET_DIR is a special case, we want to honour it
    # when it is specified, but the client may override it:
    if socket_dir:
        script.append('if [ -z "${XPRA_SOCKET_DIR}" ]; then')
        qdir = sh_quotemeta(os.path.expanduser(socket_dir))
        script.append(f'    XPRA_SOCKET_DIR="{qdir}"; export XPRA_SOCKET_DIR')
        script.append('fi')
    script.append("")
    return "\n".join(script)


def xpra_runner_shell_script(xpra_file: str, starting_dir: str) -> str:
    # We ignore failures in cd'ing, b/c it's entirely possible that we were
    # started from some temporary directory and all paths are absolute.
    qdir = sh_quotemeta(starting_dir)
    script = [
        "",
        f"cd {qdir}"]
    if OSX:
        # OSX contortions:
        # The executable is the python interpreter,
        # which is execed by a shell script, which we have to find..
        sexec = sys.executable
        bini = sexec.rfind("Resources/bin/")
        if bini > 0:
            sexec = os.path.join(sexec[:bini], "Resources", "MacOS", "Xpra")
        script.append(f"_XPRA_SCRIPT={sh_quotemeta(sexec)}\n")
        script.append("""
if command -v "$_XPRA_SCRIPT" > /dev/null; then
    # Happypath:
    exec "$_XPRA_SCRIPT" "$@"
else
    # Hope for the best:
    exec Xpra "$@"
fi
""")
    else:
        script.append("_XPRA_PYTHON=%s" % (sh_quotemeta(sys.executable),))
        script.append("_XPRA_SCRIPT=%s" % (sh_quotemeta(xpra_file),))
        script.append("""
if command -v "$_XPRA_PYTHON" > /dev/null && [ -e "$_XPRA_SCRIPT" ]; then
    # Happypath:
    exec "$_XPRA_PYTHON" "$_XPRA_SCRIPT" "$@"
else
    cat >&2 <<END
    Could not find one or both of '$_XPRA_PYTHON' and '$_XPRA_SCRIPT'
    Perhaps your environment has changed since the xpra server was started?
    I'll just try executing 'xpra' with current PATH, and hope...
END
    exec xpra "$@"
fi
""")
    return "\n".join(script)


def write_runner_shell_scripts(contents: str, overwrite: bool = True) -> None:
    assert POSIX
    # This used to be given a display-specific name, but now we give it a
    # single fixed name and if multiple servers are started then the last one
    # will clobber the rest.  This isn't great, but the tradeoff is that it
    # makes it possible to use bare 'ssh:hostname' display names and
    # autodiscover the proper numeric display name when only one xpra server
    # is running on the remote host.  Might need to revisit this later if
    # people run into problems or autodiscovery turns out to be less useful
    # than expected.
    log = get_logger()
    MODE = 0o700
    from xpra.platform.paths import get_script_bin_dirs
    for d in get_script_bin_dirs():
        scriptdir = osexpand(d)
        if not os.path.exists(scriptdir):
            try:
                os.mkdir(scriptdir, MODE)
            except Exception as e:
                log("os.mkdir(%s, %s)", scriptdir, oct(MODE), exc_info=True)
                log.warn("Warning: failed to create script directory '%s':", scriptdir)
                log.warn(" %s", e)
                if scriptdir.startswith("/var/run/user") or scriptdir.startswith("/run/user"):
                    log.warn(" ($XDG_RUNTIME_DIR has not been created?)")
                continue
        scriptpath = os.path.join(scriptdir, "run-xpra")
        if os.path.exists(scriptpath) and not overwrite:
            continue
        # Write out a shell-script so that we can start our proxy in a clean
        # environment:
        try:
            with umask_context(0o022):
                h = os.open(scriptpath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, MODE)
                try:
                    os.write(h, contents.encode())
                finally:
                    os.close(h)
        except Exception as e:
            log("writing to %s", scriptpath, exc_info=True)
            log.error("Error: failed to write script file '%s':", scriptpath)
            log.error(" %s\n", e)


def open_log_file(logpath: str):
    """ renames the existing log file if it exists,
        then opens it for writing.
    """
    if os.path.exists(logpath):
        try:
            os.rename(logpath, logpath + ".old")
        except OSError:
            pass
    try:
        return os.open(logpath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    except OSError as e:
        raise InitException(f"cannot open log file {logpath!r}: {e}") from None


def select_log_file(log_dir: str, log_file: str, display_name: str) -> str:
    """ returns the log file path we should be using given the parameters,
        this may return a temporary logpath if display_name is not available.
    """
    if log_file:
        if os.path.isabs(log_file):
            logpath = log_file
        else:
            logpath = os.path.join(log_dir, log_file)
        v = shellsub(logpath, {"DISPLAY": display_name})
        if display_name or v == logpath:
            # we have 'display_name', or we just don't need it:
            return v
    if display_name:
        logpath = norm_makepath(log_dir, display_name) + ".log"
    else:
        logpath = os.path.join(log_dir, f"tmp_{os.getpid()}.log")
    return logpath


# Redirects stdin from /dev/null, and stdout and stderr to the file with the
# given file descriptor. Returns file objects pointing to the old stdout and
# stderr, which can be used to write a message about the redirection.
def redirect_std_to_log(logfd: int) -> tuple:
    # preserve old stdio in new filehandles for use (and subsequent closing)
    # by the caller
    old_fd_stdout = os.dup(1)
    old_fd_stderr = os.dup(2)
    stdout = os.fdopen(old_fd_stdout, "w", 1)
    stderr = os.fdopen(old_fd_stderr, "w", 1)

    # close the old stdio file handles
    os.close(0)
    os.close(1)
    os.close(2)

    # replace stdin with /dev/null
    fd0 = os.open("/dev/null", os.O_RDONLY)
    if fd0 != 0:
        os.dup2(fd0, 0)
        os.close(fd0)

    # replace standard stdout/stderr by the log file
    os.dup2(logfd, 1)
    os.dup2(logfd, 2)
    os.close(logfd)

    # Make these line-buffered:
    sys.stdout = os.fdopen(1, "w", 1)
    sys.stderr = os.fdopen(2, "w", 1)
    return stdout, stderr


def daemonize() -> None:
    os.chdir("/")
    if os.fork():
        os._exit(0)  # pylint: disable=protected-access
    os.setsid()
    if os.fork():
        os._exit(0)  # pylint: disable=protected-access


def write_pid(pidfile: str, pid: int) -> int:
    if pid <= 0:
        raise ValueError(f"invalid pid value {pid}")
    log = get_logger()
    pidstr = str(pid)
    try:
        with open(pidfile, "w", encoding="latin1") as f:
            if POSIX:
                os.fchmod(f.fileno(), 0o640)
            f.write(f"{pidstr}\n")
            f.flush()
            try:
                fd = f.fileno()
                inode = os.fstat(fd).st_ino
            except OSError as e:
                log("fstat", exc_info=True)
                log.error(f"Error accessing inode of {pidfile!r}: {e}")
                inode = 0
        space = "" if pid == os.getpid() else " "
        log.info(f"{space}wrote pid {pidstr} to {pidfile!r}")
        return inode
    except Exception as e:
        log(f"write_pid({pidfile}, {pid})", exc_info=True)
        log.info(f"Error: failed to write pid {pidstr} to {pidfile!r}")
        log.error(f" {e}")
        return 0


def write_pidfile(pidfile: str) -> int:
    return write_pid(pidfile, os.getpid())


def rm_pidfile(pidfile: str, inode: int) -> bool:
    # verify this is the right file!
    log = get_logger()
    log("cleanuppidfile(%s, %s)", pidfile, inode)
    if inode > 0:
        try:
            i = os.stat(pidfile).st_ino
            log("cleanuppidfile: current inode=%i", i)
            if i != inode:
                log.warn(f"Warning: pidfile {pidfile!r} inode has changed")
                log.warn(f" was {inode}, now {i}")
                log.warn(" it would be unsafe to delete it")
                return False
        except OSError as e:
            log("rm_pidfile(%s, %s)", pidfile, inode, exc_info=True)
            log.warn(f"Warning: failed to stat pidfile {pidfile!r}")
            log.warn(f" {e!r}")
            return False
    try:
        os.unlink(pidfile)
        return True
    except OSError as e:
        log("rm_pidfile(%s, %s)", pidfile, inode, exc_info=True)
        log.warn(f"Warning: failed to remove pidfile {pidfile!r}")
        log.warn(f" {e!r}")
        return False


def get_uinput_device_path(device) -> str:
    log = get_logger()
    try:
        log("get_uinput_device_path(%s)", device)
        fd = device._Device__uinput_fd
        log("fd(%s)=%s", device, fd)
        import fcntl
        import ctypes
        path_len = 16
        buf = ctypes.create_string_buffer(path_len)
        # this magic value was calculated using the C macros:
        path_len = fcntl.ioctl(fd, 2148554028, buf)
        if 0 < path_len < 16:
            virt_dev_path = (buf.raw[:path_len].rstrip(b"\0")).decode()
            log("UI_GET_SYSNAME(%s)=%s", fd, virt_dev_path)
            uevent_path = "/sys/devices/virtual/input/%s" % virt_dev_path
            event_dirs = [x for x in os.listdir(uevent_path) if x.startswith("event")]
            log("event dirs(%s)=%s", uevent_path, event_dirs)
            for d in event_dirs:
                uevent_filename = os.path.join(uevent_path, d, "uevent")
                uevent_conf = open(uevent_filename, "rb").read()
                for line in uevent_conf.splitlines():
                    if line.find(b"=") > 0:
                        k, v = line.split(b"=", 1)
                        log("%s=%s", k, v)
                        if k == b"DEVNAME":
                            dev_path = (b"/dev/%s" % v).decode("latin1")
                            log(f"found device path: {dev_path}")
                            return dev_path
    except Exception as e:
        log("get_uinput_device_path(%s)", device, exc_info=True)
        log.error("Error: cannot query uinput device path:")
        log.estr(e)
    return ""


def has_uinput() -> bool:
    if not envbool("XPRA_UINPUT", True):
        return False
    try:
        import uinput
        assert uinput
    except ImportError:
        log = get_logger()
        log("has_uinput()", exc_info=True)
        log("no uinput module (not usually needed)")
        return False
    except Exception as e:
        log = get_logger()
        log("has_uinput()", exc_info=True)
        log.warn("Warning: the system python uinput module looks broken:")
        log.warn(" %s", e)
        return False
    try:
        uinput.fdopen()  # @UndefinedVariable
    except Exception as e:
        log = get_logger()
        log("has_uinput()", exc_info=True)
        if isinstance(e, OSError) and e.errno == 19:
            log("no uinput: is the kernel module installed?")
        else:
            log.info("cannot use uinput for virtual devices,")
            log.info(" this is usually a permission issue:")
            log.info(" %s", e)
        return False
    return True


def create_uinput_device(uid: int, events, name: str) -> tuple[str, Any, str] | None:
    log = get_logger()
    import uinput  # @UnresolvedImport
    BUS_USB = 0x03
    # BUS_VIRTUAL = 0x06
    VENDOR = 0xffff
    PRODUCT = 0x1000
    # our 'udev_product_version' script will use the version attribute to set
    # the udev OWNER value
    VERSION = uid
    try:
        device = uinput.Device(events, name=name, bustype=BUS_USB, vendor=VENDOR, product=PRODUCT, version=VERSION)
    except OSError as e:
        log("uinput.Device creation failed", exc_info=True)
        if os.getuid() == 0:
            # running as root, this should work!
            log.error("Error: cannot open uinput,")
            log.error(" make sure that the kernel module is loaded")
            log.error(" and that the /dev/uinput device exists:")
            log.estr(e)
        return None
    dev_path = get_uinput_device_path(device)
    if not dev_path:
        device.destroy()
        return None
    return name, device, dev_path


def create_uinput_pointer_device(uuid: str, uid) -> tuple[str, Any, str] | None:
    if not envbool("XPRA_UINPUT_POINTER", True):
        return None
    from uinput import (
        REL_X, REL_Y, REL_WHEEL,
        BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE,
        BTN_EXTRA, BTN_FORWARD, BTN_BACK,
    )
    events = (
        REL_X, REL_Y, REL_WHEEL,
        BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE,
        BTN_EXTRA, BTN_FORWARD, BTN_BACK,
    )
    # REL_HIRES_WHEEL = 0x10
    # uinput.REL_HWHEEL,
    name = f"Xpra Virtual Pointer {uuid}"
    return create_uinput_device(uid, events, name)


def create_uinput_touchpad_device(uuid: str, uid: int) -> tuple[str, Any, str] | None:
    if not envbool("XPRA_UINPUT_TOUCHPAD", False):
        return None
    from uinput import BTN_TOUCH, ABS_X, ABS_Y, ABS_PRESSURE
    events = (
        BTN_TOUCH,
        ABS_X + (0, 2 ** 24 - 1, 0, 0),
        ABS_Y + (0, 2 ** 24 - 1, 0, 0),
        ABS_PRESSURE + (0, 255, 0, 0),
        # BTN_TOOL_PEN,
    )
    name = f"Xpra Virtual Touchpad {uuid}"
    return create_uinput_device(uid, events, name)


def create_uinput_devices(uinput_uuid: str, uid: int) -> dict[str, Any]:
    log = get_logger()
    try:
        import uinput  # @UnresolvedImport
        assert uinput
    except (ImportError, NameError) as e:
        log.error("Error: cannot access python uinput module:")
        log.estr(e)
        return {}
    pointer = create_uinput_pointer_device(uinput_uuid, uid)
    touchpad = create_uinput_touchpad_device(uinput_uuid, uid)
    if not pointer and not touchpad:
        return {}

    def i(device):
        if not device:
            return {}
        name, uinput_pointer, dev_path = device
        return {
            "name": name,
            "uinput": uinput_pointer,
            "device": dev_path,
        }

    return {
        "pointer": i(pointer),
        "touchpad": i(touchpad),
    }


def create_input_devices(uinput_uuid: str, uid: int) -> dict[str, Any]:
    return create_uinput_devices(uinput_uuid, uid)


def setuidgid(uid: int, gid: int) -> None:
    if not POSIX:
        return
    log = get_util_logger()
    if os.getuid() != uid or os.getgid() != gid:
        # find the username for the given uid:
        from pwd import getpwuid
        try:
            username = getpwuid(uid).pw_name
        except KeyError:
            raise ValueError(f"uid {uid} not found") from None
        # set the groups:
        if hasattr(os, "initgroups"):  # python >= 2.7
            os.initgroups(username, gid)
        else:
            import grp
            groups = [gr.gr_gid for gr in grp.getgrall() if username in gr.gr_mem]
            os.setgroups(groups)
    # change uid and gid:
    try:
        if os.getgid() != gid:
            os.setgid(gid)
    except OSError as e:
        log.error(f"Error: cannot change gid to {gid}")
        if os.getgid() == 0:
            # don't run as root!
            raise
        log.estr(e)
        log.error(f" continuing with gid={os.getgid()}")
    try:
        if os.getuid() != uid:
            os.setuid(uid)
    except OSError as e:
        log.error(f"Error: cannot change uid to {uid}")
        if os.getuid() == 0:
            # don't run as root!
            raise
        log.estr(e)
        log.error(f" continuing with uid={os.getuid()}")
    log(f"new uid={os.getuid()}, gid={os.getgid()}")
