#!/usr/bin/env python3

# This file is part of Xpra.
# Copyright (C) 2010-2023 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

##############################################################################
# FIXME: Cython.Distutils.build_ext leaves crud in the source directory.

import re
import sys
import glob
import shlex
import shutil
import os.path
import subprocess
from time import sleep

try:
    from distutils.core import setup
    from distutils.command.build import build
    from distutils.command.install_data import install_data
except ImportError as e:
    print(f"no distutils: {e}, trying setuptools")
    from setuptools import setup
    from setuptools.command.build import build
    from setuptools.command.install import install as install_data

import xpra
from xpra.os_util import (
    get_status_output, load_binary_file, get_distribution_version_id,
    getuid,
    BITS, WIN32, OSX, LINUX, POSIX, NETBSD, FREEBSD, OPENBSD,
    is_Ubuntu, is_Debian, is_Fedora,
    is_CentOS, is_AlmaLinux, is_RockyLinux, is_RedHat, is_openSUSE, is_OracleLinux,
    )

if sys.version_info<(3, 6):
    raise RuntimeError("xpra no longer supports Python versions older than 3.6")
if BITS!=64:
    print(f"Warning: {BITS}-bit architecture, only 64-bits are officially supported")
    for _ in range(5):
        sleep(1)
        print(".")


#*******************************************************************************
print(" ".join(sys.argv))

#*******************************************************************************
# build options, these may get modified further down..
#
data_files = []
modules = []
packages = []       #used by py2app
excludes = []       #only used by cx_freeze on win32
ext_modules = []
cmdclass = {}
scripts = []
description = "multi-platform screen and application forwarding system"
long_description = "Xpra is a multi platform persistent remote display server and client for " + \
            "forwarding applications and desktop screens. Also known as 'screen for X11'."
url = "https://xpra.org/"


XPRA_VERSION = xpra.__version__         #@UndefinedVariable
setup_options = {
    "name"              : "xpra",
    "version"           : XPRA_VERSION,
    "license"           : "GPLv2+",
    "author"            : "Antoine Martin",
    "author_email"      : "antoine@xpra.org",
    "url"               : url,
    "download_url"      : "https://xpra.org/src/",
    "description"       : description,
    "long_description"  : long_description,
    "data_files"        : data_files,
    "py_modules"        : modules,
    "project_urls"      : {
        "Documentation" : "https://github.com/Xpra-org/xpra/tree/master/docs",
        "Funding"       : "https://github.com/sponsors/totaam",
        "Source"        : "https://github.com/Xpra-org/xpra",
        },
    }


if "pkg-info" in sys.argv:
    def write_PKG_INFO():
        with open("PKG-INFO", "wb") as f:
            pkg_info_values = setup_options.copy()
            pkg_info_values.update({
                                    "metadata_version"  : "1.1",
                                    "summary"           :  description,
                                    "home_page"         : url,
                                    })
            for k in ("Metadata-Version", "Name", "Version", "Summary", "Home-page",
                      "Author", "Author-email", "License", "Download-URL", "Description"):
                v = pkg_info_values[k.lower().replace("-", "_")]
                f.write(("%s: %s\n" % (k, v)).encode())
    write_PKG_INFO()
    sys.exit(0)


print("Xpra version %s" % XPRA_VERSION)
#*******************************************************************************
# Most of the options below can be modified on the command line
# using --with-OPTION or --without-OPTION
# only the default values are specified here:
#*******************************************************************************

try:
    import cython
    print(f"found Cython version {cython.__version__}")
    cython_version = int(cython.__version__.split('.')[0])
except (ValueError, ImportError):
    print("WARNING: unable to detect Cython version")
    cython_version = 0


PKG_CONFIG = os.environ.get("PKG_CONFIG", "pkg-config")
def check_pkgconfig():
    v = get_status_output([PKG_CONFIG, "--version"])
    has_pkg_config = v[0]==0 and v[1]
    if has_pkg_config:
        print("found pkg-config version: %s" % v[1].strip("\n\r"))
    else:
        print("WARNING: pkg-config not found!")
check_pkgconfig()

for arg in list(sys.argv):
    if arg.startswith("--pkg-config-path="):
        pcp = arg[len("--pkg-config-path="):]
        pcps = [pcp] + os.environ.get("PKG_CONFIG_PATH", "").split(os.path.pathsep)
        os.environ["PKG_CONFIG_PATH"] = os.path.pathsep.join([x for x in pcps if x])
        print("using PKG_CONFIG_PATH="+os.environ["PKG_CONFIG_PATH"])
        sys.argv.remove(arg)

def no_pkgconfig(*_pkgs_options, **_ekw):
    return {}

def pkg_config_ok(*args):
    return get_status_output([PKG_CONFIG] + [str(x) for x in args])[0]==0

def pkg_config_version(req_version, pkgname):
    r, out, _ = get_status_output([PKG_CONFIG, "--modversion", pkgname])
    if r!=0 or not out:
        return False
    out = out.rstrip("\n\r").split(" ")[0]  #ie: "0.155.2917 0a84d98" -> "0.155.2917"
    #workaround for libx264 invalid version numbers:
    #ie: "0.163.x" or "0.164.3094M"
    while out[-1].isalpha() or out[-1]==".":
        out = out[:-1]
    # pylint: disable=import-outside-toplevel
    try:
        from packaging.version import parse
        return parse(out)>=parse(req_version)
    except ImportError:
        from distutils.version import LooseVersion  # pylint: disable=deprecated-module
        return LooseVersion(out)>=LooseVersion(req_version)


DEFAULT = True
if "--minimal" in sys.argv:
    sys.argv.remove("--minimal")
    DEFAULT = False
skip_build = "--skip-build" in sys.argv
ARCH = get_status_output(["uname", "-m"])[1].strip("\n\r")
ARM = ARCH.startswith("arm") or ARCH.startswith("aarch")
RISCV = ARCH.startswith("riscv")
print(f"ARCH={ARCH}")

INCLUDE_DIRS = os.environ.get("INCLUDE_DIRS", os.path.join(sys.prefix, "include")).split(os.pathsep)
if os.environ.get("INCLUDE_DIRS", None) is None and not WIN32:
    # sys.prefix is where the Python interpreter is installed. This may be very different from where
    # the C/C++ headers are installed. So do some guessing here:

    ALWAYS_INCLUDE_DIRS = ["/usr/include", "/usr/local/include"]
    for d in ALWAYS_INCLUDE_DIRS:
        if os.path.isdir(d) and d not in INCLUDE_DIRS:
            INCLUDE_DIRS.append(d)

print("using INCLUDE_DIRS=%s" % (INCLUDE_DIRS, ))

CPP = os.environ.get("CPP", "cpp")
CC = os.environ.get("CC", "gcc")
print(f"CPP={CPP}")
print(f"CC={CPP}")

shadow_ENABLED = DEFAULT
server_ENABLED = DEFAULT
rfb_ENABLED = DEFAULT
quic_ENABLED = DEFAULT
ssh_ENABLED = DEFAULT
http_ENABLED = DEFAULT
service_ENABLED = LINUX and server_ENABLED
sd_listen_ENABLED = POSIX and pkg_config_ok("--exists", "libsystemd")
proxy_ENABLED  = DEFAULT
client_ENABLED = DEFAULT
scripts_ENABLED = not WIN32
cython_ENABLED = DEFAULT
cython_tracing_ENABLED = False
modules_ENABLED = DEFAULT
data_ENABLED = DEFAULT

def find_header_file(name, isdir=False):
    matches = [v for v in
               [d+name for d in INCLUDE_DIRS]
               if os.path.exists(v) and os.path.isdir(v)==isdir]
    if not matches:
        return None
    return matches[0]
def has_header_file(name, isdir=False):
    return bool(find_header_file(name, isdir))

x11_ENABLED = DEFAULT and not WIN32 and not OSX
xinput_ENABLED = x11_ENABLED
uinput_ENABLED = x11_ENABLED
dbus_ENABLED = DEFAULT and x11_ENABLED and not (OSX or WIN32)
gtk_x11_ENABLED = DEFAULT and not WIN32 and not OSX
gtk3_ENABLED = DEFAULT and client_ENABLED
opengl_ENABLED = DEFAULT and client_ENABLED
pam_ENABLED = DEFAULT and (server_ENABLED or proxy_ENABLED) and LINUX and (find_header_file("/security", isdir=True) or pkg_config_ok("--exists", "pam", "pam_misc"))

proc_use_procps         = LINUX and has_header_file("/proc/procps.h")
proc_use_libproc        = LINUX and has_header_file("/libproc2/pids.h")
proc_ENABLED            = LINUX and (proc_use_procps or proc_use_libproc)

xdg_open_ENABLED        = (LINUX or FREEBSD) and DEFAULT
netdev_ENABLED          = LINUX and DEFAULT
vsock_ENABLED           = LINUX and has_header_file("/linux/vm_sockets.h")
lz4_ENABLED             = DEFAULT
bencode_ENABLED         = DEFAULT
cython_bencode_ENABLED  = DEFAULT
rencodeplus_ENABLED     = DEFAULT
brotli_ENABLED          = DEFAULT and has_header_file("/brotli/decode.h") and has_header_file("/brotli/encode.h")
qrencode_ENABLED        = DEFAULT and has_header_file("/qrencode.h")
clipboard_ENABLED       = DEFAULT
Xdummy_ENABLED          = None if POSIX else False  #None means auto-detect
Xdummy_wrapper_ENABLED  = None if POSIX else False  #None means auto-detect
audio_ENABLED           = DEFAULT
printing_ENABLED        = DEFAULT
crypto_ENABLED          = DEFAULT
mdns_ENABLED            = DEFAULT
websockets_ENABLED      = DEFAULT

codecs_ENABLED          = DEFAULT
enc_proxy_ENABLED       = DEFAULT
enc_x264_ENABLED        = DEFAULT and pkg_config_version("0.155", "x264")
openh264_ENABLED        = DEFAULT and pkg_config_version("2.0", "openh264")
openh264_decoder_ENABLED = openh264_ENABLED
openh264_encoder_ENABLED = openh264_ENABLED
#crashes on 32-bit windows:
pillow_ENABLED          = DEFAULT
argb_ENABLED            = DEFAULT
spng_decoder_ENABLED    = DEFAULT and pkg_config_version("0.6", "spng")
spng_encoder_ENABLED    = DEFAULT and pkg_config_version("0.7", "spng")
webp_ENABLED            = DEFAULT and pkg_config_version("0.5", "libwebp")
jpeg_encoder_ENABLED    = DEFAULT and pkg_config_version("1.2", "libturbojpeg")
jpeg_decoder_ENABLED    = DEFAULT and pkg_config_version("1.4", "libturbojpeg")
avif_ENABLED            = DEFAULT and pkg_config_version("0.9", "libavif") and not OSX
vpx_ENABLED             = DEFAULT and pkg_config_version("1.7", "vpx") and BITS==64
ffmpeg_ENABLED          = DEFAULT and BITS==64
enc_ffmpeg_ENABLED      = ffmpeg_ENABLED and pkg_config_version("58.18", "libavcodec")
#opencv currently broken on 32-bit windows (crashes on load):
webcam_ENABLED          = DEFAULT and not OSX and not WIN32
notifications_ENABLED   = DEFAULT
keyboard_ENABLED        = DEFAULT
v4l2_ENABLED            = DEFAULT and (not WIN32 and not OSX and not FREEBSD and not OPENBSD)
evdi_ENABLED            = DEFAULT and LINUX and pkg_config_version("1.9", "evdi")
drm_ENABLED             = DEFAULT and (LINUX or FREEBSD) and pkg_config_version("2.4", "libdrm")
#ffmpeg 3.1 or later is required
dec_avcodec2_ENABLED    = ffmpeg_ENABLED and pkg_config_version("57", "libavcodec")
csc_swscale_ENABLED     = ffmpeg_ENABLED and pkg_config_ok("--exists", "libswscale")
csc_cython_ENABLED      = DEFAULT
nvidia_ENABLED          = DEFAULT and not OSX and BITS==64
nvjpeg_encoder_ENABLED  = nvidia_ENABLED and pkg_config_ok("--exists", "nvjpeg")
nvjpeg_decoder_ENABLED  = nvidia_ENABLED and pkg_config_ok("--exists", "nvjpeg")
nvenc_ENABLED           = nvidia_ENABLED and pkg_config_version("10", "nvenc")
nvdec_ENABLED           = False
nvfbc_ENABLED           = nvidia_ENABLED and not ARM and pkg_config_ok("--exists", "nvfbc")
cuda_kernels_ENABLED    = nvidia_ENABLED and (nvenc_ENABLED or nvjpeg_encoder_ENABLED)
cuda_rebuild_ENABLED    = cuda_kernels_ENABLED and not WIN32
csc_libyuv_ENABLED      = DEFAULT and pkg_config_ok("--exists", "libyuv")
gstreamer_ENABLED       = DEFAULT
example_ENABLED         = DEFAULT

#Cython / gcc / packaging build options:
docs_ENABLED            = DEFAULT
pandoc_lua_ENABLED      = DEFAULT
annotate_ENABLED        = DEFAULT
warn_ENABLED            = True
strict_ENABLED          = False
PIC_ENABLED             = not WIN32     #ming32 moans that it is always enabled already
debug_ENABLED           = False
verbose_ENABLED         = False
bundle_tests_ENABLED    = False
tests_ENABLED           = False
rebuild_ENABLED         = not skip_build


#allow some of these flags to be modified on the command line:
CODEC_SWITCHES = [
    "enc_x264",
    "enc_proxy",
    "cuda_kernels", "cuda_rebuild",
    "openh264", "openh264_decoder", "openh264_encoder",
    "nvidia", "nvenc", "nvdec", "nvfbc", "nvjpeg_encoder", "nvjpeg_decoder",
    "vpx", "webp", "pillow",
    "spng_decoder", "spng_encoder",
    "jpeg_encoder", "jpeg_decoder",
    "avif", "argb",
    "v4l2", "evdi", "drm",
    "ffmpeg", "dec_avcodec2", "csc_swscale", "enc_ffmpeg",
    "csc_cython", "csc_libyuv", "gstreamer",
    ]
