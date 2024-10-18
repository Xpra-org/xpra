#!/bin/python
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path
import shlex
from datetime import datetime
from collections.abc import Iterable
from importlib.util import find_spec, spec_from_file_location, module_from_spec

from glob import glob
from subprocess import getstatusoutput, check_output, Popen, getoutput
from shutil import which, rmtree, copyfile, move, copytree

KEY_FILE = "E:\\xpra.pfx"
DIST = "dist"
LIB_DIR = f"{DIST}/lib"

DEBUG = os.environ.get("XPRA_DEBUG", "0") != "0"
PYTHON = os.environ.get("PYTHON", "python3")
MINGW_PREFIX = os.environ.get("MINGW_PREFIX", "")
TIMESTAMP_SERVER = "http://timestamp.digicert.com"
# alternative:
# http://timestamp.comodoca.com/authenticode

PROGRAMFILES = "C:\\Program Files"
PROGRAMFILES_X86 = "C:\\Program Files (x86)"
SYSTEM32 = "C:\\Windows\\System32"

BUILD_INFO = "xpra/build_info.py"

LOG_DIR = "packaging/MSWindows/"

NPROCS = int(os.environ.get("NPROCS", os.cpu_count()))

BUILD_CUDA_KERNEL = "packaging\\MSWindows\\BUILD_CUDA_KERNEL.BAT"


def parse_command_line():
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
    add("full", help="fat build including everything")
    add("installer", help="create an EXE installer")
    add("run", help="run the installer")
    add("msi", help="create an MSI installer")
    add("sign", help="sign the EXE and MSI installers")
    add("tests", help="run the unit tests", default=False)
    add("zip-modules", help="zip up python modules")
    add("cuda", help="build CUDA kernels for nvidia codecs")
    add("service", help="build the system service")
    add("docs", help="generate the documentation")
    add("html5", help="bundle the `xpra-html5` client")
    add("manual", help="bundle the user manual")
    add("numpy", help="bundle `numpy`")
    add("putty", help="bundle putty `plink`")
    add("openssh", help="bundle the openssh client")
    add("openssl", help="bundle the openssl tools")
    add("paexec", help="bundle `paexec`")
    add("desktop-logon", help="build `desktop-logon` tool")

    args = ap.parse_args()
    if not args.full:
        # disable many switches:
        args.cuda = args.numpy = args.service = args.docs = args.html5 = args.manual = False
        args.putty = args.openssh = args.openssl = args.paexec = args.desktop_logon = False
    if args.verbose:
        global DEBUG
        DEBUG = True
    return args


def step(message: str) -> None:
    now = datetime.now()
    ts = f"{now.hour:02}:{now.minute:02}:{now.second:02}"
    print(f"* {ts} {message}")


def debug(message: str) -> None:
    if DEBUG:
        print("    "+message)


def csv(values: Iterable) -> str:
    return ", ".join(str(x) for x in values)


def get_build_args(args) -> list[str]:
    xpra_args = []
    if args.full:
        xpra_args.append("--with-qt6_client")
    else:
        for option in (
            "shadow", "server", "proxy", "rfb",
            "dbus",
            "encoders", "avif", "gstreamer_video",
            "nvfbc", "cuda_kernels",
            "csc_cython",
            "webcam",
            "win32_tools",
            "docs",
            "qt6_client",
        ):
            xpra_args.append(f"--without-{option}")
        xpra_args.append("--with-Os")
    if not args.cuda:
        xpra_args.append("--without-nvidia")
    # we can't do 'docs' this way :(
    # for arg in ("docs", ):
    #    value = getattr(args, arg)
    #    xpra_args.append(f"--with-{arg}={value}")       #ie: "--with-docs=True"
    return xpra_args


