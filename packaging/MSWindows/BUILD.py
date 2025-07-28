#!/bin/env python3
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import re
import sys
import json
import os.path
import shlex
import hashlib
from typing import Any

from sysconfig import get_path
from datetime import datetime
from collections import namedtuple
from collections.abc import Iterable
from importlib.util import find_spec, spec_from_file_location, module_from_spec

from glob import glob
from subprocess import getstatusoutput, check_output, Popen, PIPE
from shutil import which, rmtree, copyfile, move, copytree

KEY_FILE = "E:\\xpra.pfx"
DIST = "dist"
LIB_DIR = f"{DIST}/lib"

ARCH = os.environ.get("MSYSTEM_CARCH", "")

DEBUG = os.environ.get("XPRA_DEBUG", "0") != "0"
PYTHON = os.environ.get("PYTHON", "python%i.%i" % sys.version_info[:2])
MINGW_PREFIX = os.environ.get("MINGW_PREFIX", "")
MSYSTEM_CARCH = os.environ.get("MSYSTEM_CARCH", "x86_64")
PACKAGE_PREFIX = os.environ.get("MINGW_PACKAGE_PREFIX", f"mingw-w64-{MSYSTEM_CARCH}") + "-"
MSYS2_PACKAGE_PREFIX = "msys2-"
MSYS_DLL_PREFIX = "msys-"

X11_DLL_DIR = os.environ.get("X11_DLL_DIR", "E:/vcxsrv")

TIMESTAMP_SERVER = "http://timestamp.digicert.com"
# alternative:
# http://timestamp.comodoca.com/authenticode

PROGRAMFILES = "C:\\Program Files"
PROGRAMFILES_X86 = "C:\\Program Files (x86)"
SYSTEM32 = "C:\\Windows\\System32"

SRC_INFO = "xpra/src_info.py"
BUILD_INFO = "xpra/build_info.py"
SBOM_JSON = "sbom.json"

LOG_DIR = "packaging/MSWindows/"

NPROCS = int(os.environ.get("NPROCS", os.cpu_count()))

BUILD_CUDA_KERNEL = "packaging\\MSWindows\\BUILD_CUDA_KERNEL.BAT"

EXTRA_PYTHON_MODULES = [
    "unittest", "psutil", "pynvml",
    "browser_cookie3",
    "gssapi", "ldap", "ldap3", "pyu2f", "sqlite3",
]


def parse_command_line(argv: list[str]):
    from argparse import ArgumentParser, BooleanOptionalAction
    ap = ArgumentParser()

    # noinspection PyShadowingBuiltins
    def add(name: str, help: str, default=True):
        ap.add_argument(f"--{name}", default=default, action=BooleanOptionalAction, help=help)
    add("verbose", help="print extra diagnostic messages", default=False)
    add("clean", help="clean build directories")
    add("build", help="compile the source")
    add("install", help="run install step")
    add("fixups", help="run misc fixups")
    add("zip", help="generate a ZIP installation file")
    add("verpatch", help="run `verpatch` on the executables")
    add("light", help="trimmed down build")
    add("sbom", help="record SBOM")
    add("exe", help="create an EXE installer")
    add("run", help="run the EXE installer")
    add("msi", help="create an MSI installer")
    add("sign", help="sign the EXE and MSI installers")
    add("tests", help="run the unit tests", default=False)
    add("zip-modules", help="zip up python modules")
    add("cuda", help="build CUDA kernels for nvidia codecs")
    add("service", help="build the system service", default=ARCH != "aarch64")
    add("docs", help="generate the documentation", default=ARCH != "aarch64")
    add("html5", help="bundle the `xpra-html5` client")
    add("x11", help="include X11 bindings", default=False)
    add("manual", help="bundle the user manual")
    add("numpy", help="bundle `numpy`")
    add("putty", help="bundle putty `plink`")
    add("openssh", help="bundle the openssh client")
    add("openssl", help="bundle the openssl tools")
    add("paexec", help="bundle `paexec`")
    add("desktop-logon", help="build `desktop-logon` tool")
    ap.add_argument("--build-args", default="", help="extra build arguments")

    args, unknown_args = ap.parse_known_args(argv)
    if args.light:
        # disable many switches:
        args.cuda = args.numpy = args.service = args.docs = args.html5 = args.manual = False
        args.putty = args.openssh = args.openssl = args.paexec = args.desktop_logon = False
    if args.verbose:
        global DEBUG
        DEBUG = True
    return args, unknown_args


def step(message: str) -> None:
    now = datetime.now()
    ts = f"{now.hour:02}:{now.minute:02}:{now.second:02}"
    print(f"* {ts} {message}")


def debug(message: str) -> None:
    if DEBUG:
        print("    "+message)


def csv(values: Iterable) -> str:
    return ", ".join(str(x) for x in values)


def du(path: str) -> int:
    if os.path.isfile(path):
        return os.path.getsize(path)
    return sum(os.path.getsize(f) for f in glob(f"{path}/**", recursive=True) if os.path.isfile(f))


def get_build_args(args) -> list[str]:
    xpra_args = ["--without-gstreamer_video"]
    if args.light:
        for option in (
            "shadow", "server", "proxy", "rfb",
            "dbus",
            "encoders", "avif",
            "nvfbc", "cuda_kernels",
            "csc_cython",
            "webcam",
            "win32_tools",
            "docs",
            "qt6_client",
            "websockets_browser_cookie",
            "service",
            "yaml",
        ):
            xpra_args.append(f"--without-{option}")
        xpra_args.append("--with-Os")
    else:
        xpra_args.append("--with-qt6_client")
    if not args.cuda:
        xpra_args.append("--without-nvidia")
    if args.x11:
        xpra_args.append("--with-x11")
    if args.build_args:
        xpra_args += shlex.split(args.build_args)
    # we can't do 'docs' this way :(
    # for arg in ("docs", ):
    #    value = getattr(args, arg)
    #    xpra_args.append(f"--with-{arg}={value}")       #ie: "--with-docs=True"
    return xpra_args


def _find_command(name: str, env_name: str, *paths) -> str:
    cmd = os.environ.get(env_name, "")
    if cmd and os.path.exists(cmd):
        return cmd
    cwd_cmd = os.path.abspath(f"./{name}.exe")
    if os.path.exists(cwd_cmd):
        return cwd_cmd
    cmd = which(name)
    if cmd and os.path.exists(cmd):
        return cmd
    for path in paths:
        if os.path.exists(path) and os.path.isfile(path):
            return path
    return ""


def find_command(name: str, env_name: str, *paths) -> str:
    cmd = _find_command(name, env_name, *paths)
    if cmd:
        return cmd
    print(f"{name!r} not found")
    print(f" (you can set the {env_name!r} environment variable to point to it)")
    print(f" tried %PATH%={os.environ.get('PATH')}")
    print(f" tried {paths=}")
    raise RuntimeError(f"{name!r} not found")


def search_command(wholename: str, *dirs: str) -> str:
    debug(f"searching for {wholename!r} in {dirs}")
    for dirname in dirs:
        if not os.path.exists(dirname):
            continue
        cmd = ["find", dirname, "-wholename", wholename]
        r, output = getstatusoutput(cmd)
        debug(f"getstatusoutput({cmd})={r}, {output}")
        if r == 0:
            return output.splitlines()[0]
    raise RuntimeError(f"{wholename!r} not found in {dirs}")