SWITCHES = [
    "cython", "cython_tracing",
    "modules", "data",
    "codecs",
    ] + CODEC_SWITCHES + [
    "bencode", "cython_bencode", "rencodeplus", "brotli", "qrencode",
    "vsock", "netdev", "proc", "mdns", "lz4",
    "clipboard",
    "scripts",
    "server", "client", "dbus", "x11", "xinput", "uinput", "sd_listen",
    "gtk_x11", "service",
    "gtk3", "example",
    "pam", "xdg_open",
    "audio", "opengl", "printing", "webcam", "notifications", "keyboard",
    "rebuild",
    "docs", "pandoc_lua",
    "annotate", "warn", "strict",
    "shadow", "proxy", "rfb", "quic", "http", "ssh",
    "debug", "PIC",
    "Xdummy", "Xdummy_wrapper", "verbose", "tests", "bundle_tests",
    ]
#some switches can control multiple switches:
SWITCH_ALIAS = {
    "codecs"    : ["codecs"] + CODEC_SWITCHES,
    "openh264"  : ("openh264", "openh264_decoder", "openh264_encoder"),
    "nvidia"    : ("nvidia", "nvenc", "nvdec", "nvfbc", "nvjpeg_encoder", "nvjpeg_decoder", "cuda_kernels", "cuda_rebuild"),
    "ffmpeg"    : ("ffmpeg", "dec_avcodec2", "csc_swscale", "enc_ffmpeg"),
    "cython"    : ("cython", "codecs",
                   "server", "client", "shadow",
                   "cython_bencode", "rencodeplus", "brotli", "qrencode", "websockets", "netdev", "vsock",
                   "lz4",
                   "gtk3", "x11", "gtk_x11",
                   "pam", "sd_listen", "proc",
                   ),
    }

def show_help():
    setup()
    print("Xpra specific build and install switches:")
    for x in sorted(SWITCHES):
        d = globals()[f"{x}_ENABLED"]
        with_str = f"  --with-{x}"
        without_str = f"  --without-{x}"
        if d is True or d is False:
            default_str = str(d)
        else:
            default_str = "auto-detect"
        print("%s or %s (default: %s)" % (with_str.ljust(25), without_str.ljust(30), default_str))
    print("  --pkg-config-path=PATH")
    print("  --rpath=PATH")
HELP = "-h" in sys.argv or "--help" in sys.argv
if HELP:
    show_help()
    sys.exit(0)

install = None
rpath = None
ssl_cert = None
ssl_key = None
minifier = None
share_xpra = None
dummy_driver_version = None
filtered_args = []
def filter_argv():
    for arg in sys.argv:
        matched = False
        for x in ("rpath", "ssl-cert", "ssl-key", "install", "share-xpra", "dummy-driver-version"):
            varg = f"--{x}="
            if arg.startswith(varg):
                value = arg[len(varg):]
                globals()[x.replace("-", "_")] = value
                #remove these arguments from sys.argv,
                #except for --install=PATH
                matched = x!="install"
                break
        if matched:
            continue
        for x in SWITCHES:
            with_str = f"--with-{x}"
            without_str = f"--without-{x}"
            var_names = list(SWITCH_ALIAS.get(x, [x]))
            #recurse once, so an alias can container aliases:
            for v in tuple(var_names):
                var_names += list(SWITCH_ALIAS.get(v, []))
            if arg.startswith(with_str+"="):
                for var in var_names:
                    globals()[f"{var}_ENABLED"] = arg[len(with_str)+1:]
                matched = True
                break
            if arg==with_str:
                for var in var_names:
                    globals()[f"{var}_ENABLED"] = True
                matched = True
                break
            if arg==without_str:
                for var in var_names:
                    globals()[f"{var}_ENABLED"] = False
                matched = True
                break
        if not matched:
            filtered_args.append(arg)
filter_argv()
#enable any codec groups with at least one codec enabled:
#ie: enable "nvidia" if "nvenc" is enabled
for group, items in SWITCH_ALIAS.items():
    if globals()[f"{group}_ENABLED"]:
        #already enabled
        continue
    for item in items:
        if globals()[f"{item}_ENABLED"]:
            print(f"enabling {group!r} for {item!r}")
            globals()[f"{group}_ENABLED"] = True
            break
sys.argv = filtered_args
if "clean" not in sys.argv and "sdist" not in sys.argv:
    def show_switch_info():
        switches_info = {}
        for x in SWITCHES:
            switches_info[x] = globals()[f"{x}_ENABLED"]
        print("build switches:")
        for k in sorted(SWITCHES):
            v = switches_info[k]
            print("* %s : %s" % (str(k).ljust(20), {None : "Auto", True : "Y", False : "N"}.get(v, v)))
    show_switch_info()

    #sanity check the flags:
    if clipboard_ENABLED and not server_ENABLED and not gtk3_ENABLED:
        print("Warning: clipboard can only be used with the server or one of the gtk clients!")
        clipboard_ENABLED = False
    if x11_ENABLED and WIN32:
        print("Warning: enabling x11 on MS Windows is unlikely to work!")
    if gtk_x11_ENABLED and not x11_ENABLED:
        print("Error: you must enable x11 to support gtk_x11!")
        sys.exit(1)
    if client_ENABLED and not gtk3_ENABLED:
        print("Warning: client is enabled but none of the client toolkits are!?")
    if DEFAULT and (not client_ENABLED and not server_ENABLED):
        print("Warning: you probably want to build at least the client or server!")
    if DEFAULT and not pillow_ENABLED:
        print("Warning: including Python Pillow is VERY STRONGLY recommended")
    if DEFAULT and (not enc_x264_ENABLED and not vpx_ENABLED):
        print("Warning: no x264 and no vpx support!")
        print(" you should enable at least one of these two video encodings")

if install is None and WIN32:
    install = os.environ.get("MINGW_PREFIX", sys.prefix or "dist")
if share_xpra is None:
    share_xpra = os.path.join("share", "xpra")


def should_rebuild(src_file, bin_file):
    if not os.path.exists(bin_file):
        return "no file"
    if rebuild_ENABLED:
        if os.path.getctime(bin_file)<os.path.getctime(src_file):
            return "binary file out of date"
        if os.path.getctime(bin_file)<os.path.getctime(__file__):
            return "newer build file"
    return None


def convert_doc(fsrc, fdst, fmt="html", force=False):
    bsrc = os.path.basename(fsrc)
    bdst = os.path.basename(fdst)
    if not force and not should_rebuild(fsrc, fdst):
        return
    print("  %-20s -> %s" % (bsrc, bdst))
    pandoc = os.environ.get("PANDOC", "pandoc")
    cmd = [pandoc, "--from", "commonmark", "--to", fmt, "-o", fdst, fsrc]
    if fmt=="html" and pandoc_lua_ENABLED:
        if is_Ubuntu() and get_distribution_version_id()<="18.04":
            print("pandoc is missing the lua-filter option")
            print(" cannot preserve HTML links in documentation")
        else:
            cmd += ["--lua-filter", "./fs/bin/links-to-html.lua"]
    r = subprocess.Popen(cmd).wait(30)
    assert r==0, "'%s' returned %s" % (" ".join(cmd), r)

def convert_doc_dir(src, dst, fmt="html", force=False):
    print("%-20s -> %s" % (src, dst))
    if not os.path.exists(dst):
        os.makedirs(dst, mode=0o755)
    for x in os.listdir(src):
        fsrc = os.path.join(src, x)
        if os.path.isdir(fsrc):
            fdst = os.path.join(dst, x)
            convert_doc_dir(fsrc, fdst, fmt, force)
        elif fsrc.endswith(".md"):
            fdst = os.path.join(dst, x.replace("README", "index")[:-3]+"."+fmt)
            convert_doc(fsrc, fdst, fmt, force)
        elif fsrc.endswith(".png"):
            fdst = os.path.join(dst, x)
            print(f"copying {fsrc} -> {fdst} (%s)" % oct(0o644))
            os.makedirs(name=dst, mode=0o755, exist_ok=True)
            data = load_binary_file(fsrc)
            with open(fdst, "wb") as f:
                f.write(data)
                os.chmod(fdst, 0o644)
        else:
            print(f"ignoring {fsrc!r}")

def convert_docs(fmt="html"):
    paths = [x for x in sys.argv[2:] if not x.startswith("--")]
    if len(paths)==1 and os.path.isdir(paths[0]):
        convert_doc_dir("docs", paths[0])
    elif paths:
        for x in paths:
            convert_doc(x, f"build/{x}", fmt=fmt)
    else:
        convert_doc_dir("docs", "build/docs", fmt=fmt)


if "doc" in sys.argv:
    convert_docs("html")
    sys.exit(0)

if "pdf-doc" in sys.argv:
    convert_docs("pdf")
    sys.exit(0)

if len(sys.argv)<2:
    print(f"{sys.argv[0]} arguments are missing!")
    sys.exit(1)

if sys.argv[1]=="unittests":
    os.execv("./tests/unittests/run", ["run"] + sys.argv[2:])
assert "unittests" not in sys.argv, sys.argv


#*******************************************************************************
# default sets:
external_includes = ["hashlib", "ctypes", "platform"]
if gtk3_ENABLED or audio_ENABLED:
    external_includes += ["gi"]

external_excludes = [
                    #Tcl/Tk
                    "Tkconstants", "tkinter", "tcl",
                    #PIL bits that import TK:
                    "PIL._tkinter_finder", "_imagingtk", "PIL._imagingtk", "ImageTk", "PIL.ImageTk", "FixTk",
                    #formats we don't use:
                    "GimpGradientFile", "GimpPaletteFile", "BmpImagePlugin", "TiffImagePlugin",
                    #not used:
                    "curses", "pdb",
                    "tty",
                    "setuptools", "doctest",
                    "nose", "pytest", "_pytest", "pluggy", "more_itertools", "apipkg", "py", "funcsigs",
                    "Cython", "cython", "pyximport",
                    "pydoc_data",
                    ]
if not crypto_ENABLED:
    external_excludes += ["ssl", "_ssl", "uvloop"]
if not client_ENABLED:
    external_excludes += ["mimetools"]

if not client_ENABLED and not server_ENABLED:
    excludes += ["PIL"]
if not dbus_ENABLED:
    excludes += ["dbus"]


#because of differences in how we specify packages and modules
#for distutils / py2app and cx_freeze
#use the following functions, which should get the right
#data in the global variables "packages", "modules" and "excludes"

def remove_packages(*mods):
    """ ensures that the given packages are not included:
        removes them from the "modules" and "packages" list and adds them to "excludes" list
    """
    for m in list(modules):
        for x in mods:
            if m.startswith(x):
                modules.remove(m)
                break
    for x in mods:
        if x in packages:
            packages.remove(x)
        if x not in excludes:
            excludes.append(x)

def add_packages(*pkgs):
    """ adds the given packages to the packages list,
        and adds all the modules found in this package (including the package itself)
    """
    for x in pkgs:
        if x not in packages:
            packages.append(x)
    add_modules(*pkgs)

def add_modules(*mods):
    def add(v):
        if v not in modules:
            modules.append(v)
    do_add_modules(add, *mods)

def do_add_modules(op, *mods):
    """ adds the packages and any .py module found in the packages to the "modules" list
    """
    for x in mods:
        #ugly path stripping:
        if x.startswith("./"):
            x = x[2:]
        if x.endswith(".py"):
            x = x[:-3]
            x = x.replace("/", ".") #.replace("\\", ".")
        pathname = os.path.sep.join(x.split("."))
        #is this a file module?
        f = f"{pathname}.py"
        if os.path.exists(f) and os.path.isfile(f):
            op(x)
        if os.path.exists(pathname) and os.path.isdir(pathname):
            #add all file modules found in this directory
            for f in os.listdir(pathname):
                #make sure we only include python files,
                #and ignore eclipse copies
                if f.endswith(".py") and not f.startswith("Copy "):
                    fname = os.path.join(pathname, f)
                    if os.path.isfile(fname):
                        modname = f"{x}."+f.replace(".py", "")
                        op(modname)

def toggle_packages(enabled, *module_names):
    if enabled:
        add_packages(*module_names)
    else:
        remove_packages(*module_names)

def toggle_modules(enabled, *module_names):
    if enabled:
        def op(v):
            if v not in modules:
                modules.append(v)
        do_add_modules(op, *module_names)
    else:
        remove_packages(*module_names)


#always included:
if modules_ENABLED:
    add_modules("xpra", "xpra.platform", "xpra.net", "xpra.scripts.main")


#*******************************************************************************
# Utility methods for building with Cython

def add_cython_ext(*args, **kwargs):
    if "--no-compile" in sys.argv and not ("build" in sys.argv and "install" in sys.argv):
        return
    if not cython_ENABLED:
        raise ValueError(f"cannot build {args}: cython compilation is disabled")
    if cython_tracing_ENABLED:
        kwargs["define_macros"] = [
            ('CYTHON_TRACE', 1),
            ('CYTHON_TRACE_NOGIL', 1),
            ]
        kwargs.setdefault("extra_compile_args", []).append("-Wno-error")
    # pylint: disable=import-outside-toplevel
    from Cython.Distutils import build_ext, Extension
    ext_modules.append(Extension(*args, **kwargs))
    cmdclass['build_ext'] = build_ext

def ace(modnames="xpra.x11.bindings.xxx", pkgconfig_names="", optimize=None, **kwargs):
    src = modnames.split(",")
    modname = src[0]
    if not src[0].endswith(".pyx"):
        src[0] = src[0].replace(".", "/")+".pyx"
    if isinstance(pkgconfig_names, str):
        pkgconfig_names = [x for x in pkgconfig_names.split(",") if x]
    pkgc = pkgconfig(*pkgconfig_names, optimize=optimize)
    for addto in ("extra_link_args", "extra_compile_args"):
        value = kwargs.pop(addto, None)
        if value:
            if isinstance(value, str):
                value = (value, )
            add_to_keywords(pkgc, addto, *value)
            for v in value:
                if v.startswith("-Wno-error="):
                    #make sure to remove the corresponding switch that may enable it:
                    warning = v.split("-Wno-error=", 1)[1]
                    if remove_from_keywords(pkgc, addto, f"-W{warning}"):
                        print(f"removed -W{warning} for {modname}")
    pkgc.update(kwargs)
    CPP = kwargs.get("language", "")=="c++"
    if CPP:
        #default to "-std=c++11" for c++
        if not any(v.startswith("-std=") for v in pkgc.get("extra_compile_args", ())):
            add_to_keywords(pkgc, "extra_compile_args", "-std=c++11")
        #all C++ modules trigger an address warning in the module initialization code:
        if WIN32:
            add_to_keywords(pkgc, "extra_compile_args", "-Wno-error=address")
    if get_clang_version()>=(14, ):
        add_to_keywords(pkgc, "extra_compile_args", "-Wno-error=unreachable-code-fallthrough")
    add_cython_ext(modname, src, **pkgc)