def find_command(name: str, env_name: str, *paths) -> str:
    cmd = os.environ.get(env_name, "")
    if cmd and os.path.exists(cmd):
        return cmd
    cmd = which(name)
    if cmd and os.path.exists(cmd):
        return cmd
    for path in paths:
        if os.path.exists(path) and os.path.isfile(path):
            return path
    print(f"{name!r} not found")
    print(f" (you can set the {env_name!r} environment variable to point to it)")
    raise RuntimeError(f"{name!r} not found")


def find_java() -> str:
    try:
        return find_command("java", "JAVA")
    except RuntimeError:
        pass
    # try my hard-coded default first to save time:
    java = f"{PROGRAMFILES}\\Java\\jdk1.8.0_121\\bin\\java.exe"
    if java and getstatusoutput(f"{java} --version")[0] == 0:
        return java
    dirs = (f"{PROGRAMFILES}/Java", f"{PROGRAMFILES}", f"{PROGRAMFILES_X86}")
    for directory in dirs:
        r, output = getstatusoutput(f"find {directory} -name java.exe")
        if r == 0:
            return output[0]
    raise RuntimeError(f"java.exe was not found in {dirs}")


def sanity_checks(args) -> None:
    if args.html5:
        if not os.path.exists("xpra-html5") or not os.path.isdir("xpra-html5"):
            print("html5 client not found")
            print(" perhaps run: `git clone https://github.com/Xpra-org/xpra-html5`")
            raise RuntimeError("`xpra-html5` client not found")

        # Find a java interpreter we can use for the html5 minifier
        os.environ["JAVA"] = find_java()

    if args.sign:
        try:
            signtool = find_command("signtool", "SIGNTOOL",
                                    f"{PROGRAMFILES}\\Microsoft SDKs\\Windows\\v7.1\\Bin\\signtool.exe"
                                    f"{PROGRAMFILES}\\Microsoft SDKs\\Windows\\v7.1A\\Bin\\signtool.exe"
                                    f"{PROGRAMFILES_X86}\\Windows Kits\\8.1\\Bin\\x64\\signtool.exe"
                                    f"{PROGRAMFILES_X86}\\Windows Kits\\10\\App Certification Kit\\signtool.exe")
        except RuntimeError:
            # try the hard (slow) way:
            r, output = getstatusoutput('find "c:\\Program\\ Files*" -wholename "*/x64/signtool.exe"')
            if r != 0:
                raise
            signtool = output[0]
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
    if os.path.exists(log_filename):
        os.unlink(log_filename)
    if not kwargs.get("shell"):
        cmd = command_args(cmd)
    with open(log_filename, "w") as f:
        ret = Popen(cmd, stdout=f, stderr=f, **kwargs).wait()
    if ret != 0:
        show_tail(log_filename)
        raise RuntimeError(f"{cmd!r} failed and returned {ret}, see {log_filename!r}")


def find_delete(path: str, name: str, mindepth=0) -> None:
    debug(f"deleting all instances of {name!r} from {path!r}/")
    cmd = ["find", path]
    if mindepth > 0:
        cmd += ["-mindepth", str(mindepth)]
    if name:
        cmd += ["-name", "'"+name+"'"]
    cmd += ["-type", "f"]
    output = getoutput(command_args(cmd))
    for filename in output.splitlines():
        if os.path.exists(filename):
            debug(f"removing {filename!r}")
            os.unlink(filename)


def rmrf(path: str) -> None:
    if not os.path.exists(path):
        print(f"Warning: {path!r} does not exist")
        return
    rmtree(path)


def clean() -> None:
    step("Cleaning output directories and generated files")
    debug("cleaning log files:")
    find_delete("packaging/MSWindows/", "*.log")
    for dirname in (DIST, "build"):
        if os.path.exists(dirname):
            rmtree(dirname)
        os.mkdir(dirname)
    # clean sometimes errors on removing pyd files,
    # so do it with rm instead:
    debug("removing compiled dll and pyd files:")
    find_delete("xpra", "*-cpython-*dll")
    find_delete("xpra", "*-cpython-*pyd")
    debug("python clean")
    log_command(f"{PYTHON} ./setup.py clean", "clean.log")
    debug("remove comtypes cache:")
    # clean comtypes cache - it should not be included!
    check_output(command_args("clear_comtypes_cache.exe -y"))
    debug("ensure build info is regenerated")
    if os.path.exists(BUILD_INFO):
        os.unlink(BUILD_INFO)