def find_java() -> str:
    try:
        return _find_command("java", "JAVA")
    except RuntimeError as e:
        debug(f"`java` was not found: {e}")
    # try my hard-coded default first to save time:
    java = f"{PROGRAMFILES}\\Java\\jdk1.8.0_121\\bin\\java.exe"
    if java and getstatusoutput(f"{java} --version")[0] == 0:
        return java
    dirs = (f"{PROGRAMFILES}/Java", f"{PROGRAMFILES}", f"{PROGRAMFILES_X86}")
    for directory in dirs:
        r, output = getstatusoutput(f"find {directory!r} -name java.exe")
        if r == 0:
            return output[0]
    raise RuntimeError(f"java.exe was not found in {dirs}")


def check_html5() -> None:
    step("Verify `xpra-html5` is installed")
    if not os.path.exists("xpra-html5") or not os.path.isdir("xpra-html5"):
        print("html5 client not found")
        print(" perhaps run: `git clone https://github.com/Xpra-org/xpra-html5`")
        raise RuntimeError("`xpra-html5` client not found")

    # Find a java interpreter we can use for the html5 minifier
    os.environ["JAVA"] = find_java()


def check_signtool() -> None:
    step("locating `signtool`")
    if os.path.exists("./signtool.exe"):
        return
    try:
        signtool = find_command("signtool", "SIGNTOOL",
                                f"{PROGRAMFILES}\\Microsoft SDKs\\Windows\\v7.1\\Bin\\signtool.exe"
                                f"{PROGRAMFILES}\\Microsoft SDKs\\Windows\\v7.1A\\Bin\\signtool.exe"
                                f"{PROGRAMFILES_X86}\\Windows Kits\\8.1\\Bin\\x64\\signtool.exe"
                                f"{PROGRAMFILES_X86}\\Windows Kits\\10\\App Certification Kit\\signtool.exe")
    except RuntimeError:
        signtool = ""
    if not signtool:
        # try the hard (slow) way:
        signtool = find_vs_command("signtool.exe")
        if not signtool:
            raise RuntimeError("signtool not found")
    debug(f"{signtool=}")
    copyfile(signtool, "./signtool.exe")


def show_tail(filename: str) -> None:
    if os.path.exists(filename):
        print(f"showing the last 10 lines of {filename!r}:")
        os.system(f"tail -n 10 {filename}")


def command_args(cmd: str | list[str]) -> list[str]:
    # make sure we use an absolute path for the command:
    if isinstance(cmd, str):
        parts = shlex.split(cmd)
    else:
        parts = cmd
    cmd_exe = parts[0]
    if not os.path.isabs(cmd_exe):
        cmd_exe = which(cmd_exe)
        if cmd_exe:
            parts[0] = cmd_exe
    return parts


def log_command(cmd: str | list[str], log_filename: str, **kwargs) -> None:
    debug(f"running {cmd!r} and sending the output to {log_filename!r}")
    if not os.path.isabs(log_filename):
        log_filename = os.path.join(LOG_DIR, log_filename)
    delfile(log_filename)
    if not kwargs.get("shell"):
        cmd = command_args(cmd)
    with open(log_filename, "w") as f:
        ret = Popen(cmd, stdout=f, stderr=f, **kwargs).wait()
    if ret != 0:
        show_tail(log_filename)
        raise RuntimeError(f"{cmd!r} failed and returned {ret}, see {log_filename!r}")


def find_delete(path: str, name: str, mindepth=0) -> None:
    debug(f"deleting all instances of {name!r} from {path!r}")
    cmd = ["find", path]
    if mindepth > 0:
        cmd += ["-mindepth", str(mindepth)]
    if name:
        cmd += ["-name", "'"+name+"'"]
    cmd += ["-type", "f"]
    cmd = command_args(cmd)
    output = check_output(cmd).decode()
    for filename in output.splitlines():
        delfile(filename)


def rmrf(path: str) -> None:
    if not os.path.exists(path):
        print(f"Warning: {path!r} does not exist")
        return
    rmtree(path)


def delfile(path: str) -> None:
    if os.path.exists(path):
        debug(f"removing {path!r}")
        os.unlink(path)


def clean() -> None:
    step("Cleaning output directories and generated files")
    debug("cleaning log files:")
    find_delete("packaging/MSWindows/", "*.log")
    for dirname in (DIST, "build"):
        rmrf(dirname)
        os.mkdir(dirname)
    # clean sometimes errors on removing pyd files,
    # so do it with rm instead:
    debug("removing compiled dll and pyd files:")
    find_delete("xpra", "*-cpython-*dll")
    find_delete("xpra", "*-cpython-*pyd")
    debug("python clean")
    log_command(f"{PYTHON} ./setup.py clean", "clean.log")
    debug("removing comtypes cache")
    # clean comtypes cache - it should not be included!
    check_output(command_args("clear_comtypes_cache.exe -y"))
    debug("ensure build info is regenerated")
    delfile(BUILD_INFO)


def find_windowskit_command(name="mc") -> str:
    debug(f"find_windowskit_command({name!r})")
    cwd_cmd = os.path.abspath(f"./{name}.exe")
    if os.path.exists(cwd_cmd):
        return cwd_cmd
    # the proper way would be to run vsvars64.bat
    # but we only want to locate 3 commands,
    # so we find them "by hand":
    ARCH_DIRS = ("x64", "x86")
    paths = []
    for prog_dir in (PROGRAMFILES, PROGRAMFILES_X86):
        for V in (8.1, 10):
            for ARCH in ARCH_DIRS:
                paths += glob(f"{prog_dir}\\Windows Kits\\{V}\\bin\\*\\{ARCH}\\{name}.exe")
    env_name = name.upper()   # ie: "MC"
    return find_command(name, env_name, *paths)


def find_vs_command(name="link") -> str:
    debug(f"find_vs_command({name!r})")
    cwd_cmd = os.path.abspath(f"./{name}.exe")
    if os.path.exists(cwd_cmd):
        return cwd_cmd
    dirs = []
    for prog_dir in (PROGRAMFILES, PROGRAMFILES_X86):
        for VSV in (14.0, 17.0, 19.0, 2019, 2022):
            vsdir = f"{prog_dir}\\Microsoft Visual Studio\\{VSV}"
            if os.path.exists(vsdir):
                dirs.append(f"{vsdir}\\VC\\bin")
                dirs.append(f"{vsdir}\\BuildTools\\VC\\Tools\\MSVC")
    return search_command(f"*/x64/{name}.exe", *dirs)


def build_service() -> None:
    step("Compiling system service shim")
    XPRA_SERVICE_EXE = "Xpra-Service.exe"
    SERVICE_SRC_DIR = os.path.join(os.path.abspath("."), "packaging", "MSWindows", "service")
    for filename in ("event_log.rc", "event_log.res", "MSG00409.bin", XPRA_SERVICE_EXE):
        path = os.path.join(SERVICE_SRC_DIR, filename)
        delfile(path)

    MC = find_windowskit_command("mc")
    RC = find_windowskit_command("rc")
    LINK = find_vs_command("link")

    log_command([MC, "-U", "event_log.mc"], "service-mc.log", cwd=SERVICE_SRC_DIR)
    log_command([RC, "event_log.rc"], "service-rc.log", cwd=SERVICE_SRC_DIR)
    log_command([LINK, "-dll", "-noentry", "-out:event_log.dll", "event_log.res"], "service-link.log",
                cwd=SERVICE_SRC_DIR)
    log_command(["g++", "-o", XPRA_SERVICE_EXE, "Xpra-Service.cpp", "-Wno-write-strings"], "service-gcc.log",
                cwd=SERVICE_SRC_DIR)
    os.rename(os.path.join(SERVICE_SRC_DIR, XPRA_SERVICE_EXE), os.path.join(DIST, XPRA_SERVICE_EXE))


