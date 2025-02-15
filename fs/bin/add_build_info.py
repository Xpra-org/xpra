#!/usr/bin/env python3

# This file is part of Xpra.
# Copyright (C) 2011-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# pylint: disable=bare-except

import datetime
import shutil
from subprocess import Popen, PIPE, STDOUT, run
import socket
import platform
import os.path
import re
import sys


SRC_INFO_FILE = "./xpra/src_info.py"
BUILD_INFO_FILE = "./xpra/build_info.py"


def bytestostr(x) -> str:
    if isinstance(x, bytes):
        return x.decode("latin1")
    return str(x)


def update_properties(props: dict, filename: str) -> None:
    eprops = get_properties(filename)
    for key,value in props.items():
        set_prop(eprops, key, value)
    save_properties(eprops, filename)


def write_props(f, props: dict, prefix="") -> None:
    def u(v) -> bytes:
        if isinstance(v, bytes):
            return v
        try:
            v = v.decode()
        except (UnicodeDecodeError, AttributeError):
            v = str(v)
        try:
            return v.encode("utf-8")
        except UnicodeEncodeError:
            return v.encode("latin1")

    def w(v) -> None:
        f.write(u(v))

    def fmt(value) -> str:
        if isinstance(value, (bool, tuple, int)):
            return str(value)
        s = bytestostr(value).replace("'", "\\'")
        return f"'{s}'"

    for name in sorted(props.keys()):
        if prefix:
            w(f"{prefix}{fmt(name)}")
        else:
            w(name)
        w(f" = {fmt(props[name])}\n")


def save_properties(props: dict, filename: str) -> None:
    if os.path.exists(filename):
        try:
            os.unlink(filename)
        except OSError:
            print(f"WARNING: failed to delete {filename!r}")
    with open(filename, mode='wb') as f:
        write_props(f, props)
    print(f"updated {filename!r} with:")
    for k in sorted(props.keys()):
        print("* %s = %s" % (str(k).ljust(20), bytestostr(props[k])))


def get_properties(filename: str) -> dict:
    props = dict()
    if not os.path.exists(filename):
        return props
    with open(filename, "rb") as f:
        for line in f:
            try:
                s = line.decode("utf-8")
            except UnicodeDecodeError:
                # str cannot be decoded!
                s = str(line)
            s = s.strip()
            if not s:
                continue
            if s[0] in ('!', '#'):
                continue
            parts = s.split("=", 1)
            if len(parts)<2:
                print(f"missing equal sign in {s!r}")
                continue
            name = parts[0]
            value = parts[1]
            if not value:
                continue
            if value[0] != "'" or value[-1] != "'":
                continue
            props[name] = value[1:-1]
    return props


def get_machineinfo() -> str:
    if platform.uname()[4]:
        return platform.uname()[4]
    return "unknown"


def get_cpuinfo() -> str:
    if platform.uname()[5]:
        return platform.uname()[5]
    if os.path.exists("/proc/cpuinfo"):
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(": ")[1].replace("\n", "").replace("\r", "")
    return "unknown"


def get_status_output(*args, **kwargs) -> tuple[int, str | bytes, str | bytes]:
    kwargs["stdout"] = PIPE
    kwargs["stderr"] = STDOUT
    try:
        p = Popen(*args, **kwargs)
    except Exception as e:
        print("error running %s,%s: %s" % (args, kwargs, e))
        return -1, "", ""
    stdout, stderr = p.communicate()
    return p.returncode, stdout, stderr


def get_output_lines(cmd, valid_exit_code=0):
    try:
        returncode, stdout, stderr = get_status_output(cmd, shell=True)
        if returncode != valid_exit_code:
            print("'%s' failed with return code %s" % (cmd, returncode))
            print("stderr: %s" % stderr)
            return ()
        if not stdout:
            print("could not get output from command '%s'" % (cmd,))
            return ()
        out = stdout.decode('utf-8')
        return out.splitlines()
    except Exception as e:
        print("error running '%s': %s" % (cmd, e))
    return ()


def get_first_line_output(cmd, valid_exit_code=0) -> str:
    lines = get_output_lines(cmd, valid_exit_code)
    if lines:
        return lines[0]
    return ""


def get_nvcc_version() -> str:
    if sys.platform == "darwin":
        return ""
    for nvcc in ("/usr/local/cuda/bin/nvcc", "/opt/cuda/bin/nvcc", shutil.which("nvcc")):
        if nvcc and os.path.exists(nvcc):
            cmd = f"{nvcc} --version"
            lines = get_output_lines(cmd)
            if lines:
                vline = lines[-1]
                vpos = vline.rfind(", V")
                if vpos>0:
                    return vline[vpos+3:]
    return ""


def get_compiler_version():
    cc_version = "%s --version" % os.environ.get("CC", "gcc")
    if sys.platform == "darwin":
        lines = get_output_lines(cc_version)
        for line in lines:
            if line.startswith("Apple"):
                return line
        return None
    return get_first_line_output(cc_version)