def build_service() -> None:
    step("* Compiling system service shim")
    # ARCH_DIRS = ("x64", "x86")
    raise NotImplementedError()


VERSION = "invalid"
VERSION_INFO = (0, 0)
REVISION = "invalid"
FULL_VERSION = "invalid"
BUILD_ARCH_INFO = "invalid"
EXTRA_VERSION = ""
ZERO_PADDED_VERSION = (0, 0, 0, 0)


def set_version_info(full: bool):
    step("Collection version information")
    for filename in ("src_info.py", "build_info.py"):
        path = os.path.join("xpra", filename)
        if os.path.exists(path):
            os.unlink(path)
    log_command([PYTHON, "fs/bin/add_build_info.py", "src", "build"], "add-build-info.log")
    print("    Python " + sys.version)

    def load(src: str):
        spec = spec_from_file_location("xpra", f"xpra/{src}")
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    xpra = load("__init__.py")
    src_info = load("src_info.py")
    global VERSION, VERSION_INFO, REVISION, ZERO_PADDED_VERSION, FULL_VERSION, BUILD_ARCH_INFO, EXTRA_VERSION
    VERSION = xpra.__version__
    VERSION_INFO = xpra.__version_info__
    REVISION = src_info.REVISION
    LOCAL_MODIFICATIONS = src_info.LOCAL_MODIFICATIONS

    FULL_VERSION = f"{VERSION}-r{REVISION}"
    if LOCAL_MODIFICATIONS:
        FULL_VERSION += "M"

    EXTRA_VERSION = "" if full else "-Light"

    # ie: "x86_64"
    BUILD_ARCH_INFO = "-" + os.environ.get("MSYSTEM_CARCH", "")

    # for msi and verpatch:
    padded = (list(VERSION_INFO) + [0, 0, 0])[:3] + [REVISION]
    ZERO_PADDED_VERSION = ".".join(str(x) for x in padded)

    print(f"    Xpra{EXTRA_VERSION} {FULL_VERSION}")


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
        log_command([BUILD_CUDA_KERNEL, kname], f"nvcc-{kname}.log")


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


def install_exe() -> None:
    step("Generating installation directory")
    log_command(f"{PYTHON} ./setup.py install_exe --install={DIST}", "install.log")


def install_docs() -> None:
    step("Generating the documentation")
    if not os.path.exists(f"{DIST}/doc"):
        os.mkdir(f"{DIST}/doc")
    env = os.environ.copy()
    env["PANDOC"] = find_command("pandoc", "PANDOC", f"{PROGRAMFILES}\\Pandoc\\pandoc.exe")
    log_command(f"{PYTHON} ./setup.py doc", "pandoc.log", env=env)


def fixups(full: bool) -> None:
    step("Fixups")
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
    if os.path.exists(f"{LIB_DIR}/comtypes/gen"):
        rmtree(f"{LIB_DIR}/comtypes/gen")
    debug("gdk loaders")
    if not full:
        lpath = os.path.join(LIB_DIR, "gdk-pixbuf-2.0", "2.10.0", "loaders")
        KEEP_LOADERS = ("jpeg", "png", "xpm", "svg", "wmf")
        for filename in os.listdir(lpath):
            if not any(filename.find(keep) for keep in KEEP_LOADERS):
                debug(f"removing {filename!r}")
                os.unlink(os.path.join(lpath, filename))
    debug("remove ffmpeg libraries")
    for libname in ("avcodec", "avformat", "avutil", "swscale", "swresample", "zlib1", "xvidcore"):
        find_delete(LIB_DIR, libname)
    debug("move lz4")