VersionInfo = namedtuple("VersionInfo", ("string", "value", "revision", "full_string", "arch_info", "extra", "padded"))
version_info = VersionInfo("invalid", (0, 0), 0, "invalid", "arch", "extra", (0, 0, 0, 0))


def set_version_info(light: bool) -> None:
    step("Collecting version information")
    for filename in ("src_info.py", "build_info.py"):
        path = os.path.join("xpra", filename)
        delfile(path)
    log_command([PYTHON, "fs/bin/add_build_info.py", "src", "build"], "add-build-info.log")
    print("    Python " + sys.version)
    load_version_info(light)


def load_version_info(light: bool) -> None:

    def load_module(src: str):
        spec = spec_from_file_location("xpra", src)
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    xpra = load_module("xpra/__init__.py")
    src_info = load_module(SRC_INFO)

    revision = src_info.REVISION

    full_string = f"{xpra.__version__}-r{revision}"
    if src_info.LOCAL_MODIFICATIONS:
        full_string += "M"

    extra = "-Light" if light else ""
    # ie: "x86_64"
    arch_info = "-" + MSYSTEM_CARCH

    # for msi and verpatch:
    padded = (list(xpra.__version_info__) + [0, 0, 0])[:3] + [revision]
    padded = ".".join(str(x) for x in padded)

    print(f"    Xpra{extra} {full_string}")
    print(f"    using {NPROCS} cpus")
    global version_info
    version_info = VersionInfo(xpra.__version__, xpra.__version_info__, revision, full_string, arch_info, extra, padded)


################################################################################
# Build: clean, build extensions, generate exe directory


def build_cuda_kernels() -> None:
    step("Building CUDA kernels")
    for cupath in glob("fs/share/xpra/cuda/*.cu"):
        kname = os.path.splitext(os.path.basename(cupath))[0]
        cu = os.path.splitext(cupath)[0]
        # ie: "fs/share/xpra/cuda/BGRX_to_NV12.cu" -> "fs/share/xpra/cuda/BGRX_to_NV12"
        fatbin = f"{cu}.fatbin"
        if not os.path.exists(fatbin):
            debug(f"rebuilding {kname!r}: {fatbin!r} does not exist")
        else:
            ftime = os.path.getctime(fatbin)
            ctime = os.path.getctime(cupath)
            if ftime >= ctime:
                debug(f"{fatbin!r} ({ftime}) is already newer than {cupath!r} ({ctime})")
                continue
            debug(f"need to rebuild: {fatbin!r} ({ftime}) is older than {cupath!r} ({ctime})")
            os.unlink(fatbin)
        log_command([BUILD_CUDA_KERNEL, kname], f"nvcc-{kname}.log", shell=True)


def build_ext(args) -> None:
    step("Building Cython modules")
    build_args = get_build_args(args) + ["--inplace"]
    if NPROCS > 0:
        build_args += ["-j", str(NPROCS)]
    args_str = " ".join(build_args)
    log_command(f"{PYTHON} ./setup.py build_ext {args_str}", "build.log")


def run_tests() -> None:
    step("Running unit tests")
    env = os.environ.copy()
    env["PYTHONPATH"] = ".:./tests/unittests"
    env["XPRA_COMMAND"] = "./fs/bin/xpra"
    log_command(f"{PYTHON} ./setup.py unittests", "unittest.log", env=env)


def install_exe(args) -> None:
    step("Generating installation directory")
    args_str = " ".join(get_build_args(args))
    log_command(f"{PYTHON} ./setup.py install_exe {args_str} --install={DIST}", "install.log")


def install_docs() -> None:
    step("Generating the documentation")
    if not os.path.exists(f"{DIST}/doc"):
        os.mkdir(f"{DIST}/doc")
    env = os.environ.copy()
    env["PANDOC"] = find_command("pandoc", "PANDOC", f"{PROGRAMFILES}\\Pandoc\\pandoc.exe")
    log_command(f"{PYTHON} ./setup.py doc", "pandoc.log", env=env)


def fixups(light: bool) -> None:
    step("Fixups: paths, etc")
    # fix case sensitive mess:
    gi_dir = f"{LIB_DIR}/girepository-1.0"
    debug("Glib misspelt")
    os.rename(f"{gi_dir}/Glib-2.0.typelib", f"{gi_dir}/GLib-2.0.typelib.tmp")
    os.rename(f"{gi_dir}/GLib-2.0.typelib.tmp", f"{gi_dir}/GLib-2.0.typelib")

    debug("cx_Logging")
    # fixup cx_Logging, required by the service class before we can patch sys.path to find it:
    if os.path.exists(f"{LIB_DIR}/cx_Logging.pyd"):
        os.rename(f"{LIB_DIR}/cx_Logging.pyd", f"{DIST}/cx_Logging.pyd")
    debug("comtypes")
    # fixup cx freeze wrongly including an empty dir:
    gen = f"{LIB_DIR}/comtypes/gen"
    if os.path.exists(gen):
        rmrf(gen)
    debug("gdk loaders")
    lpath = os.path.join(LIB_DIR, "gdk-pixbuf-2.0", "2.10.0", "loaders")
    KEEP_LOADERS = ["jpeg", "png", "xpm", "svg", "wmf", "ico"]
    if not light:
        KEEP_LOADERS += ["pnm", "tiff", "icns"]
    loaders = os.listdir(lpath)
    debug(f"loaders({lpath})={loaders}")
    for filename in loaders:
        if not filename.endswith(".dll") or not any(filename.find(keep) >= 0 for keep in KEEP_LOADERS):
            debug(f"removing {filename!r}")
            os.unlink(os.path.join(lpath, filename))
    debug("gio modules")
    BUNDLE_GIO = ["libproxy", "openssl"]
    if not light:
        BUNDLE_GIO += ["gnutls"]
    os.mkdir(f"{LIB_DIR}/gio")
    os.mkdir(f"{LIB_DIR}/gio/modules")
    for modname in BUNDLE_GIO:
        gio_filename = f"gio/modules/libgio{modname}.dll"
        copyfile(f"{MINGW_PREFIX}/lib/{gio_filename}", f"{LIB_DIR}/{gio_filename}")
    log_command(f"gio-querymodules.exe {LIB_DIR}/gio/modules", "gio-cache.log")
    debug("remove ffmpeg libraries")
    for libname in ("avcodec", "avformat", "avutil", "swscale", "swresample", "zlib1", "xvidcore"):
        find_delete(LIB_DIR, libname)
    debug("move lz4")