def tace(toggle, *args, **kwargs):
    if toggle:
        ace(*args, **kwargs)


def insert_into_keywords(kw, key, *args):
    values = kw.setdefault(key, [])
    for arg in args:
        values.insert(0, arg)

def add_to_keywords(kw, key, *args):
    values = kw.setdefault(key, [])
    for arg in args:
        values.append(arg)
def remove_from_keywords(kw, key, value):
    values = kw.get(key)
    i = 0
    while values and value in values:
        values.remove(value)
        i += 1
    return i


def checkdirs(*dirs):
    for d in dirs:
        if not os.path.exists(d) or not os.path.isdir(d):
            raise RuntimeError(f"cannot find a directory which is required for building: {d!r}")

def CC_is_clang():
    if CC.find("clang")>=0:
        return True
    return get_clang_version()>(0, )

clang_version = None
def get_clang_version():
    global clang_version
    if clang_version is not None:
        return clang_version
    r, _, err = get_status_output([CC, "-v"])
    clang_version = (0, )
    if r!=0:
        #not sure!
        return clang_version
    for line in err.splitlines():
        for v_line in ("Apple clang version", "clang version"):
            if line.startswith(v_line):
                v_str = line[len(v_line):].strip().split(" ")[0]
                tmp_version = []
                for p in v_str.split("."):
                    try:
                        tmp_version.append(int(p))
                    except ValueError:
                        break
                print(f"found {v_line}: %s" % ".".join(str(x) for x in tmp_version))
                clang_version = tuple(tmp_version)
                return clang_version
    #not found!
    return clang_version

_gcc_version = None
def get_gcc_version():
    global _gcc_version
    if _gcc_version is not None:
        return _gcc_version
    _gcc_version = (0, )
    if CC_is_clang():
        return _gcc_version
    r, _, err = get_status_output([CC, "-v"])
    if r==0:
        V_LINE = "gcc version "
        tmp_version = []
        for line in err.splitlines():
            if not line.startswith(V_LINE):
                continue
            v_str = line[len(V_LINE):].strip().split(" ")[0]
            for p in v_str.split("."):
                try:
                    tmp_version.append(int(p))
                except ValueError:
                    break
            print("found gcc version: %s" % ".".join(str(x) for x in tmp_version))
            break
        _gcc_version = tuple(tmp_version)
    return _gcc_version


def vernum(s):
    return tuple(int(v) for v in s.split("-", 1)[0].split("."))

def get_dummy_driver_version():
    #try various rpm names:
    for rpm_name in ("xorg-x11-drv-dummy", "xf86-video-dummy"):
        r, out, err = get_status_output(["rpm", "-q", "--queryformat", "%{VERSION}", rpm_name])
        if r==0:
            print(f"rpm query found dummy driver version {out}")
            return out
        print(f"rpm query: out={out}, err={err}")
    r, out, _ = get_status_output(["dpkg-query", "--showformat=${Version}", "--show", "xserver-xorg-video-dummy"])
    if r==0:
        if out.find(":")>=0:
            #ie: "1:0.3.8-2" -> "0.3.8"
            out = out.split(":", 1)[1]
        print(f"dpkg-query found dummy driver version {out}")
        return out
    return "0.4.0"

# Tweaked from http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/502261
def exec_pkgconfig(*pkgs_options, **ekw):
    kw = dict(ekw)
    if "INCLUDE_DIRS" in os.environ:
        for d in INCLUDE_DIRS:
            add_to_keywords(kw, 'extra_compile_args', "-I", d)
    optimize = kw.pop("optimize", None)
    if optimize and not debug_ENABLED and not cython_tracing_ENABLED:
        if isinstance(optimize, bool):
            optimize = int(optimize)*3
        add_to_keywords(kw, 'extra_compile_args', "-O%i" % optimize)
    ignored_flags = kw.pop("ignored_flags", [])
    ignored_tokens = kw.pop("ignored_tokens", [])

    #for distros that don't patch distutils,
    #we have to add the python cflags:
    if not (is_Fedora() or is_Debian() or is_CentOS() or is_RedHat() or is_AlmaLinux() or is_RockyLinux() or is_OracleLinux() or is_openSUSE()):
        # pylint: disable=import-outside-toplevel
        import sysconfig
        for cflag in shlex.split(sysconfig.get_config_var('CFLAGS') or ''):
            add_to_keywords(kw, 'extra_compile_args', cflag)

    def add_tokens(s, add_to="extra_link_args"):
        if not s:
            return
        flag_map = {
            '-I': 'include_dirs',
            '-L': 'library_dirs',
            '-l': 'libraries',
            }
        for token in shlex.split(s):
            if token in ignored_tokens:
                continue
            if token[:2] in ignored_flags:
                continue
            if token[:2] in flag_map:
                #this overrules 'add_to' - is this still needed?
                if len(token)>2:
                    add_to_keywords(kw, flag_map[token[:2]], token[2:])
                else:
                    print(f"Warning: invalid token {token!r}")
            else:
                add_to_keywords(kw, add_to, token)

    def hascflag(s):
        return s in kw.get("extra_compile_args", [])
    def addcflags(*s):
        add_to_keywords(kw, "extra_compile_args", *s)
    def addldflags(*s):
        add_to_keywords(kw, "extra_link_args", *s)

    if pkgs_options:
        for pc_arg, add_to in {
            "--libs" : "extra_link_args",
            "--cflags" : "extra_compile_args",
            }.items():
            pkg_config_cmd = ["pkg-config", pc_arg] + list(pkgs_options)
            if verbose_ENABLED:
                print(f"pkg_config_cmd={pkg_config_cmd}")
            r, pkg_config_out, err = get_status_output(pkg_config_cmd)
            if r!=0:
                sys.exit("ERROR: call to '%s' failed (err=%s)" % (" ".join(pkg_config_cmd), err))
            if verbose_ENABLED:
                print(f"pkg-config output: {pkg_config_out}")
            add_tokens(pkg_config_out, add_to)
            if verbose_ENABLED:
                print(f"pkg-config kw={kw}")
    if warn_ENABLED:
        addcflags("-Wall")
        addldflags("-Wall")
    if strict_ENABLED:
        if CC.find("clang")>=0:
            #clang emits too many warnings with cython code,
            #so we can't enable Werror without turning off some warnings:
            #this list of flags should allow clang to build the whole source tree,
            #as of Cython 0.26 + clang 4.0. Other version combinations may require
            #(un)commenting other switches.
            if not hascflag("-Wno-error"):
                addcflags("-Werror")
            addcflags(
                "-Wno-deprecated-register",
                "-Wno-unused-command-line-argument",
                #"-Wno-unneeded-internal-declaration",
                #"-Wno-unknown-attributes",
                #"-Wno-unused-function",
                #"-Wno-self-assign",
                #"-Wno-sometimes-uninitialized",
                #cython adds rpath to the compilation command??
                #and the "-specs=/usr/lib/rpm/redhat/redhat-hardened-cc1" is also ignored by clang:
                )
        else:
            if not hascflag("-Wno-error"):
                addcflags("-Werror")
            if NETBSD:
                #see: http://trac.cython.org/ticket/395
                addcflags("-fno-strict-aliasing")
            elif FREEBSD:
                addcflags("-Wno-error=unused-function")
        remove_from_keywords(kw, 'extra_compile_args', "-fpermissive")
    if PIC_ENABLED:
        addcflags("-fPIC")
    if debug_ENABLED:
        addcflags("-g", "-ggdb")
        if not WIN32:
            addcflags("-fsanitize=address")
            addldflags("-fsanitize=address")
    if rpath and kw.get("libraries"):
        insert_into_keywords(kw, "library_dirs", rpath)
        insert_into_keywords(kw, "extra_link_args", f"-Wl,-rpath={rpath}")
    CFLAGS = os.environ.get("CFLAGS")
    LDFLAGS = os.environ.get("LDFLAGS")
    #win32 remove double "-march=x86-64 -mtune=generic -O2 -pipe -O3"?
    if verbose_ENABLED:
        print(f"adding CFLAGS={CFLAGS}")
        print(f"adding LDFLAGS={LDFLAGS}")
    add_tokens(CFLAGS, "extra_compile_args")
    add_tokens(LDFLAGS, "extra_link_args")
    #add_to_keywords(kw, 'include_dirs', '.')
    if debug_ENABLED and WIN32 and MINGW_PREFIX:
        extra_compile_args.append("-DDEBUG")
    if verbose_ENABLED:
        print(f"exec_pkgconfig({pkgs_options}, {ekw})={kw}")
    return kw
pkgconfig = exec_pkgconfig


#*******************************************************************************


def get_base_conf_dir(install_dir, stripbuildroot=True):
    #in some cases we want to strip the buildroot (to generate paths in the config file)
    #but in other cases we want the buildroot path (when writing out the config files)
    #and in some cases, we don't have the install_dir specified (called from detect_xorg_setup, and that's fine too)
    #this is a bit hackish, but I can't think of a better way of detecting it
    #(ie: "$HOME/rpmbuild/BUILDROOT/xpra-0.15.0-0.fc21.x86_64/usr")
    dirs = (install_dir or sys.prefix).split(os.path.sep)
    if install_dir and stripbuildroot:
        pkgdir = os.environ.get("pkgdir")
        if "debian" in dirs and "tmp" in dirs:
            #ugly fix for stripping the debian tmp dir:
            #ie: "???/tmp/???/tags/v0.15.x/src/debian/tmp/" -> ""
            while "tmp" in dirs:
                dirs = dirs[dirs.index("tmp")+1:]
        elif "debian" in dirs:
            #same for recent debian versions:
            #ie: "xpra-2.0.2/debian/xpra/usr" -> "usr"
            i = dirs.index("debian")
            while i>=0 and len(dirs)>i+1:
                if dirs[i+1] == "xpra":
                    dirs = dirs[i+2:]
                i = dirs.index("debian")
        elif "BUILDROOT" in dirs:
            #strip rpm style build root:
            #[$HOME, "rpmbuild", "BUILDROOT", "xpra-$VERSION"] -> []
            dirs = dirs[dirs.index("BUILDROOT")+2:]
        elif "pkg" in dirs:
            #archlinux
            #ie: "/build/xpra/pkg/xpra/etc" -> "etc"
            #find the last 'pkg' from the list of directories:
            i = max(loc for loc, val in enumerate(dirs) if val == "pkg")
            if len(dirs)>i+1 and dirs[i+1] in ("xpra", "xpra-git"):
                dirs = dirs[i+2:]
        elif pkgdir and install_dir.startswith(pkgdir):
            #arch build dir:
            dirs = install_dir.lstrip(pkgdir).split(os.path.sep)
        elif "usr" in dirs:
            #ie: ["some", "path", "to", "usr"] -> ["usr"]
            #assume "/usr" or "/usr/local" is the build root
            while "usr" in dirs[1:]:
                dirs = dirs[dirs[1:].index("usr")+1:]
        elif "image" in dirs:
            # Gentoo's "${PORTAGE_TMPDIR}/portage/${CATEGORY}/${PF}/image/_python2.7" -> ""
            while "image" in dirs:
                dirs = dirs[dirs.index("image")+2:]
    #now deal with the fact that "/etc" is used for the "/usr" prefix
    #but "/usr/local/etc" is used for the "/usr/local" prefix..
    if dirs and dirs[-1]=="usr":
        dirs = dirs[:-1]
    #is this an absolute path?
    if not dirs or dirs[0]=="usr" or (install_dir or sys.prefix).startswith(os.path.sep):
        #ie: ["/", "usr"] or ["/", "usr", "local"]
        dirs.insert(0, os.path.sep)
    return dirs

def get_conf_dir(install_dir, stripbuildroot=True):
    dirs = get_base_conf_dir(install_dir, stripbuildroot)
    if "etc" not in dirs:
        dirs.append("etc")
    dirs.append("xpra")
    return os.path.join(*dirs)

def detect_xorg_setup(install_dir=None):
    # pylint: disable=import-outside-toplevel
    from xpra.scripts import config
    config.debug = config.warn
    conf_dir = get_conf_dir(install_dir)
    dummy = Xdummy_ENABLED
    if bool(dummy_driver_version):
        dummy = True
    return config.detect_xvfb_command(conf_dir, None, dummy, Xdummy_wrapper_ENABLED)

def detect_xdummy_setup(install_dir=None):
    # pylint: disable=import-outside-toplevel
    from xpra.scripts import config
    config.debug = config.warn
    conf_dir = get_conf_dir(install_dir)
    return config.detect_xdummy_command(conf_dir, None, Xdummy_wrapper_ENABLED)