def bundle_numpy(bundle: bool) -> None:
    step(f"numpy: {bundle}")
    lib_numpy = f"{LIB_DIR}/numpy"
    if not bundle:
        debug("removed")
        rmtree(f"{lib_numpy}")
        return
    debug("moving libraries to lib")
    for libname in ("openblas", "gfortran", "quadmath"):
        for dll in glob(f"{lib_numpy}/core/lib{libname}*.dll"):
            move(dll, LIB_DIR)
    debug("trim tests")
    rmrf(f"{lib_numpy}/doc")


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
    for gstdll in glob(f"{LIB_DIR}gst*.dll"):
        move(gstdll, lib_gst)
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
        matches = glob(f"{LIB_DIR}/{exp}")
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
    delete_dist_files(*(f"{LIB_DIR}/{exp}" for exp in exps))


def delete_dlls(full: bool) -> None:
    os.unlink("keyring/testing")
    delete_libs(
        "libjasper*", "lib2to3*", "xdg*", "olefile*", "pygtkcompat*", "jaraco*",
        "p11-kit*", "lz4",
    )
    # remove codecs we don't need:
    delete_libs("libx265*", "libjxl*", "libde265*", "libkvazaar*")
    if not full:
        delete_libs(
            "*.dist-info",
            # kerberos / gss libs:
            "libshishi*", "libgss*",
            # no dbus:
            "libdbus*",
            # no AV1:
            "libaom*", "rav1e*", "libdav1d*", "libheif*",
            # no avif:
            "libavif*", "libSvt*",
            # remove h264 encoder:
            "libx264*",
            # should not be needed:
            "libsqlite*", "libp11-kit*",
            # extra audio codecs (we just keep vorbis and opus):
            "libmp3*", "libwavpack*", "libmpdec*", "libspeex*", "libFLAC*", "libmpg123*", "libfaad*", "libfaac*",
        )

        def delgst(*exps: str) -> None:
            gstlibs = tuple(f"gstreamer-1.0/libgst{exp}*" for exp in exps)
            delete_libs(*gstlibs)
        # matching gstreamer modules:
        delgst("flac", "wavpack", "speex", "wavenc", "lame", "mpg123", "faac", "faad", "wav")
        # these started causing packaging problems with GStreamer 1.24:
        delgst("isomp4")


def trim_pillow() -> None:
    # remove PIL loaders and modules we don't need:
    step("removing unnecessary PIL plugins:")
    KEEP = (
        "Bmp", "Ico", "Jpeg", "Tiff", "Png", "Ppm", "Xpm", "WebP",
        "Image.py", "ImageChops", "ImageCms", "ImageWin", "ImageChops", "ImageColor", "ImageDraw", "ImageFile.py",
        "ImageFilter", "ImageFont", "ImageGrab", "ImageMode", "ImageOps", "ImagePalette", "ImagePath", "ImageSequence",
        "ImageStat", "ImageTransform",
    )
    kept = []
    removed = []
    for filename in glob(f"{LIB_DIR}/PIL/*Image*"):
        infoname = os.path.splitext(os.path.basename(filename))[0]
        if any(filename.find(keep) >= 0 for keep in KEEP):
            kept.append(infoname)
            continue
        removed.append(infoname)
        os.unlink(filename)
    debug(f"removed: {csv(removed)}")
    debug(f"kept: {csv(kept)}")


def trim_python_libs() -> None:
    step("removing unnecessary Python modules")
    # remove test bits we don't need:
    # delete_libs(
    #    # no need for headers:
    #    "cairo/include",
    # )
    step("removing unnecessary files")
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
    # workaround for zeroconf - just copy it wholesale
    # since I have no idea why cx_Freeze struggles with it:
    delete_libs("zeroconf")
    zc = find_spec("zeroconf")
    if not zc:
        print("Warning: zeroconf not found for Python %s" % sys.version)
        return
    zeroconf_dir = os.path.dirname(zc.origin)
    lib_zeroconf = f"{LIB_DIR}/zeroconf"
    if os.path.exists(lib_zeroconf):
        rmtree(lib_zeroconf)
    debug(f"adding zeroconf from {zeroconf_dir!r} to {lib_zeroconf!r}")
    copytree(zeroconf_dir, lib_zeroconf)