def add_numpy(bundle: bool) -> None:
    step(f"numpy: {bundle}")
    lib_numpy = f"{LIB_DIR}/numpy"
    if not bundle:
        debug("removed")
        rmrf(f"{lib_numpy}")
        delete_libs("libopenblas*", "libgfortran*", "libquadmath*")
        return
    debug("moving libraries to lib")
    for libname in ("openblas", "gfortran", "quadmath"):
        for dll in glob(f"{lib_numpy}/core/lib{libname}*.dll"):
            move(dll, LIB_DIR)
    debug("trim tests")


def move_lib(frompath: str, todir: str) -> None:
    topath = os.path.join(todir, os.path.basename(frompath))
    if os.path.exists(topath):
        # should compare that they are the same file!
        debug(f"removing {frompath!r}, already found in {topath!r}")
        os.unlink(frompath)
        return
    debug(f"moving {frompath!r} to {topath!r}")
    move(frompath, topath)


def fixup_gstreamer() -> None:
    step("Fixup GStreamer")
    lib_gst = f"{LIB_DIR}/gstreamer-1.0"
    # these are not modules, so they belong in "lib/":
    for dllname in ("gstreamer*", "gst*-1.0-*", "wavpack*", "*-?"):
        for gstdll in glob(f"{lib_gst}/lib{dllname}.dll"):
            move_lib(gstdll, f"{LIB_DIR}")
    # all the remaining libgst* DLLs are gstreamer elements:
    for gstdll in glob(f"{LIB_DIR}/gst*.dll"):
        move(gstdll, lib_gst)
    # gst-inspect and gst-launch don't need to be at the root:
    for exe in glob(f"{DIST}/gst-*.exe"):
        move_lib(exe, LIB_DIR)
    # these are not needed at all for now:
    for elementname in ("basecamerabinsrc", "photography"):
        for filename in glob(f"{LIB_DIR}/libgst{elementname}*"):
            os.unlink(filename)


def fixup_dlls() -> None:
    step("Fixup DLLs")
    debug("remove dll.a")
    # why is it shipping those files??
    find_delete(DIST, "*dll.a")
    debug("moving most DLLs to lib/")
    # but keep the core DLLs in the root (python, gcc, etc):
    exclude = ("msvcrt", "libpython", "libgcc", "libwinpthread", "pdfium")
    for dll in glob(f"{DIST}/*.dll"):
        if any(dll.find(excl) >= 0 for excl in exclude):
            continue
        move_lib(dll, LIB_DIR)
    debug("fixing cx_Freeze duplication")
    # remove all the pointless cx_Freeze duplication:
    for dll in glob(f"{DIST}/*.dll") + glob(f"{LIB_DIR}/*dll"):
        filename = os.path.basename(dll)
        # delete from any sub-directories:
        find_delete(LIB_DIR, filename, mindepth=2)


def delete_dist_files(*exps: str) -> None:
    for exp in exps:
        matches = glob(f"{DIST}/{exp}")
        if not matches:
            print(f"Warning: glob {exp!r} did not match any files!")
            continue
        for path in matches:
            if os.path.isdir(path):
                debug(f"removing tree at: {path!r}")
                rmtree(path)
            else:
                debug(f"removing {path!r}")
                os.unlink(path)


def delete_libs(*exps: str) -> None:
    debug(f"deleting libraries: {exps}")
    delete_dist_files(*(f"lib/{exp}" for exp in exps))


def delete_dlls(light: bool) -> None:
    step("Deleting unnecessary DLLs")
    delete_libs(
        "libjasper*", "xdg*", "olefile*", "pygtkcompat*", "jaraco*",
        "p11-kit*", "lz4",
    )
    # remove codecs we don't need:
    delete_libs("libx265*", "libjxl*", "libde265*", "libkvazaar*")
    if light:
        # let's keep kerberos / gss libs because clients can use them:
        # "libshishi*", "libgss*"
        delete_libs(
            # no dbus:
            "libdbus*",
            # no AV1:
            "rav1e*", "libheif*",
            # no avif:
            "libavif*", "libSvt*",
            # remove h264 encoder:
            "libx264*",
            # should not be needed:
            "libp11-kit*",
            # extra audio codecs (we just keep vorbis and opus):
            "libmp3*", "libwavpack*", "libmpdec*", "libFLAC*", "libmpg123*", "libfaad*", "libfaac*",
        )

        def delgst(*exps: str) -> None:
            gstlibs = tuple(f"gstreamer-1.0/libgst{exp}*" for exp in exps)
            delete_libs(*gstlibs)
        # matching gstreamer modules:
        delgst("flac", "wavpack", "wavenc", "lame", "mpg123", "faac", "faad", "wav")
        # these started causing packaging problems with GStreamer 1.24:
        delgst("isomp4")


def trim_pillow() -> None:
    # remove PIL loaders and modules we don't need:
    step("Removing unnecessary PIL plugins")
    KEEP = (
        "Bmp", "Ico", "Jpeg", "Tiff", "Png", "Ppm", "Xpm", "WebP",
        "Image.py", "ImageChops", "ImageCms", "ImageWin", "ImageChops", "ImageColor", "ImageDraw", "ImageFile.py",
        "ImageFilter", "ImageFont", "ImageGrab", "ImageMode", "ImageOps", "ImagePalette", "ImagePath", "ImageSequence",
        "ImageStat", "ImageTransform",
    )
    NO_KEEP = ("Jpeg2K", )
    kept = []
    removed = []
    for filename in glob(f"{LIB_DIR}/PIL/*Image*"):
        infoname = os.path.splitext(os.path.basename(filename))[0]
        if any(filename.find(keep) >= 0 for keep in KEEP) and not any(filename.find(nokeep) >= 0 for nokeep in NO_KEEP):
            kept.append(infoname)
            continue
        removed.append(infoname)
        os.unlink(filename)
    debug(f"removed: {csv(removed)}")
    debug(f"kept: {csv(kept)}")


def trim_python_libs() -> None:
    step("Removing unnecessary Python modules")
    # remove test bits we don't need:
    delete_libs(
        "backports",
        "importlib_resources/compat",
        "importlib_resources/tests",
        # no need for headers:
        # "cairo/include"
    )
    step("Removing unnecessary files")
    for ftype in (
        # no runtime type checks:
        "py.typed",
        # remove source:
        "*.bak",
        "*.orig",
        "*.pyx",
        "*.c",
        "*.cpp",
        "*.m",
        "constants.txt",
        "*.h",
        "*.html",
        "*.pxd",
        "*.cu",
    ):
        find_delete(DIST, ftype)


def fixup_zeroconf() -> None:
    lib_zeroconf = f"{LIB_DIR}/zeroconf"
    rmrf(lib_zeroconf)
    # workaround for zeroconf - just copy it wholesale
    # since I have no idea why cx_Freeze struggles with it:
    zc = find_spec("zeroconf")
    if not zc:
        print("Warning: zeroconf not found for Python %s" % sys.version)
        return
    zeroconf_dir = os.path.dirname(zc.origin)
    debug(f"adding zeroconf from {zeroconf_dir!r} to {lib_zeroconf!r}")
    copytree(zeroconf_dir, lib_zeroconf)


def rm_empty_dir(dirpath: str) -> None:
    cmd = ["find", dirpath, "-type", "d", "-empty"]
    output = check_output(command_args(cmd))
    for path in output.splitlines():
        os.rmdir(path)


def rm_empty_dirs() -> None:
    step("Removing empty directories")
    for _ in range(3):
        rm_empty_dir(DIST)