def get_linker_version():
    if sys.platform == "darwin":
        ld_version = "%s -v" % os.environ.get("LD", "ld")
        lines = get_output_lines(ld_version)
        for line in lines:
            if line.find("using: ")>0:
                return line.split("using: ", 1)[1]
        return None
    ld_version = "%s --version" % os.environ.get("LD", "ld")
    return get_first_line_output(ld_version)


def set_prop(props, key: str, value) -> None:
    if value is None:
        return
    if value not in ("unknown", "") or props.get(key) is None:
        props[key] = value


def get_platform_name() -> str:
    # better version info than standard python platform:
    if sys.platform.startswith("sun"):
        # couldn't find a better way to distinguish opensolaris from solaris...
        with open("/etc/release", "r", encoding="latin1") as f:
            data = f.read()
        if data and str(data).lower().find("opensolaris"):
            return "OpenSolaris"
        return "Solaris"
    if sys.platform == "darwin":
        try:
            # ie: MacOS 10.14.6
            return "MacOS %s" % platform.mac_ver()[0]
        except (AttributeError, TypeError, IndexError):
            return "MacOS"
    if sys.platform.find("openbsd")>=0:
        return "OpenBSD"
    if sys.platform.startswith("win"):
        try:
            out = run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "$OutputEncoding = [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding; (Get-CimInstance Win32_OperatingSystem).Caption | Out-String",
                 ],
                 capture_output=True,
                 text=True,
                 encoding="utf-8",
            ).stdout.strip()
            return out
        except OSError:
            pass
        return "Microsoft Windows"
    if sys.platform.find("bsd") >= 0:
        return "BSD"
    try:
        from xpra.util.system import get_linux_distribution
        ld = get_linux_distribution()
        ldvalid = tuple(x for x in ld if x not in ("", "unknown", "n/a"))
        if ldvalid:
            return "Linux %s" % (" ".join(ldvalid))
    except Exception:
        pass
    return sys.platform


def alnum(v: str | bytes) -> str:
    return "".join(v for v in filter(str.isalnum, bytestostr(v)))


def record_build_info() -> None:
    props = get_properties(BUILD_INFO_FILE)
    source_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if source_epoch:
        # reproducible builds:
        build_time = datetime.datetime.fromtimestamp(int(source_epoch), tz=datetime.timezone.utc)
        build_date = build_time.date()
    else:
        # win32, macos and older build environments:
        build_time = datetime.datetime.now()
        build_date = datetime.date.today()
        # also record username and hostname:
        try:
            import getpass
            set_prop(props, "BUILT_BY", getpass.getuser())
        except OSError:
            set_prop(props, "BUILT_BY", os.environ.get("USER"))
        set_prop(props, "BUILT_ON", socket.gethostname())
    set_prop(props, "BUILD_DATE", build_date.isoformat())
    set_prop(props, "BUILD_TIME", build_time.strftime("%H:%M"))
    set_prop(props, "BUILD_MACHINE", get_machineinfo())
    set_prop(props, "BUILD_CPU", get_cpuinfo())
    set_prop(props, "BUILD_BIT", platform.architecture()[0])
    set_prop(props, "BUILD_OS", get_platform_name())
    set_prop(props, "BUILD_TYPE", os.environ.get("BUILD_TYPE", ""))
    try:
        from Cython import __version__ as cython_version
    except ImportError:
        cython_version = "unknown"
    set_prop(props, "PYTHON_VERSION", ".".join(str(x) for x in sys.version_info[:3]))
    set_prop(props, "CYTHON_VERSION", cython_version)
    set_prop(props, "COMPILER_VERSION", get_compiler_version())
    set_prop(props, "NVCC_VERSION", get_nvcc_version())
    set_prop(props, "LINKER_VERSION", get_linker_version())
    # record pkg-config versions:
    PKG_CONFIG = os.environ.get("PKG_CONFIG", "pkg-config")
    if os.name == "nt":
        returncode, out, _ = get_status_output(["pacman", "-Q"])
        if returncode == 0:
            for line in out.decode().splitlines():
                parts = line.split(" ")
                if len(parts) != 2:
                    continue
                pkg_name, version = parts
                pkg_name = alnum(pkg_name)
                set_prop(props, f"lib_{pkg_name}", version)
    elif sys.platform == "darwin":
        returncode, out, _ = get_status_output(["jhbuild", "list", "-a", "-r"])
        if returncode == 0:
            for line in out.decode().splitlines():
                parts = line.split(" ")
                if len(parts) != 2:
                    continue
                pkg_name, version = parts
                if pkg_name == "Modules":
                    continue
                pkg_name = alnum(pkg_name)
                set_prop(props, f"lib_{pkg_name}", version.lstrip("(").rstrip(")"))
    else:
        for pkg in (
            "libc",
            "vpx", "x264", "webp", "yuv", "nvenc", "nvfbc",
            "nvenc",
            "x11", "xrandr", "xtst", "xfixes", "xkbfile", "xcomposite", "xdamage", "xext",
            "gobject-introspection-1.0",
            "gtk+-3.0", "py3cairo", "pygobject-3.0", "gtk+-x11-3.0",
            "python3",
        ):
            # fugly magic for turning the package atom into a legal variable name:
            pkg_name = alnum(pkg.lstrip("lib"))
            if pkg_name.rsplit("_", 1)[-1].rstrip("0123456789.")=="":
                pkg_name = "_".join(pkg_name.split("_")[:-1])
            cmd = [PKG_CONFIG, "--modversion", pkg]
            returncode, out, _ = get_status_output(cmd)
            if returncode == 0:
                set_prop(props, "lib_"+pkg_name, out.decode().replace("\n", "").replace("\r", ""))
    # we could potentially limit this data collection to win32 and macos?
    returncode, out, _ = get_status_output(["pip3", "freeze"])
    if returncode == 0:
        for line in out.decode().splitlines():
            parts = line.split("==")
            if len(parts) != 2:
                continue
            pkg_name, version = parts
            pkg_name = alnum(pkg_name)
            set_prop(props, f"lib_python_{pkg_name}", version)

    save_properties(props, BUILD_INFO_FILE)


