#!/usr/bin/env python3

# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# pylint: disable=bare-except

import datetime
from shutil import which
from subprocess import Popen, PIPE, STDOUT, getstatusoutput, run
from typing import Any
from collections.abc import Sequence
import socket
import platform
import os.path
import sys


SRC_INFO_FILE = "xpra/src_info.py"
BUILD_INFO_FILE = "xpra/build_info.py"


def update_properties(props: dict[str, Any], filename: str) -> None:
    eprops = get_properties(filename)
    eprops.update(props)
    save_properties(eprops, filename)


def save_properties(props: dict[str, Any], filename: str) -> None:
    if os.path.exists(filename):
        try:
            os.unlink(filename)
        except OSError:
            print(f"WARNING: failed to delete {filename!r}")
    print(f"# updated {filename!r} with:")
    with open(filename, mode="w") as f:
        for k in sorted(props.keys()):
            v = props[k]
            pair = f"{k} = {v!r}"
            f.write(f"{pair}\n")
            print(pair)


def get_properties(filename: str) -> dict[str, Any]:
    props = dict()
    if not os.path.exists(filename):
        return props

    from importlib.util import spec_from_file_location, module_from_spec
    spec = spec_from_file_location("xpra", filename)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    for attr in dir(module):
        if attr.startswith("_"):
            continue
        props[attr] = getattr(module, attr)
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


def get_status_output(*args, **kwargs) -> tuple[int, bytes, bytes]:
    kwargs["stdout"] = PIPE
    kwargs["stderr"] = STDOUT
    try:
        p = Popen(*args, **kwargs)
    except Exception as e:
        print("error running %s,%s: %s" % (args, kwargs, e))
        return -1, "", ""
    stdout, stderr = p.communicate()
    return p.returncode, stdout, stderr


def get_output_lines(cmd, valid_exit_code=0) -> Sequence[str]:
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
    for nvcc in ("/usr/local/cuda/bin/nvcc", "/opt/cuda/bin/nvcc", which("nvcc")):
        if nvcc and os.path.exists(nvcc):
            cmd = f"{nvcc} --version"
            lines = get_output_lines(cmd)
            if lines:
                vline = lines[-1]
                vpos = vline.rfind(", V")
                if vpos>0:
                    return vline[vpos+3:]
    return ""


def get_compiler_version() -> str:
    cc_version = "%s --version" % os.environ.get("CC", "gcc")
    if sys.platform == "darwin":
        lines = get_output_lines(cc_version)
        for line in lines:
            if line.startswith("Apple"):
                return line
        return ""
    return get_first_line_output(cc_version)


def get_linker_version() -> str:
    if sys.platform == "darwin":
        ld_version = "%s -v" % os.environ.get("LD", "ld")
        lines = get_output_lines(ld_version)
        for line in lines:
            if line.find("using: ")>0:
                return line.split("using: ", 1)[1]
        return ""
    ld_version = "%s --version" % os.environ.get("LD", "ld")
    return get_first_line_output(ld_version)


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


def get_build_props() -> dict[str, Any]:
    props = {}
    source_epoch = os.environ.get("SOURCE_DATE_EPOCH", "")
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
            props["user"] = getpass.getuser()
        except OSError:
            props["user"] = os.environ.get("USER", "")
        props["on"] = socket.gethostname()

    props.update({
        "date": build_date.isoformat(),
        "time": build_time.strftime("%H:%M"),
        "machine": get_machineinfo(),
        "cpu": get_cpuinfo(),
        "bit": platform.architecture()[0],
        "os": get_platform_name(),
        "type": os.environ.get("BUILD_TYPE", ""),
    })
    try:
        from Cython import __version__ as cython_version
    except ImportError:
        cython_version = "unknown"
    props.update({
        "python": ".".join(str(x) for x in sys.version_info[:3]),
        "cython": cython_version,
        "compiler": get_compiler_version(),
        "nvcc": get_nvcc_version(),
        "linker": get_linker_version(),
    })
    return props


def get_libs() -> dict[str, Any]:
    # record pkg-config versions:
    PKG_CONFIG = os.environ.get("PKG_CONFIG", "pkg-config")
    libs: dict[str, Any] = {}
    if os.name == "nt":
        returncode, out, _ = get_status_output(["pacman", "-Q"])
        if returncode == 0:
            for line in out.decode().splitlines():
                parts = line.split(" ")
                if len(parts) != 2:
                    continue
                pkg_name, version = parts
                libs[pkg_name] = version
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
                libs[pkg_name] = version.lstrip("(").rstrip(")")
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
            cmd = [PKG_CONFIG, "--modversion", pkg]
            returncode, out, _ = get_status_output(cmd)
            if returncode == 0:
                libs[pkg] = out.decode().replace("\n", "").replace("\r", "")
    return libs


def get_python_libs() -> dict[str, Any]:
    # we could potentially limit this data collection to win32 and macos?
    python_libs: dict[str, Any] = {}
    returncode, out, _ = get_status_output(["pip3", "freeze"])
    if returncode == 0:
        python_libs: dict[str, Any] = {}
        for line in out.decode().splitlines():
            parts = line.split("==")
            if len(parts) != 2:
                continue
            pkg_name, version = parts
            python_libs[pkg_name] = version
    return python_libs


def record_build_info() -> None:
    props = get_properties(BUILD_INFO_FILE)
    props.update({
        "build": get_build_props(),
    })
    if os.environ.get("RECORD_LIBS", "1") == "1":
        props.update({
            "libs": get_libs(),
            "python_libs": get_python_libs(),
        })
    if sys.platform == "darwin":
        sbom = {}
        packages = {}
        SKIPPED = ("xar", "cpio", "bomutils", )
        for package_name in get_jhbuild_package_list():
            if package_name in SKIPPED or package_name.startswith("meta-"):
                continue
            pinfo = get_jhbuild_package_info(package_name)
            if pinfo:
                sbom[package_name] = (0, "", package_name, pinfo.get("Version", ""))
                packages[package_name] = {key: value for key, value in pinfo.items() if key in ("Name", "Version", "URL")}
        props["sbom"] = sbom
        props["packages"] = packages
    save_properties(props, BUILD_INFO_FILE)


def get_jhbuild_package_list() -> list[str]:
    cmd = "jhbuild list"
    r, output = getstatusoutput(cmd)
    if r:
        print(f"`jhbuild list` failed and returned {r}")
        return []
    packages = []
    for line in output.split("\n"):
        if line.find(" ") >= 0:
            continue
        packages.append(line.strip())
    return packages


def get_jhbuild_package_info(name: str) -> dict[str, str]:
    cmd = f"jhbuild info {name}"
    r, output = getstatusoutput(cmd)
    if r:
        print(f"`jhbuild info {name}` failed and returned {r}")
        return {}
    props: dict[str, str] = {}
    for line in output.split("\n"):
        parts = line.split(":", 1)
        if len(parts) == 2:
            props[parts[0].strip()] = parts[1].strip()
    return props


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


def check_file(filename: str) -> bool:
    return os.path.exists(filename) and os.path.isfile(filename) and os.stat(filename).st_size > 0


def main(args):
    if not check_file(SRC_INFO_FILE) or "src" in args:
        record_src_info()
    if not check_file(BUILD_INFO_FILE) or "build" in args:
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