def zip_modules(light: bool) -> None:
    step("zipping up some Python modules")
    # these modules contain native code or data files,
    # so they will require special treatment:
    # xpra numpy cryptography PIL nacl cffi gtk gobject glib aioquic pylsqpack > /dev/null
    ZIPPED = [
        "OpenGL", "encodings", "future", "paramiko", "html",
        "pyasn1", "asn1crypto", "async_timeout",
        "OpenSSL", "keyring",
        "ifaddr", "pyaes", "service_identity",
        "re", "platformdirs", "attr", "setproctitle", "pyvda", "zipp",
        "distutils", "comtypes", "email", "multiprocessing", "packaging",
        "pkg_resources", "pycparser", "idna", "ctypes", "json",
        "http", "enum", "winreg", "copyreg", "_thread", "_dummythread",
        "builtins", "importlib",
        "logging", "queue", "urllib", "xml", "xmlrpc", "pyasn1_modules",
        "concurrent", "collections",
    ]
    if not light:
        ZIPPED += EXTRA_PYTHON_MODULES
    log_command(["zip", "--move", "-ur", "library.zip"] + ZIPPED, "zip.log", cwd=LIB_DIR)


def setup_share(light: bool) -> None:
    step("Deleting unnecessary `share/` files")
    delete_dist_files(
        "share/xml",
        "share/glib-2.0/codegen",
        "share/glib-2.0/gdb",
        "share/glib-2.0/gettext",
        "share/locale",
        "share/gstreamer-1.0",
        "share/gst-plugins-base",
        "share/p11-kit",
    )
    if light:
        # remove extra bits that take up a lot of space:
        delete_dist_files(
            "share/icons/Adwaita/cursors",
            "share/fonts/gsfonts",
            "share/fonts/adobe*",
            "share/fonts/cantarell",
        )
    step("Removing empty icon directories")
    # remove empty icon directories
    for _ in range(4):
        rm_empty_dir(f"{DIST}/share/icons")


def add_manifests(light: bool) -> None:
    step("Adding EXE manifests")
    EXES = [
        "Bug_Report", "Xpra-Launcher", "Xpra", "Xpra_cmd", "Configure", "PDFIUM_Print",
    ]
    if not light:
        EXES += [
            "Xpra-Shadow", "Xpra-Proxy_cmd", "Xpra-Proxy",
            "Python_exec_cmd", "Python_exec_gui",
            "Xpra-Launcher-Debug",
            "Config_info",
            "Python_execfile_cmd", "Python_execfile_gui",
            "Print", "NVidia_info", "NvFBC_capture", "CUDA_info",
            "Auth_Dialog",
            "OpenGL_check",
            "GTK_info", "NativeGUI_info", "Screenshot",
            "Version_info", "Network_info", "Keymap_info", "Keyboard_info",
            "SystemTray_Test", "U2F_Tool",
            "SQLite_auth_tool", "SQL_auth_tool",
            "Encoding_info", "Path_info", "Feature_info", "NativeGUI_info",
            "Xpra_Audio",
            "GStreamer_info", "Audio_Devices",
            "gst-launch-1.0", "gst-inspect-1.0",
            "Webcam_info", "Webcam_Test",
            "System-Auth-Test", "LDAP-Auth-Test", "LDAP3-Auth-Test",
            "System-Logon-Test", "Events_Test", "GTK_Keyboard_Test",
        ]
    with open('packaging/MSWindows/exe.manifest', 'r') as file:
        xml_file_content = file.read()
    zero_padded_version = version_info.padded
    xml_file_content = xml_file_content.replace("XPRA_ZERO_PADDED_VERSION", zero_padded_version)
    with open('packaging/MSWindows/exe.manifest.tmp', 'w') as file:
        file.write(xml_file_content)
    for exe in EXES:
        copyfile("packaging/MSWindows/exe.manifest.tmp", f"{DIST}/{exe}.exe.manifest")
    os.remove('packaging/MSWindows/exe.manifest.tmp')


def gen_caches() -> None:
    step("Generating gdk pixbuf loaders cache")
    cmd = ["gdk-pixbuf-query-loaders.exe"]
    for loader in glob(f"{DIST}/lib/gdk-pixbuf-2.0/2.10.0/loaders/*"):
        cmd.append(loader.split(f"{DIST}/", 1)[1])
    with Popen(cmd, cwd=os.path.abspath(DIST), stdout=PIPE, text=True) as proc:
        cache, err = proc.communicate(None)
    if proc.returncode != 0:
        raise RuntimeError(f"gdk-pixbuf-query-loaders.exe failed and returned {proc.returncode}: {err}"
                           " - you may need to run `chcp.com 65001`")
    # replace absolute paths:
    cache = re.sub(r'".*xpra/dist/lib/', '"lib/', cache)
    with open(f"{LIB_DIR}/gdk-pixbuf-2.0/2.10.0/loaders.cache", "w") as cache_file:
        cache_file.write(cache)
    step("Generating icons and theme cache")
    for itheme in glob(f"{DIST}/share/icons/*"):
        log_command(["gtk-update-icon-cache.exe", "-t", "-i", itheme], "icon-cache.log")


def bundle_manual() -> None:
    step("Generating HTML Manual Page")
    manual = os.path.join(DIST, "manual.html")
    delfile(manual)
    with open("fs/share/man/man1/xpra.1", "rb") as f:
        man = f.read()
    proc = Popen(["groff", "-mandoc", "-Thtml"], stdin=PIPE, stdout=PIPE, stderr=PIPE)
    out, err = proc.communicate(man)
    if proc.returncode != 0:
        raise RuntimeError(f"groff failed and returned {proc.returncode}: {err!r}")
    debug(f"groff warnings: {err!r}")
    with open(manual, "wb") as manual_file:
        manual_file.write(out)


def bundle_html5() -> None:
    step("Installing the HTML5 client")
    www = os.path.join(os.path.abspath("."), DIST, "www")
    if not os.path.exists(www):
        os.mkdir(www)
    html5 = os.path.join(os.path.abspath("."), "xpra-html5")
    debug(f"running html5 install step in {html5!r}")
    log_command([PYTHON, "./setup.py", "install", www], "html5.log", cwd=html5)


def bundle_putty() -> None:
    step("Bundling TortoisePlink")
    tortoiseplink = find_command("TortoisePlink", "TORTOISEPLINK",
                                 f"{PROGRAMFILES}\\TortoiseSVN\\bin\\TortoisePlink.exe")
    copyfile(tortoiseplink, f"{DIST}/Plink.exe")
    for dll in ("vcruntime140.dll", "msvcp140.dll", "vcruntime140_1.dll"):
        copyfile(f"{SYSTEM32}/{dll}", f"{DIST}/{dll}")


def bundle_dlls(*expr: str) -> None:
    for exp in expr:
        matches = glob(f"{exp}.dll")
        if not matches:
            print(f"Warning: no dll matching {exp!r}")
            continue
        for match in matches:
            name = os.path.basename(match)
            target = f"{DIST}/{name}"
            if not os.path.exists(target):
                copyfile(match, target)