def rm_empty_dirs() -> None:
    step("Removing empty directories")

    def rm_empty_dir() -> None:
        cmd = ["find", DIST, "-type", "d", "-empty"]
        output = getoutput(command_args(cmd))
        for path in output.splitlines():
            os.rmdir(path)

    for _ in range(3):
        rm_empty_dir()


def zip_modules(full: bool) -> None:
    step("zipping up some Python modules")
    # these modules contain native code or data files,
    # so they will require special treatment:
    # xpra numpy cryptography PIL nacl cffi gtk gobject glib aioquic pylsqpack > /dev/null
    ZIPPED = [
        "OpenGL", "encodings", "future", "paramiko", "html",
        "pyasn1", "asn1crypto", "async_timeout",
        "certifi", "OpenSSL", "pkcs11", "keyring",
        "ifaddr", "pyaes", "browser_cookie3", "service_identity",
        "re", "platformdirs", "attr", "setproctitle", "pyvda", "zipp",
        "distutils", "comtypes", "email", "multiprocessing", "packaging",
        "pkg_resources", "pycparser", "idna", "ctypes", "json",
        "http", "enum", "winreg", "copyreg", "_thread", "_dummythread",
        "builtins", "importlib",
        "logging", "queue", "urllib", "xml", "xmlrpc", "pyasn1_modules",
        "concurrent", "collections",
    ]
    EXTRAS = ["test", "unittest", "gssapi", "pynvml", "ldap", "ldap3", "pyu2f", "sqlite3", "psutil"]
    if not full:
        delete_libs(*EXTRAS)
    else:
        ZIPPED += EXTRAS
    if os.path.exists(f"{LIB_DIR}/library.zip"):
        os.unlink(f"{LIB_DIR}/library.zip")
    log_command(["zip", "--move", "-ur", "library.zip"] + ZIPPED, "zip.log", cwd=LIB_DIR)


def setup_share(full: bool) -> None:
    step("Deleting unnecessary share/ files")
    delete_dist_files(
        "share/xml", "share/glib-2.0/codegen", "share/glib-2.0/gdb", "share/glib-2.0/gettext",
        "share/themes/Default/gtk-2.0*"
    )
    if not full:
        # remove extra bits that take up a lot of space:
        delete_dist_files(
            "share/icons/Adwaita/cursors",
            "share/fonts/gsfonts",
            "share/fonts/adobe*",
            "share/fonts/cantarell",
            "qt.conf",
        )
    step("Removing empty icon directories")
    # remove empty icon directories
    for _ in range(4):
        os.system(f"find {DIST}/share/icons -type d -exec rmdir {{}} \\; 2> /dev/null")


def add_manifests() -> None:
    step("Adding EXE manifests")
    EXES = [
        "Bug_Report", "Xpra-Launcher", "Xpra", "Xpra_cmd",
        # these are only included in full builds:
        "GTK_info", "NativeGUI_info", "Screenshot", "Xpra-Shadow",
    ]
    for exe in EXES:
        if os.path.exists(f"{DIST}/{exe}.exe"):
            copyfile("packaging/MSWindows/exe.manifest", f"{DIST}/{exe}.exe.manifest")


def gen_caches() -> None:
    step("Generating gdk pixbuf loaders.cache")
    cmd = 'gdk-pixbuf-query-loaders.exe "lib/gdk-pixbuf-2.0/2.10.0/loaders/*"'
    with open(f"{LIB_DIR}/gdk-pixbuf-2.0/2.10.0/loaders.cache", "w") as cache:
        if Popen(cmd, cwd=os.path.abspath(DIST), stdout=cache, shell=True).wait() != 0:
            raise RuntimeError("gdk-pixbuf-query-loaders.exe failed")
    step("Generating icons and theme cache")
    for itheme in glob(f"{DIST}/share/icons/*"):
        os.system(f"gtk-update-icon-cache.exe -t -i {itheme!r}")