def build_xpra_conf(install_dir):
    # pylint: disable=import-outside-toplevel
    #generates an actual config file from the template
    xvfb_command = detect_xorg_setup(install_dir)
    xdummy_command = detect_xdummy_setup(install_dir)
    fake_xinerama = "no"
    if POSIX and not OSX and not (is_Debian() or is_Ubuntu()):
        from xpra.x11.fakeXinerama import find_libfakeXinerama
        fake_xinerama = find_libfakeXinerama() or "auto"
    from xpra.platform.features import DEFAULT_START_ENV, DEFAULT_ENV, SOURCE
    def bstr(b):
        if b is None:
            return "auto"
        return "yes" if int(b) else "no"
    default_start_env = "\n".join(f"start-env = {x}" for x in DEFAULT_START_ENV)
    default_env = "\n".join(f"env = {x}" for x in DEFAULT_ENV)
    source = "\n".join(f"source = {x}" for x in SOURCE)
    conf_dir = get_conf_dir(install_dir)
    print(f"get_conf_dir({install_dir})={conf_dir}")
    from xpra.platform.features import DEFAULT_PULSEAUDIO_CONFIGURE_COMMANDS
    from xpra.platform.paths import get_socket_dirs
    from xpra.scripts.config import (
        wrap_cmd_str, unexpand,
        get_default_key_shortcuts, get_default_systemd_run, get_default_pulseaudio_command,
        DEFAULT_POSTSCRIPT_PRINTER, DEFAULT_PULSEAUDIO,
        )
    #remove build paths and user specific paths with UID ("/run/user/UID/Xpra"):
    socket_dirs = [unexpand(x) for x in get_socket_dirs()]
    if POSIX and getuid()>0:
        #remove any paths containing the uid,
        #osx uses /var/tmp/$UID-Xpra,
        #but this should not be included in the default config for all users!
        #(the buildbot's uid!)
        socket_dirs = [x for x in socket_dirs if x.find(str(getuid()))<0]
    #FIXME: we should probably get these values from the default config instead
    pdf, postscript = "", ""
    if POSIX and printing_ENABLED:
        try:
            if "/usr/sbin" not in sys.path:
                sys.path.append("/usr/sbin")
            from xpra.platform.pycups_printing import get_printer_definition
            print("probing cups printer definitions")
            pdf = get_printer_definition("pdf")
            postscript = get_printer_definition("postscript") or DEFAULT_POSTSCRIPT_PRINTER
            print(f"pdf={pdf}, postscript={postscript}")
        except Exception as e:
            print(f"could not probe for pdf/postscript printers: {e}")
    def pretty_cmd(cmd):
        return " ".join(cmd)
    #OSX doesn't have webcam support yet (no opencv builds on 10.5.x)
    webcam = webcam_ENABLED and not (OSX or WIN32)
    #no python-avahi on RH / CentOS, need dbus module on *nix:
    is_RH = is_RedHat() or is_CentOS() or is_OracleLinux() or is_AlmaLinux() or is_RockyLinux()
    mdns = mdns_ENABLED and (OSX or WIN32 or (not is_RH and dbus_ENABLED))
    SUBS = {
        'xvfb_command'          : wrap_cmd_str(xvfb_command),
        'xdummy_command'        : wrap_cmd_str(xdummy_command).replace("\n", "\n#"),
        'fake_xinerama'         : fake_xinerama,
        'ssh_command'           : "auto",
        'key_shortcuts'         : "".join(f"key-shortcut = {x}\n" for x in get_default_key_shortcuts()),
        'remote_logging'        : "both",
        'start_env'             : default_start_env,
        'env'                   : default_env,
        'pulseaudio'            : bstr(DEFAULT_PULSEAUDIO),
        'pulseaudio_command'    : pretty_cmd(get_default_pulseaudio_command()),
        'pulseaudio_configure_commands' : "\n".join(("pulseaudio-configure-commands = %s" % pretty_cmd(x)) for x in DEFAULT_PULSEAUDIO_CONFIGURE_COMMANDS),
        'conf_dir'              : conf_dir,
        'bind'                  : "auto",
        'ssl_cert'              : ssl_cert or "",
        'ssl_key'               : ssl_key or "",
        'systemd_run'           : get_default_systemd_run(),
        'socket_dirs'           : "".join(f"socket-dirs = {x}\n" for x in socket_dirs),
        'log_dir'               : "auto",
        "source"                : source,
        'mdns'                  : bstr(mdns),
        'notifications'         : bstr(OSX or WIN32 or dbus_ENABLED),
        'dbus_proxy'            : bstr(not OSX and not WIN32 and dbus_ENABLED),
        'pdf_printer'           : pdf,
        'postscript_printer'    : postscript,
        'webcam'                : ["no", "auto"][webcam],
        'mousewheel'            : "on",
        'printing'              : bstr(printing_ENABLED),
        'dbus_control'          : bstr(dbus_ENABLED),
        'mmap'                  : bstr(True),
        'opengl'                : "probe",
        'headerbar'             : ["auto", "no"][OSX or WIN32],
        }
    def convert_templates(subdirs):
        dirname = os.path.join(*(["fs", "etc", "xpra"] + subdirs))
        #get conf dir for install, without stripping the build root
        target_dir = os.path.join(get_conf_dir(install_dir, stripbuildroot=False), *subdirs)
        print(f"convert_templates({subdirs}) dirname={dirname}, target_dir={target_dir}")
        if not os.path.exists(target_dir):
            try:
                os.makedirs(target_dir)
            except Exception as e:
                print(f"cannot create target dir {target_dir!r}: {e}")
        for f in sorted(os.listdir(dirname)):
            if f.endswith("osx.conf.in") and not OSX:
                continue
            filename = os.path.join(dirname, f)
            if os.path.isdir(filename):
                convert_templates(subdirs+[f])
                continue
            if not f.endswith(".in"):
                continue
            with open(filename, "r", encoding="latin1") as f_in:
                template  = f_in.read()
            target_file = os.path.join(target_dir, f[:-len(".in")])
            print(f"generating {target_file} from {f}")
            with open(target_file, "w", encoding="latin1") as f_out:
                config_data = template % SUBS
                f_out.write(config_data)
    convert_templates([])


#*******************************************************************************
def clean():
    #clean and sdist don't actually use cython,
    #so skip this (and avoid errors)
    global pkgconfig
    pkgconfig = no_pkgconfig
    #always include everything in this case:
    add_packages("xpra")
    #ensure we remove the files we generate:
    CLEAN_FILES = [
                   "xpra/build_info.py",
                   "xpra/gtk_common/gtk3/gdk_atoms.c",
                   "xpra/gtk_common/gtk3/gdk_bindings.c",
                   "xpra/x11/gtk3/gdk_bindings.c",
                   "xpra/x11/gtk3/gdk_display_source.c",
                   "xpra/x11/bindings/xwait.c",
                   "xpra/x11/bindings/wait_for_x_server.c",
                   "xpra/x11/bindings/keyboard.c",
                   "xpra/x11/bindings/display_source.c",
                   "xpra/x11/bindings/events.c",
                   "xpra/x11/bindings/window.c",
                   "xpra/x11/bindings/randr.c",
                   "xpra/x11/bindings/res.c",
                   "xpra/x11/bindings/core.c",
                   "xpra/x11/bindings/posix_display_source.c",
                   "xpra/x11/bindings/xwayland.c",
                   "xpra/x11/bindings/ximage.c",
                   "xpra/x11/bindings/xi2.c",
                   "xpra/platform/win32/propsys.cpp",
                   "xpra/platform/darwin/gdk3_bindings.c",
                   "xpra/platform/posix/sd_listen.c",
                   "xpra/platform/posix/netdev_query.c",
                   "xpra/platform/posix/proc_libproc.c",
                   "xpra/platform/posix/proc_procps.c",
                   "xpra/net/bencode/cython_bencode.c",
                   "xpra/net/rencodeplus/rencodeplus.c",
                   "xpra/net/brotli/compressor.c",
                   "xpra/net/brotli/decompressor.c",
                   "xpra/net/qrcode/qrencode.c",
                   "xpra/net/websockets/mask.c",
                   "xpra/net/vsock/vsock.c",
                   "xpra/net/lz4/lz4.c",
                   "xpra/buffers/membuf.c",
                   "xpra/buffers/xxh.c",
                   "xpra/buffers/cyxor.c",
                   "xpra/codecs/vpx/encoder.c",
                   "xpra/codecs/vpx/decoder.c",
                   "xpra/codecs/nvidia/nvenc/encoder.c",
                   "xpra/codecs/nvidia/nvdec/decoder.c",
                   "xpra/codecs/nvidia/nvfbc/fbc_capture_linux.cpp",
                   "xpra/codecs/nvidia/nvfbc/fbc_capture_win.cpp",
                   "xpra/codecs/nvidia/nvjpeg/common.c",
                   "xpra/codecs/nvidia/nvjpeg/encoder.c",
                   "xpra/codecs/nvidia/nvjpeg/decoder.c",
                   "xpra/codecs/avif/encoder.c",
                   "xpra/codecs/avif/decoder.c",
                   "xpra/codecs/x264/encoder.c",
                   "xpra/codecs/spng/encoder.c",
                   "xpra/codecs/spng/decoder.c",
                   "xpra/codecs/jpeg/encoder.c",
                   "xpra/codecs/jpeg/decoder.c",
                   "xpra/codecs/ffmpeg/encoder.c",
                   "xpra/codecs/ffmpeg/av_log.c",
                   "xpra/codecs/ffmpeg/colorspace_converter.c",
                   "xpra/codecs/ffmpeg/decoder.c",
                   "xpra/codecs/openh264/encoder.c",
                   "xpra/codecs/openh264/decoder.c",
                   "xpra/codecs/v4l2/pusher.c",
                   "xpra/codecs/v4l2/constants.pxi",
                   "xpra/codecs/evdi/capture.cpp",
                   "xpra/codecs/drm/drm.c",
                   "xpra/codecs/webp/encoder.c",
                   "xpra/codecs/webp/decoder.c",
                   "xpra/codecs/libyuv/colorspace_converter.cpp",
                   "xpra/codecs/csc_cython/colorspace_converter.c",
                   "xpra/codecs/argb/argb.c",
                   "xpra/codecs/nvapi_version.c",
                   "xpra/gtk_common/gdk_atoms.c",
                   "xpra/client/gtk3/cairo_workaround.c",
                   "xpra/server/cystats.c",
                   "xpra/rectangle.c",
                   "xpra/server/window/motion.c",
                   "xpra/server/pam.c",
                   "fs/etc/xpra/xpra.conf",
                   #special case for the generated xpra conf files in build (see #891):
                   "build/etc/xpra/xpra.conf"] + glob.glob("build/etc/xpra/conf.d/*.conf")
    if cuda_rebuild_ENABLED:
        CLEAN_FILES += glob.glob("fs/share/xpra/cuda/*.fatbin")
    for x in CLEAN_FILES:
        p, ext = os.path.splitext(x)
        if ext in (".c", ".cpp", ".pxi"):
            #clean the Cython annotated html files:
            CLEAN_FILES.append(p+".html")
            if WIN32:
                #on win32, the build creates ".pyd" files, clean those too:
                CLEAN_FILES.append(p+".pyd")
                #when building with python3, we need to clean files named like:
                #"xpra/codecs/csc_libyuv/colorspace_converter-cpython-36m.dll"
                filename = os.path.join(os.getcwd(), p.replace("/", os.path.sep)+"*.dll")
                CLEAN_FILES += glob.glob(filename)
    if 'clean' in sys.argv:
        CLEAN_FILES.append("xpra/build_info.py")
    for x in CLEAN_FILES:
        filename = os.path.join(os.getcwd(), x.replace("/", os.path.sep))
        if os.path.exists(filename):
            if verbose_ENABLED:
                print(f"removing Cython/build generated file: {x}")
            os.unlink(filename)

if 'clean' in sys.argv or 'sdist' in sys.argv:
    clean()

def add_build_info(*args):
    cmd = [sys.executable, "./fs/bin/add_build_info.py"]+list(args)
    r = subprocess.Popen(cmd).wait(30)
    assert r==0, "'%s' returned %s" % (" ".join(cmd), r)

if "clean" not in sys.argv:
    # Add build info to build_info.py file:
    add_build_info("build")
    if modules_ENABLED:
        # ensure it is included in the module list if it didn't exist before
        add_modules("xpra.build_info")

if "sdist" in sys.argv:
    add_build_info("src")

if "install" in sys.argv or "build" in sys.argv:
    #if installing from source tree rather than
    #from a source snapshot, we may not have a "src_info" file
    #so create one:
    add_build_info()
    if modules_ENABLED:
        # ensure it is now included in the module list
        add_modules("xpra.src_info")


if 'clean' in sys.argv or 'sdist' in sys.argv:
    #take shortcut to skip cython/pkgconfig steps:
    setup(**setup_options)
    sys.exit(0)



def glob_recurse(srcdir):
    m = {}
    for root, _, files in os.walk(srcdir):
        for f in files:
            dirname = root[len(srcdir)+1:]
            m.setdefault(dirname, []).append(os.path.join(root, f))
    return m