def bundle_openssh() -> None:
    step("Bundling OpenSSH")
    for exe_name in ("ssh", "sshpass", "ssh-keygen"):
        exe = which(exe_name)
        if not exe:
            raise RuntimeError(f"{exe_name!r} not found!")
        copyfile(exe, f"{DIST}/{exe_name}.exe")
    bin_dir = os.path.dirname(which("ssh"))
    debug(f"looking for msys DLLs in {bin_dir!r}")
    msys_dlls = tuple(
        f"{bin_dir}/msys-{dllname}*" for dllname in (
            "2.0", "gcc_s", "crypto", "z", "gssapi", "asn1", "com_err", "roken",
            "crypt", "heimntlm", "krb5", "heimbase", "wind", "hx509", "hcrypto", "sqlite3",
        )
    )
    bundle_dlls(*msys_dlls)


def bundle_openssl() -> None:
    step("Bundling OpenSSL")
    copyfile(f"{MINGW_PREFIX}/bin/openssl.exe", f"{DIST}/openssl.exe")
    ssl_dir = f"{DIST}/etc/ssl"
    if not os.path.exists(ssl_dir):
        os.mkdir(ssl_dir)
    copyfile(f"{MINGW_PREFIX}/etc/ssl/openssl.cnf", f"{ssl_dir}/openssl.cnf")
    # we need those libraries at the top level:
    bundle_dlls(f"{LIB_DIR}/libssl-*", f"{LIB_DIR}/libcrypto-*")


def bundle_paxec() -> None:
    step("Bundling paexec")
    copyfile(f"{MINGW_PREFIX}/bin/paexec.exe", f"{DIST}/paexec.exe")


def bundle_desktop_logon() -> None:
    step("Bundling desktop_logon")
    dl_dlls = tuple(f"{MINGW_PREFIX}/bin/{dll}" for dll in ("AxMSTSCLib", "MSTSCLib", "DesktopLogon"))
    bundle_dlls(*dl_dlls)


def bundle_x11_dlls() -> None:
    bundle_dlls(f"{X11_DLL_DIR}/*")


def add_cuda(enabled: bool) -> None:
    step(f"cuda: {enabled}")
    if not enabled:
        delete_libs("pycuda*")
        find_delete(DIST, "pycuda*")
        find_delete(DIST, "libnv*")
        find_delete(DIST, "cuda.conf")
        delete_libs("curand*")
        cuda_dir = os.path.join(LIB_DIR, "cuda")
        if os.path.exists(cuda_dir):
            rmtree(cuda_dir)
        return
    # pycuda wants a CUDA_PATH with "/bin" in it:
    if not os.path.exists(f"{DIST}/bin"):
        os.mkdir(f"{DIST}/bin")
    # keep the cuda bits at the root:
    for nvdll in glob(f"{LIB_DIR}/libnv*.dll"):
        move_lib(nvdll, DIST)


def rec_options(args) -> None:
    info = dict((k, getattr(args, k)) for k in dir(args) if not k.startswith("_"))
    with open(BUILD_INFO, "a") as f:
        f.write(f"\n\nBUILD_OPTIONS={info!r}\n")


def find_source(path: str) -> str:
    basename = os.path.basename(path)
    if path.endswith(".exe"):
        filename = which(basename)
        if filename:
            return filename
    # try "$MINGW_PREFIX/bin/$basename" and "$MINGW_PREFIX/$path":
    for filename in (os.path.join(MINGW_PREFIX, "bin", basename), os.path.join(MINGW_PREFIX, path)):
        if os.path.exists(filename):
            return filename
    # try %PATH%:
    for bpath in os.environ.get("PATH", "").split(os.path.pathsep):
        filename = os.path.join(bpath, basename)
        if os.path.exists(filename):
            return filename
    return ""


def get_command_info(*args: str) -> dict[str, str]:
    cmd = command_args(list(args))
    r, output = getstatusoutput(cmd)
    if r:
        debug(f"{args} failed and returned {r}")
        return {}
    props: dict[str, str] = {}
    for line in output.split("\n"):
        parts = line.split(":", 1)
        if len(parts) == 2:
            props[parts[0].strip()] = parts[1].strip()
    return props


def get_pacman_package_info(name: str) -> dict[str, str]:
    return get_command_info("pacman", "-Qi", name)


def get_pip_package_info(name: str) -> dict[str, str]:
    return get_command_info("pip", "show", name)


def get_package(path: str) -> tuple[str, str]:
    filename = find_source(path)
    if not filename:
        debug(f"failed to locate source path for {path!r}")
        return "", ""
    cmd = command_args(["pacman", "-Qo", filename])
    r, output = getstatusoutput(cmd)
    if r:
        debug(f"pacman failed for {filename!r} and returned {r}")
        return "", ""
    # ie: "/usr/bin/msys-2.0.dll is owned by msys2-runtime 3.5.4-2" ->
    #     ["/usr/bin/msys-2.0.dll", "msys2-runtime 3.5.4-2"]
    parts = output.split("\n")[0].split("is owned by ")
    if len(parts) != 2:
        debug(f"unable to parse pacman output: {output!r}")
        return "", ""
    # ie: "msys2-runtime 3.5.4-2" -> ["msys2-runtime", "3.5.4-2"]
    package, version = parts[1].split(" ", 1)
    return package, version


def get_py_lib_dirs() -> list[str]:
    # python modules:
    py_lib_dirs: list[str] = []
    for k in ("stdlib", "platstdlib", "purelib", "platlib", ):
        path = get_path(k)
        if os.path.exists(path) and path not in py_lib_dirs:
            py_lib_dirs.append(path)
            for extra in ("lib-dynload", "win32", "pywin32_system32"):
                epath = os.path.join(path, extra)
                if os.path.exists(epath) and epath not in py_lib_dirs:
                    py_lib_dirs.append(epath)
    debug(f"using python lib directories: {py_lib_dirs!r}")
    return py_lib_dirs


def pip_sbom_rec(prefix: str, filename: str) -> dict[str, Any]:
    pip_rec = get_pip_package_info(filename)
    if not pip_rec:
        return {}
    rec = {
        "package": "python-" + pip_rec["Name"],
        "version": pip_rec["Version"],
        "pip": True,
    }
    dist_path = os.path.join(prefix, filename)
    add_size_checksum(rec, dist_path)
    return rec


def sbom_rec(path: str) -> dict[str, Any]:
    package, version = get_package(path)
    if not (package and version):
        return {}
    rec = {
        "package": package,
        "version": version,
    }
    dist_path = os.path.join(DIST, path)
    add_size_checksum(rec, dist_path)
    return rec


def add_size_checksum(rec: dict[str, Any], dist_path: str) -> None:
    if os.path.isdir(dist_path):
        rec["size"] = du(dist_path)
    else:
        rec["size"] = os.stat(dist_path).st_size
        with open(dist_path, "rb") as f:
            data = f.read()
        rec["checksum"] = hashlib.sha256(data).hexdigest()


def find_glob_paths(dirname: str, glob_str: str) -> list[str]:
    cmd = command_args(["find", dirname, "-name", "'"+glob_str+"'"])
    r, output = getstatusoutput(cmd)
    assert r == 0, f"{cmd!r} failed and returned {r}"
    return output.splitlines()


def shorten_package_name(package: str) -> str:
    if package.startswith(PACKAGE_PREFIX):
        return package[len(PACKAGE_PREFIX):]
    if os.path.basename(package).startswith(MSYS_DLL_PREFIX):
        # ie: "msys-com_err-1.dll"
        return package
    if package.startswith(MSYS2_PACKAGE_PREFIX):
        # ie: "msys2-runtime"
        return package
    debug(f"unexpected package prefix: {package!r}")
    return package