def bundle_manual() -> None:
    step("Generating HTML Manual Page")
    os.system("groff.exe -mandoc -Thtml < ./fs/share/man/man1/xpra.1 > ${DIST}/manual.html")


def bundle_html5() -> None:
    step("Installing the HTML5 client")
    www = os.path.join(os.path.abspath("."), DIST, "www")
    if not os.path.exists(www):
        os.mkdir(www)
    html5 = os.path.join(os.path.abspath("."), DIST, "xpra-html5")
    log_command(f"{PYTHON} ./setup.py install {www!r}", "html5.log", cwd=html5)


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
            copyfile(match, f"{DIST}/{name}")


def bundle_openssh() -> None:
    step("Bundling OpenSSH")
    for exe_name in ("ssh", "sshpass", "ssh-keygen"):
        exe = which(exe_name)
        if not exe:
            raise RuntimeError(f"{exe_name!r} not found!")
        copyfile(exe, f"{DIST}/{exe_name}.exe")
    msys_dlls = tuple(
        f"/usr/bin/msys-{dllname}*.dll" for dllname in (
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


def add_cuda(enabled: bool) -> None:
    if not enabled:
        find_delete(DIST, "pycuda*")
        find_delete(DIST, "libnv*")
        find_delete(DIST, "cuda.conf")
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


def verpatch() -> None:
    EXCLUDE = ("plink", "openssh", "openssl", "paexec")

    def run_verpatch(filename: str, descr: str):
        check_output(f'verpatch {filename} //s desc "{descr}" //va "{ZERO_PADDED_VERSION}" "'
                     f'//s company "xpra.org" //s copyright "(c) xpra.org 2020" "'
                     f'//s product "xpra" //pv "{ZERO_PADDED_VERSION}"')

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


def show_diskusage() -> None:
    print()
    print("  installation disk usage:")
    os.system(f"du -sm {DIST!r}")
    print()


################################################################################
# packaging: ZIP / EXE / MSI

def create_zip() -> None:
    step("Creating ZIP file:")
    ZIP_DIR = f"Xpra{EXTRA_VERSION}{BUILD_ARCH_INFO}_{FULL_VERSION}"
    ZIP_FILENAME = f"{ZIP_DIR}.zip"
    if os.path.exists(ZIP_DIR):
        rmtree(ZIP_DIR)
    if os.path.exists(ZIP_FILENAME):
        os.unlink(ZIP_FILENAME)

    if os.path.exists(ZIP_DIR):
        rmtree(ZIP_DIR)
    copytree(DIST, ZIP_DIR)
    check_output(f"zip -9qmr {ZIP_FILENAME!r} {ZIP_DIR!r}")
    print()
    os.system(f"du -sm {ZIP_FILENAME!r}")
    print()


def create_installer(args) -> str:
    step("Creating the installer using InnoSetup")
    innosetup = find_command("innosetup", "INNOSETUP",
                             f"{PROGRAMFILES}\\Inno Setup 6\\ISCC.exe",
                             f"{PROGRAMFILES_X86}\\Inno Setup 6\\ISCC.exe",
                             )
    SETUP_EXE = "Xpra_Setup.exe"
    INSTALLER_FILENAME = f"Xpra${EXTRA_VERSION}${BUILD_ARCH_INFO}_Setup_{FULL_VERSION}.exe"
    XPRA_ISS = "xpra.iss"
    APPID = "Xpra_is1"
    INNOSETUP_LOG = "innosetup.log"
    for filename in (INNOSETUP_LOG, INSTALLER_FILENAME, SETUP_EXE):
        if os.path.exists(filename):
            os.unlink(filename)
    copyfile("packaging/MSWindows/xpra.iss", XPRA_ISS)
    with open(XPRA_ISS, "r") as f:
        contents = f.readlines()
    lines = []
    subs = {
        "AppId": APPID,
        "AppName": f"Xpra {VERSION}",
        "UninstallDisplayName": f"Xpra {VERSION}",
        "AppVersion": FULL_VERSION,
    }
    for line in contents:
        if line.startswith("    PostInstall()") and not args.full:
            # don't run post-install openssl:
            line = "Log('skipped post-install');"
        elif line.find("Xpra Shadow Server") >= 0 and not args.full:
            # no shadow server in light builds
            continue
        elif line.find("Command Manual") >= 0 and not args.docs:
            # remove link to the manual:
            continue
        if line.find("=") > 0:
            parts = line.split("=", 1)
            if parts[0] in subs:
                line = parts[0] + "=" + subs[parts[0]]
        lines.append(line)
    with open(XPRA_ISS, "w") as f:
        f.writelines(lines)

    log_command([innosetup, XPRA_ISS], INNOSETUP_LOG)
    os.unlink(XPRA_ISS)

    os.rename(f"{DIST}/SETUP_EXE", f"{INSTALLER_FILENAME}")
    return INSTALLER_FILENAME


def sign_file(filename: str) -> None:
    log_command(f'signtool.exe sign //v //f {KEY_FILE} //t "{TIMESTAMP_SERVER}" "${filename}"', "signtool.log")


def sign_installer(installer: str) -> None:
    step("Signing EXE")
    sign_file(installer)
    print()
    os.system(f"du -sm ${installer!r}")
    print()


def run_installer(installer: str) -> None:
    step("Finished - running the new installer")
    # we need to escape slashes!
    # (this doesn't preserve spaces.. we should use shift instead)
    os.system(installer)


def create_msi() -> str:
    msiwrapper = find_command("msiwrapper", "MSIWRAPPER",
                              f"{PROGRAMFILES}\\MSI Wrapper\\MsiWrapper.exe")
    MSI_FILENAME = f"Xpra{EXTRA_VERSION}{BUILD_ARCH_INFO}_{FULL_VERSION}.msi"
    # we need to quadruple escape backslashes!
    # as they get interpreted by the shell and sed, multiple times:
    # CWD = os.getcwd()   #`pwd | sed 's+/\([a-zA-Z]\)/+\1:\\\\\\\\+g; s+/+\\\\\\\\+g'`
    # print(f"CWD={CWD}")
    # cat "packaging\\MSWindows\\msi.xml" | sed "s+\$CWD+${CWD}+g" | sed "s+\$INPUT+${INSTALLER_FILENAME}+g" | sed "s+\$OUTPUT+${MSI_FILENAME}+g" | sed "s+\$ZERO_PADDED_VERSION+${ZERO_PADDED_VERSION}+g" | sed "s+\$FULL_VERSION+${FULL_VERSION}+g" > msi.xml
    #"${MSIWRAPPER}"
    log_command(f"{msiwrapper} msi.xml", "msiwrapper.log")
    return MSI_FILENAME


def sign_msi(msi: str) -> None:
    step("Signing MSI")
    sign_file(msi)
    print()
    os.system(f"du -sm {msi}")
    print()


def build(args) -> None:
    set_version_info(args.full)

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
        install_exe()

    if args.fixups:
        fixups(args.full)
        bundle_numpy(args.numpy)
        fixup_gstreamer()
        fixup_dlls()
        trim_pillow()
        trim_python_libs()
        fixup_zeroconf()
        rm_empty_dirs()

    if args.zip_modules:
        zip_modules(args.full)

    setup_share(args.full)
    add_manifests()
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
    add_cuda(args.cuda)

    if args.verpatch:
        verpatch()
    show_diskusage()
    if args.zip:
        create_zip()
    if args.installer:
        installer = create_installer(args)
        if args.sign:
            sign_installer(installer)
        if args.run:
            run_installer(installer)
        if args.msi:
            msi = create_msi(installer)
            if args.sign:
                sign_msi(msi)


def main():
    args = parse_command_line()
    build(args)


if __name__ == "__main__":
    main()