#*******************************************************************************
if WIN32:
    MINGW_PREFIX = os.environ.get("MINGW_PREFIX")
    assert MINGW_PREFIX, "you must run this build from a MINGW environment"
    if modules_ENABLED:
        add_packages("xpra.platform.win32", "xpra.platform.win32.namedpipes")
    remove_packages("xpra.platform.darwin", "xpra.platform.posix")

    #this is where the win32 gi installer will put things:
    gnome_include_path = os.environ.get("MINGW_PREFIX")

    #cx_freeze doesn't use "data_files"...
    del setup_options["data_files"]
    #it wants source files first, then where they are placed...
    #one item at a time (no lists)
    #all in its own structure called "include_files" instead of "data_files"...
    def add_data_files(target_dir, files):
        if verbose_ENABLED:
            print(f"add_data_files({target_dir}, {files})")
        assert isinstance(target_dir, str)
        assert isinstance(files, (list, tuple))
        for f in files:
            target_file = os.path.join(target_dir, os.path.basename(f))
            data_files.append((f, target_file))

    #only add the cx_freeze specific options
    #only if we are packaging:
    if "install_exe" in sys.argv:
        #with cx_freeze, we don't use py_modules
        del setup_options["py_modules"]
        from cx_Freeze import setup, Executable     #@UnresolvedImport @Reimport
        if not hasattr(sys, "base_prefix"):
            #workaround for broken sqlite hook with python 2.7, see:
            #https://github.com/anthony-tuininga/cx_Freeze/pull/272
            sys.base_prefix = sys.prefix

        #pass a potentially nested dictionary representing the tree
        #of files and directories we do want to include
        def add_dir(base, defs):
            if verbose_ENABLED:
                print(f"add_dir({base}, {defs})")
            if isinstance(defs, (list, tuple)):
                for sub in defs:
                    if isinstance(sub, dict):
                        add_dir(base, sub)
                    else:
                        assert isinstance(sub, str)
                        filename = os.path.join(gnome_include_path, base, sub)
                        if os.path.exists(filename):
                            add_data_files(base, [filename])
                        else:
                            print(f"Warning: missing {filename!r}")
            else:
                assert isinstance(defs, dict)
                for d, sub in defs.items():
                    assert isinstance(sub, (dict, list, tuple))
                    #recurse down:
                    add_dir(os.path.join(base, d), sub)

        def add_gi_typelib(*libs):
            if verbose_ENABLED:
                print(f"add_gi_typelib({libs})")
            add_dir('lib',      {"girepository-1.0":    [f"{x}.typelib" for x in libs]})
        def add_gi_gir(*libs):
            if verbose_ENABLED:
                print(f"add_gi_gir({libs})")
            add_dir('share',    {"gir-1.0" :            [f"{x}.gir" for x in libs]})
        #convenience method for adding GI libs and "typelib" and "gir":
        def add_gi(*libs):
            add_gi_typelib(*libs)
            add_gi_gir(*libs)

        def add_DLLs(*dll_names):
            try:
                do_add_DLLs("lib", *dll_names)
            except Exception as e:
                print(f"Error: failed to add DLLs: {dll_names}")
                print(f" {e}")
                sys.exit(1)

        def do_add_DLLs(prefix="lib", *dll_names):
            dll_names = list(dll_names)
            dll_files = []
            version_re = re.compile(r"-[0-9\.-]+$")
            dirs = os.environ.get("PATH").split(os.path.pathsep)
            if os.path.exists(gnome_include_path):
                dirs.insert(0, gnome_include_path)
            if verbose_ENABLED:
                print(f"add_DLLs: looking for {dll_names} in {dirs}")
            for d in dirs:
                if not os.path.exists(d):
                    continue
                for x in os.listdir(d):
                    dll_path = os.path.join(d, x)
                    if os.path.isdir(dll_path):
                        continue
                    x = x.lower()
                    if prefix and not x.startswith(prefix):
                        continue
                    if not x.endswith(".dll"):
                        continue
                    #strip prefix (ie: "lib") and ".dll":
                    #ie: "libatk-1.0-0.dll" -> "atk-1.0-0"
                    nameversion = x[len(prefix):-4]
                    if verbose_ENABLED:
                        print(f"checking {x}: {nameversion}")
                    m = version_re.search(nameversion)          #look for version part of filename
                    if m:
                        dll_version = m.group(0)                #found it, ie: "-1.0-0"
                        dll_name = nameversion[:-len(dll_version)]  #ie: "atk"
                        dll_version = dll_version.lstrip("-")   #ie: "1.0-0"
                    else:
                        dll_version = ""                        #no version
                        dll_name = nameversion                  #ie: "libzzz.dll" -> "zzz"
                    if dll_name in dll_names:
                        #this DLL is on our list
                        print("%s %s %s" % (dll_name.ljust(22), dll_version.ljust(10), x))
                        dll_files.append(dll_path)
                        dll_names.remove(dll_name)
            if dll_names:
                print("some DLLs could not be found:")
                for x in dll_names:
                    print(f" - {prefix}{x}*.dll")
            add_data_files("", dll_files)

        #list of DLLs we want to include, without the "lib" prefix, or the version and extension
        #(ie: "libatk-1.0-0.dll" -> "atk")
        if audio_ENABLED or gtk3_ENABLED:
            add_DLLs('gio', 'girepository', 'glib',
                     'gnutls', 'gobject', 'gthread',
                     'orc', 'stdc++',
                     'winpthread',
                     )
        if gtk3_ENABLED:
            add_DLLs('atk',
                     #'dbus', 'dbus-glib',
                     'gdk', 'gdk_pixbuf', 'gtk',
                     'cairo-gobject', 'cairo', 'pango', 'pangocairo', 'pangoft2', 'pangowin32',
                     'harfbuzz', 'harfbuzz-gobject',
                     'jasper', 'epoxy',
                     'intl',
                     'p11-kit',
                     'jpeg', 'png16', 'rsvg',
                     'webp', "webpdecoder",
                     'tiff',
                     )

        if gtk3_ENABLED:
            add_dir('etc', ["fonts", "gtk-3.0", "pkcs11"])     #add "dbus-1"?
            add_dir('lib', ["gdk-pixbuf-2.0", "gtk-3.0",
                            "p11-kit", "pkcs11"])
            add_dir('share', ["fontconfig", "fonts", "glib-2.0",        #add "dbus-1"?
                              "p11-kit", "xml",
                              {"locale" : ["en"]},
                              {"themes" : ["Default"]}
                             ])
            ICONS = ["24x24", "48x48", "scalable", "cursors", "index.theme"]
            for theme in ("Adwaita", ): #"hicolor"
                add_dir("share/icons/"+theme, ICONS)
            add_dir("share/themes/Windows-10", [
                "CREDITS", "LICENSE.md", "README.md",
                "gtk-3.20", "index.theme"])
        if gtk3_ENABLED or audio_ENABLED:
            #causes warnings:
            #add_dir('lib', ["gio"])
            packages.append("gi")
            add_gi_typelib("Gio-2.0", "GIRepository-2.0", "Glib-2.0", "GModule-2.0",
                   "GObject-2.0")
        if gtk3_ENABLED:
            add_gi("Atk-1.0",
                   "Notify-0.7",
                   "GDesktopEnums-3.0", "Soup-2.4",
                   "GdkPixbuf-2.0", "Gdk-3.0", "Gtk-3.0",
                   "HarfBuzz-0.0",
                   "Pango-1.0", "PangoCairo-1.0", "PangoFT2-1.0",
                   "Rsvg-2.0",
                   )
            add_gi_typelib("cairo-1.0",
                           "fontconfig-2.0", "freetype2-2.0",
                           "libproxy-1.0", "libxml2-2.0")
            #we no longer support GtkGL:
            #if opengl_ENABLED:
            #    add_gi("GdkGLExt-3.0", "GtkGLExt-3.0", "GL-1.0")
            add_DLLs('curl', 'soup')

        if client_ENABLED:
            #svg pixbuf loader:
            add_DLLs("rsvg", "croco")

        if client_ENABLED or server_ENABLED:
            add_DLLs("qrencode")

        if audio_ENABLED:
            add_dir("share", ["gst-plugins-base", "gstreamer-1.0"])
            add_gi("Gst-1.0", "GstAllocators-1.0", "GstAudio-1.0", "GstBase-1.0",
                   "GstTag-1.0")
            add_DLLs('gstreamer', 'orc-test')
            for p in ("app", "audio", "base", "codecparsers", "fft", "net", "video",
                      "pbutils", "riff", "sdp", "rtp", "rtsp", "tag", "uridownloader",
                      #I think 'coreelements' needs those (otherwise we would exclude them):
                      "basecamerabinsrc", "mpegts", "photography",
                      ):
                add_DLLs(f"gst{p}")
            #DLLs needed by the plugins:
            add_DLLs("faac", "faad", "flac", "mpg123")      #"mad" is no longer included?
            #add the gstreamer plugins we need:
            GST_PLUGINS = ("app",
                           "cutter", "removesilence",
                           #muxers:
                           "gdp", "matroska", "ogg", "isomp4",
                           "audioparsers", "audiorate", "audioconvert", "audioresample", "audiotestsrc",
                           "coreelements", "directsound", "directsoundsrc", "wasapi",
                           #codecs:
                           "opus", "opusparse", "flac", "lame", "mpg123", "speex", "faac", "faad",
                           "volume", "vorbis", "wavenc", "wavpack", "wavparse",
                           "autodetect",
                           #decodebin used for playing "new-client" sound:
                           "playback", "typefindfunctions",
                           #video codecs:
                           "vpx", "x264", "aom", "openh264", "d3d11", "winscreencap",
                           "videoconvertscale", "videorate",
                           )
            add_dir(os.path.join("lib", "gstreamer-1.0"), [("libgst%s.dll" % x) for x in GST_PLUGINS])
            #END OF SOUND

        if server_ENABLED:
            #used by proxy server:
            external_includes += ["multiprocessing", "setproctitle"]

        external_includes += ["encodings", "mimetypes"]
        if client_ENABLED:
            external_includes += [
                "shlex",                #for parsing "open-command"
                "ftplib", "fileinput",  #for version check
                "urllib", "http.cookiejar", "http.client",
                #for websocket browser cookie:
                "browser_cookie3", "pyaes", "pbkdf2", "keyring",
                ]

        if dec_avcodec2_ENABLED:
            #why isn't this one picked up automatically?
            add_DLLs("x265")

        #hopefully, cx_Freeze will fix this horror:
        #(we shouldn't have to deal with DLL dependencies)
        import site
        lib_python = os.path.dirname(site.getsitepackages()[0])
        lib_dynload_dir = os.path.join(lib_python, "lib-dynload")
        add_data_files('', glob.glob(f"{lib_dynload_dir}/zlib*dll"))
        for x in ("io", "codecs", "abc", "_weakrefset", "encodings"):
            add_data_files("lib/", glob.glob(f"{lib_python}/{x}*"))
        #ensure that cx_freeze won't automatically grab other versions that may lay on our path:
        os.environ["PATH"] = gnome_include_path+";"+os.environ.get("PATH", "")
        bin_excludes = ["MSVCR90.DLL", "MFC100U.DLL"]
        cx_freeze_options = {
                            "includes"          : external_includes,
                            "packages"          : packages,
                            "include_files"     : data_files,
                            "excludes"          : excludes,
                            "include_msvcr"     : True,
                            "bin_excludes"      : bin_excludes,
                            }
        #cx_Freeze v5 workarounds:
        if nvenc_ENABLED or nvdec_ENABLED or nvfbc_ENABLED:
            add_packages("numpy.core._methods", "numpy.lib.format")

        setup_options["options"] = {"build_exe" : cx_freeze_options}
        executables = []
        setup_options["executables"] = executables

        def add_exe(script, icon, base_name, base="Console"):
            executables.append(Executable(
                        script                  = script,
                        init_script             = None,
                        #targetDir               = "dist",
                        icon                    = f"fs/share/xpra/icons/{icon}",
                        target_name             = f"{base_name}.exe",
                        base                    = base,
                        ))

        def add_console_exe(script, icon, base_name):
            add_exe(script, icon, base_name)
        def add_gui_exe(script, icon, base_name):
            add_exe(script, icon, base_name, base="Win32GUI")
        def add_service_exe(script, icon, base_name):
            add_exe(script, icon, base_name, base="Win32Service")

        #UI applications (detached from shell: no text output if ran from cmd.exe)
        if (client_ENABLED or server_ENABLED) and gtk3_ENABLED:
            add_gui_exe("fs/bin/xpra",                         "xpra.ico",         "Xpra")
            add_gui_exe("xpra/platform/win32/scripts/shadow_server.py",       "server-notconnected.ico", "Xpra-Shadow")
            add_gui_exe("fs/bin/xpra_launcher",                "xpra.ico",         "Xpra-Launcher")
            add_console_exe("fs/bin/xpra_launcher",            "xpra.ico",         "Xpra-Launcher-Debug")
            add_gui_exe("xpra/gtk_common/gtk_view_keyboard.py", "keyboard.ico",     "GTK_Keyboard_Test")
            add_gui_exe("xpra/scripts/bug_report.py",           "bugs.ico",         "Bug_Report")
            add_gui_exe("xpra/platform/win32/gdi_screen_capture.py", "screenshot.ico", "Screenshot")
        if server_ENABLED:
            add_gui_exe("fs/libexec/xpra/auth_dialog",          "authentication.ico", "Auth_Dialog")
        #Console: provide an Xpra_cmd.exe we can run from the cmd.exe shell
        add_console_exe("fs/bin/xpra",                     "xpra_txt.ico",     "Xpra_cmd")
        add_console_exe("xpra/scripts/version.py",          "information.ico",  "Version_info")
        add_console_exe("xpra/net/net_util.py",             "network.ico",      "Network_info")
        if gtk3_ENABLED:
            add_console_exe("xpra/scripts/gtk_info.py",         "gtk.ico",          "GTK_info")
            add_console_exe("xpra/gtk_common/keymap.py",        "keymap.ico",       "Keymap_info")
            add_console_exe("xpra/platform/keyboard.py",        "keymap.ico",       "Keyboard_info")
            add_gui_exe("xpra/client/gtk3/example/tray.py", "xpra.ico",         "SystemTray_Test")
            add_gui_exe("xpra/client/gtk3/u2f_tool.py",     "authentication.ico", "U2F_Tool")
        if client_ENABLED or server_ENABLED:
            add_console_exe("xpra/platform/win32/scripts/exec.py",     "python.ico", "Python_exec_cmd")
            add_gui_exe("xpra/platform/win32/scripts/exec.py",     "python.ico", "Python_exec_gui")
            add_console_exe("xpra/platform/win32/scripts/execfile.py", "python.ico", "Python_execfile_cmd")
            add_gui_exe("xpra/platform/win32/scripts/execfile.py", "python.ico", "Python_execfile_gui")
            add_console_exe("xpra/scripts/config.py",           "gears.ico",        "Config_info")
        if server_ENABLED:
            add_console_exe("xpra/server/auth/sqlite_auth.py",  "sqlite.ico",        "SQLite_auth_tool")
            add_console_exe("xpra/server/auth/sql_auth.py",     "sql.ico",           "SQL_auth_tool")
            add_console_exe("xpra/server/auth/win32_auth.py",   "authentication.ico", "System-Auth-Test")
            add_console_exe("xpra/server/auth/ldap_auth.py",    "authentication.ico", "LDAP-Auth-Test")
            add_console_exe("xpra/server/auth/ldap3_auth.py",   "authentication.ico", "LDAP3-Auth-Test")
            add_console_exe("xpra/platform/win32/scripts/proxy.py", "xpra_txt.ico",     "Xpra-Proxy_cmd")
            add_gui_exe("xpra/platform/win32/scripts/proxy.py", "xpra.ico",         "Xpra-Proxy")
            add_console_exe("xpra/platform/win32/lsa_logon_lib.py", "xpra_txt.ico",     "System-Logon-Test")
        if client_ENABLED:
            add_console_exe("xpra/codecs/loader.py",            "encoding.ico",     "Encoding_info")
            add_console_exe("xpra/platform/paths.py",           "directory.ico",    "Path_info")
            add_console_exe("xpra/platform/features.py",        "features.ico",     "Feature_info")
        if client_ENABLED:
            add_console_exe("xpra/platform/gui.py",             "browse.ico",       "NativeGUI_info")
            add_console_exe("xpra/platform/win32/gui.py",       "loop.ico",         "Events_Test")
        if audio_ENABLED:
            add_console_exe("xpra/audio/gstreamer_util.py",     "gstreamer.ico",    "GStreamer_info")
            add_console_exe("fs/bin/xpra",                     "speaker.ico",      "Xpra_Audio")
            add_console_exe("xpra/platform/win32/directsound.py", "speaker.ico",      "Audio_Devices")
            #add_console_exe("xpra/audio/src.py",                "microphone.ico",   "Audio_Record")
            #add_console_exe("xpra/audio/sink.py",               "speaker.ico",      "Audio_Play")
            add_data_files("", (shutil.which("gst-launch-1.0.exe"), ))
        if opengl_ENABLED:
            add_console_exe("xpra/client/gl/gl_check.py",   "opengl.ico",       "OpenGL_check")
        if webcam_ENABLED:
            add_console_exe("xpra/platform/webcam.py",          "webcam.ico",    "Webcam_info")
            add_console_exe("xpra/scripts/show_webcam.py",          "webcam.ico",    "Webcam_Test")
        if printing_ENABLED:
            add_console_exe("xpra/platform/printing.py",        "printer.ico",     "Print")
            add_console_exe("xpra/platform/win32/pdfium.py",    "printer.ico",     "PDFIUM_Print")
            do_add_DLLs("", "pdfium")
        if nvenc_ENABLED or nvdec_ENABLED:
            add_console_exe("xpra/codecs/nvidia/nv_util.py",                   "nvidia.ico",   "NVidia_info")
        if nvfbc_ENABLED:
            add_console_exe("xpra/codecs/nvidia/nvfbc/capture.py",             "nvidia.ico",   "NvFBC_capture")
        if nvfbc_ENABLED or nvenc_ENABLED or nvdec_ENABLED or nvjpeg_encoder_ENABLED or nvjpeg_decoder_ENABLED:
            add_console_exe("xpra/codecs/nvidia/cuda_context.py",  "cuda.ico",     "CUDA_info")

    if ("install_exe" in sys.argv) or ("install" in sys.argv):
        #FIXME: how do we figure out what target directory to use?
        print("calling build_xpra_conf in-place")
        #building etc files in-place:
        if data_ENABLED:
            build_xpra_conf("./fs")
            add_data_files('etc/xpra',
                           glob.glob("fs/etc/xpra/*conf")+
                           glob.glob("fs/etc/xpra/nvenc*.keys")+
                           glob.glob("fs/etc/xpra/nvfbc*.keys")
                           )
            add_data_files('etc/xpra/conf.d', glob.glob("fs/etc/xpra/conf.d/*conf"))

    if data_ENABLED:
        add_data_files("", [
            "packaging/MSWindows/website.url",
            "packaging/MSWindows/DirectShow.tlb",
            "packaging/MSWindows/TaskbarLib.tlb",
            ])

    remove_packages(*external_excludes)
    external_includes += [
        "pyu2f",
        "mmap",
        "comtypes"      #used by webcam and netdev_query
        ]
    remove_packages("comtypes.gen")         #this is generated at runtime
                                            #but we still have to remove the empty directory by hand
                                            #afterwards because cx_freeze does weird things (..)
    remove_packages(#not used on win32:
                    #we handle GL separately below:
                    "OpenGL", "OpenGL_accelerate",
                    #this is a mac osx thing:
                    "ctypes.macholib")

    if webcam_ENABLED:
        external_includes.append("cv2")
    else:
        remove_packages("cv2")

    external_includes.append("cairo")
    external_includes.append("certifi")

    if nvenc_ENABLED or nvdec_ENABLED or nvfbc_ENABLED:
        external_includes.append("numpy")
    else:
        remove_packages("unittest", "difflib",  #avoid numpy warning (not an error)
                        "pydoc")

    #add subset of PyOpenGL modules (only when installing):
    if opengl_ENABLED and "install_exe" in sys.argv:
        #for this hack to work, you must add "." to the sys.path
        #so python can load OpenGL from the install directory
        #(further complicated by the fact that "." is the "frozen" path...)
        #but we re-add those two directories to the library.zip as part of the build script
        import OpenGL
        print(f"*** copying PyOpenGL modules to {install} ***")
        glmodules = {
            "OpenGL" : OpenGL,
            }
        try:
            import OpenGL_accelerate        #@UnresolvedImport
        except ImportError as e:
            print("Warning: missing OpenGL_accelerate module")
            print(f" {e}")
        else:
            glmodules["OpenGL_accelerate"] = OpenGL_accelerate
        for module_name, module in glmodules.items():
            module_dir = os.path.dirname(module.__file__ )
            try:
                shutil.copytree(
                    module_dir, os.path.join(install, "lib", module_name),
                    ignore = shutil.ignore_patterns(
                        "Tk", "AGL", "EGL",
                        "GLX", "GLX.*", "_GLX.*",
                        "GLE", "GLES1", "GLES2", "GLES3",
                        )
                )
                print(f"copied {module_dir} to {install}/{module_name}")
            except Exception as e:
                if not isinstance(e, WindowsError) or ("already exists" not in str(e)): #@UndefinedVariable
                    raise

    if data_ENABLED:
        add_data_files("share/metainfo",      ["fs/share/metainfo/xpra.appdata.xml"])
        for d in ("http-headers", "content-type", "content-categories", "content-parent"):
            add_data_files(f"etc/xpra/{d}", glob.glob(f"fs/etc/xpra/{d}/*"))

    #END OF win32