def rec_sbom() -> None:
    step("Recording SBOM")
    sbom: dict[str, dict[str, Any]] = {}
    py_lib_dirs: list[str] = get_py_lib_dirs()

    def find_prefixed_sbom_rec(filename: str, prefixes: list[str]) -> dict[str, Any]:
        for prefix in prefixes:
            src_path = os.path.join(prefix, filename)
            if os.path.exists(src_path):
                rec = sbom_rec(src_path) or pip_sbom_rec(prefix, filename)
                if rec:
                    package = rec["package"]
                    version = rec["version"]
                    debug(f" * {filename!r}: {package!r}, {version!r}")
                    return rec
        print(f"Warning: unknown source for filename {filename!r}, tried {prefixes}")
        return {}

    def rec_py_lib(path: str) -> None:
        assert path.startswith("lib/"), f"invalid path {path!r}"
        name = os.path.basename(path)
        rec = find_prefixed_sbom_rec(name, py_lib_dirs)
        if rec:
            sbom[f"lib/{path}"] = rec

    def rec_pyqt_lib(path: str) -> None:
        assert path.startswith("lib/PyQt6")
        share_dirs = os.environ.get("XDG_DATA_DIRS", f"{MINGW_PREFIX}/share").split(os.path.pathsep)
        dirs = []
        for share_dir in share_dirs:
            dirs += glob(f"{share_dir}/qt6/plugins/*")
        name = os.path.basename(path)
        rec = find_prefixed_sbom_rec(name, dirs)
        if rec:
            sbom[path] = rec

    def rec_cuda(path: str) -> None:
        if not os.path.exists("CUDA") or not os.path.isdir("CUDA"):
            raise RuntimeError("CUDA not found!")
        version_json = os.path.join("CUDA", "version.json")
        if not os.path.exists(version_json):
            raise RuntimeError(f"{version_json!r} does not exist")
        with open(version_json, "r") as f:
            version_data = json.loads(f.read())
        cuda_version = version_data["cuda"]["version"]
        sbom[path] = {
            "package": "cuda",
            "version": cuda_version,
        }

    globbed_paths = find_glob_paths(DIST, "*.dll") + find_glob_paths(LIB_DIR, "*.exe")
    debug(f"adding DLLs and EXEs: {globbed_paths}")
    for globbed_path in globbed_paths:
        path = globbed_path[len(DIST)+1:]
        if path.startswith("lib/PyQt6"):
            rec_pyqt_lib(path)
        elif path.startswith("lib/python"):
            # some need to be resolved in the python library paths:
            rec_py_lib(path)
        elif path.startswith("lib/curand"):
            rec_cuda(path)
        elif path in ("AxMSTSCLib.dll", "MSTSCLib.dll", "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"):
            debug(f"ignoring {path!r} (.NET SDK)")
        elif path in ("DesktopLogon.dll", ):
            debug(f"ignoring {path!r} (one of ours)")
        else:
            rec = sbom_rec(path)
            if rec:
                package = rec["package"]
                version = rec["version"]
                debug(f" * {path!r}: {package!r}, {version!r}")
                sbom[path] = rec
            else:
                print(f"Warning: no package data found for {path!r}")

    # python modules:
    debug("adding python modules")
    SKIP_DIRS = (
        "xpra", "tlb",
        "gi", "gio", "pkcs11", "girepository-1.0", "gstreamer-1.0", "gtk-3.0", "gdk-pixbuf-2.0",
    )
    for child in os.listdir(LIB_DIR):
        if child in SKIP_DIRS or child.endswith(".dll"):
            continue
        path = os.path.join(LIB_DIR, child)
        if os.path.isdir(path) or path.endswith(".py") or path.endswith(".pyd"):
            rec_py_lib(os.path.join("lib", child))
    # add this one by hand because cx_Freeze hides it in `library.zip`,
    # and we don't want to start unpacking a large ZIP file and converting .pyc to .py
    # just for one filename:
    rec_py_lib(os.path.join("lib", "decorator.py"))

    # summary: list of packages
    packages = tuple(sorted(set(rec["package"] for rec in sbom.values())))
    debug(f"adding package info for {packages}")
    packages_info: dict[str, dict] = {}
    for package_name in packages:
        package = shorten_package_name(package_name)
        # keep only the keys relevant to the sbom:
        info = get_pacman_package_info(package_name) or get_pip_package_info(package_name)
        exported_info = {}
        for key in (
            "Name", "Version", "Description",
            "Architecture", "URL", "Licenses", "Depends On", "Required By", "Provides",
        ):
            value = info.get(key)
            if str(value) == "None":
                continue
            if key in ("Depends On", "Required By", "Provides"):
                value = [x.strip() for x in str(value).split(" ") if x.strip()]
            exported_info[key] = value
        packages_info[package] = exported_info

    debug(f"recording sbom data: {len(sbom)} paths, {len(packages)} packages")
    with open(BUILD_INFO, "a") as f:
        f.write(f"\n# {len(sbom)} SBOM path entries:\n")
        f.write(f"sbom={sbom!r}\n")
        f.write(f"\n# {len(packages_info)} packages:\n")
        f.write(f"packages={packages_info!r}\n")
    # also replace it in the target directory:
    find_delete(LIB_DIR, os.path.basename(BUILD_INFO))
    copyfile(BUILD_INFO, f"{LIB_DIR}/{BUILD_INFO}")


def export_sbom() -> None:
    WIN_PYTHON = "C:\\Program Files\\Python312\\python.exe"
    SBOM_SCRIPT = "packaging\\MSWindows\\cyclonedx_sbom.py"
    output = f"{DIST}/{SBOM_JSON}"
    delfile(output)
    env = os.environ.copy()
    env["PYTHONPATH"] = "."
    log_command([WIN_PYTHON, SBOM_SCRIPT, output], "export-sbom.log", env=env)
    # make a copy that can be distributed separately:
    SBOM_FILENAME = f"Xpra{version_info.extra}{version_info.arch_info}_{version_info.full_string}.json"
    delfile(SBOM_FILENAME)
    copyfile(output, SBOM_FILENAME)


def verpatch() -> None:
    EXCLUDE = ("plink", "openssh", "openssl", "paexec")

    def run_verpatch(filename: str, descr: str) -> None:
        log_command(["verpatch", filename,
                     "/s", "desc", descr,
                     "/va", version_info.padded,
                     "/s", "company", "xpra.org",
                     "/s", "copyright", "(c) xpra.org 2024",
                     "/s", "product", "xpra",
                     "/pv", version_info.padded,
                     ], "verpatch.log")

    for exe in glob(f"{DIST}/*.exe"):
        if any(exe.lower().find(excl) >= 0 for excl in EXCLUDE):
            continue
        exe_name = os.path.basename(exe)
        if exe_name in ("Xpra_cmd.exe", "Xpra.exe", "Xpra-Proxy.exe"):
            # handled separately below
            continue
        assert exe_name.endswith(".exe")
        tool_name = exe_name[:-3].replace("Xpra_", "").replace("_", " ").replace("-", " ")
        run_verpatch(exe, f"Xpra {tool_name}")
    run_verpatch(f"{DIST}/Xpra_cmd.exe", "Xpra command line")
    run_verpatch(f"{DIST}/Xpra.exe", "Xpra")
    if os.path.exists(f"{DIST}/Xpra-Proxy.exe"):
        run_verpatch(f"{DIST}/Xpra-Proxy.exe", "Xpra Proxy Server")