def get_vcs_props():
    props = {
        "REVISION": "unknown",
        "LOCAL_MODIFICATIONS": 0,
        "BRANCH": "unknown",
        "COMMIT": "unknown"
    }
    branch = None
    for cmd in (
        r"git branch --show-current",
        # when in detached state, the one above does not work, but this one does:
        r"git branch --remote --verbose --no-abbrev --contains | sed -rne 's/^[^\/]*\/([^\ ]+).*$/\1/p'",
        # if all else fails:
        r"git branch | grep '* '",
    ):
        proc = Popen(cmd, stdout=PIPE, stderr=PIPE, shell=True)
        out, _ = proc.communicate()
        if proc.returncode == 0:
            branch_out = out.decode("utf-8").splitlines()
            if branch_out:
                branch = branch_out[0]
                if branch.startswith("* "):
                    branch = branch[2:]
                break
    if not branch:
        print("Warning: could not get branch information")
    else:
        props["BRANCH"] = branch

    # use the number of changes since the last tag:
    proc = Popen("git describe --long --always --tags", stdout=PIPE, stderr=PIPE, shell=True)
    out, _ = proc.communicate()
    if proc.returncode != 0:
        print("'git describe --long --always --tags' failed with return code %s" % proc.returncode)
        return props
    if not out:
        print("could not get version information")
        return props
    out = out.decode('utf-8').splitlines()[0]
    # ie: out=v4.0.6-58-g6e6614571
    parts = out.split("-")
    if len(parts) == 1:
        commit = parts[0]
        print("could not get revision number - no tags?")
        rev_str = "0"
    elif len(parts) == 3:
        rev_str = parts[1]
        commit = parts[2]
    else:
        print("could not parse version information from string: %s" % out)
        return props
    props["COMMIT"] = commit
    try:
        rev = int(rev_str)
    except ValueError:
        print("could not parse revision counter from string: %s (original version string: %s)" % (rev_str, out))
        return props

    if branch == "master":
        # fake a sequential revision number that continues where svn left off,
        # by counting the commits and adding a magic value (5014)
        proc = Popen("git rev-list --count HEAD --first-parent", stdout=PIPE, stderr=PIPE, shell=True)
        out, _ = proc.communicate()
        if proc.returncode != 0:
            print("failed to get commit count using 'git rev-list --count HEAD'")
            sys.exit(1)
        rev = int(out.decode("utf-8").splitlines()[0]) + 5014
    props["REVISION"] = rev
    # find number of local files modified:
    changes = 0
    proc = Popen("git status", stdout=PIPE, stderr=PIPE, shell=True)
    (out, _) = proc.communicate()
    if proc.poll() != 0:
        print("could not get status of local files")
        return props

    lines = out.decode('utf-8').splitlines()
    for line in lines:
        sline = line.strip()
        if sline.startswith("modified: ") or sline.startswith("new file:") or sline.startswith("deleted:"):
            changes += 1
    props["LOCAL_MODIFICATIONS"] = changes
    return props


def record_src_info() -> None:
    update_properties(get_vcs_props(), SRC_INFO_FILE)


def has_src_info() -> bool:
    return os.path.exists(SRC_INFO_FILE) and os.path.isfile(SRC_INFO_FILE)


def has_build_info() -> bool:
    return os.path.exists(BUILD_INFO_FILE) and os.path.isfile(BUILD_INFO_FILE)


def main(args):
    if not has_src_info() or "src" in args:
        record_src_info()
    if not has_build_info() or "build" in args:
        record_build_info()
    if "revision" in args:
        props = get_vcs_props()
        try:
            mods = int(props.get("LOCAL_MODIFICATIONS"))
        except ValueError:
            mods = 0
        commit = props.get("COMMIT")
        print("%s r%s%s%s" % (
            props.get("BRANCH"),
            props.get("REVISION"),
            "M" if mods>0 else "",
            " (%s)" % commit if commit else "",
        )
        )


if __name__ == "__main__":
    main(sys.argv)