#*******************************************************************************
else:
    #OSX and *nix:
    libexec_scripts = []
    if scripts_ENABLED:
        libexec_scripts += ["xpra_signal_listener"]
    if LINUX or FREEBSD:
        if scripts_ENABLED:
            libexec_scripts += ["xpra_udev_product_version"]
        if xdg_open_ENABLED:
            libexec_scripts += ["xdg-open", "gnome-open", "gvfs-open"]
        if server_ENABLED:
            libexec_scripts.append("auth_dialog")
    def add_data_files(target_dir, files):
        assert isinstance(target_dir, str)
        assert isinstance(files, (list, tuple))
        data_files.append((target_dir, files))
    if is_openSUSE():
        # basically need $(basename $(rpm -E '%{_libexecdir}'))
        libexec_dir = "__LIBEXECDIR__"
    else:
        libexec_dir = "libexec"
    add_data_files(libexec_dir+"/xpra/", [f"fs/libexec/xpra/{x}" for x in libexec_scripts])
    if data_ENABLED:
        man_path = "share/man"
        icons_dir = "icons"
        if OPENBSD or FREEBSD:
            man_path = "man"
        if OPENBSD or FREEBSD or is_openSUSE():
            icons_dir = "pixmaps"
        man_pages = ["fs/share/man/man1/xpra.1", "fs/share/man/man1/xpra_launcher.1"]
        if not OSX:
            man_pages.append("fs/share/man/man1/run_scaled.1")
        add_data_files(f"{man_path}/man1",  man_pages)
        add_data_files("share/applications",  glob.glob("fs/share/applications/*.desktop"))
        add_data_files("share/mime/packages", ["fs/share/mime/packages/application-x-xpraconfig.xml"])
        add_data_files(f"share/{icons_dir}", glob.glob("fs/share/icons/*.png"))
        add_data_files("share/metainfo",      ["fs/share/metainfo/xpra.appdata.xml"])

    #here, we override build and install so we can
    #generate our /etc/xpra/xpra.conf
    class build_override(build):
        def run(self):
            build.run(self)
            self.run_command("build_conf")

    class build_conf(build):
        def run(self):
            try:
                build_base = self.distribution.command_obj['build'].build_base
            except Exception:
                build_base = self.build_base
            build_xpra_conf(build_base)

    class install_data_override(install_data):

        def finalize_options(self):
            self.install_base = self.install_platbase = None
            install_data.finalize_options(self)

        def run(self):
            install_dir = self.install_dir
            if install_dir.endswith("egg"):
                install_dir = install_dir.split("egg")[1] or sys.prefix
            else:
                install_data.run(self)
            print(f"install_data_override.run() install_dir={install_dir}")
            root_prefix = None
            for x in sys.argv:
                if x.startswith("--prefix="):
                    root_prefix = x[len("--prefix="):]
            if not root_prefix:
                root_prefix = install_dir.rstrip("/")
            if root_prefix.endswith("/usr"):
                #ie: "/" or "/usr/src/rpmbuild/BUILDROOT/xpra-0.18.0-0.20160513r12573.fc23.x86_64/"
                root_prefix = root_prefix[:-4]
            for x in sys.argv:
                if x.startswith("--root="):
                    root_prefix = x[len("--root="):]
            print(f"install_data_override.run() root_prefix={root_prefix}")
            build_xpra_conf(root_prefix)

            def copytodir(src, dst_dir, dst_name=None, chmod=0o644, subs=None):
                #print("copytodir%s" % (src, dst_dir, dst_name, chmod, subs))
                #convert absolute paths:
                if dst_dir.startswith("/"):
                    dst_dir = root_prefix+dst_dir
                else:
                    dst_dir = install_dir.rstrip("/")+"/"+dst_dir
                #make sure the target directory exists:
                self.mkpath(dst_dir)
                #generate the target filename:
                filename = os.path.basename(src)
                dst_file = os.path.join(dst_dir, dst_name or filename)
                #copy it
                print(f"copying {src} -> {dst_dir} (%s)" % oct(chmod))
                data = load_binary_file(src)
                if subs:
                    for k,v in subs.items():
                        data = data.replace(k, v)
                with open(dst_file, "wb") as f:
                    f.write(data)
                if chmod:
                    print(f"chmod({dst_file}, %s)" % oct(chmod))
                    os.chmod(dst_file, chmod)

            def dirtodir(src_dir, dst_dir):
                print(f"dirtodir({src_dir}, {dst_dir})")
                for f in os.listdir(src_dir):
                    copytodir(os.path.join(src_dir, f), dst_dir)

            if printing_ENABLED and POSIX:
                #install "/usr/lib/cups/backend" with 0700 permissions:
                lib_cups = "lib/cups"
                if FREEBSD:
                    lib_cups = "libexec/cups"
                copytodir("fs/lib/cups/backend/xpraforwarder", f"{lib_cups}/backend", chmod=0o700)

            if x11_ENABLED:
                #install xpra_Xdummy if we need it:
                xvfb_command = detect_xorg_setup()
                if any(x.find("xpra_Xdummy")>=0 for x in (xvfb_command or [])) or Xdummy_wrapper_ENABLED is True:
                    copytodir("fs/bin/xpra_Xdummy", "bin", chmod=0o755)
                #install xorg*.conf, cuda.conf and nvenc.keys:
                etc_xpra_files = {}
                def addconf(name, dst_name=None):
                    etc_xpra_files[name] = dst_name
                if uinput_ENABLED:
                    addconf("xorg-uinput.conf")
                if nvenc_ENABLED or nvdec_ENABLED or nvfbc_ENABLED:
                    addconf("cuda.conf")
                if nvenc_ENABLED:
                    addconf("nvenc.keys")
                if nvfbc_ENABLED:
                    addconf("nvfbc.keys")
                if vernum(dummy_driver_version or get_dummy_driver_version()) < (0, 4):
                    addconf("xorg-legacy.conf", "xorg.conf")
                else:
                    addconf("xorg.conf")
                for src, dst_name in etc_xpra_files.items():
                    copytodir(f"fs/etc/xpra/{src}", "/etc/xpra", dst_name=dst_name)
                copytodir("fs/etc/X11/xorg.conf.d/90-xpra-virtual.conf", "/etc/X11/xorg.conf.d/")

            if pam_ENABLED:
                copytodir("fs/etc/pam.d/xpra", "/etc/pam.d")

            systemd_dir = "/lib/systemd/system"
            if is_openSUSE():
                systemd_dir = "__UNITDIR__"
            if service_ENABLED:
                #Linux init service:
                subs = {}
                if is_RedHat() or is_CentOS() or is_AlmaLinux() or is_RockyLinux() or is_OracleLinux() or is_Fedora():
                    cdir = "/etc/sysconfig"
                elif is_Debian() or is_Ubuntu():
                    cdir = "/etc/default"
                elif os.path.exists("/etc/sysconfig"):
                    cdir = "/etc/sysconfig"
                else:
                    cdir = "/etc/default"
                if is_openSUSE():
                    #openSUSE does things differently:
                    cdir = "__FILLUPDIR__"
                    shutil.copy("fs/etc/sysconfig/xpra", "fs/etc/sysconfig/sysconfig.xpra")
                    os.chmod("fs/etc/sysconfig/sysconfig.xpra", 0o644)
                    copytodir("fs/etc/sysconfig/sysconfig.xpra", cdir)
                else:
                    copytodir("fs/etc/sysconfig/xpra", cdir)
                if cdir!="/etc/sysconfig":
                    #also replace the reference to it in the service file below
                    subs[b"/etc/sysconfig"] = cdir.encode()
                if os.path.exists("/bin/systemctl") or os.path.exists("/usr/bin/systemctl") or sd_listen_ENABLED:
                    if sd_listen_ENABLED:
                        copytodir("fs/lib/systemd/system/xpra.service", systemd_dir,
                                  subs=subs)
                    else:
                        copytodir("fs/lib/systemd/system/xpra-nosocketactivation.service", systemd_dir,
                                  dst_name="xpra.service", subs=subs)
                else:
                    copytodir("fs/etc/init.d/xpra", "/etc/init.d")
            if sd_listen_ENABLED:
                copytodir("fs/lib/systemd/system/xpra.socket", systemd_dir)
            if dbus_ENABLED and proxy_ENABLED:
                copytodir("fs/etc/dbus-1/system.d/xpra.conf", "/etc/dbus-1/system.d")

            if docs_ENABLED:
                doc_dir = f"{install_dir}/share/doc/xpra/"
                convert_doc_dir("./docs", doc_dir)

            if data_ENABLED:
                for etc_dir in ("http-headers", "content-type", "content-categories", "content-parent"):
                    dirtodir(f"fs/etc/xpra/{etc_dir}", f"/etc/xpra/{etc_dir}")

    # add build_conf to build step
    cmdclass.update({
             'build'        : build_override,
             'build_conf'   : build_conf,
             'install_data' : install_data_override,
             })

    if OSX:
        #pyobjc needs email.parser
        external_includes += ["email", "uu", "urllib", "objc", "cups", "six"]
        external_includes += ["kerberos", "future", "pyu2f", "paramiko", "nacl"]
        #OSX package names (ie: gdk-x11-2.0 -> gdk-2.0, etc)
        add_packages("xpra.platform.darwin")
        remove_packages("xpra.platform.win32", "xpra.platform.posix")
        #to support GStreamer 1.x we need this:
        modules += ["importlib", "mimetypes"]
        #for PyOpenGL:
        add_packages("numpy.core._methods", "numpy.lib.format")
    else:
        add_packages("xpra.platform.posix")
        remove_packages("xpra.platform.win32", "xpra.platform.darwin")
        if data_ENABLED:
            #not supported by all distros, but doesn't hurt to install them anyway:
            if not FREEBSD:
                for x in ("tmpfiles.d", "sysusers.d"):
                    add_data_files(f"lib/{x}", [f"fs/lib/{x}/xpra.conf"])
            if uinput_ENABLED:
                add_data_files("lib/udev/rules.d/", ["fs/lib/udev/rules.d/71-xpra-virtual-pointer.rules"])

    #gentoo does weird things, calls --no-compile with build *and* install
    #then expects to find the cython modules!? ie:
    #> python2.7 setup.py build -b build-2.7 install --no-compile \
    # --root=/var/tmp/portage/x11-wm/xpra-0.7.0/temp/images/2.7
    #otherwise we use the flags to skip pkgconfig
    if ("--no-compile" in sys.argv or "--skip-build" in sys.argv) and not ("build" in sys.argv and "install" in sys.argv):
        pkgconfig = no_pkgconfig

    if OSX and "py2app" in sys.argv:
        import py2app    #@UnresolvedImport
        assert py2app is not None

        #don't use py_modules or scripts with py2app, and no cython:
        del setup_options["py_modules"]
        scripts = []
        def add_cython_ext(*_args, **_kwargs):  # pylint: disable=function-redefined
            pass

        remove_packages("ctypes.wintypes", "colorsys")
        remove_packages(*external_excludes)

        try:
            # pylint: disable=ungrouped-imports
            from xpra.src_info import REVISION
        except ImportError:
            REVISION = "unknown"
        Plist = {
            "CFBundleDocumentTypes" : {
                "CFBundleTypeExtensions"    : ["Xpra"],
                "CFBundleTypeName"          : "Xpra Session Config File",
                "CFBundleName"              : "Xpra",
                "CFBundleTypeRole"          : "Viewer",
                },
            "CFBundleGetInfoString" : f"{XPRA_VERSION}-{REVISION} (c) 2012-2022 https://xpra.org/",
            "CFBundleIdentifier"            : "org.xpra.xpra",
            }
        #Note: despite our best efforts, py2app will not copy all the modules we need
        #so the make-app.sh script still has to hack around this problem.
        add_modules(*external_includes)
        py2app_options = {
            'iconfile'          : './fs/share/icons/xpra.icns',
            'plist'             : Plist,
            'site_packages'     : False,
            'argv_emulation'    : True,
            'strip'             : False,
            'includes'          : modules,
            'excludes'          : excludes,
            'frameworks'        : ['CoreFoundation', 'Foundation', 'AppKit'],
            }
        setup_options["options"] = {"py2app": py2app_options}
        setup_options["app"]     = ["xpra/scripts/main.py"]