################################################################################
# packaging: ZIP / EXE / MSI

def create_zip() -> None:
    step("Creating ZIP file:")
    ZIP_DIR = f"Xpra{version_info.extra}{version_info.arch_info}_{version_info.full_string}"
    ZIP_FILENAME = f"{ZIP_DIR}.zip"
    if os.path.exists(ZIP_DIR):
        rmrf(ZIP_DIR)
    delfile(ZIP_FILENAME)
    copytree(DIST, ZIP_DIR)
    log_command(["zip", "-9mr", ZIP_FILENAME, ZIP_DIR], "zip.log")
    size = du(ZIP_FILENAME) // 1024 // 1024
    print(f"{ZIP_FILENAME}: {size}MB")


def create_exe(args) -> str:
    step("Creating the EXE installer using InnoSetup")
    innosetup = find_command("innosetup", "INNOSETUP",
                             f"{PROGRAMFILES}\\Inno Setup 6\\ISCC.exe",
                             f"{PROGRAMFILES_X86}\\Inno Setup 6\\ISCC.exe",
                             )
    SETUP_EXE = f"{DIST}/Xpra_Setup.exe"
    INSTALLER_FILENAME = f"Xpra{version_info.extra}{version_info.arch_info}_Setup_{version_info.full_string}.exe"
    XPRA_ISS = "xpra.iss"
    INNOSETUP_LOG = "innosetup.log"
    for filename in (XPRA_ISS, INNOSETUP_LOG, INSTALLER_FILENAME, SETUP_EXE):
        delfile(filename)
    with open("packaging/MSWindows/xpra.iss", "r") as f:
        contents = f.readlines()
    lines = []
    subs = {
        "AppId": "Xpra_is1",
        "AppName": f"Xpra {version_info.string}",
        "UninstallDisplayName": f"Xpra {version_info.string}",
        "AppVersion": version_info.full_string,
    }
    for line in contents:
        if line.startswith("    PostInstall()") and args.light:
            # don't run post-install openssl:
            line = "Log('skipped post-install');"
        elif line.find("Xpra Shadow Server") >= 0 and args.light:
            # no shadow server in light builds
            continue
        elif line.find("Command Manual") >= 0 and not args.docs:
            # remove link to the manual:
            continue
        if line.find("=") > 0:
            parts = line.split("=", 1)
            if parts[0] in subs:
                line = parts[0] + "=" + subs[parts[0]]+"\n"
        lines.append(line)
    with open(XPRA_ISS, "w") as f:
        f.writelines(lines)

    log_command([innosetup, XPRA_ISS], INNOSETUP_LOG)
    os.unlink(XPRA_ISS)

    os.rename(SETUP_EXE, INSTALLER_FILENAME)
    size = du(INSTALLER_FILENAME) // 1024 // 1024
    print(f"{INSTALLER_FILENAME}: {size}MB")
    return INSTALLER_FILENAME


def sign_file(filename: str) -> None:
    log_command(["signtool.exe", "sign", "/fd", "SHA256", "/v", "/f", KEY_FILE, "/t", TIMESTAMP_SERVER, filename], "signtool.log")


def create_msi(exe: str) -> str:
    msiwrapper = find_command("msiwrapper", "MSIWRAPPER",
                              f"{PROGRAMFILES}\\MSI Wrapper\\MsiWrapper.exe",
                              f"{PROGRAMFILES_X86}\\MSI Wrapper\\MsiWrapper.exe")
    MSI_FILENAME = f"Xpra{version_info.extra}{version_info.arch_info}_{version_info.full_string}.msi"
    # search and replace in the template file:
    subs: dict[str, str] = {
        "CWD": os.getcwd(),
        "INPUT": exe,
        "OUTPUT": MSI_FILENAME,
        "ZERO_PADDED_VERSION": version_info.padded,
        "FULL_VERSION": version_info.full_string,
    }
    with open("packaging\\MSWindows\\msi.xml", "r") as template:
        msi_data = template.read()
    for varname, value in subs.items():
        msi_data = msi_data.replace(f"${varname}", value)
    MSI_XML = "msi.xml"
    with open(MSI_XML, "w") as f:
        f.write(msi_data)
    log_command([msiwrapper, MSI_XML], "msiwrapper.log")
    size = du(MSI_FILENAME) // 1024 // 1024
    print(f"{MSI_FILENAME}: {size}MB")
    return MSI_FILENAME


def build(args) -> None:
    set_version_info(args.light)
    if args.html5:
        check_html5()
    if args.sign:
        check_signtool()

    if args.clean:
        clean()
    if args.service:
        build_service()
    if args.cuda:
        build_cuda_kernels()
    if args.build:
        build_ext(args)
    if args.tests:
        run_tests()
    if args.install:
        add_manifests(args.light)
        install_exe(args)

    if args.fixups:
        fixups(args.light)
        fixup_gstreamer()
        fixup_dlls()
        delete_dlls(args.light)
        trim_python_libs()
        trim_pillow()
        fixup_zeroconf()
        if args.light:
            delete_libs(*EXTRA_PYTHON_MODULES)
        rm_empty_dirs()

    add_cuda(args.cuda)
    add_numpy(args.numpy)

    setup_share(args.light)
    gen_caches()

    if args.docs:
        bundle_manual()
        install_docs()
    if args.html5:
        bundle_html5()
    if args.putty:
        bundle_putty()
    if args.openssh:
        bundle_openssh()
    if args.openssl:
        bundle_openssl()
    if args.paexec:
        bundle_paxec()
    if args.desktop_logon:
        bundle_desktop_logon()
    if args.x11:
        bundle_x11_dlls()
    rec_options(args)
    if args.sbom:
        rec_sbom()
        export_sbom()

    if args.zip_modules:
        zip_modules(args.light)

    if args.verpatch:
        verpatch()

    size = du(DIST) // 1024 // 1024
    print(f"installed size: {size}MB")
    if args.zip:
        create_zip()
    if args.exe:
        exe = create_exe(args)
        if not os.path.exists(exe):
            raise RuntimeError(f"failed to create EXE installer {exe!r}")
        if args.sign:
            step("Signing EXE")
            sign_file(exe)
        if args.run:
            step(f"Running the new EXE installer {exe!r}")
            os.system(exe)
        if args.msi:
            msi = create_msi(exe)
            if not os.path.exists(msi):
                raise RuntimeError("failed to create msi")
            if args.sign:
                step("Signing MSI")
                sign_file(msi)


def main(argv) -> None:
    args, unknownargs = parse_command_line(argv)
    if len(unknownargs) > 1:
        if len(unknownargs) != 2:
            raise ValueError(f"too many arguments: {unknownargs!r}")
        arg = unknownargs[1]
        if arg == "sbom":
            rec_sbom()
        elif arg == "export-sbom":
            load_version_info(args.light)
            export_sbom()
        elif arg == "gen-caches":
            gen_caches()
        elif arg == "zip":
            create_zip()
        elif arg == "exe":
            create_exe(args)
        else:
            raise ValueError(f"unknown argument {arg!r}")
    else:
        build(args)


if __name__ == "__main__":
    main(sys.argv)