if WIN32 or OSX:
    external_includes += ["ssl", "_ssl"]
    #socks proxy support:
    add_packages("socks")
    if pillow_ENABLED:
        external_includes += ["PIL", "PIL.Image", "PIL.WebPImagePlugin"]
    if crypto_ENABLED or OSX:
        external_includes += ["cffi", "_cffi_backend"]
    if crypto_ENABLED:
        if OSX:
            #quic:
            add_packages("uvloop")
        #python-cryptography needs workarounds for bundling:
        external_includes += [
            "cryptography", "idna", "idna.idnadata", "appdirs",
            ]
        add_modules("cryptography.hazmat.bindings._openssl",
                    "cryptography.hazmat.bindings._constant_time",
                    "cryptography.hazmat.bindings._padding",
                    "cryptography.hazmat.backends.openssl",
                    "cryptography.fernet")


if scripts_ENABLED:
    scripts += ["fs/bin/xpra", "fs/bin/xpra_launcher"]
    if not OSX and not WIN32:
        scripts.append("fs/bin/run_scaled")
toggle_modules(WIN32, "xpra/scripts/win32_service")

if data_ENABLED:
    if not is_openSUSE():
        add_data_files(share_xpra,                  ["README.md", "COPYING"])
    add_data_files(share_xpra,                      ["fs/share/xpra/bell.wav"])
    if LINUX or FREEBSD:
        add_data_files(share_xpra,                  ["fs/share/xpra/autostart.desktop"])
    ICONS = glob.glob("fs/share/xpra/icons/*.png")
    if OSX:
        ICONS += glob.glob("fs/share/xpra/icons/*.icns")
    if WIN32:
        ICONS += glob.glob("fs/share/xpra/icons/*.ico")
    add_data_files(f"{share_xpra}/icons",         ICONS)
    add_data_files(f"{share_xpra}/css",           glob.glob("fs/share/xpra/css/*"))

#*******************************************************************************
if cython_ENABLED:
    add_packages("xpra.buffers")
    buffers_pkgconfig = pkgconfig(optimize=3)
    import platform
    #this may well be sub-optimal:
    extra_compile_args = "-mfpmath=387" if platform.machine()=="i386" else None
    tace(cython_ENABLED, "xpra.buffers.membuf,xpra/buffers/memalign.c", optimize=3, extra_compile_args=extra_compile_args)
    tace(cython_ENABLED, "xpra.buffers.xxh,xpra/buffers/xxhash.c", optimize=3, extra_compile_args=extra_compile_args)

toggle_packages(dbus_ENABLED, "xpra.dbus")
toggle_packages(server_ENABLED or proxy_ENABLED, "xpra.server", "xpra.server.auth")
toggle_packages(proxy_ENABLED, "xpra.server.proxy")
toggle_packages(server_ENABLED, "xpra.server.window")
toggle_packages(server_ENABLED and rfb_ENABLED, "xpra.server.rfb")
toggle_packages(server_ENABLED or shadow_ENABLED, "xpra.server.mixins", "xpra.server.source")
toggle_packages(shadow_ENABLED, "xpra.server.shadow")
toggle_packages(server_ENABLED or client_ENABLED, "xpra.clipboard")
toggle_packages(x11_ENABLED and dbus_ENABLED and server_ENABLED, "xpra.x11.dbus")
toggle_packages(notifications_ENABLED, "xpra.notifications")

#cannot use toggle here as cx_Freeze will complain if we try to exclude this module:
if dbus_ENABLED and server_ENABLED:
    add_packages("xpra.server.dbus")

tace(OSX, "xpra.platform.darwin.gdk3_bindings,xpra/platform/darwin/transparency_glue.m",
     ("gtk+-3.0", "pygobject-3.0"), language="objc", extra_compile_args=(
                "-ObjC",
                "-I/System/Library/Frameworks/Cocoa.framework/Versions/A/Headers/",
                "-I/System/Library/Frameworks/AppKit.framework/Versions/C/Headers/")
     )

toggle_packages(x11_ENABLED, "xpra.x11", "xpra.x11.bindings")
if x11_ENABLED:
    ace("xpra.x11.bindings.events", "x11")
    ace("xpra.x11.bindings.xwait", "x11")
    ace("xpra.x11.bindings.wait_for_x_server", "x11")
    ace("xpra.x11.bindings.display_source", "x11")
    ace("xpra.x11.bindings.core", "x11")
    ace("xpra.x11.bindings.xwayland", "x11")
    ace("xpra.x11.bindings.posix_display_source", "x11")
    ace("xpra.x11.bindings.randr", "x11,xrandr")
    ace("xpra.x11.bindings.keyboard", "x11,xtst,xfixes,xkbfile")
    ace("xpra.x11.bindings.window", "x11,xtst,xfixes,xcomposite,xdamage,xext")
    ace("xpra.x11.bindings.ximage", "x11,xext,xcomposite")
    ace("xpra.x11.bindings.res", "x11,xres")
    tace(xinput_ENABLED, "xpra.x11.bindings.xi2", "x11,xi")

toggle_packages(gtk_x11_ENABLED, "xpra.x11.gtk_x11")
toggle_packages(server_ENABLED and gtk_x11_ENABLED, "xpra.x11.models", "xpra.x11.desktop")
if gtk_x11_ENABLED:
    add_packages("xpra.x11.gtk3")
    ace("xpra.x11.gtk3.gdk_display_source", "gdk-3.0")
    ace("xpra.x11.gtk3.gdk_bindings,xpra/x11/gtk3/gdk_x11_macros.c", "gdk-3.0,xdamage")

tace(client_ENABLED and gtk3_ENABLED, "xpra.client.gtk3.cairo_workaround", "py3cairo",
     extra_compile_args=["-Wno-error=parentheses-equality"] if CC_is_clang() else [])


#build tests, but don't install them:
toggle_packages(tests_ENABLED, "unit")


if bundle_tests_ENABLED:
    def bundle_tests():
        #bundle the tests directly (not in library.zip):
        for k,v in glob_recurse("unit").items():
            if k!="":
                k = os.sep+k
            add_data_files("unit"+k, v)
    bundle_tests()


#special case for client: cannot use toggle_packages which would include gtk3, etc:
if client_ENABLED:
    add_modules("xpra.client")
    add_packages("xpra.client.base")
    add_packages("xpra.client.mixins", "xpra.client.auth")
    add_modules("xpra.scripts.gtk_info", "xpra.scripts.show_webcam", "xpra.scripts.pinentry_wrapper")
if gtk3_ENABLED:
    add_modules("xpra.scripts.bug_report")
toggle_packages((client_ENABLED and gtk3_ENABLED) or audio_ENABLED or server_ENABLED, "xpra.gtk_common")
toggle_packages(client_ENABLED and gtk3_ENABLED, "xpra.client.gtk3", "xpra.client.gtk3", "xpra.client.gui")
toggle_packages((client_ENABLED and gtk3_ENABLED) or (audio_ENABLED and WIN32 and MINGW_PREFIX), "gi")
toggle_packages(client_ENABLED and opengl_ENABLED and gtk3_ENABLED, "xpra.client.gl.gtk3")
toggle_packages(client_ENABLED and gtk3_ENABLED and example_ENABLED, "xpra.client.gtk3.example")
if client_ENABLED and WIN32 and MINGW_PREFIX:
    ace("xpra.platform.win32.propsys,xpra/platform/win32/setappid.cpp",
        language="c++",
        extra_link_args = ("-luuid", "-lshlwapi", "-lole32", "-static-libgcc")
        )

if client_ENABLED or server_ENABLED:
    add_modules("xpra.codecs")
toggle_packages(keyboard_ENABLED, "xpra.keyboard")
if client_ENABLED or server_ENABLED:
    add_modules(
        "xpra.scripts.config",
        "xpra.scripts.parsing",
        "xpra.scripts.exec_util",
        "xpra.scripts.fdproxy",
        "xpra.scripts.version",
        )
if server_ENABLED or proxy_ENABLED:
    add_modules("xpra.scripts.server")
if WIN32 and client_ENABLED and gtk3_ENABLED:
    add_modules("xpra.scripts.gtk_info")

toggle_packages(not WIN32, "xpra.platform.pycups_printing")
toggle_packages(client_ENABLED and opengl_ENABLED, "xpra.client.gl")

toggle_modules(audio_ENABLED, "xpra.audio")
toggle_modules(audio_ENABLED and not (OSX or WIN32), "xpra.audio.pulseaudio")

toggle_packages(clipboard_ENABLED, "xpra.clipboard")
tace(clipboard_ENABLED, "xpra.gtk_common.gtk3.gdk_atoms", "gtk+-3.0")
toggle_packages(clipboard_ENABLED or gtk3_ENABLED, "xpra.gtk_common.gtk3")
tace(gtk3_ENABLED, "xpra.gtk_common.gtk3.gdk_bindings", "gtk+-3.0,pygobject-3.0")

tace(client_ENABLED or server_ENABLED, "xpra.buffers.cyxor", optimize=3)
tace(client_ENABLED or server_ENABLED or shadow_ENABLED, "xpra.rectangle", optimize=3)
tace(server_ENABLED or shadow_ENABLED, "xpra.server.cystats", optimize=3)
tace(server_ENABLED or shadow_ENABLED, "xpra.server.window.motion", optimize=3)
if pam_ENABLED:
    if pkg_config_ok("--exists", "pam", "pam_misc"):
        pam_kwargs = {"pkgconfig_names" : "pam,pam_misc"}
    else:
        pam_kwargs = {
            "extra_compile_args" : "-I" + find_header_file("/security", isdir=True),
            "extra_link_args"    : ("-lpam", "-lpam_misc"),
            }
    ace("xpra.server.pam", **pam_kwargs)

#platform:
tace(sd_listen_ENABLED, "xpra.platform.posix.sd_listen", "libsystemd")
tace(proc_ENABLED and proc_use_procps, "xpra.platform.posix.proc_procps", "libprocps", extra_compile_args = "-Wno-error")
tace(proc_ENABLED and proc_use_libproc, "xpra.platform.posix.proc_libproc", "libproc2", language="c++")

#codecs:
toggle_packages(enc_proxy_ENABLED, "xpra.codecs.proxy")

toggle_packages(nvidia_ENABLED, "xpra.codecs.nvidia")
CUDA_BIN = f"{share_xpra}/cuda"
if cuda_kernels_ENABLED:
    #find nvcc:
    from xpra.util import sorted_nicely  # pylint: disable=import-outside-toplevel
    path_options = os.environ.get("PATH", "").split(os.path.pathsep)
    if WIN32:
        external_includes.append("pycuda")
        nvcc_exe = "nvcc.exe"
        CUDA_DIR = os.environ.get("CUDA_DIR", "C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA")
        path_options += ["./cuda/bin/"]+list(reversed(sorted_nicely(glob.glob(f"{CUDA_DIR}\\*\\bin"))))
    else:
        nvcc_exe = "nvcc"
        path_options += ["/usr/local/cuda/bin", "/opt/cuda/bin"]
        path_options += list(reversed(sorted_nicely(glob.glob("/usr/local/cuda*/bin"))))
        path_options += list(reversed(sorted_nicely(glob.glob("/opt/cuda*/bin"))))
    options = [os.path.join(x, nvcc_exe) for x in path_options]
    #prefer the one we find on the $PATH, if any:
    v = shutil.which(nvcc_exe)
    if v and (v not in options):
        options.insert(0, v)
    nvcc_versions = {}
    def get_nvcc_version(command):
        if not os.path.exists(command):
            return None
        code, out, _ = get_status_output([command, "--version"])
        if code!=0:
            return None
        vpos = out.rfind(", V")
        if vpos>0:
            version = out[vpos+3:].split("\n")[0]
            version_str = f" version {version}"
        else:
            version = "0"
            version_str = " unknown version!"
        print(f"found CUDA compiler: {filename}{version_str}")
        return tuple(int(x) for x in version.split("."))
    for filename in options:
        vnum = get_nvcc_version(filename)
        if vnum:
            nvcc_versions[vnum] = filename
    nvcc_version = nvcc = None
    if nvcc_versions:
        #choose the most recent one:
        nvcc_version, nvcc = list(reversed(sorted(nvcc_versions.items())))[0]
        if len(nvcc_versions)>1:
            print(f" using version {nvcc_version} from {nvcc}")
    if cuda_kernels_ENABLED and (nvenc_ENABLED or nvjpeg_encoder_ENABLED):
        assert nvcc, "cannot find nvcc compiler!"
        def get_nvcc_args():
            nvcc_cmd = [nvcc, "-fatbin"]
            gcc_version = get_gcc_version()
            if not CC_is_clang() and gcc_version<(7, 5):
                print("gcc versions older than 7.5 are not supported!")
                for _ in range(5):
                    sleep(1)
                    print(".")
            if (8,1)<=gcc_version<(9, ):
                #GCC 8.1 has compatibility issues with CUDA 9.2,
                #so revert to C++03:
                nvcc_cmd.append("-std=c++03")
            #GCC 6 uses C++11 by default:
            else:
                nvcc_cmd.append("-std=c++11")
            if gcc_version>=(12, 0) or CC_is_clang():
                nvcc_cmd.append("--allow-unsupported-compiler")
            if nvcc_version>=(11, 5):
                nvcc_cmd += ["-arch=all",
                        "-Wno-deprecated-gpu-targets",
                        ]
                if nvcc_version>=(11, 6):
                    nvcc_cmd += ["-Xnvlink", "-ignore-host-info"]
                return nvcc_cmd
            #older versions, add every arch we know about:
            comp_code_options = []
            if nvcc_version>=(7, 5):
                comp_code_options.append((52, 52))
                comp_code_options.append((53, 53))
            if nvcc_version>=(8, 0):
                comp_code_options.append((60, 60))
                comp_code_options.append((61, 61))
                comp_code_options.append((62, 62))
            if nvcc_version>=(9, 0):
                comp_code_options.append((70, 70))
            if nvcc_version>=(10, 0):
                comp_code_options.append((75, 75))
            if nvcc_version>=(11, 0):
                comp_code_options.append((80, 80))
            if nvcc_version>=(11, 1):
                comp_code_options.append((86, 86))
            #if nvcc_version>=(11, 6):
            #    comp_code_options.append((87, 87))
            for arch, code in comp_code_options:
                nvcc_cmd.append(f"-gencode=arch=compute_{arch},code=sm_{code}")
            return nvcc_cmd
        nvcc_args = get_nvcc_args()
        #first compile the cuda kernels
        #(using the same cuda SDK for both nvenc modules for now..)
        kernels = []
        if nvenc_ENABLED:
            kernels += ["XRGB_to_NV12", "XRGB_to_YUV444", "BGRX_to_NV12", "BGRX_to_YUV444"]
        if nvjpeg_encoder_ENABLED:
            kernels += ["BGRX_to_RGB", "RGBX_to_RGB", "RGBA_to_RGBAP", "BGRA_to_RGBAP"]
        nvcc_commands = []
        for kernel in kernels:
            cuda_src = f"fs/share/xpra/cuda/{kernel}.cu"
            cuda_bin = f"fs/share/xpra/cuda/{kernel}.fatbin"
            if os.path.exists(cuda_bin) and (cuda_rebuild_ENABLED is False):
                continue
            reason = should_rebuild(cuda_src, cuda_bin)
            if not reason:
                continue
            print(f"rebuilding {kernel}: {reason}")
            kbuild_cmd = nvcc_args + ["-c", cuda_src, "-o", cuda_bin]
            print(f"CUDA compiling %s ({reason})" % kernel.ljust(16))
            print(" "+" ".join(f"{x!r}" for x in kbuild_cmd))
            nvcc_commands.append(kbuild_cmd)
        #parallel build:
        nvcc_errors = []
        def nvcc_compile(nvcc_cmd):
            c, stdout, stderr = get_status_output(nvcc_cmd)
            if c!=0:
                nvcc_errors.append(c)
                print(f"Error: failed to compile CUDA kernel {kernel}")
                print(f" using command: {nvcc_cmd}")
                print(stdout or "")
                print(stderr or "")
        nvcc_threads = []
        for cmd in nvcc_commands:
            from threading import Thread
            t = Thread(target=nvcc_compile, args=(cmd,))
            t.start()
            nvcc_threads.append(t)
        for t in nvcc_threads:
            if nvcc_errors:
                sys.exit(1)
            t.join()
        add_data_files(CUDA_BIN, [f"fs/share/xpra/cuda/{x}.fatbin" for x in kernels])
    if WIN32 and (nvjpeg_encoder_ENABLED or nvjpeg_decoder_ENABLED or nvenc_ENABLED or nvdec_ENABLED):
        assert nvcc_versions
        CUDA_BIN_DIR = os.path.dirname(nvcc)
        add_data_files("", glob.glob(f"{CUDA_BIN_DIR}/cudart64*dll"))
        #if pycuda is built with curand, add this:
        #add_data_files("", glob.glob(f"{CUDA_BIN_DIR}/curand64*dll"))
        if nvjpeg_encoder_ENABLED or nvjpeg_decoder_ENABLED:
            add_data_files("", glob.glob(f"{CUDA_BIN_DIR}/nvjpeg64*dll"))
if cuda_kernels_ENABLED or is_Debian() or is_Ubuntu():
    add_data_files(CUDA_BIN, ["fs/share/xpra/cuda/README.md"])

toggle_packages(nvfbc_ENABLED, "xpra.codecs.nvidia.nvfbc")
#platform: ie: `linux2` -> `linux`, `win32` -> `win`
fbcplatform = sys.platform.rstrip("0123456789")
tace(nvfbc_ENABLED, f"xpra.codecs.nvidia.nvfbc.fbc_capture_{fbcplatform}", "nvfbc", language="c++")
tace(nvenc_ENABLED, "xpra.codecs.nvidia.nvenc.encoder", "nvenc",
     extra_compile_args="-Wno-error=sign-compare" if get_gcc_version()<(8, ) else "")
tace(nvdec_ENABLED, "xpra.codecs.nvidia.nvdec.decoder", "nvdec,cuda")

toggle_packages(argb_ENABLED, "xpra.codecs.argb")
tace(argb_ENABLED, "xpra.codecs.argb.argb", optimize=3)
toggle_packages(evdi_ENABLED, "xpra.codecs.evdi")

tace(evdi_ENABLED, "xpra.codecs.evdi.capture", "evdi", language="c++")
toggle_packages(drm_ENABLED, "xpra.codecs.drm")
tace(drm_ENABLED, "xpra.codecs.drm.drm", "libdrm")
toggle_packages(enc_x264_ENABLED, "xpra.codecs.x264")
tace(enc_x264_ENABLED, "xpra.codecs.x264.encoder", "x264")
toggle_packages(openh264_ENABLED, "xpra.codecs.openh264")
tace(openh264_decoder_ENABLED, "xpra.codecs.openh264.decoder", "openh264", language="c++")
tace(openh264_encoder_ENABLED, "xpra.codecs.openh264.encoder", "openh264", language="c++")
toggle_packages(pillow_ENABLED, "xpra.codecs.pillow")
toggle_packages(webp_ENABLED, "xpra.codecs.webp")
tace(webp_ENABLED, "xpra.codecs.webp.encoder", "libwebp")
tace(webp_ENABLED, "xpra.codecs.webp.decoder", "libwebp")
toggle_packages(spng_decoder_ENABLED or spng_encoder_ENABLED, "xpra.codecs.spng")
tace(spng_decoder_ENABLED, "xpra.codecs.spng.decoder", "spng")
tace(spng_decoder_ENABLED, "xpra.codecs.spng.encoder", "spng")
toggle_packages(nvjpeg_encoder_ENABLED or nvjpeg_decoder_ENABLED, "xpra.codecs.nvidia.nvjpeg")
tace(nvjpeg_encoder_ENABLED or nvjpeg_decoder_ENABLED, "xpra.codecs.nvidia.nvjpeg.common", "cuda,nvjpeg")
tace(nvjpeg_encoder_ENABLED, "xpra.codecs.nvidia.nvjpeg.encoder", "cuda,nvjpeg")
tace(nvjpeg_decoder_ENABLED, "xpra.codecs.nvidia.nvjpeg.decoder","cuda,nvjpeg")
toggle_packages(jpeg_decoder_ENABLED or jpeg_encoder_ENABLED, "xpra.codecs.jpeg")
tace(jpeg_encoder_ENABLED, "xpra.codecs.jpeg.encoder", "libturbojpeg")
tace(jpeg_decoder_ENABLED, "xpra.codecs.jpeg.decoder", "libturbojpeg")
toggle_packages(avif_ENABLED, "xpra.codecs.avif")
tace(avif_ENABLED, "xpra.codecs.avif.encoder", "libavif")
tace(avif_ENABLED, "xpra.codecs.avif.decoder", "libavif")
#swscale and avcodec2 use libav_common/av_log:
toggle_packages(ffmpeg_ENABLED, "xpra.codecs.ffmpeg")
tace(ffmpeg_ENABLED, "xpra.codecs.ffmpeg.av_log", "libavutil")
tace(dec_avcodec2_ENABLED, "xpra.codecs.ffmpeg.decoder,xpra/codecs/ffmpeg/register_compat.c", "libavcodec,libavutil,libavformat")
tace(csc_swscale_ENABLED, "xpra.codecs.ffmpeg.colorspace_converter", "libswscale,libavutil")
tace(enc_ffmpeg_ENABLED, "xpra.codecs.ffmpeg.encoder", "libavcodec,libavformat,libavutil", extra_compile_args="-Wno-deprecated-declarations")
toggle_packages(csc_libyuv_ENABLED, "xpra.codecs.libyuv")
tace(csc_libyuv_ENABLED, "xpra.codecs.libyuv.colorspace_converter", "libyuv", language="c++")
toggle_packages(csc_cython_ENABLED, "xpra.codecs.csc_cython")
tace(csc_cython_ENABLED, "xpra.codecs.csc_cython.colorspace_converter", optimize=3)
toggle_packages(vpx_ENABLED, "xpra.codecs.vpx")
tace(vpx_ENABLED, "xpra.codecs.vpx.encoder", "vpx")
tace(vpx_ENABLED, "xpra.codecs.vpx.decoder", "vpx")
toggle_packages(gstreamer_ENABLED, "xpra.codecs.gstreamer")

toggle_packages(v4l2_ENABLED, "xpra.codecs.v4l2")
tace(v4l2_ENABLED, "xpra.codecs.v4l2.pusher")

#network:
#workaround this warning on MS Windows with Cython 3.0.0b1:
# "warning: comparison of integer expressions of different signedness: 'long unsigned int' and 'long int' [-Wsign-compare]"
#simply adding -Wno-error=sign-compare is not enough:
ECA_WIN32SIGN = ["-Wno-error"] if (WIN32 and cython_version==3) else []
toggle_packages(client_ENABLED or server_ENABLED, "xpra.net.protocol")
toggle_packages(websockets_ENABLED, "xpra.net.websockets", "xpra.net.websockets.headers")
tace(websockets_ENABLED, "xpra.net.websockets.mask", optimize=3, extra_compile_args=ECA_WIN32SIGN)
toggle_packages(rencodeplus_ENABLED, "xpra.net.rencodeplus.rencodeplus")
tace(rencodeplus_ENABLED, "xpra.net.rencodeplus.rencodeplus", optimize=3)
toggle_packages(bencode_ENABLED, "xpra.net.bencode")
toggle_packages(bencode_ENABLED and cython_bencode_ENABLED, "xpra.net.bencode.cython_bencode")
tace(cython_bencode_ENABLED, "xpra.net.bencode.cython_bencode", optimize=3)
toggle_packages(brotli_ENABLED, "xpra.net.brotli")
tace(brotli_ENABLED, "xpra.net.brotli.decompressor", extra_link_args="-lbrotlidec")
tace(brotli_ENABLED, "xpra.net.brotli.compressor", extra_link_args="-lbrotlienc")
toggle_packages(mdns_ENABLED, "xpra.net.mdns")
toggle_packages(quic_ENABLED, "xpra.net.quic")
toggle_packages(ssh_ENABLED, "xpra.net.ssh")
toggle_packages(http_ENABLED or quic_ENABLED, "xpra.net.http")
toggle_packages(rfb_ENABLED, "xpra.net.rfb")
toggle_packages(qrencode_ENABLED, "xpra.net.qrcode")
tace(qrencode_ENABLED, "xpra.net.qrcode.qrencode", extra_link_args="-lqrencode", extra_compile_args=ECA_WIN32SIGN)
tace(netdev_ENABLED, "xpra.platform.posix.netdev_query")
toggle_packages(vsock_ENABLED, "xpra.net.vsock")
tace(vsock_ENABLED, "xpra.net.vsock.vsock")
toggle_packages(lz4_ENABLED, "xpra.net.lz4")
tace(lz4_ENABLED, "xpra.net.lz4.lz4", "liblz4")


if ext_modules:
    from Cython.Build import cythonize
    compiler_directives = {
        "auto_pickle"           : False,
        "language_level"        : 3,
        "cdivision"             : True,
        "always_allow_keywords" : False,
        "unraisable_tracebacks" : True,
        }
    if annotate_ENABLED:
        from Cython.Compiler import Options
        Options.annotate = True
        Options.docstrings = False
        Options.buffer_max_dims = 3
    if strict_ENABLED and verbose_ENABLED:
        compiler_directives.update({
            #"warn.undeclared"       : True,
            #"warn.maybe_uninitialized" : True,
            "warn.unused"           : True,
            "warn.unused_result"    : True,
            })
    if cython_tracing_ENABLED:
        compiler_directives.update({
            "linetrace" : True,
            "binding" : True,
            "profile" : True,
            })

    nthreads = int(os.environ.get("NTHREADS", 0 if (debug_ENABLED or WIN32 or OSX or ARM or RISCV) else os.cpu_count()))
    setup_options["ext_modules"] = cythonize(ext_modules,
                                             nthreads=nthreads,
                                             gdb_debug=debug_ENABLED,
                                             compiler_directives=compiler_directives,
                                             )
if cmdclass:
    setup_options["cmdclass"] = cmdclass
if scripts:
    setup_options["scripts"] = scripts


def main():
    if OSX or WIN32 or debug_ENABLED:
        print()
        print("setup options:")
        if verbose_ENABLED:
            print("setup_options=%s" % (setup_options,))
        for k, v in setup_options.items():
            print(f"* {k}={v!r}")
        print("")

    setup(**setup_options)


if __name__ == "__main__":
    main()
