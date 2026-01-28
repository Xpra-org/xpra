#!/usr/bin/env python3

# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

##############################################################################
# FIXME: Cython.Distutils.build_ext leaves crud in the source directory.

import re
import sys
import shlex
import shutil
import os.path
import subprocess
from glob import glob
from time import sleep
from collections.abc import Sequence

if sys.version_info < (3, 10):
    raise RuntimeError("xpra no longer supports Python versions older than 3.10")

# required for PEP 517
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

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
from xpra.os_util import BITS, WIN32, OSX, LINUX, POSIX, NETBSD, FREEBSD, OPENBSD, getuid
from xpra.util.system import is_distribution_variant, get_linux_distribution, is_DEB, is_RPM
from xpra.util.io import load_binary_file, get_status_output

if BITS != 64:
    print(f"Warning: {BITS}-bit architecture, only 64-bits are officially supported")
    for _ in range(5):
        sleep(1)
        print(".")


def is_Fedora() -> bool:
    return is_distribution_variant("Fedora")


def is_openSUSE() -> bool:
    return is_distribution_variant("openSUSE")


#*******************************************************************************
print(" ".join(sys.argv))

#*******************************************************************************
# build options, these may get modified further down..
#
data_files = []
modules = []
packages = []       # used by `py2app`
excludes = []       # only used by `cx_Freeze` on win32
ext_modules = []
cmdclass = {}
scripts = []
description = "multi-platform screen and application forwarding system"
long_description = "".join(
    "Xpra is a multi platform persistent remote display server and client for "
    "forwarding applications and desktop screens. Also known as 'screen for X11'."
)
url = "https://xpra.org/"


XPRA_VERSION = xpra.__version__
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
    def write_PKG_INFO() -> None:
        with open("PKG-INFO", "wb") as f:
            pkg_info_values = setup_options.copy()
            pkg_info_values |= {
                "metadata_version": "1.1",
                "summary": description,
                "home_page": url,
            }
            for k in (
                "Metadata-Version", "Name", "Version", "Summary", "Home-page",
                "Author", "Author-email", "License", "Download-URL", "Description"
            ):
                v = pkg_info_values[k.lower().replace("-", "_")]
                f.write(("%s: %s\n" % (k, v)).encode())
    write_PKG_INFO()
    sys.exit(0)


print("Xpra version %s" % XPRA_VERSION)
print("Python version %s" % (".".join(str(v) for v in sys.version_info[:3])))
#*******************************************************************************
# Most of the options below can be modified on the command line
# using --with-OPTION or --without-OPTION
# only the default values are specified here:
#*******************************************************************************


PKG_CONFIG = os.environ.get("PKG_CONFIG", "pkg-config")


def check_pkgconfig() -> None:
    v = get_status_output([PKG_CONFIG, "--version"])
    has_pkg_config = v[0] == 0 and v[1]
    if not has_pkg_config:
        print("WARNING: pkg-config not found!")


check_pkgconfig()

for arg in list(sys.argv):
    if arg.startswith("--pkg-config-path="):
        pcp = arg[len("--pkg-config-path="):]
        pcps = os.environ.get("PKG_CONFIG_PATH", "").split(os.path.pathsep) + [pcp]
        os.environ["PKG_CONFIG_PATH"] = os.path.pathsep.join(x for x in pcps if x)
        print("using PKG_CONFIG_PATH="+os.environ["PKG_CONFIG_PATH"])
        sys.argv.remove(arg)


def no_pkgconfig(*_pkgs_options, **_ekw) -> dict:
    return {}


def pkg_config_ok(*args) -> bool:
    return get_status_output([PKG_CONFIG] + [str(x) for x in args])[0] == 0


def pkg_config_exists(*names: str) -> bool:
    return pkg_config_ok("--exists", *names)


def pkg_config_version(req_version: str, pkgname: str) -> bool:
    r, out, _ = get_status_output([PKG_CONFIG, "--modversion", pkgname])
    if r != 0 or not out:
        return False
    out = out.rstrip("\n\r").split(" ")[0]  # ie: "0.155.2917 0a84d98" -> "0.155.2917"
    # workaround for libx264 invalid version numbers:
    # ie: "0.163.x" or "0.164.3094M"
    while out[-1].isalpha() or out[-1]==".":
        out = out[:-1]
    # pylint: disable=import-outside-toplevel
    try:
        from packaging.version import parse
        return parse(out) >= parse(req_version)
    except ImportError:
        from distutils.version import LooseVersion  # pylint: disable=deprecated-module
        return LooseVersion(out) >= LooseVersion(req_version)


argv = sys.argv + list(filter(len, os.environ.get("XPRA_EXTRA_BUILD_ARGS", "").split(" ")))
DEFAULT = True
if "--minimal" in argv:
    argv.remove("--minimal")
    DEFAULT = False
skip_build = "--skip-build" in argv
ARCH = os.environ.get("MSYSTEM_CARCH", "") or get_status_output(["uname", "-m"])[1].strip("\n\r")
ARM = ARCH.startswith("arm") or ARCH.startswith("aarch")
RISCV = ARCH.startswith("riscv")
print(f"ARCH={ARCH}")
TIMEOUT = 60
if ARM or RISCV:
    # arm64 and riscv builds run on emulated CPU, very slowly
    TIMEOUT = 600


INCLUDE_DIRS = os.environ.get("INCLUDE_DIRS", os.path.join(sys.prefix, "include")).split(os.pathsep)
if os.environ.get("INCLUDE_DIRS", None) is None and not WIN32:
    # sys.prefix is where the Python interpreter is installed. This may be very different from where
    # the C/C++ headers are installed. So do some guessing here:

    ALWAYS_INCLUDE_DIRS = ["/usr/include", "/usr/local/include"]
    for d in ALWAYS_INCLUDE_DIRS:
        if os.path.isdir(d) and d not in INCLUDE_DIRS:
            INCLUDE_DIRS.append(d)

print("INCLUDE_DIRS=%s" % (INCLUDE_DIRS, ))

shadow_ENABLED = DEFAULT
server_ENABLED = DEFAULT
rfb_ENABLED = DEFAULT
quic_ENABLED = DEFAULT
ssh_ENABLED = DEFAULT
ssl_ENABLED = DEFAULT
http_ENABLED = DEFAULT
service_ENABLED = LINUX and server_ENABLED
sd_listen_ENABLED = POSIX and pkg_config_exists("libsystemd")
proxy_ENABLED = DEFAULT
client_ENABLED = DEFAULT
qt6_client_ENABLED = False
pyglet_client_ENABLED = False
tk_client_ENABLED = False
scripts_ENABLED = not WIN32
cython_ENABLED = DEFAULT
cython_shared_ENABLED = True
cythonize_more_ENABLED = False
cython_tracing_ENABLED = False
modules_ENABLED = DEFAULT
data_ENABLED = DEFAULT


def find_header_file(name: str, isdir=False) -> str:
    matches = [v for v in
               [os.path.join(d, name) for d in INCLUDE_DIRS]
               if os.path.exists(v) and os.path.isdir(v) == isdir]
    if not matches:
        return ""
    return matches[0]


def has_header_file(name, isdir=False) -> bool:
    return bool(find_header_file(name, isdir))


x11_ENABLED = DEFAULT and not WIN32 and not OSX
wayland_client_ENABLED = not WIN32 and not OSX and pkg_config_exists("wayland-client")
wayland_server_ENABLED = not WIN32 and not OSX and pkg_config_exists("wlroots-0.19") and pkg_config_exists("wayland-server")
xinput_ENABLED = x11_ENABLED
uinput_ENABLED = x11_ENABLED
dbus_ENABLED = DEFAULT and (x11_ENABLED or WIN32) and not OSX
gtk_x11_ENABLED = DEFAULT and not WIN32 and not OSX
gtk3_ENABLED = DEFAULT and client_ENABLED
ism_ext_ENABLED = DEFAULT and gtk3_ENABLED and data_ENABLED
opengl_ENABLED = DEFAULT and client_ENABLED
has_pam_headers = has_header_file("security", isdir=True) or pkg_config_exists("pam", "pam_misc")
pam_ENABLED = DEFAULT and (server_ENABLED or proxy_ENABLED) and LINUX and has_pam_headers
peercred_ENABLED = OSX or sys.platform.lower().find("bsd") >= 0

proc_use_procps         = LINUX and has_header_file("proc/procps.h")
proc_use_libproc        = LINUX and has_header_file("libproc2/pids.h")
proc_ENABLED            = LINUX and (proc_use_procps or proc_use_libproc)

xdg_open_ENABLED        = (LINUX or FREEBSD) and DEFAULT
netdev_ENABLED          = LINUX and DEFAULT
vsock_ENABLED           = LINUX and has_header_file("linux/vm_sockets.h")
lz4_ENABLED             = DEFAULT
rencodeplus_ENABLED     = DEFAULT
brotli_ENABLED          = DEFAULT and has_header_file("brotli/decode.h") and has_header_file("brotli/encode.h")
cityhash_ENABLED        = False  # has_header_file("/city.h")
qrencode_ENABLED        = DEFAULT and has_header_file("qrencode.h")
clipboard_ENABLED       = DEFAULT
Xdummy_ENABLED          = None if POSIX else False  # None means auto-detect
Xdummy_wrapper_ENABLED  = None if POSIX else False  # None means auto-detect
audio_ENABLED           = DEFAULT
printing_ENABLED        = DEFAULT
crypto_ENABLED          = DEFAULT
mdns_ENABLED            = DEFAULT
mmap_ENABLED            = DEFAULT
websockets_ENABLED      = DEFAULT
websockets_browser_cookie_ENABLED = DEFAULT
yaml_ENABLED            = DEFAULT

codecs_ENABLED          = DEFAULT
encoders_ENABLED        = codecs_ENABLED
decoders_ENABLED        = codecs_ENABLED
enc_x264_ENABLED        = DEFAULT and pkg_config_version("0.155", "x264")
openh264_ENABLED        = DEFAULT and pkg_config_version("2.0", "openh264")
openh264_decoder_ENABLED = openh264_ENABLED
openh264_encoder_ENABLED = openh264_ENABLED
aom_ENABLED             = DEFAULT and pkg_config_version("3.0", "aom")
pillow_ENABLED          = DEFAULT
pillow_encoder_ENABLED  = pillow_ENABLED
pillow_decoder_ENABLED  = pillow_ENABLED
argb_ENABLED            = DEFAULT
argb_encoder_ENABLED    = argb_ENABLED
# some platforms have "spng.pc", others use "libspng.pc"..
spng_pc = "libspng" if pkg_config_exists("libspng") else "spng"
spng_decoder_ENABLED    = DEFAULT and pkg_config_version("0.6", spng_pc)
spng_encoder_ENABLED    = DEFAULT and pkg_config_version("0.7", spng_pc)
webp_ENABLED            = DEFAULT and pkg_config_version("0.5", "libwebp")
webp_encoder_ENABLED    = webp_ENABLED
webp_decoder_ENABLED    = webp_ENABLED
jpeg_encoder_ENABLED    = DEFAULT and pkg_config_version("1.2", "libturbojpeg")
jpeg_decoder_ENABLED    = DEFAULT and pkg_config_version("1.4", "libturbojpeg")
avif_ENABLED            = DEFAULT and pkg_config_version("0.9", "libavif") and not OSX
avif_encoder_ENABLED    = avif_ENABLED
avif_decoder_ENABLED    = avif_ENABLED
vpx_ENABLED             = DEFAULT and pkg_config_version("1.7", "vpx") and BITS==64
vpx_encoder_ENABLED     = vpx_ENABLED
vpx_decoder_ENABLED     = vpx_ENABLED
amf_ENABLED             = pkg_config_version("1.0", "amf") or has_header_file("AMF/components/VideoEncoderVCE.h")
amf_encoder_ENABLED     = amf_ENABLED
remote_encoder_ENABLED  = DEFAULT
# opencv currently broken on 32-bit windows (crashes on load):
webcam_ENABLED          = DEFAULT and not OSX and not WIN32
notifications_ENABLED   = DEFAULT
keyboard_ENABLED        = DEFAULT
v4l2_ENABLED            = DEFAULT and (not WIN32 and not OSX and not FREEBSD and not OPENBSD)
evdi_ENABLED            = DEFAULT and LINUX and pkg_config_version("1.10", "evdi")
drm_ENABLED             = DEFAULT and (LINUX or FREEBSD) and pkg_config_version("2.4", "libdrm")
csc_cython_ENABLED      = DEFAULT
nvidia_ENABLED          = DEFAULT and not OSX and BITS==64 and not RISCV
nvjpeg_encoder_ENABLED  = nvidia_ENABLED and pkg_config_exists("nvjpeg")
nvjpeg_decoder_ENABLED  = nvidia_ENABLED and pkg_config_exists("nvjpeg")
nvenc_ENABLED           = nvidia_ENABLED and pkg_config_version("10", "nvenc")
nvdec_ENABLED           = False
nvfbc_ENABLED           = nvidia_ENABLED and not ARM and pkg_config_exists("nvfbc")
cuda_kernels_ENABLED    = nvidia_ENABLED and (nvenc_ENABLED or nvjpeg_encoder_ENABLED)
cuda_rebuild_ENABLED    = None if (nvidia_ENABLED and not WIN32) else False
csc_libyuv_ENABLED      = DEFAULT and pkg_config_exists("libyuv")
gstreamer_ENABLED       = DEFAULT
gstreamer_audio_ENABLED = gstreamer_ENABLED
gstreamer_video_ENABLED = gstreamer_ENABLED and not OSX
example_ENABLED         = DEFAULT
win32_tools_ENABLED     = WIN32 and DEFAULT

# Cython / gcc / packaging build options:
docs_ENABLED            = DEFAULT and shutil.which("pandoc")
pandoc_lua_ENABLED      = DEFAULT
annotate_ENABLED        = False
warn_ENABLED            = True
strict_ENABLED          = False
Os_ENABLED              = False
PIC_ENABLED             = not WIN32     # ming32 moans that it is always enabled already
debug_ENABLED           = False
verbose_ENABLED         = False
bundle_tests_ENABLED    = False
tests_ENABLED           = False
rebuild_ENABLED         = not skip_build


# allow some of these flags to be modified on the command line:
ENCODER_SWITCHES = [
    "enc_x264", "openh264_encoder", "nvenc", "nvjpeg_encoder",
    "vpx_encoder", "webp_encoder", "pillow_encoder",
    "amf_encoder",
    "spng_encoder", "jpeg_encoder", "avif_encoder",
    "argb_encoder",
    "remote_encoder",
]
DECODER_SWITCHES = [
    "openh264_decoder",
    "nvdec", "nvjpeg_decoder",
    "vpx_decoder", "webp_decoder", "pillow_decoder",
    "spng_decoder", "jpeg_decoder", "avif_decoder",
]
CODEC_SWITCHES = ENCODER_SWITCHES + DECODER_SWITCHES + [
    "cuda_kernels", "cuda_rebuild",
    "nvidia", "nvfbc",
    "openh264",
    "vpx", "webp",
    "pillow",
    "avif", "argb",
    "v4l2", "evdi", "drm",
    "csc_cython", "csc_libyuv",
    "gstreamer", "gstreamer_audio", "gstreamer_video",
]
# some switches can control multiple switches:
SWITCH_ALIAS = {
    "codecs": ["codecs"] + CODEC_SWITCHES,
    "encoders": ENCODER_SWITCHES,
    "decoders": DECODER_SWITCHES,
    "argb" : ("argb_encoder", ),
    "pillow": ("pillow_encoder", "pillow_decoder"),
    "vpx" : ("vpx_encoder", "vpx_decoder"),
    "amf": ("amf_encoder", ),
    "webp" : ("webp_encoder", "webp_decoder"),
    "avif": ("avif_encoder", "avif_decoder"),
    "openh264": ("openh264", "openh264_decoder", "openh264_encoder"),
    "nvidia": ("nvidia", "nvenc", "nvdec", "nvfbc", "nvjpeg_encoder", "nvjpeg_decoder", "cuda_kernels"),
    "gstreamer": ("gstreamer_audio", "gstreamer_video"),
    "cython": (
        "cython", "codecs",
        "server", "client", "shadow",
        "rencodeplus", "brotli", "cityhash", "qrencode", "websockets", "netdev", "vsock",
        "lz4",
        "x11", "gtk_x11",
        "pam", "sd_listen", "proc",
        "peercred",
    ),
}

SWITCHES = []
# add the ones we have aliases for:
for sw, deps in SWITCH_ALIAS.items():
    SWITCHES += [sw] + list(deps)
for sw in CODEC_SWITCHES:
    if sw not in SWITCHES:
        SWITCHES.append(sw)

SWITCHES += [
    "cython_tracing", "cythonize_more", "cython_shared",
    "modules", "data",
    "brotli", "cityhash", "qrencode",
    "vsock", "netdev", "proc", "mdns", "lz4", "mmap",
    "clipboard",
    "scripts",
    "server", "client", "dbus", "x11", "xinput", "uinput", "sd_listen",
    "gtk_x11", "service",
    "gtk3", "example",
    "wayland_client", "wayland_server",
    "qt6_client", "pyglet_client", "tk_client",
    "ism_ext",
    "pam", "xdg_open", "peercred",
    "audio", "opengl", "printing", "webcam", "notifications", "keyboard",
    "rebuild",
    "docs", "pandoc_lua",
    "annotate", "warn", "strict", "Os",
    "shadow", "proxy", "rfb", "quic", "http", "ssh", "ssl",
    "debug", "PIC",
    "Xdummy", "Xdummy_wrapper", "verbose", "tests", "bundle_tests",
    "win32_tools", "websockets_browser_cookie",
    "yaml",
]
SWITCHES = list(sorted(set(SWITCHES)))


install = ""
rpath = ""
ssl_cert = ""
ssl_key = ""
share_xpra = os.path.join("share", "xpra")
filtered_args = []


def filter_argv() -> None:
    for arg in argv:
        matched = False
        for x in ("rpath", "ssl-cert", "ssl-key", "install", "share-xpra", "dummy-driver-version"):
            varg = f"--{x}="
            if arg.startswith(varg):
                value = arg[len(varg):]
                globals()[x.replace("-", "_")] = value
                # remove these arguments from sys.argv,
                # except for --install=PATH
                matched = x!="install"
                break
        if matched:
            continue
        for x in SWITCHES:
            with_str = f"--with-{x}"
            without_str = f"--without-{x}"
            yes_str = f"--{x}"
            no_str = f"--no-{x}"
            var_names = list(SWITCH_ALIAS.get(x, [x]))
            # recurse once, so an alias can container aliases:
            for v in tuple(var_names):
                var_names += list(SWITCH_ALIAS.get(v, []))
            for with_value_str in (with_str, yes_str):
                if arg.startswith(with_value_str+"="):
                    for var in var_names:
                        globals()[f"{var}_ENABLED"] = arg[len(with_value_str)+1:]
                    matched = True
                    break
            if arg in (with_str, yes_str):
                for var in var_names:
                    globals()[f"{var}_ENABLED"] = True
                matched = True
                break
            if arg in (without_str, no_str):
                for var in var_names:
                    globals()[f"{var}_ENABLED"] = False
                matched = True
                break
        if not matched:
            filtered_args.append(arg)


filter_argv()
# enable any codec groups with at least one codec enabled:
# ie: enable "nvidia" if "nvenc" is enabled
for group, items in SWITCH_ALIAS.items():
    if globals()[f"{group}_ENABLED"]:
        # already enabled
        continue
    for item in items:
        if globals()[f"{item}_ENABLED"]:
            print(f"enabling {group!r} for {item!r}")
            globals()[f"{group}_ENABLED"] = True
            break
sys.argv = filtered_args

if not install and WIN32:
    MINGW_PREFIX = os.environ.get("MINGW_PREFIX", "")
    install = MINGW_PREFIX or sys.prefix or "dist"


def should_rebuild(src_file: str, bin_file: str) -> str:
    if not os.path.exists(bin_file):
        return "no file"
    if rebuild_ENABLED and os.path.getctime(bin_file) < os.path.getctime(src_file):
        return "binary file is out of date"
    return ""


def convert_doc(fsrc: str, fdst: str, fmt="html", force=False) -> None:
    bsrc = os.path.basename(fsrc)
    bdst = os.path.basename(fdst)
    if not force and not should_rebuild(fsrc, fdst):
        return
    print(f"  {bsrc:<30} -> {bdst}")
    pandoc = os.environ.get("PANDOC", "") or shutil.which("pandoc")
    if WIN32 and not pandoc:
        pandoc = "/c/Program Files/Pandoc/pandoc.exe"
    if not os.path.exists(pandoc):
        raise RuntimeError("`pandoc` was not found!")
    cmd = [pandoc, "--from", "commonmark", "--to", fmt, "-o", fdst, fsrc]
    if fmt=="html" and pandoc_lua_ENABLED:
        cmd += ["--lua-filter", "./fs/bin/links-to-html.lua"]
    r = subprocess.Popen(cmd).wait(TIMEOUT)
    assert r==0, "'%s' returned %s" % (" ".join(cmd), r)


def convert_doc_dir(src, dst, fmt="html", force=False) -> None:
    print(f"* {src:<20} -> {dst}")
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
            print(f"  {fsrc:<50} -> {fdst} (%s)" % oct(0o644))
            os.makedirs(name=dst, mode=0o755, exist_ok=True)
            data = load_binary_file(fsrc)
            with open(fdst, "wb") as f:
                f.write(data)
                os.chmod(fdst, 0o644)
        else:
            print(f"ignoring {fsrc!r}")


def convert_docs(fmt="html") -> None:
    paths = [x for x in sys.argv[2:] if not x.startswith("--")]
    if len(paths)==1 and os.path.isdir(paths[0]):
        convert_doc_dir("docs", paths[0])
    elif paths:
        for x in paths:
            convert_doc(x, f"build/{x}", fmt=fmt)
    else:
        convert_doc_dir("docs", "build/docs", fmt=fmt)


def du(path: str) -> int:
    if os.path.isfile(path):
        return os.path.getsize(path)
    return sum(os.path.getsize(f) for f in glob(f"{path}/**", recursive=True) if os.path.isfile(f))


def build_package() -> int:
    if not LINUX:
        raise RuntimeError("packaging is not implemented here yet, use platform specific scripts instead")
    print("* installing beta repository tools and libraries")
    install_repo("-beta")
    print("* installing dev-env")
    from subprocess import run
    cmd = install_dev_env_command()
    if not cmd:
        return 1
    if os.geteuid() != 0:
        cmd.insert(0, "sudo")
    if run(cmd).returncode != 0:
        raise RuntimeError("failed to install dev-env using %r" % shlex.join(cmd))
    print("* creating source archive")
    cmd = ["python3", "./setup.py", "sdist", "--formats=xztar"]
    if run(cmd).returncode != 0:
        raise RuntimeError("failed to install create sdist source using %r" % shlex.join(cmd))
    src_xz = f"./dist/xpra-{XPRA_VERSION}.tar.xz"
    if not os.path.exists(src_xz):
        raise RuntimeError(f"cannot find {src_xz!r}")
    size = du(src_xz)
    print(f"{src_xz}: {size}B")

    if is_RPM():
        rpmbuild_dir = os.path.expanduser("~/rpmbuild")
        if not os.path.exists(rpmbuild_dir):
            os.mkdir(rpmbuild_dir)
        sources_dir = os.path.join(rpmbuild_dir, "SOURCES")
        if not os.path.exists(sources_dir):
            os.mkdir(sources_dir)
        shutil.copy(src_xz, sources_dir)
        cmd = ["rpmbuild", "-ba", "./packaging/rpm/xpra.spec"]
        if run(cmd).returncode != 0:
            raise RuntimeError("failed to generate RPM package with %r" % shlex.join(cmd))
        return 0

    if is_DEB():
        deb_src = f"../xpra-{XPRA_VERSION}.orig.tar.xz"
        shutil.copy(src_xz, deb_src)
        cmd = ["debuild", "-us", "-uc", "-b"]
        if run(cmd).returncode != 0:
            raise RuntimeError("failed to generate RPM package with %r" % shlex.join(cmd))
        return 0
    print("sorry, your distribution is not supported by this subcommand")
    return 1


def install_dev_env() -> int:
    cmd = install_dev_env_command()
    if not cmd:
        return 1
    if os.geteuid() != 0:
        cmd.insert(0, "sudo")
    from shutil import which
    exe = which(cmd[0])
    os.execv(exe, cmd)


def install_dev_env_command() -> list[str]:
    if not LINUX:
        print(f"'dev-env' subcommand is not supported on {sys.platform!r}")
        return []

    def add_flags(cmd: list[str], flag_to_pkgs: dict[str, Sequence[str]]) -> list[str]:
        for flag_str, pkg_names in flag_to_pkgs.items():
            flags = flag_str.split("|")
            if any(globals()[f"{flag}_ENABLED"] for flag in flags):
                cmd += list(set(pkg_names))
        return cmd

    if is_RPM() and not is_openSUSE():
        py3 = os.environ.get("PYTHON3", "")
        if not py3:
            py3 = "python3"
            # is this default python?
            exit_code, out, _ = get_status_output(["python3", "--version"])
            if exit_code == 0:
                # ie: out = "Python 3.12.4"
                try:
                    default_python_version = tuple(int(nstr) for nstr in out.split(" ", 1)[-1].split(".", 2))
                except ValueError:
                    pass
                else:
                    if len(default_python_version) >= 2 and sys.version_info[:2] != default_python_version[:2]:
                        # this is not the default python interpreter!
                        py3 = "python%i.%i" % sys.version_info[:2]
        if any(is_distribution_variant(x) for x in (
            "RedHat", "AlmaLinux", "Rocky Linux", "CentOS", "Oracle Linux",
        )):
            print("Note: you may need to enable the 'crb' and 'powertools' repositories, ie:")
            print(" dnf-3 config-manager --set-enabled crb")

        flag_to_pkgs = {
            "modules": (
                # generic build requirements:
                "tar", "grep", "gawk", "gcc", "gcc-c++", "pkgconfig",
                "which", "coreutils",
                f"{py3}-cryptography", ),
            "cython": (f"{py3}-devel", f"{py3}-cython", f"{py3}-setuptools", "xxhash-devel", ),
            "lz4": ("pkgconfig(liblz4)", ),
            "brotli": ("pkgconfig(libbrotlidec)", "pkgconfig(libbrotlienc)", ),
            "qrencode": ("pkgconfig(libqrencode)", ),
            "gtk3": (
                f"{py3}-gobject", "pkgconfig(pygobject-3.0)", "pkgconfig(py3cairo)", "pkgconfig(gtk+-3.0)",
                "pkgconfig(gobject-introspection-1.0)",
            ),
            "nvidia|tests": (f"{py3}-numpy", ),
            "drm": ("pkgconfig(libdrm)", ),
            "vpx": ("pkgconfig(vpx)", ),
            "webp": ("pkgconfig(libwebp)", ),
            "jpeg_decoder|jpeg_encoder": ("pkgconfig(libturbojpeg)", ),
            "csc_libyuv": ("pkgconfig(libyuv)", ),
            "openh264": ("pkgconfig(openh264)", ),
            "spng_decoder|spng_encoder": ("pkgconfig(spng)", ),
            "evdi": ("libevdi-devel", ),
            "enc_x264": ("pkgconfig(x264)", ),
            "avif": ("pkgconfig(libavif)", ),
            "nvidia": ("cuda", ),
            "docs": ("pandoc", ),
            "tests": ("gstreamer1", "gstreamer1-plugins-good", "pulseaudio", "pulseaudio-utils", "desktop-file-utils", "xclip", ),
            "x11": ("pkgconfig(xkbfile)", "pkgconfig(xtst)", "pkgconfig(xcomposite)",
                    "pkgconfig(xdamage)", "pkgconfig(xres)", "pkgconfig(xfixes)", "pkgconfig(xrandr)",
                    ),
            "Xdummy": ("xorg-x11-drv-dummy", ),
            "proc": ("procps-ng-devel" if is_Fedora() else "pkgconfig(libprocps)", ),
            "sd_listen": ("pkgconfig(libsystemd)", ),
            "pam": ("pam-devel", ),
        }
        if py3 == "python3":
            # we don't have a spec file for this one, can only install the default python3 package:
            flag_to_pkgs["printing"] = (f"{py3}-cups", )
        return add_flags(["dnf", "install"], flag_to_pkgs)
    if is_DEB():
        flag_to_pkgs = {
            "modules": (
                "python3-dev",
                "pkgconf", "xz-utils", "lsb-release",
            ),
            "cython": ("gcc", "cython3", "libxxhash-dev", ),
            "x11": ("libx11-dev", "libxcomposite-dev", "libxdamage-dev",
                    "libxtst-dev", "libxkbfile-dev", "libxres-dev",
                    "xvfb",
                    ),
            "drm": ("libdrm-dev", ),
            "evdi": ("libevdi0-dev", ),
            "avif": ("libavif-dev", ),
            "csc_libyuv": ("libyuv-dev", ),
            "vpx": ("libvpx-dev", ),
            "enc_x264": ("libx264-dev", ),
            "openh264": ("libopenh264-dev", ),
            "webp": ("libwebp-dev", ),
            "jpeg_decoder|jpeg_encoder": ("libturbojpeg-dev", ),
            "spng_decoder|spng_encoder": ("libspng-dev", ),
            "gtk3": ("libgtk-3-dev", "python3-cairo-dev", "python-gi-dev"),
            "sd_listen": ("python-gi-dev", ),
            "pam": ("libpam0g-dev", ),
            "proc": ("libproc2-dev", ),
            "lz4": ("liblz4-dev", ),
            "brotli": ("libbrotli-dev", ),
            "qrencode": ("libqrencode-dev", ),
            "docs": ("pandoc", ),
        }
        return add_flags(["apt", "install"], flag_to_pkgs)
    distro = get_linux_distribution()
    print("'dev-env' subcommand is not supported on your distribution")
    print(" %s" % " ".join(distro))
    print(" please submit a patch")
    return []


def install_repo(repo_variant="") -> None:
    if not LINUX:
        print(f"'install{repo_variant}-repo' subcommand is not supported on {sys.platform!r}")
        sys.exit(1)
    distro = get_linux_distribution()
    setup_cmds: list[list[str]] = []

    DEB_VARIANTS = (
        "focal", "jammy", "noble", "oracular", "plucky",
        "bullseye", "bookworm", "trixie", "sid",
    )

    variant = distro[2]  # ie: "noble"
    if distro[0] in ("Debian", "Ubuntu") or variant in DEB_VARIANTS:
        if variant not in DEB_VARIANTS:
            raise ValueError(f"Debian / Ubuntu variant {variant} is not supported by this subcommand")
        to = "/etc/apt/sources.list.d/"
        setup_cmds.append(["wget", "-O", "/usr/share/keyrings/xpra.asc", "https://xpra.org/xpra.asc"])
        setup_cmds.append(["chmod", "644", "/usr/share/keyrings/xpra.asc"])
        if repo_variant != "-lts":
            setup_cmds.append(["cp", f"packaging/repos/{variant}/xpra.sources", to])
        if repo_variant:
            setup_cmds.append(["cp", f"packaging/repos/{variant}/xpra{repo_variant}.sources", to])

    else:
        # assume RPM

        def add_epel() -> None:
            setup_cmds.append(["dnf-3", "config-manager", "--set-enabled", "crb"])
            setup_cmds.append(["dnf-3", "install", "epel-release"])

        if is_Fedora():
            variant = "Fedora"
            release = get_status_output(["rpm", "-E", "%fedora"])
            assert release[0] == 0, "failed to run `rpm -E %fedora`"
            release_name = release[1].strip("\n\r")
            setup_cmds.append(["dnf-3", "install", f"https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-{release_name}.noarch.rpm"])
            # setup_cmds.append(["dnf", "install", f"https://mirrors.rpmfusion.org/free/fedora/rpmfusion-nonfree-release-{release_name}.noarch.rpm"])
            setup_cmds.append(["dnf-3", "config-manager", "--set-enabled", "fedora-cisco-openh264"])
        elif is_distribution_variant("RedHat") or is_distribution_variant("AlmaLinux"):
            variant = "almalinux"
            add_epel()
        elif is_distribution_variant("Rocky Linux"):
            variant = "rockylinux"
            add_epel()
        elif is_distribution_variant("Oracle Linux"):
            variant = "oraclelinux"
            add_epel()
        elif is_distribution_variant("CentOS"):
            variant = "CentOS-Stream"
            add_epel()
        else:
            raise ValueError(f"unsupported distribution {distro}")
        to = "/etc/yum.repos.d/"
        if repo_variant != "-lts":
            setup_cmds.append(["cp", f"packaging/repos/{variant}/xpra.repo", to])
        if repo_variant:
            setup_cmds.append(["cp", f"packaging/repos/{variant}/xpra{repo_variant}.repo", to])

    for cmd in setup_cmds:
        if os.geteuid() != 0:
            cmd.insert(0, "sudo")
        subprocess.run(cmd)


def show_help() -> None:
    setup()
    print("Xpra specific build and install switches:")
    for x in SWITCHES:
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

if "doc" in sys.argv:
    convert_docs("html")
    sys.exit(0)

if "pdf-doc" in sys.argv:
    convert_docs("pdf")
    sys.exit(0)

if "dev-env" in sys.argv:
    install_dev_env()
    sys.exit(0)

if "package" in sys.argv:
    sys.exit(build_package())

if "install-repo" in sys.argv:
    install_repo()
    sys.exit(0)

if "install-beta-repo" in sys.argv:
    install_repo("-beta")
    sys.exit(0)

if "install-lts-repo" in sys.argv:
    install_repo("-lts")
    sys.exit(0)

if len(sys.argv) < 2:
    print(f"{sys.argv[0]} arguments are missing!")
    print("usage:")
    for subcommand in (
        "--help",
        "clean",
        "sdist",
        "pkg-info",
        "build",
        "install",
        "doc",
        "pdf-doc",
        "dev-env",
        "package",
        "install-repo",
        "install-lts-repo",
        "install-beta-repo",
        "unittests",
    ):
        print(f"{sys.argv[0]} {subcommand}")
    sys.exit(1)

if sys.argv[1] == "unittests":
    os.execv("./tests/unittests/run", ["run"] + sys.argv[2:])
assert "unittests" not in sys.argv, sys.argv


if "clean" not in sys.argv and "sdist" not in sys.argv:
    def show_switch_info() -> None:
        switches_info = {}
        for x in SWITCHES:
            switches_info[x] = globals()[f"{x}_ENABLED"]
        print("build switches:")
        for k in SWITCHES:
            v = switches_info[k]
            print("* %s : %s" % (str(k).ljust(20), {None : "Auto", True : "Yes", False : "No"}.get(v, v)))
    show_switch_info()

    def check_sane_defaults() -> None:
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

    check_sane_defaults()


cythonize_kwargs = {}
CYSHARED = "./xpra/cyshared.c"
CYSHARED_EXT = "xpra.cyshared"


def check_cython3() -> None:
    try:
        import cython
        print(f"found Cython version {cython.__version__}")
        version = tuple(int(vpart) for vpart in cython.__version__.split('.')[:2])
    except (ValueError, ImportError):
        print("WARNING: unable to detect Cython version")
    else:
        global cython_shared_ENABLED
        if version < (3, ):
            print("*******************************************")
            print("please switch to Cython 3.1.x")
            print(f" version {version} is not supported")
            print("*******************************************")
            sys.exit(1)
        if version < (3, 1):
            print("please consider upgrading to Cython 3.1.x")
            cython_shared_ENABLED = False


check_cython3()


#*******************************************************************************
# default sets:
external_includes = ["hashlib", "ctypes", "platform"]
if gtk3_ENABLED or audio_ENABLED:
    external_includes += ["gi"]

external_excludes = [
    # Tcl/Tk
    "Tkconstants", "tkinter", "tcl",
    # PIL bits that import TK:
    "PIL._tkinter_finder", "_imagingtk", "PIL._imagingtk", "ImageTk", "PIL.ImageTk", "FixTk",
    # formats we don't use:
    "GimpGradientFile", "GimpPaletteFile", "BmpImagePlugin", "TiffImagePlugin",
    # not used:
    "pdb",
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
if not qt6_client_ENABLED:
    excludes += ["PyQt6"]
if not pyglet_client_ENABLED:
    excludes += ["pyglet"]
if not tk_client_ENABLED:
    excludes += ["tkinter"]


# because of differences in how we specify packages and modules
# for distutils / py2app and cx_freeze
# use the following functions, which should get the right
# data in the global variables "packages", "modules" and "excludes"


def remove_packages(*mods: str) -> None:
    """ ensures that the given packages are not included:
        removes them from the "modules" and "packages" list and adds them to "excludes" list
    """
    for m in list(modules):
        if any(m.startswith(x) for x in mods):
            modules.remove(m)
            break
    for p in list(packages):
        if any(p.startswith(x) for x in mods):
            packages.remove(p)
            break
    for x in mods:
        if x not in excludes:
            excludes.append(x)


def add_packages(*pkgs: str) -> None:
    """ adds the given packages to the packages list,
        and adds all the modules found in this package (including the package itself)
    """
    filtered_pkgs = tuple(pkg for pkg in pkgs if not any(pkg.startswith(exclude) for exclude in excludes))
    for x in filtered_pkgs:
        if x not in packages:
            packages.append(x)
    excluded = tuple(pkg for pkg in pkgs if any(pkg.startswith(exclude) for exclude in excludes))
    if excluded:
        print(f"add_packages({pkgs}) {excluded=} using {excludes=}")
    add_modules(*filtered_pkgs)


def add_modules(*mods: str) -> None:
    def add(v: str) -> None:
        if v in modules:
            return
        excluded = tuple(exclude for exclude in excludes if v.startswith(exclude))
        if excluded:
            print(f"not adding {v!r}, excluded by {excluded}")
            return
        modules.append(v)
    excluded = tuple(mod for mod in mods if any(mod.startswith(exclude) for exclude in excludes))
    if excluded:
        print(f"add_modules({mods}) {excluded=} using {excludes=}")
    do_add_modules(add, *mods)


def do_add_modules(op, *mods: str) -> None:
    """ adds the packages and any .py module found in the packages to the "modules" list
    """
    for x in mods:
        # ugly path stripping:
        if x.startswith("./"):
            x = x[2:]
        if x.endswith(".py"):
            x = x[:-3]
            x = x.replace("/", ".")    #.replace("\\", ".")
        pathname = os.path.sep.join(x.split("."))
        # is this a file module?
        f = f"{pathname}.py"
        if os.path.exists(f) and os.path.isfile(f):
            op(x)
        if os.path.exists(pathname) and os.path.isdir(pathname):
            # add all file modules found in this directory
            for f in os.listdir(pathname):
                # make sure we only include python files,
                # and ignore eclipse copies
                if f.endswith(".py") and not f.startswith("Copy "):
                    fname = os.path.join(pathname, f)
                    if os.path.isfile(fname):
                        modname = f"{x}."+f.replace(".py", "")
                        op(modname)


def toggle_packages(enabled: bool, *module_names: str) -> None:
    if enabled:
        add_packages(*module_names)
    else:
        remove_packages(*module_names)


# always included:
if modules_ENABLED:
    add_packages("xpra.util", "xpra.net")
    add_modules("xpra", "xpra.platform", "xpra.scripts.main")


#*******************************************************************************
# Utility methods for building with Cython
CPP = os.environ.get("CPP", "cpp")
CC = os.environ.get("CC", "gcc")
print(f"CC={CC}")
print(f"CPP={CPP}")

if verbose_ENABLED and not os.environ.get("DISTUTILS_DEBUG"):
    os.environ["DISTUTILS_DEBUG"] = "1"


def do_add_cython_ext(*args, **kwargs) -> None:
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


add_cython_ext = do_add_cython_ext


def ace(modnames="xpra.x11.bindings.xxx", pkgconfig_names="", optimize=None, **kwargs) -> None:
    src = modnames.split(",")
    modname = src[0]
    if not src[0].endswith(".pyx"):
        for ext in ("pyx", "py"):
            filename = src[0].replace(".", "/")+"."+ext
            if os.path.exists(filename):
                src[0] = filename
    if isinstance(pkgconfig_names, str):
        pkgconfig_names = [x for x in pkgconfig_names.split(",") if x]
    if WIN32:
        WIN32_PKGCONFIG_ALIASES = {
            "xrandr": "randrproto",
            "xext": "xextproto",
            "xdamage": "damageproto",
            "xkbfile": "kbproto",
            "xcomposite": "compositeproto",
            "xres": "resourceproto",
            "xfixes": "fixesproto",
        }
        pkgconfig_names = [WIN32_PKGCONFIG_ALIASES.get(name, name) for name in pkgconfig_names]
    pkgc = pkgconfig(*pkgconfig_names, optimize=optimize)
    for addto in ("extra_link_args", "extra_compile_args"):
        value = kwargs.pop(addto, None)
        if value:
            if isinstance(value, str):
                value = (value, )
            add_to_keywords(pkgc, addto, *value)
            for v in value:
                if v.startswith("-Wno-error="):
                    # make sure to remove the corresponding switch that may enable it:
                    warning = v.split("-Wno-error=", 1)[1]
                    if remove_from_keywords(pkgc, addto, f"-W{warning}"):
                        print(f"removed -W{warning} for {modname}")
    pkgc.update(kwargs)
    if kwargs.get("language", "") == "c++":
        # default to "-std=c++11" for c++
        if not any(v.startswith("-std=") for v in pkgc.get("extra_compile_args", ())):
            add_to_keywords(pkgc, "extra_compile_args", "-std=c++11")
        # all C++ modules trigger an address warning in the module initialization code:
        if WIN32:
            add_to_keywords(pkgc, "extra_compile_args", "-Wno-error=address")
    if (14, ) <= get_clang_version() <= (20, ):
        add_to_keywords(pkgc, "extra_compile_args", "-Wno-error=unreachable-code-fallthrough")
    add_cython_ext(modname, src, **pkgc)


def tace(toggle: bool, *args, **kwargs) -> None:
    if toggle:
        ace(*args, **kwargs)


def insert_into_keywords(kw: dict, key: str, *args) -> None:
    values = kw.setdefault(key, [])
    for arg in args:
        values.insert(0, arg)


def add_to_keywords(kw: dict, key: str, *args) -> None:
    values = kw.setdefault(key, [])
    for arg in args:
        values.append(arg)


def remove_from_keywords(kw: dict, key: str, value) -> int:
    values = kw.get(key)
    i = 0
    while values and value in values:
        values.remove(value)
        i += 1
    return i


def checkdirs(*dirs: str) -> None:
    for d in dirs:
        if not os.path.exists(d) or not os.path.isdir(d):
            raise RuntimeError(f"cannot find a directory which is required for building: {d!r}")


def CC_is_clang() -> bool:
    if CC.find("clang")>=0:
        return True
    return get_clang_version()>(0, )


clang_version = None


def get_clang_version() -> tuple[int, ...]:
    global clang_version
    if clang_version is not None:
        return clang_version
    r, _, err = get_status_output([CC, "-v"])
    clang_version = (0, )
    if r!=0:
        # not sure!
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
    # not found!
    return clang_version


_gcc_version = None


def get_gcc_version() -> tuple[int, ...]:
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


def vernum(s) -> tuple[int, ...]:
    return tuple(int(v) for v in s.split("-", 1)[0].split("."))


def add_pkgconfig_tokens(kw: dict, s: str, add_to="extra_link_args") -> None:
    if not s:
        return
    flag_map = {
        '-I': 'include_dirs',
        '-L': 'library_dirs',
        '-l': 'libraries',
    }
    ignored_flags = kw.get("ignored_flags", ())
    ignored_tokens = kw.get("ignored_tokens", ())
    skip = False
    tokens = shlex.split(s)
    for i, token in enumerate(tokens):
        if skip:
            skip = False
            continue
        if token in ignored_tokens:
            continue
        if token[:2] in ignored_flags:
            continue
        if token[:2] in flag_map:
            # this overrules 'add_to' - is this still needed?
            if len(token)>2:
                add_to_keywords(kw, flag_map[token[:2]], token[2:])
            else:
                next_arg = tokens[i + 1]
                add_to_keywords(kw, flag_map[token], next_arg)
                skip = True
        else:
            add_to_keywords(kw, add_to, token)


def add_pkgconfig(kw: dict, *pkgs_options):
    if not pkgs_options:
        return
    if verbose_ENABLED:
        print(f"add_pkgconfig_tokens will try to add packages {pkgs_options}")
    for pc_arg, add_to in {
        "--libs": "extra_link_args",
        "--cflags": "extra_compile_args",
    }.items():
        pkg_config_cmd = ["pkg-config", pc_arg] + list(pkgs_options)
        if verbose_ENABLED:
            print(f"pkg_config_cmd={pkg_config_cmd}")
        r, pkg_config_out, err = get_status_output(pkg_config_cmd)
        if r!=0:
            raise ValueError("ERROR: call to %r failed (err=%s)" % (shlex.join(pkg_config_cmd), err))
        if verbose_ENABLED:
            print(f"pkg-config output: {pkg_config_out!r}")
        add_pkgconfig_tokens(kw, pkg_config_out, add_to)
        if verbose_ENABLED:
            print(f"pkg-config kw={kw}")


# Tweaked from http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/502261
def exec_pkgconfig(*pkgs_options, **ekw) -> dict:
    if verbose_ENABLED:
        print(f"exec_pkgconfig({pkgs_options}, {ekw})")
    kw = dict(ekw)
    for d in os.environ.get("INCLUDE_DIRS", "").split(os.pathsep):
        if d.strip("'") and d.strip('"'):
            add_to_keywords(kw, 'extra_compile_args', "-I", d)
    optimize = kw.pop("optimize", 0)
    if Os_ENABLED:
        optimize = "s"
    if optimize and not debug_ENABLED and not cython_tracing_ENABLED:
        if isinstance(optimize, bool):
            optimize = int(optimize)*3
        add_to_keywords(kw, 'extra_compile_args', f"-O{optimize}")

    # for distros that don't patch distutils,
    # we have to add the python cflags:
    if not (is_RPM() or is_DEB()):    # noqa: E501
        # pylint: disable=import-outside-toplevel
        import sysconfig
        for cflag in shlex.split(sysconfig.get_config_var('CFLAGS') or ''):
            add_to_keywords(kw, 'extra_compile_args', cflag)
    if OSX:
        add_to_keywords(kw, 'extra_compile_args', "-Wno-nullability-completeness")

    def hascflag(s: str) -> bool:
        return s in kw.get("extra_compile_args", [])

    def addcflags(*s: str):
        add_to_keywords(kw, "extra_compile_args", *s)

    def addldflags(*s: str):
        add_to_keywords(kw, "extra_link_args", *s)

    add_pkgconfig(kw, *pkgs_options)

    if warn_ENABLED:
        addcflags("-Wall")
        addldflags("-Wall")
        if sys.version_info >= (3, 12):
            addcflags("-Wno-deprecated-declarations")
    if strict_ENABLED:
        if not hascflag("-Wno-error"):
            addcflags("-Werror")
        if NETBSD:
            # see: http://trac.cython.org/ticket/395
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
    CFLAGS = os.environ.get("CFLAGS", "")
    LDFLAGS = os.environ.get("LDFLAGS", "")
    # win32 remove double "-march=x86-64 -mtune=generic -O2 -pipe -O3"?
    if verbose_ENABLED:
        print(f"adding CFLAGS={CFLAGS}")
        print(f"adding LDFLAGS={LDFLAGS}")
    add_pkgconfig_tokens(kw, CFLAGS, "extra_compile_args")
    add_pkgconfig_tokens(kw, LDFLAGS, "extra_link_args")
    # add_to_keywords(kw, 'include_dirs', '.')
    if debug_ENABLED and WIN32 and MINGW_PREFIX:
        add_to_keywords(kw, 'extra_compile_args', "-DDEBUG")
    if verbose_ENABLED:
        print(f"exec_pkgconfig({pkgs_options}, {ekw})={kw}")
    # done using these:
    kw.pop("ignored_flags", None)
    kw.pop("ignored_tokens", None)
    return kw


pkgconfig = exec_pkgconfig


#*******************************************************************************


def get_base_conf_dir(install_dir: str, stripbuildroot=True) -> list[str]:
    # in some cases we want to strip the buildroot (to generate paths in the config file)
    # but in other cases we want the buildroot path (when writing out the config files)
    # and in some cases, we don't have the install_dir specified (called from detect_xorg_setup, and that's fine too)
    # this is a bit hackish, but I can't think of a better way of detecting it
    # (ie: "$HOME/rpmbuild/BUILDROOT/xpra-0.15.0-0.fc21.x86_64/usr")
    dirs = (install_dir or sys.prefix).split(os.path.sep)
    if install_dir and stripbuildroot:
        pkgdir = os.environ.get("pkgdir")
        if "debian" in dirs and "tmp" in dirs:
            # ugly fix for stripping the debian tmp dir:
            # ie: "???/tmp/???/tags/v0.15.x/src/debian/tmp/" -> ""
            while "tmp" in dirs:
                dirs = dirs[dirs.index("tmp")+1:]
        elif "debian" in dirs:
            # same for recent debian versions:
            # ie: "xpra-2.0.2/debian/xpra/usr" -> "usr"
            i = dirs.index("debian")
            while i>=0 and len(dirs)>i+1:
                if dirs[i+1] == "xpra":
                    dirs = dirs[i+2:]
                i = dirs.index("debian")
        elif "BUILDROOT" in dirs:
            # strip rpm style build root:
            # [$HOME, "rpmbuild", "BUILDROOT", "xpra-$VERSION"] -> []
            dirs = dirs[dirs.index("BUILDROOT")+2:]
        elif "pkg" in dirs:
            # archlinux
            # ie: "/build/xpra/pkg/xpra/etc" -> "etc"
            # find the last 'pkg' from the list of directories:
            i = max(loc for loc, val in enumerate(dirs) if val == "pkg")
            if len(dirs)>i+1 and dirs[i+1] in ("xpra", "xpra-git"):
                dirs = dirs[i+2:]
        elif pkgdir and install_dir.startswith(pkgdir):
            # arch build dir:
            dirs = install_dir[len(pkgdir):].split(os.path.sep)
        elif "usr" in dirs:
            # ie: ["some", "path", "to", "usr"] -> ["usr"]
            # assume "/usr" or "/usr/local" is the build root
            while "usr" in dirs[1:]:
                dirs = dirs[dirs[1:].index("usr")+1:]
        elif "image" in dirs:
            # Gentoo's "${PORTAGE_TMPDIR}/portage/${CATEGORY}/${PF}/image/_python2.7" -> ""
            while "image" in dirs:
                dirs = dirs[dirs.index("image")+2:]
    # now deal with the fact that "/etc" is used for the "/usr" prefix
    # but "/usr/local/etc" is used for the "/usr/local" prefix..
    if dirs and dirs[-1]=="usr":
        dirs = dirs[:-1]
    # is this an absolute path?
    if not dirs or dirs[0]=="usr" or (install_dir or sys.prefix).startswith(os.path.sep):
        # ie: ["/", "usr"] or ["/", "usr", "local"]
        dirs.insert(0, os.path.sep)
    return dirs


def get_conf_dir(install_dir: str, stripbuildroot=True) -> str:
    dirs = get_base_conf_dir(install_dir, stripbuildroot)
    if "etc" not in dirs:
        dirs.append("etc")
    dirs.append("xpra")
    return os.path.join(*dirs)


def detect_xorg_setup(install_dir="") -> Sequence[str]:
    # pylint: disable=import-outside-toplevel
    from xpra.scripts import config
    config.debug = config.warn
    conf_dir = get_conf_dir(install_dir)
    return config.detect_xvfb_command(conf_dir, None, Xdummy_ENABLED, Xdummy_wrapper_ENABLED)


def detect_xdummy_setup(install_dir="") -> Sequence:
    # pylint: disable=import-outside-toplevel
    from xpra.scripts import config
    config.debug = config.warn
    conf_dir = get_conf_dir(install_dir)
    return config.detect_xdummy_command(conf_dir, None, Xdummy_wrapper_ENABLED)


def convert_templates(install_dir: str, subs: dict[str, str], subdirs: Sequence[str] = ()) -> None:
    dirname = os.path.join("fs", "etc", "xpra", *subdirs)
    # get conf dir for install, without stripping the build root
    target_dir = os.path.join(get_conf_dir(install_dir, stripbuildroot=False), *subdirs)
    print(f"{dirname!r}:")
    # print(f"convert_templates({install_dir}, {subdirs}) {dirname=}, {target_dir=}")
    if not os.path.exists(target_dir):
        try:
            os.makedirs(target_dir)
        except Exception as e:
            print(f"cannot create target dir {target_dir!r}: {e}")
    template_files = os.listdir(dirname)
    if not template_files:
        print(f"Warning: no files found in {dirname!r}")
    for f in sorted(template_files):
        if f.endswith("osx.conf.in") and not OSX:
            continue
        filename = os.path.join(dirname, f)
        if os.path.isdir(filename):
            convert_templates(install_dir, subs, list(subdirs) + [f])
            continue
        if not (f.endswith(".in") or f.endswith(".conf") or f.endswith(".txt") or f.endswith(".keys")):
            print(f"Warning: skipped {f!r}")
            continue
        with open(filename, "r", encoding="latin1") as f_in:
            template = f_in.read()
        target_file = os.path.join(target_dir, f)
        if target_file.endswith(".in"):
            target_file = target_file[:-len(".in")]
        print(f"  {f!r:<50} -> {target_file!r}")
        with open(target_file, "w", encoding="latin1") as f_out:
            if f.endswith(".in"):
                try:
                    config_data = template % subs
                except ValueError:
                    print(f"error applying substitutions from {filename!r} to {target_file!r}:")
                    print(f"{config_data!r}")
                    print(f"{subs!r}")
                    raise
            else:
                config_data = template
            f_out.write(config_data)


def build_xpra_conf(install_dir: str) -> None:
    # pylint: disable=import-outside-toplevel
    # generates an actual config file from the template
    xvfb_command = detect_xorg_setup(install_dir)
    xdummy_command = detect_xdummy_setup(install_dir)
    from xpra.platform.features import DEFAULT_START_ENV, DEFAULT_ENV, SOURCE

    def bstr(b) -> str:
        if b is None:
            return "auto"
        return "yes" if int(b) else "no"
    default_start_env = "\n".join(f"start-env = {x}" for x in DEFAULT_START_ENV)
    default_env = "\n".join(f"env = {x}" for x in DEFAULT_ENV)
    source = "\n".join(f"source = {x}" for x in SOURCE)
    conf_dir = get_conf_dir(install_dir)
    print(f"get_conf_dir({install_dir})={conf_dir}")
    from xpra.platform.paths import get_socket_dirs
    from xpra.scripts.config import (
        wrap_cmd_str, unexpand,
        get_default_key_shortcuts, get_default_systemd_run,
        DEFAULT_POSTSCRIPT_PRINTER, DEFAULT_PULSEAUDIO,
    )
    # remove build paths and user specific paths with UID ("/run/user/UID/Xpra"):
    socket_dirs = [unexpand(x) for x in get_socket_dirs()]
    if POSIX and getuid()>0:
        # remove any paths containing the uid,
        # osx uses /var/tmp/$UID-Xpra,
        # but this should not be included in the default config for all users!
        # (the buildbot's uid!)
        socket_dirs = [x for x in socket_dirs if x.find(str(getuid()))<0]
    # FIXME: we should probably get these values from the default config instead
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

    # OSX doesn't have webcam support yet (no opencv builds on 10.5.x)
    webcam = webcam_ENABLED and not (OSX or WIN32)
    # no python-avahi on RH / CentOS, need dbus module on *nix:
    is_RH = is_RPM() and not (is_openSUSE() or is_Fedora())
    mdns = mdns_ENABLED and (OSX or WIN32 or (not is_RH and dbus_ENABLED))
    SUBS = {
        'xvfb_command'          : wrap_cmd_str(xvfb_command),
        'xdummy_command'        : wrap_cmd_str(xdummy_command).replace("\n", "\n#"),
        'ssh_command'           : "auto",
        'key_shortcuts'         : "".join(f"key-shortcut = {x}\n" for x in get_default_key_shortcuts()),
        'remote_logging'        : "both",
        'start_env'             : default_start_env,
        'env'                   : default_env,
        'pulseaudio'            : bstr(DEFAULT_PULSEAUDIO),
        'pulseaudio_command'    : "auto",
        'pulseaudio_configure_commands' : "none",
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
        'pdf_printer'           : pdf,
        'postscript_printer'    : postscript,
        'webcam'                : ["no", "auto"][webcam],
        'mousewheel'            : "on",
        'printing'              : bstr(printing_ENABLED),
        'dbus_control'          : bstr(dbus_ENABLED),
        'mmap'                  : "auto",
        'opengl'                : "no" if OSX else "probe",
        'headerbar'             : ["auto", "no"][OSX or WIN32],
    }
    convert_templates(install_dir, SUBS, ("conf.d", ))


#*******************************************************************************
def clean() -> None:
    # clean and sdist don't actually use cython,
    # so skip this (and avoid errors)
    global pkgconfig
    pkgconfig = no_pkgconfig
    # always include everything in this case:
    add_packages("xpra")
    # these files would match the pattern of generated files, but they are not, so protect them:
    PROTECTED = [
        "xpra/buffers/memalign.c",
        "xpra/platform/win32/setappid.cpp",
        "xpra/x11/gtk/gdk_x11_macros.c",
    ]
    # ensure we remove the files we generate:
    CLEAN_FILES = [
        "xpra/build_info.py",
        "xpra/codecs/v4l2/constants.pxi",
        # special case for the generated xpra conf files in build (see # 891):
        "build/etc/xpra/xpra.conf",
    ] + glob("build/etc/xpra/conf.d/*.conf")
    if cuda_rebuild_ENABLED:
        CLEAN_FILES += glob("fs/share/xpra/cuda/*.fatbin")
    CLEAN_DIRS = []
    for path, dirs, filenames in os.walk("xpra"):
        for dirname in dirs:
            dirpath = os.path.join(path, dirname)
            if dirname == "__pycache__":
                CLEAN_DIRS.append(dirpath)
        for filename in filenames:
            ext = os.path.splitext(filename)[-1]
            fpath = os.path.join(path, filename)
            if fpath in PROTECTED:
                continue
            if ext in (".py", ".pyx", ".pxd", ".h", ".pxi", ".fatbin", ".txt", ".m"):
                # never delete source files
                continue
            if ext in (".c", ".cpp", ".pyc", ".pyd", ".html"):
                if fpath not in CLEAN_FILES:
                    CLEAN_FILES.append(fpath)
                continue
            print(f"warning unexpected file in source tree: {fpath} with ext={ext}")
    for x in CLEAN_FILES:
        filename = os.path.join(os.getcwd(), x.replace("/", os.path.sep))
        if os.path.exists(filename):
            if verbose_ENABLED:
                print(f"cleaning: {x!r}")
            os.unlink(filename)
    for x in CLEAN_DIRS:
        dirname = os.path.join(os.getcwd(), x.replace("/", os.path.sep))
        os.rmdir(dirname)


def add_build_info(*args) -> None:
    cmd = [sys.executable, "./fs/bin/add_build_info.py"]+list(args)
    r = subprocess.Popen(cmd).wait(TIMEOUT * (1 + 10 * OSX))
    assert r==0, "'%s' returned %s" % (" ".join(cmd), r)


if "install" in sys.argv or "build" in sys.argv:
    # if installing from source tree rather than
    # from a source snapshot, we may not have a "src_info" file
    # so create one:
    add_build_info()
    if modules_ENABLED:
        # ensure it is now included in the module list
        add_modules("xpra.src_info")

if "clean" in sys.argv or "sdist" in sys.argv:
    clean()
    if "sdist" in sys.argv:
        add_build_info("src")
    # take shortcut to skip cython/pkgconfig steps:
    setup(**setup_options)
    sys.exit(0)


# Add build info to build_info.py file:
add_build_info("build")
if modules_ENABLED:
    # ensure it is included in the module list if it didn't exist before
    add_modules("xpra.build_info")


def glob_recurse(srcdir: str) -> dict[str, list[str]]:
    m = {}
    for root, _, files in os.walk(srcdir):
        for f in files:
            dirname = root[len(srcdir)+1:]
            m.setdefault(dirname, []).append(os.path.join(root, f))
    return m


#*******************************************************************************
MINGW_PREFIX = ""
if WIN32:
    MINGW_PREFIX = os.environ.get("MINGW_PREFIX", "")
    assert MINGW_PREFIX, "you must run this build from a MINGW environment"
    if modules_ENABLED:
        add_packages("xpra.platform.win32", "xpra.platform.win32.namedpipes")
    remove_packages("xpra.platform.darwin", "xpra.platform.posix")

    # this is where the win32 gi installer will put things:
    gnome_include_path = os.environ.get("MINGW_PREFIX", "")

    # cx_freeze doesn't use "data_files"...
    del setup_options["data_files"]
    # it wants source files first, then where they are placed...
    # one item at a time (no lists)
    # all in its own structure called "include_files" instead of "data_files"...

    def add_data_files(target_dir, files) -> None:
        if verbose_ENABLED:
            print(f"add_data_files({target_dir}, {files})")
        assert isinstance(target_dir, str)
        assert isinstance(files, (list, tuple))
        for f in files:
            target_file = os.path.join(target_dir, os.path.basename(f))
            data_files.append((f, target_file))

    # only add the cx_freeze specific options
    # only if we are packaging:
    if "install_exe" in sys.argv:
        # with cx_freeze, we don't use py_modules
        del setup_options["py_modules"]
        from cx_Freeze import setup, Executable     #@UnresolvedImport @Reimport
        if not hasattr(sys, "base_prefix"):
            # workaround for broken sqlite hook with python 2.7, see:
            # https://github.com/anthony-tuininga/cx_Freeze/pull/272
            sys.base_prefix = sys.prefix

        # pass a potentially nested dictionary representing the tree
        # of files and directories we do want to include
        def add_dir(base: str, defs) -> None:
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
                    # recurse down:
                    add_dir(os.path.join(base, d), sub)

        def add_gi_typelib(*libs: str) -> None:
            if verbose_ENABLED:
                print(f"add_gi_typelib({libs})")
            add_dir('lib',      {"girepository-1.0":    [f"{x}.typelib" for x in libs]})

        def add_gi_gir(*libs: str) -> None:
            if verbose_ENABLED:
                print(f"add_gi_gir({libs})")
            add_dir('share',    {"gir-1.0" :            [f"{x}.gir" for x in libs]})
        # convenience method for adding GI libs and "typelib" and "gir":

        def add_gi(*libs: str) -> None:
            add_gi_typelib(*libs)
            add_gi_gir(*libs)

        def add_DLLs(*dll_names: str) -> None:
            try:
                do_add_DLLs("lib", *dll_names)
            except Exception as e:
                print(f"Error: failed to add DLLs: {dll_names}")
                print(f" {e}")
                sys.exit(1)

        def do_add_DLLs(prefix="lib", *dll_names: str) -> None:
            dll_names = list(dll_names)
            dll_files = []
            version_re = re.compile(r"-[0-9.-]+$")
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
                    # strip prefix (ie: "lib") and ".dll":
                    # ie: "libatk-1.0-0.dll" -> "atk-1.0-0"
                    nameversion = x[len(prefix):-4]
                    if verbose_ENABLED:
                        print(f"checking {x}: {nameversion}")
                    m = version_re.search(nameversion)          # look for version part of filename
                    if m:
                        dll_version = m.group(0)                # found it, ie: "-1.0-0"
                        dll_name = nameversion[:-len(dll_version)]  # ie: "atk"
                        dll_version = dll_version.lstrip("-")   # ie: "1.0-0"
                    else:
                        dll_version = ""                        # no version
                        dll_name = nameversion                  # ie: "libzzz.dll" -> "zzz"
                    if dll_name in dll_names:
                        # this DLL is on our list
                        print("%s %s %s" % (dll_name.ljust(22), dll_version.ljust(10), x))
                        dll_files.append(dll_path)
                        dll_names.remove(dll_name)
            if dll_names:
                print("some DLLs could not be found:")
                for x in dll_names:
                    print(f" - {prefix}{x}*.dll")
            add_data_files("", dll_files)

        # list of DLLs we want to include, without the "lib" prefix, or the version and extension
        #(ie: "libatk-1.0-0.dll" -> "atk")
        if audio_ENABLED or gtk3_ENABLED:
            add_DLLs(
                'gio', 'girepository', 'glib',
                'gnutls', 'gobject', 'gthread',
                'orc', 'stdc++',
                'winpthread',
            )
        if gtk3_ENABLED:
            add_DLLs(
                'atk',
                'dbus', 'dbus-glib',
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
            add_dir('etc', ["fonts", "gtk-3.0"])     # add "dbus-1"?
            add_dir('lib', ["gdk-pixbuf-2.0", "gtk-3.0",
                            "p11-kit", "pkcs11"])
            add_dir('share',
                    [
                        "fontconfig", "fonts", "glib-2.0",        # add "dbus-1"?
                        "p11-kit", "xml",
                        {"locale" : ["en"]},
                        {"themes" : ["Default"]}
                    ])
            ICONS = ["24x24", "48x48", "scalable", "cursors", "index.theme"]
            for theme in ("Adwaita", ):   # "hicolor"
                add_dir("share/icons/"+theme, ICONS)
            add_dir("share/themes/Windows-10", [
                "CREDITS", "LICENSE.md", "README.md",
                "gtk-3.20", "index.theme"])
        if gtk3_ENABLED or audio_ENABLED:
            # causes warnings:
            # add_dir('lib', ["gio"])
            packages.append("gi")
            add_gi_typelib("Gio-2.0", "GioWin32-2.0", "GIRepository-2.0", "Glib-2.0", "GModule-2.0", "GObject-2.0")
        if gtk3_ENABLED:
            add_gi(
                "Atk-1.0",
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
            # we no longer support GtkGL:
            # if opengl_ENABLED:
            #    add_gi("GdkGLExt-3.0", "GtkGLExt-3.0", "GL-1.0")
            add_DLLs('curl', 'soup')

        if client_ENABLED:
            # svg pixbuf loader:
            add_DLLs("rsvg", "croco")
            # gio module and `xpra.net.libproxy`:
            add_DLLs("proxy")

        if client_ENABLED or server_ENABLED:
            add_DLLs("qrencode")
            # python-gssapi authentication:
            add_DLLs("gss")
            add_modules("decorator")

        # only really used by sqlite auth:
        # (but also potentially by python itself)
        add_DLLs("sqlite3")

        if audio_ENABLED:
            add_dir("share", ["gst-plugins-base", "gstreamer-1.0"])
            add_gi(
                "Gst-1.0",
                "GstAllocators-1.0",
                "GstAudio-1.0",
                "GstBase-1.0",
                "GstTag-1.0"
            )
            add_DLLs('gstreamer', 'orc-test')
            for p in (
                    "app", "audio", "base", "codecparsers", "fft", "net", "video",
                    "pbutils", "riff", "sdp", "rtp", "rtsp", "tag", "uridownloader",
                    # I think 'coreelements' needs those (otherwise we would exclude them):
                    "basecamerabinsrc", "mpegts", "photography",
            ):
                add_DLLs(f"gst{p}")
            # DLLs needed by the plugins:
            add_DLLs("faac", "faad", "flac", "mpg123")      #"mad" is no longer included?
            # add the gstreamer plugins we need:
            GST_PLUGINS = (
                "app",
                "cutter", "removesilence",
                # muxers:
                "gdp", "matroska", "ogg", "isomp4",
                "audioparsers", "audiorate", "audioconvert", "audioresample", "audiotestsrc",
                "coreelements", "directsound", "directsoundsrc", "wasapi",
                # codecs:
                "opus", "opusparse", "flac", "lame", "mpg123", "faac", "faad",
                "volume", "vorbis", "wavenc", "wavpack", "wavparse",
                "autodetect",
                # decodebin used for playing "new-client" sound:
                "playback", "typefindfunctions",
                # video codecs:
                "vpx", "x264", "aom", "openh264", "d3d11", "winscreencap",
                "videoconvertscale", "videorate",
            )
            add_dir(os.path.join("lib", "gstreamer-1.0"), [("libgst%s.dll" % x) for x in GST_PLUGINS])
            # END OF SOUND

        if server_ENABLED:
            # used by proxy server:
            external_includes += ["multiprocessing", "setproctitle"]

        external_includes += ["encodings", "mimetypes"]
        if client_ENABLED:
            external_includes += [
                "shlex",                # for parsing "open-command"
                "ftplib", "fileinput",  # for version check
                "urllib", "http.cookiejar", "http.client",
            ]
            if websockets_browser_cookie_ENABLED:
                # for websocket browser cookie:
                external_includes += ["browser_cookie3", "pyaes", "pbkdf2", "keyring"]
            else:
                remove_packages("keyring")

        # hopefully, cx_Freeze will fix this horror:
        #(we shouldn't have to deal with DLL dependencies)
        import site
        lib_python = os.path.dirname(site.getsitepackages()[0])
        lib_dynload_dir = os.path.join(lib_python, "lib-dynload")
        add_data_files('', glob(f"{lib_dynload_dir}/zlib*dll"))
        for x in ("io", "codecs", "abc", "_weakrefset", "encodings"):
            add_data_files("lib/", glob(f"{lib_python}/{x}*"))
        # ensure that cx_freeze won't automatically grab other versions that may lay on our path:
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
        # cx_Freeze v5 workarounds:
        if nvenc_ENABLED or nvdec_ENABLED or nvfbc_ENABLED:
            external_includes += [
                "numpy",
                "pycuda",
                "pynvml",
            ]
            add_packages("numpy.lib.format")
        else:
            remove_packages(
                "numpy",
                "pycuda",
                "unittest",
                "difflib",  # avoid numpy warning (not an error)
                "pydoc",
            )

        setup_options["options"] = {"build_exe" : cx_freeze_options}
        executables = []
        setup_options["executables"] = executables

        def add_exe(script, icon, base_name, base="Console") -> None:
            kwargs = {}
            manifest = f"dist/{base_name}.exe.manifest"
            if os.path.exists(manifest):
                kwargs["manifest"] = manifest
            executables.append(Executable(
                script=script, init_script=None,
                # targetDir               = "dist",
                icon=f"fs/share/xpra/icons/{icon}",
                target_name=f"{base_name}.exe",
                base=base,
                **kwargs
            ))

        def add_console_exe(script, icon, base_name) -> None:
            add_exe(script, icon, base_name)

        def add_gui_exe(script, icon, base_name) -> None:
            add_exe(script, icon, base_name, base="gui")

        def add_service_exe(script, icon, base_name) -> None:
            add_exe(script, icon, base_name, base="Win32Service")

        # UI applications (detached from shell: no text output if ran from cmd.exe)
        if (client_ENABLED or server_ENABLED) and gtk3_ENABLED:
            add_gui_exe("fs/bin/xpra",                         "xpra.ico",         "Xpra")
            add_gui_exe("fs/bin/xpra_launcher",                "xpra.ico",         "Xpra-Launcher")
            if win32_tools_ENABLED:
                add_console_exe("fs/bin/xpra_launcher",            "xpra.ico",         "Xpra-Launcher-Debug")
                add_gui_exe("packaging/MSWindows/tools/gtk_keyboard_test.py", "keyboard.ico",     "GTK_Keyboard_Test")
            add_gui_exe("packaging/MSWindows/tools/bug_report.py",           "bugs.ico",         "Bug_Report")
            add_gui_exe("xpra/gtk/configure/main.py",        "directory.ico",         "Configure")
        if shadow_ENABLED:
            add_gui_exe("xpra/platform/win32/scripts/shadow_server.py",       "server-notconnected.ico", "Xpra-Shadow")
            if win32_tools_ENABLED:
                add_gui_exe("packaging/MSWindows/tools/screenshot.py", "screenshot.ico", "Screenshot")
        if win32_tools_ENABLED and server_ENABLED:
            add_gui_exe("fs/libexec/xpra/auth_dialog",          "authentication.ico", "Auth_Dialog")
        # Console: provide an Xpra_cmd.exe we can run from the cmd.exe shell
        add_console_exe("fs/bin/xpra",                     "xpra_txt.ico",     "Xpra_cmd")
        if win32_tools_ENABLED:
            add_console_exe("xpra/platform/win32/scripts/exec.py",     "python.ico", "Python_exec_cmd")
            add_gui_exe("xpra/platform/win32/scripts/exec.py",     "python.ico", "Python_exec_gui")
        if gstreamer_ENABLED and win32_tools_ENABLED:
            add_console_exe("packaging/MSWindows/tools/lib_delegate.py", "gstreamer.ico", "gst-launch-1.0")
            add_data_files("lib/", (shutil.which("gst-launch-1.0.exe"), ))
            add_console_exe("packaging/MSWindows/tools/lib_delegate.py", "gstreamer.ico", "gst-inspect-1.0")
            add_data_files("lib/", (shutil.which("gst-inspect-1.0.exe"), ))
            add_console_exe("fs/bin/xpra", "speaker.ico", "Xpra_Audio")
        if printing_ENABLED:
            add_console_exe("xpra/platform/win32/pdfium.py",    "printer.ico",     "PDFIUM_Print")
            do_add_DLLs("", "pdfium")
        # extra tools:
        if win32_tools_ENABLED:
            add_console_exe("xpra/scripts/version.py",          "information.ico",  "Version_info")
            add_console_exe("xpra/net/net_util.py",             "network.ico",      "Network_info")
            if gtk3_ENABLED:
                add_console_exe("packaging/MSWindows/tools/gtk_info.py",         "gtk.ico",          "GTK_info")
                add_console_exe("xpra/gtk/keymap.py",        "keymap.ico",       "Keymap_info")
                add_console_exe("xpra/platform/keyboard.py",        "keymap.ico",       "Keyboard_info")
                add_gui_exe("packaging/MSWindows/tools/systemtray_test.py", "xpra.ico",         "SystemTray_Test")
                add_gui_exe("xpra/gtk/dialogs/u2f_tool.py",     "authentication.ico", "U2F_Tool")
            if client_ENABLED or server_ENABLED:
                add_console_exe("xpra/platform/win32/scripts/execfile.py", "python.ico", "Python_execfile_cmd")
                add_gui_exe("xpra/platform/win32/scripts/execfile.py", "python.ico", "Python_execfile_gui")
                add_console_exe("xpra/scripts/config.py",           "gears.ico",        "Config_info")
            if server_ENABLED:
                add_console_exe("xpra/auth/sqlite.py",  "sqlite.ico",        "SQLite_auth_tool")
                add_console_exe("xpra/auth/sql.py",     "sql.ico",           "SQL_auth_tool")
                add_console_exe("xpra/auth/win32.py",   "authentication.ico", "System-Auth-Test")
                add_console_exe("xpra/auth/ldap.py",    "authentication.ico", "LDAP-Auth-Test")
                add_console_exe("xpra/auth/ldap3.py",   "authentication.ico", "LDAP3-Auth-Test")
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
                add_console_exe("xpra/platform/win32/directsound.py", "speaker.ico",      "Audio_Devices")
                # add_console_exe("xpra/audio/src.py",                "microphone.ico",   "Audio_Record")
                # add_console_exe("xpra/audio/sink.py",               "speaker.ico",      "Audio_Play")
            if opengl_ENABLED:
                add_console_exe("xpra/opengl/check.py",   "opengl.ico",       "OpenGL_check")
            if webcam_ENABLED:
                add_console_exe("xpra/platform/webcam.py",          "webcam.ico",    "Webcam_info")
                add_console_exe("xpra/scripts/show_webcam.py",          "webcam.ico",    "Webcam_Test")
            if printing_ENABLED:
                add_console_exe("xpra/platform/printing.py",        "printer.ico",     "Print")
            if nvenc_ENABLED or nvdec_ENABLED:
                add_console_exe("xpra/codecs/nvidia/util.py",                   "nvidia.ico",   "NVidia_info")
            if nvfbc_ENABLED:
                add_console_exe("xpra/codecs/nvidia/nvfbc/capture.py",             "nvidia.ico",   "NvFBC_capture")
            if nvfbc_ENABLED or nvenc_ENABLED or nvdec_ENABLED or nvjpeg_encoder_ENABLED or nvjpeg_decoder_ENABLED:
                add_console_exe("xpra/codecs/nvidia/cuda/info.py",  "cuda.ico",     "CUDA_info")

    if ("install_exe" in sys.argv) or ("install" in sys.argv):
        # FIXME: how do we figure out what target directory to use?
        print("calling build_xpra_conf in-place")
        # building etc files in-place:
        if data_ENABLED:
            build_xpra_conf("./fs")
            conf_files = ["xpra.conf"]
            if shadow_ENABLED:
                if nvidia_ENABLED:
                    conf_files.append("cuda.conf")
                if nvfbc_ENABLED:
                    conf_files.append("nvfbc.keys")
                if nvenc_ENABLED:
                    conf_files.append("nvenc.keys")
            add_data_files("etc/xpra", [f"fs/etc/xpra/{conf_file}" for conf_file in conf_files])
            prefixes = ["0*", "1*", "2*", "3*", "4*"]
            if shadow_ENABLED or proxy_ENABLED:
                prefixes.append("50_server_network")
            if proxy_ENABLED:
                prefixes.append("65_proxy")
            conf_d_files = []
            for prefix in prefixes:
                conf_d_files += glob(f"fs/etc/xpra/conf.d/{prefix}.conf")
            add_data_files("etc/xpra/conf.d", conf_d_files)

    if data_ENABLED:
        add_data_files("", ["packaging/MSWindows/website.url"])
        add_data_files("lib/tlb", ["packaging/MSWindows/TaskbarLib.tlb"])
        if webcam_ENABLED:
            add_data_files("lib/tlb", ["packaging/MSWindows/DirectShow.tlb"])

    remove_packages(*external_excludes)
    external_includes += [
        "pyu2f",
        "mmap",
        "comtypes", "comtypes.stream",      # used by webcam, netdev_query, taskbar progress (file-transfers), etc
        "wmi", "win32com",
    ]
    # this is generated at runtime,
    # but we still have to remove the empty directory by hand
    # afterwards because cx_freeze does weird things (..)
    remove_packages("comtypes.gen")
    # not used on win32:
    # we handle GL separately below:
    remove_packages(
        "OpenGL", "OpenGL_accelerate",
        # this is a mac osx thing:
        "ctypes.macholib",
    )

    if quic_ENABLED:
        external_includes += ["pyasn1", "winloop", "winloop._noop", "aioquic", "pylsqpack"]
        add_modules("aioquic._buffer")

    if webcam_ENABLED:
        external_includes.append("cv2")
    else:
        remove_packages("cv2")

    if client_ENABLED:
        external_includes.append("pyvda")

    if qt6_client_ENABLED:
        external_includes.append("PyQt6")
    else:
        remove_packages("PyQt6")

    if pyglet_client_ENABLED:
        external_includes.append("pyglet")
    else:
        remove_packages("pyglet")

    if tk_client_ENABLED:
        external_includes.append("tkinter")
    else:
        remove_packages("tkinter")

    if shadow_ENABLED:
        external_includes.append("watchdog")

    if yaml_ENABLED:
        external_includes.append("yaml")

    if codecs_ENABLED:
        external_includes.append("decimal")
        external_includes.append("_pydecimal")

    external_includes.append("cairo")
    external_includes.append("certifi")

    # add subset of PyOpenGL modules (only when installing):
    if opengl_ENABLED and "install_exe" in sys.argv:
        # for this hack to work, you must add "." to the sys.path
        # so python can load OpenGL from the installation directory
        #(further complicated by the fact that "." is the "frozen" path...)
        # but we re-add those two directories to the library.zip as part of the build script
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
            module_dir = os.path.dirname(module.__file__)
            try:
                shutil.copytree(
                    module_dir, os.path.join(install, "lib", module_name),
                    ignore=shutil.ignore_patterns(
                        "Tk", "AGL", "EGL",
                        "GLX", "GLX.*", "_GLX.*",
                        "GLE", "GLES1", "GLES2", "GLES3",
                    )
                )
                print(f"copied {module_dir} to {install}/{module_name}")
            except Exception as e:
                if not isinstance(e, WindowsError) or ("already exists" not in str(e)):  # @UndefinedVariable
                    raise

    if data_ENABLED and shadow_ENABLED:
        add_data_files("share/metainfo",      ["fs/share/metainfo/xpra.appdata.xml"])
        for d in ("http-headers", "content-type", "content-categories", "content-parent"):
            add_data_files(f"etc/xpra/{d}", glob(f"fs/etc/xpra/{d}/*"))

    # END OF win32
#*******************************************************************************
else:
    # OSX and *nix:
    libexec_scripts = []
    if scripts_ENABLED:
        libexec_scripts += ["xpra_signal_listener"]
    if POSIX:
        libexec_scripts += ["daemonizer"]
    if LINUX or FREEBSD:
        if scripts_ENABLED:
            libexec_scripts += ["xpra_udev_product_version"]
        if xdg_open_ENABLED:
            libexec_scripts += ["xdg-open", "gnome-open", "gvfs-open"]
        if server_ENABLED:
            libexec_scripts.append("auth_dialog")
    if x11_ENABLED:
        libexec_scripts.append("xpra_weston_xvfb")

    def add_data_files(target_dir: str, files) -> None:
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
        if OPENBSD:
            man_path = "man"
        if OPENBSD or FREEBSD or is_openSUSE():
            icons_dir = "pixmaps"
        man_pages = ["fs/share/man/man1/xpra.1", "fs/share/man/man1/xpra_launcher.1"]
        if not OSX:
            man_pages.append("fs/share/man/man1/run_scaled.1")
        add_data_files(f"{man_path}/man1",  man_pages)
        add_data_files("share/applications",  glob("fs/share/applications/*.desktop"))
        add_data_files("share/mime/packages", ["fs/share/mime/packages/application-x-xpraconfig.xml"])
        add_data_files(f"share/{icons_dir}", glob("fs/share/icons/*.png"))
        add_data_files("share/metainfo",      ["fs/share/metainfo/xpra.appdata.xml"])

    # here, we override build and install so we can
    # generate /etc/xpra/conf.d/*.conf
    class build_override(build):
        def run(self) -> None:
            build.run(self)
            self.run_command("build_conf")

    class build_conf(build):
        def run(self) -> None:
            try:
                build_base = self.distribution.command_obj['build'].build_base
            except (AttributeError, KeyError):
                build_base = self.build_base
            build_xpra_conf(build_base)

    class install_data_override(install_data):

        def finalize_options(self) -> None:
            self.install_base = self.install_platbase = None
            install_data.finalize_options(self)
            self.actual_install_dir = self._get_install_dir()
            self.actual_root_prefix = self._get_root_prefix()

        def _get_install_dir(self):
            install_dir = self.install_dir
            if install_dir.endswith("egg"):
                install_dir = install_dir.split("egg")[1] or sys.prefix
            if verbose_ENABLED:
                print(f"  install_dir={install_dir!r}")
            return install_dir

        def _get_root_prefix(self) -> str:
            root_prefix = ""
            for x in sys.argv:
                if x.startswith("--root="):
                    return x[len("--root="):]
                if x.startswith("--prefix="):
                    root_prefix = x[len("--prefix="):]
            if not root_prefix:
                install_dir = self._get_install_dir()
                root_prefix = install_dir.rstrip("/")
            if root_prefix.endswith("/usr"):
                # ie: "/" or "/usr/src/rpmbuild/BUILDROOT/xpra-0.18.0-0.20160513r12573.fc23.x86_64/"
                root_prefix = root_prefix[:-4]
            if verbose_ENABLED:
                print(f"  root_prefix={root_prefix!r}")
            return root_prefix

        def copytodir(self, src: str, dst_dir: str, dst_name="", chmod=0o644, subs: dict | None=None) -> None:
            # print("copytodir%s" % (src, dst_dir, dst_name, chmod, subs))
            # convert absolute paths:
            dst_prefix = self.actual_root_prefix if dst_dir.startswith("/") else self.actual_install_dir
            dst_dir = dst_prefix.rstrip("/")+"/"+dst_dir.lstrip("/")
            # make sure the target directory exists:
            self.mkpath(dst_dir)
            # generate the target filename:
            filename = os.path.basename(src)
            dst_file = os.path.join(dst_dir, dst_name or filename)
            # copy it
            print(f"  {src!r:<50} -> {dst_dir!r} (%s)" % oct(chmod))
            data = load_binary_file(src)
            if subs:
                for k,v in subs.items():
                    data = data.replace(k, v)
            with open(dst_file, "wb") as f:
                f.write(data)
            if chmod:
                # print(f"  chmod({dst_file!r}, %s)" % oct(chmod))
                os.chmod(dst_file, chmod)

        def dirtodir(self, src_dir: str, dst_dir: str) -> None:
            print(f"{src_dir!r}:")
            for f in os.listdir(src_dir):
                self.copytodir(os.path.join(src_dir, f), dst_dir)

        def run(self) -> None:
            if not self.install_dir.endswith("egg"):
                install_data.run(self)
            print("install_data_override.run()")

            if printing_ENABLED and POSIX:
                # install "/usr/lib/cups/backend" with 0700 permissions:
                lib_cups = "lib/cups"
                if FREEBSD:
                    lib_cups = "libexec/cups"
                self.copytodir("fs/lib/cups/backend/xpraforwarder", f"{lib_cups}/backend", chmod=0o700)

            etc_xpra_files = {}

            def addconf(name, dst_name=None) -> None:
                etc_xpra_files[name] = dst_name

            addconf("xpra.conf")
            if nvenc_ENABLED or nvdec_ENABLED or nvfbc_ENABLED:
                addconf("cuda.conf")
            if nvenc_ENABLED:
                addconf("nvenc.keys")
            if nvfbc_ENABLED:
                addconf("nvfbc.keys")

            build_xpra_conf(self.actual_root_prefix)

            if x11_ENABLED:
                # install xpra_Xdummy if we need it:
                xvfb_command = detect_xorg_setup()
                if any(x.find("xpra_Xdummy") >= 0 for x in xvfb_command) or Xdummy_wrapper_ENABLED is True:
                    self.copytodir("fs/bin/xpra_Xdummy", "bin", chmod=0o755)
                # install xorg*.conf, cuda.conf and nvenc.keys:

                if uinput_ENABLED:
                    addconf("xorg-uinput.conf")
                addconf("xorg.conf")
                for src, dst_name in etc_xpra_files.items():
                    self.copytodir(f"fs/etc/xpra/{src}", "/etc/xpra", dst_name=dst_name)
                self.copytodir("fs/etc/X11/xorg.conf.d/90-xpra-virtual.conf", "/etc/X11/xorg.conf.d/")

            if pam_ENABLED:
                self.copytodir("fs/etc/pam.d/xpra", "/etc/pam.d")

            systemd_dir = "/lib/systemd/system"
            if is_openSUSE():
                systemd_dir = "__UNITDIR__"
            if service_ENABLED:
                # Linux init service:
                subs = {}
                if is_RPM():
                    cdir = "/etc/sysconfig"
                elif is_DEB():
                    cdir = "/etc/default"
                elif os.path.exists("/etc/sysconfig"):
                    cdir = "/etc/sysconfig"
                else:
                    cdir = "/etc/default"
                if is_openSUSE():
                    # openSUSE does things differently:
                    cdir = "__FILLUPDIR__"
                    shutil.copy("fs/etc/sysconfig/xpra", "fs/etc/sysconfig/sysconfig.xpra")
                    os.chmod("fs/etc/sysconfig/sysconfig.xpra", 0o644)
                    self.copytodir("fs/etc/sysconfig/sysconfig.xpra", cdir)
                else:
                    self.copytodir("fs/etc/sysconfig/xpra", cdir)
                if cdir!="/etc/sysconfig":
                    # also replace the reference to it in the service file below
                    subs[b"/etc/sysconfig"] = cdir.encode()
                if os.path.exists("/bin/systemctl") or os.path.exists("/usr/bin/systemctl") or sd_listen_ENABLED:
                    if sd_listen_ENABLED:
                        self.copytodir("fs/lib/systemd/system/xpra.service", systemd_dir, subs=subs)
                        self.copytodir("fs/lib/systemd/system/xpra-encoder.service", systemd_dir, subs=subs)
                    else:
                        self.copytodir("fs/lib/systemd/system/xpra-nosocketactivation.service", systemd_dir,
                                       dst_name="xpra.service", subs=subs)
                else:
                    self.copytodir("fs/etc/init.d/xpra", "/etc/init.d")
            if sd_listen_ENABLED:
                self.copytodir("fs/lib/systemd/system/xpra.socket", systemd_dir)
                self.copytodir("fs/lib/systemd/system/xpra-encoder.socket", systemd_dir)
            if POSIX and dbus_ENABLED and proxy_ENABLED:
                self.copytodir("fs/etc/dbus-1/system.d/xpra.conf", "/etc/dbus-1/system.d")

            if docs_ENABLED:
                doc_dir = f"{self.actual_install_dir}/share/doc/xpra/"
                convert_doc_dir("./docs", doc_dir)

            if data_ENABLED:
                for etc_dir in ("http-headers", "content-type", "content-categories", "content-parent"):
                    self.dirtodir(f"fs/etc/xpra/{etc_dir}", f"/etc/xpra/{etc_dir}")
                if audio_ENABLED:
                    self.dirtodir("fs/etc/xpra/pulse", "/etc/xpra/pulse")
    # add build_conf to build step
    cmdclass |= {
        'build'        : build_override,
        'build_conf'   : build_conf,
        'install_data' : install_data_override,
    }

    if OSX:
        # pyobjc needs email.parser
        external_includes += ["email", "uu", "urllib", "objc", "cups", "six"]
        external_includes += ["kerberos", "future", "pyu2f", "paramiko", "nacl"]
        if yaml_ENABLED:
            external_includes.append("yaml")
        # OSX package names (ie: gdk-x11-2.0 -> gdk-2.0, etc)
        add_packages("xpra.platform.darwin")
        remove_packages("xpra.platform.win32", "xpra.platform.posix")
        # to support GStreamer 1.x we need this:
        modules += ["importlib", "mimetypes"]
        remove_packages("numpy")
    else:
        add_packages("xpra.platform.posix")
        remove_packages("xpra.platform.win32", "xpra.platform.darwin")
        if data_ENABLED:
            # not supported by all distros, but doesn't hurt to install them anyway:
            if not FREEBSD:
                for x in ("tmpfiles.d", "sysusers.d"):
                    add_data_files(f"lib/{x}", [f"fs/lib/{x}/xpra.conf"])
            if uinput_ENABLED:
                add_data_files("lib/udev/rules.d/", ["fs/lib/udev/rules.d/71-xpra-virtual-pointer.rules"])

    # gentoo does weird things, calls --no-compile with build *and* install
    # then expects to find the cython modules!? ie:
    #> python2.7 setup.py build -b build-2.7 install --no-compile \
    # --root=/var/tmp/portage/x11-wm/xpra-0.7.0/temp/images/2.7
    # otherwise we use the flags to skip pkgconfig
    if ("--no-compile" in sys.argv or "--skip-build" in sys.argv) and not ("build" in sys.argv and "install" in sys.argv):  # noqa: E501
        pkgconfig = no_pkgconfig

    if OSX and "py2app" in sys.argv:
        import py2app    #@UnresolvedImport
        assert py2app is not None

        # don't use py_modules or scripts with `py2app`, and no cython:
        del setup_options["py_modules"]
        scripts = []

        def noop(*_args, **_kwargs):  # pylint: disable=function-redefined
            pass
        add_cython_ext = noop

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
        # Note: despite our best efforts, `py2app` will not copy all the modules we need
        # so the make-app.sh script still has to hack around this problem.
        add_modules(*external_includes)
        py2app_options = {
            'iconfile'          : './fs/share/icons/xpra.icns',
            'plist'             : Plist,
            'site_packages'     : False,
            'argv_emulation'    : False,
            'strip'             : False,
            'includes'          : modules,
            'excludes'          : excludes,
            'frameworks'        : ['CoreFoundation', 'Foundation', 'AppKit'],
        }
        setup_options["options"] = {"py2app": py2app_options}
        setup_options["app"]     = ["xpra/scripts/main.py"]


if WIN32 or OSX:
    external_includes += ["ssl", "_ssl"]
    # socks proxy support:
    add_packages("socks")
    if pillow_encoder_ENABLED or pillow_decoder_ENABLED:
        external_includes += ["PIL", "PIL.Image", "PIL.WebPImagePlugin"]
    if crypto_ENABLED or OSX:
        external_includes += ["cffi", "_cffi_backend"]
    if crypto_ENABLED:
        if OSX:
            # quic:
            add_packages("uvloop")
        # python-cryptography needs workarounds for bundling:
        external_includes += [
            "bcrypt", "cryptography", "idna", "idna.idnadata", "appdirs",
        ]
        add_modules(
            "cryptography",
            "cryptography.hazmat",
            "cryptography.hazmat.backends.openssl.backend",
            "cryptography.hazmat.bindings._rust.openssl",
            "cryptography.hazmat.bindings.openssl",
            "cryptography.hazmat.primitives.hashes",
            "cryptography.hazmat.primitives.asymetric",
            "cryptography.hazmat.primitives.ciphers",
            "cryptography.hazmat.primitives.kdf",
            "cryptography.hazmat.primitives.serialization",
            "cryptography.hazmat.primitives.twofactor",
            "cryptography.fernet",
            "cryptography.exceptions",
        )

if POSIX and ism_ext_ENABLED:
    ism_dir = "share/gnome-shell/extensions/input-source-manager@xpra_org"
    add_data_files(ism_dir, glob(f"fs/{ism_dir}/*"))
    add_data_files(ism_dir, ["COPYING"])

if scripts_ENABLED:
    scripts += ["fs/bin/xpra", "fs/bin/xpra_launcher"]
    if not OSX and not WIN32:
        scripts.append("fs/bin/run_scaled")

toggle_packages(WIN32 and service_ENABLED, "xpra/platform/win32/service")

if data_ENABLED:
    if not is_openSUSE():
        add_data_files(share_xpra,                  ["README.md", "COPYING"])
    add_data_files(share_xpra,                      ["fs/share/xpra/bell.wav"])
    if LINUX or FREEBSD:
        add_data_files(share_xpra,                  ["fs/share/xpra/autostart.desktop"])
    ICONS = glob("fs/share/xpra/icons/*.png")
    if OSX:
        ICONS += glob("fs/share/xpra/icons/*.icns")
    if WIN32:
        ICONS += glob("fs/share/xpra/icons/*.ico")
    add_data_files(f"{share_xpra}/icons",         ICONS)
    add_data_files(f"{share_xpra}/images",        glob("fs/share/xpra/images/*"))
    add_data_files(f"{share_xpra}/css",           glob("fs/share/xpra/css/*"))

#*******************************************************************************
if cython_ENABLED:
    add_packages("xpra.buffers")
    tace(cython_ENABLED, "xpra.buffers.membuf,xpra/buffers/memalign.c", optimize=3)
    tace(cython_ENABLED, "xpra.buffers.xxh", "libxxhash", optimize=3)
    if cityhash_ENABLED:
        ace("xpra.buffers.cityhash", optimize=3,
            language="c++",
            extra_link_args="-lcityhash")

    if cython_shared_ENABLED:
        # re-generate shared utility
        from xpra.util.io import which
        major, minor = sys.version_info[:2]
        cython_exe = which(f"python{major}.{minor}-cython") or which("cython") or "/usr/local/bin/cython"
        subprocess.run([cython_exe, "--generate-shared", CYSHARED])
        if os.path.exists(CYSHARED):
            cythonize_kwargs["shared_utility_qualified_name"] = CYSHARED_EXT
            add_cython_ext(CYSHARED_EXT, sources=[CYSHARED])

toggle_packages(dbus_ENABLED, "xpra.dbus")
toggle_packages(server_ENABLED or client_ENABLED, "xpra.auth")
toggle_packages(server_ENABLED or proxy_ENABLED, "xpra.server")
toggle_packages(server_ENABLED and codecs_ENABLED, "xpra.server.encoder")
toggle_packages(server_ENABLED, "xpra.server.runner")
toggle_packages(proxy_ENABLED, "xpra.server.proxy")
toggle_packages(server_ENABLED, "xpra.server.window")
toggle_packages(server_ENABLED and rfb_ENABLED, "xpra.server.rfb")
toggle_packages(server_ENABLED or shadow_ENABLED, "xpra.server.subsystem", "xpra.server.source")
toggle_packages(shadow_ENABLED, "xpra.server.shadow")
toggle_packages(shadow_ENABLED and x11_ENABLED, "xpra.x11.shadow")
toggle_packages(clipboard_ENABLED, "xpra.clipboard")
toggle_packages(x11_ENABLED, "xpra.x11.selection")
toggle_packages(x11_ENABLED and dbus_ENABLED and server_ENABLED, "xpra.x11.dbus")
toggle_packages(uinput_ENABLED, "xpra.x11.uinput")
toggle_packages(notifications_ENABLED, "xpra.notification")

# cannot use toggle here as cx_Freeze will complain if we try to exclude this module:
if dbus_ENABLED and server_ENABLED:
    add_packages("xpra.server.dbus")

tace(OSX, "xpra.platform.darwin.gdk3_bindings,xpra/platform/darwin/transparency_glue.m",
     ("gtk+-3.0", "pygobject-3.0"),
     language="objc",
     extra_compile_args=(
         "-ObjC",
         "-I/System/Library/Frameworks/Cocoa.framework/Versions/A/Headers/",
         "-I/System/Library/Frameworks/AppKit.framework/Versions/C/Headers/"))

toggle_packages(x11_ENABLED, "xpra.x11", "xpra.x11.bindings")
if x11_ENABLED:
    ace("xpra.x11.bindings.xwait", "x11")
    ace("xpra.x11.bindings.wait_for_x_server", "x11")
    ace("xpra.x11.bindings.display_source", "x11")
    ace("xpra.x11.bindings.core", "x11")
    ace("xpra.x11.bindings.ximage", "x11")
    ace("xpra.x11.bindings.xwayland", "x11")
    ace("xpra.x11.bindings.events", "x11")
    ace("xpra.x11.bindings.window", "x11")
    ace("xpra.x11.bindings.loop", "x11")
    if not WIN32:
        ace("xpra.x11.bindings.test", "xtst")
        ace("xpra.x11.bindings.shape", "xext")
        ace("xpra.x11.bindings.damage", "xdamage")
        if pkg_config_exists("xpresent"):
            ace("xpra.x11.bindings.present", "xpresent")
        ace("xpra.x11.bindings.fixes", "xfixes")
        ace("xpra.x11.bindings.cursor", "xcursor")
        ace("xpra.x11.bindings.keyboard", "xkbfile")
        ace("xpra.x11.bindings.res", "xres")
        ace("xpra.x11.bindings.composite", "xcomposite")
        ace("xpra.x11.bindings.xkb", "xkbfile")
        ace("xpra.x11.bindings.saveset", "x11")
        ace("xpra.x11.bindings.classhint", "x11")
        ace("xpra.x11.bindings.shm", "xext")
        ace("xpra.x11.bindings.randr", "xrandr")
        ace("xpra.x11.bindings.record", "xtst")
    tace(xinput_ENABLED, "xpra.x11.bindings.xi2", "x11,xi")

toggle_packages(server_ENABLED and gtk_x11_ENABLED, "xpra.x11.gtk")
toggle_packages(server_ENABLED and x11_ENABLED,
                "xpra.x11.models", "xpra.x11.desktop", "xpra.x11.server", "xpra.x11.subsystem")
if gtk_x11_ENABLED:
    add_packages("xpra.x11.bindings")
    ace("xpra.x11.gtk.display_source", "gdk-3.0")
    ace("xpra.x11.gtk.bindings,xpra/x11/gtk/gdk_x11_macros.c", "gdk-3.0,xdamage,xfixes")

tace(client_ENABLED and gtk3_ENABLED, "xpra.gtk.cairo_image", "py3cairo",
     extra_compile_args=["-Wno-error=parentheses-equality"] if CC_is_clang() else [], optimize=3)


# build tests, but don't install them:
toggle_packages(tests_ENABLED, "unit")


if bundle_tests_ENABLED:
    def bundle_tests() -> None:
        # bundle the tests directly (not in library.zip):
        for k, v in glob_recurse("unit").items():
            if k != "":
                k = os.sep+k
            add_data_files("unit" + k, v)
    bundle_tests()


# special case for client: cannot use toggle_packages which would include bindings, etc:
if client_ENABLED:
    add_modules("xpra.client")
    add_packages("xpra.client.base")
    add_packages("xpra.client.subsystem")
    add_modules("xpra.scripts.pinentry")
    if qt6_client_ENABLED:
        add_modules("xpra.client.qt6")
    if pyglet_client_ENABLED:
        add_modules("xpra.client.pyglet")
    if tk_client_ENABLED:
        add_modules("xpra.client.tk")
toggle_packages(gtk3_ENABLED, "xpra.gtk", "xpra.gtk.examples", "xpra.gtk.dialogs", "xpra.gtk.configure")
toggle_packages(client_ENABLED, "xpra.client.gui", "xpra.client.gui.window")
toggle_packages(client_ENABLED and gtk3_ENABLED, "xpra.client.gtk3", "xpra.client.gtk3.window")
toggle_packages((client_ENABLED and gtk3_ENABLED) or (audio_ENABLED and WIN32 and bool(MINGW_PREFIX)), "gi")
if client_ENABLED and WIN32 and MINGW_PREFIX:
    ace("xpra.platform.win32.propsys,xpra/platform/win32/setappid.cpp",
        language="c++",
        extra_link_args=("-luuid", "-lshlwapi", "-lole32", "-static-libgcc"))

if client_ENABLED or server_ENABLED:
    add_modules("xpra.codecs")
    add_packages("xpra.challenge")
toggle_packages(keyboard_ENABLED, "xpra.keyboard")
toggle_packages(keyboard_ENABLED, "xpra.pointer")
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
    add_modules("xpra.scripts.session")

toggle_packages(not WIN32, "xpra.platform.pycups_printing")
toggle_packages(opengl_ENABLED, "xpra.opengl")
toggle_packages(client_ENABLED and opengl_ENABLED and gtk3_ENABLED, "xpra.client.gtk3.opengl")

toggle_packages(audio_ENABLED, "xpra.audio")
toggle_packages(audio_ENABLED and not (OSX or WIN32), "xpra.audio.pulseaudio")

toggle_packages(clipboard_ENABLED, "xpra.clipboard")
toggle_packages(clipboard_ENABLED or gtk3_ENABLED, "xpra.gtk.bindings")
tace(clipboard_ENABLED, "xpra.gtk.bindings.atoms", "gtk+-3.0")
tace(gtk3_ENABLED, "xpra.gtk.bindings.gobject", "gtk+-3.0,pygobject-3.0")

tace(client_ENABLED or server_ENABLED, "xpra.buffers.cyxor", optimize=3)
tace(client_ENABLED or server_ENABLED or shadow_ENABLED, "xpra.util.rectangle", optimize=3)
tace(server_ENABLED or shadow_ENABLED, "xpra.server.cystats", optimize=3)
tace(server_ENABLED or shadow_ENABLED, "xpra.server.window.motion", optimize=3)
if pam_ENABLED:
    if pkg_config_exists("pam", "pam_misc"):
        pam_kwargs = pkgconfig("pam", "pam_misc")
    else:
        sec_dir = os.path.dirname(find_header_file("security", isdir=True))
        pam_kwargs = {
            "extra_compile_args": "-I" + sec_dir,
            "extra_link_args": ("-lpam", "-lpam_misc"),
        }
    ace("xpra.platform.pam", **pam_kwargs)
if peercred_ENABLED:
    ace("xpra.platform.bsd.peercred")

# platform:
tace(sd_listen_ENABLED, "xpra.platform.posix.sd_listen", "libsystemd")
tace(proc_ENABLED and proc_use_procps, "xpra.platform.posix.proc_procps", "libprocps",
     extra_compile_args="-Wno-error")
tace(proc_ENABLED and proc_use_libproc, "xpra.platform.posix.proc_libproc", "libproc2", language="c++")

# codecs:
toggle_packages(nvidia_ENABLED, "xpra.codecs.nvidia")
toggle_packages(nvidia_ENABLED, "xpra.codecs.nvidia.cuda")
CUDA_BIN = f"{share_xpra}/cuda"
if cuda_kernels_ENABLED:
    kernels = (
        "XRGB_to_NV12", "XRGB_to_YUV444", "BGRX_to_NV12", "BGRX_to_YUV444",
        "BGRX_to_RGB", "RGBX_to_RGB", "RGBA_to_RGBAP", "BGRA_to_RGBAP",
    )
    rebuild = []
    if cuda_rebuild_ENABLED is True:
        rebuild = list(kernels)
    elif cuda_rebuild_ENABLED is None:
        for kernel in kernels:
            cu_src = f"fs/share/xpra/cuda/{kernel}.cu"
            fatbin = f"fs/share/xpra/cuda/{kernel}.fatbin"
            assert os.path.exists(cu_src)
            reason = should_rebuild(cu_src, fatbin)
            if reason:
                print(f"* rebuilding {kernel}: {reason}")
                rebuild.append(kernel)
    if rebuild:
        # add cwd to PYTHONPATH:
        env = os.environ.copy()
        paths = env.pop("PYTHONPATH", "").split(os.pathsep)+[os.getcwd()]
        env["PYTHONPATH"] = os.pathsep.join(paths)
        r = subprocess.Popen(["./fs/bin/build_cuda_kernels.py"]+rebuild, env=env).wait()
        if r!=0:
            print(f"failed to rebuild the cuda kernels {rebuild}")
            sys.exit(1)
    if cuda_kernels_ENABLED:
        add_data_files(CUDA_BIN, [f"fs/share/xpra/cuda/{x}.fatbin" for x in kernels])
    if WIN32 and (nvjpeg_encoder_ENABLED or nvjpeg_decoder_ENABLED or nvenc_ENABLED or nvdec_ENABLED):
        CUDA_BIN_DIR = os.path.abspath("./cuda/")
        add_data_files("", glob(f"{CUDA_BIN_DIR}/cudart64*dll"))
        # if pycuda is built with curand, add this:
        # add_data_files("", glob(f"{CUDA_BIN_DIR}/curand64*dll"))
        if nvjpeg_encoder_ENABLED or nvjpeg_decoder_ENABLED:
            add_data_files("", glob(f"{CUDA_BIN_DIR}/nvjpeg64*dll"))
if cuda_kernels_ENABLED or is_DEB():
    add_data_files(CUDA_BIN, ["fs/share/xpra/cuda/README.md"])

cuda = "cuda"
if nvjpeg_encoder_ENABLED or nvjpeg_decoder_ENABLED or nvdec_ENABLED:
    # try to find a platform specific pkg-config file for cuda:
    cuda_arch = f"cuda-{ARCH}"
    for pcdir in os.environ.get("PKG_CONFIG_PATH", "/usr/lib/pkgconfig:/usr/lib64/pkgconfig").split(":"):
        if os.path.exists(f"{pcdir}/cuda-{ARCH}.pc"):
            cuda = cuda_arch

toggle_packages(nvfbc_ENABLED, "xpra.codecs.nvidia.nvfbc")
# platform: ie: `linux2` -> `linux`, `win32` -> `win`
fbcplatform = sys.platform.rstrip("0123456789")
tace(nvfbc_ENABLED, f"xpra.codecs.nvidia.nvfbc.capture_{fbcplatform}", "nvfbc", language="c++")
tace(nvenc_ENABLED, "xpra.codecs.nvidia.nvenc.nvencode", "nvenc")
tace(nvenc_ENABLED, "xpra.codecs.nvidia.nvenc.api", "nvenc")
tace(nvenc_ENABLED, "xpra.codecs.nvidia.nvenc.encoder", "nvenc")

toggle_packages(argb_ENABLED, "xpra.codecs.argb")
toggle_packages(argb_encoder_ENABLED, "xpra.codecs.argb.encoder")
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
toggle_packages(aom_ENABLED, "xpra.codecs.aom")
tace(aom_ENABLED, "xpra.codecs.aom.api", "aom", language="c++")
tace(aom_ENABLED, "xpra.codecs.aom.decoder", "aom", language="c++")
toggle_packages(pillow_encoder_ENABLED or pillow_decoder_ENABLED, "xpra.codecs.pillow")
toggle_packages(pillow_encoder_ENABLED, "xpra.codecs.pillow.encoder")
toggle_packages(pillow_decoder_ENABLED, "xpra.codecs.pillow.decoder")
toggle_packages(webp_encoder_ENABLED or webp_decoder_ENABLED, "xpra.codecs.webp")
tace(webp_encoder_ENABLED, "xpra.codecs.webp.encoder", "libwebp")
tace(webp_decoder_ENABLED, "xpra.codecs.webp.decoder", "libwebp")
toggle_packages(spng_decoder_ENABLED or spng_encoder_ENABLED, "xpra.codecs.spng")
tace(spng_decoder_ENABLED, "xpra.codecs.spng.decoder", spng_pc)
tace(spng_encoder_ENABLED, "xpra.codecs.spng.encoder", spng_pc)
toggle_packages(nvjpeg_encoder_ENABLED or nvjpeg_decoder_ENABLED, "xpra.codecs.nvidia.nvjpeg")
tace(nvjpeg_encoder_ENABLED or nvjpeg_decoder_ENABLED, "xpra.codecs.nvidia.nvjpeg.common", f"{cuda},nvjpeg")
tace(nvjpeg_encoder_ENABLED, "xpra.codecs.nvidia.nvjpeg.encoder", f"{cuda},nvjpeg")
tace(nvjpeg_decoder_ENABLED, "xpra.codecs.nvidia.nvjpeg.decoder",f"{cuda},nvjpeg")
toggle_packages(jpeg_decoder_ENABLED or jpeg_encoder_ENABLED, "xpra.codecs.jpeg")
tace(jpeg_encoder_ENABLED, "xpra.codecs.jpeg.encoder", "libturbojpeg")
tace(jpeg_decoder_ENABLED, "xpra.codecs.jpeg.decoder", "libturbojpeg")
toggle_packages(avif_ENABLED, "xpra.codecs.avif")
tace(avif_encoder_ENABLED, "xpra.codecs.avif.encoder", "libavif")
tace(avif_decoder_ENABLED, "xpra.codecs.avif.decoder", "libavif")
toggle_packages(csc_libyuv_ENABLED, "xpra.codecs.libyuv")
tace(csc_libyuv_ENABLED, "xpra.codecs.libyuv.converter", "libyuv", language="c++")
toggle_packages(csc_cython_ENABLED, "xpra.codecs.csc_cython")
tace(csc_cython_ENABLED, "xpra.codecs.csc_cython.converter", optimize=3)
toggle_packages(vpx_encoder_ENABLED or vpx_decoder_ENABLED, "xpra.codecs.vpx")
tace(vpx_encoder_ENABLED, "xpra.codecs.vpx.encoder", "vpx")
tace(vpx_decoder_ENABLED, "xpra.codecs.vpx.decoder", "vpx")
toggle_packages(amf_ENABLED, "xpra.codecs.amf")
if amf_ENABLED:
    try:
        amf_kwargs = pkgconfig("amf")
    except ValueError:
        amf_kwargs = {
            "extra_compile_args": "-I" + find_header_file("AMF", isdir=True),
            # "extra_link_args": ("-lpam", "-lpam_misc"),
        }
        print(f"using default amf args: {amf_kwargs}")
    tace(amf_encoder_ENABLED, "xpra.codecs.amf.common", **amf_kwargs)
    tace(amf_encoder_ENABLED, "xpra.codecs.amf.encoder", **amf_kwargs)
    toggle_packages(WIN32, "xpra.platform.win32.d3d11")
    tace(WIN32, "xpra.platform.win32.d3d11.device")
toggle_packages(gstreamer_ENABLED, "xpra.gstreamer")
toggle_packages(gstreamer_video_ENABLED, "xpra.codecs.gstreamer")
toggle_packages(remote_encoder_ENABLED, "xpra.codecs.remote")

toggle_packages(v4l2_ENABLED, "xpra.codecs.v4l2")
tace(v4l2_ENABLED, "xpra.codecs.v4l2.virtual")

# network:
# workaround this warning on MS Windows with Cython 3.0.0b1:
# "warning: comparison of integer expressions of different signedness:
#   'long unsigned int' and 'long int' [-Wsign-compare]"
# simply adding -Wno-error=sign-compare is not enough:
ECA_WIN32SIGN = ["-Wno-error"] if WIN32 else []
toggle_packages(client_ENABLED or server_ENABLED, "xpra.net.protocol", "xpra.net.control")
toggle_packages(websockets_ENABLED, "xpra.net.websockets", "xpra.net.websockets.headers")
tace(websockets_ENABLED, "xpra.net.websockets.mask", optimize=3, extra_compile_args=ECA_WIN32SIGN)
toggle_packages(rencodeplus_ENABLED, "xpra.net.rencodeplus.rencodeplus")
tace(rencodeplus_ENABLED, "xpra.net.rencodeplus.rencodeplus", optimize=3)
toggle_packages(brotli_ENABLED, "xpra.net.brotli")
tace(brotli_ENABLED, "xpra.net.brotli.decompressor", extra_link_args="-lbrotlidec")
tace(brotli_ENABLED, "xpra.net.brotli.compressor", extra_link_args="-lbrotlienc")
toggle_packages(mdns_ENABLED, "xpra.net.mdns")
toggle_packages(mmap_ENABLED, "xpra.net.mmap")
toggle_packages(quic_ENABLED, "xpra.net.asyncio")
toggle_packages(quic_ENABLED, "xpra.net.quic")
toggle_packages(ssh_ENABLED, "xpra.net.ssh", "xpra.net.ssh.paramiko")
toggle_packages(ssl_ENABLED, "xpra.net.ssl")
toggle_packages(http_ENABLED or quic_ENABLED, "xpra.net.http")
toggle_packages(rfb_ENABLED, "xpra.net.rfb")
toggle_packages(qrencode_ENABLED, "xpra.net.qrcode")
tace(qrencode_ENABLED, "xpra.net.qrcode.qrencode", extra_link_args="-lqrencode", extra_compile_args=ECA_WIN32SIGN)
tace(netdev_ENABLED, "xpra.platform.posix.netdev_query")
toggle_packages(vsock_ENABLED, "xpra.net.vsock")
tace(vsock_ENABLED, "xpra.net.vsock.vsock")
toggle_packages(lz4_ENABLED, "xpra.net.lz4")
tace(lz4_ENABLED, "xpra.net.lz4.lz4", "liblz4")

toggle_packages(wayland_client_ENABLED or wayland_server_ENABLED, "xpra.wayland")
tace(wayland_client_ENABLED, "xpra.wayland.wait_for_display", "wayland-client")
XDG_SHELL_PROTOCOL_HEADER = "./xpra/wayland/xdg-shell-protocol.h"
if wayland_server_ENABLED and not os.path.exists(XDG_SHELL_PROTOCOL_HEADER):
    print("generating %r" % XDG_SHELL_PROTOCOL_HEADER)
    subprocess.run(["wayland-scanner", "server-header",
                    "/usr/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml",
                    XDG_SHELL_PROTOCOL_HEADER])
tace(wayland_server_ENABLED, "xpra.wayland.compositor", "wlroots-0.19,libdrm,wayland-server,pixman-1",
     extra_compile_args=["-DWLR_USE_UNSTABLE", "-I./xpra/wayland/"])
tace(wayland_server_ENABLED, "xpra.wayland.pointer", "wlroots-0.19,wayland-server",
     extra_compile_args=["-DWLR_USE_UNSTABLE", "-I./xpra/wayland/"])
tace(wayland_server_ENABLED, "xpra.wayland.keyboard", "wlroots-0.19,wayland-server",
     extra_compile_args=["-DWLR_USE_UNSTABLE", "-I./xpra/wayland/"])
toggle_packages(wayland_server_ENABLED, "xpra.wayland.models")

if cythonize_more_ENABLED:
    def ax(base):
        dirname = base.replace(".", os.path.sep)
        for x in glob(f"{dirname}/*.py"):
            if not x.endswith("__init__.py"):
                mod = x[:-3].replace(os.path.sep, ".")
                ace(mod)

    if opengl_ENABLED:
        ax("xpra.opengl")
    if client_ENABLED:
        ax("xpra.client.base")
        if gtk3_ENABLED:
            ax("xpra.client.gtk3")
            ax("xpra.client.gtk3.window")
            if opengl_ENABLED:
                ax("xpra.client.gtk3.opengl")
        ax("xpra.client.gui")
        ax("xpra.client.gui.window")
        ax("xpra.client.subsystem")
        if qt6_client_ENABLED:
            ax("xpra.client.qt6")
        if pyglet_client_ENABLED:
            ax("xpra.client.pyglet")
        if tk_client_ENABLED:
            ax("xpra.client.tk")
    if client_ENABLED or server_ENABLED:
        ax("xpra.challenge")
    if clipboard_ENABLED:
        ax("xpra.clipboard")
    if codecs_ENABLED:
        ax("xpra.codecs")
        if pillow_encoder_ENABLED or pillow_decoder_ENABLED:
            ax("xpra.codecs.pillow")
            if pillow_encoder_ENABLED:
                ax("xpra.codecs.pillow.encoder")
            if pillow_decoder_ENABLED:
                ax("xpra.codecs.pillow.decoder")
        if gstreamer_video_ENABLED:
            ax("xpra.codecs.gstreamer")
        if remote_encoder_ENABLED:
            ax("xpra.codecs.remote")
    if gstreamer_ENABLED:
        ax("xpra.gstreamer")
    if gtk3_ENABLED:
        ax("xpra.gtk")
        ax("xpra.gtk.dialogs")
        ax("xpra.gtk.configure")
        if example_ENABLED:
            ax("xpra.gtk.examples")
    if keyboard_ENABLED:
        ax("xpra.keyboard")
    if http_ENABLED:
        ax("xpra.net.http")
    if mdns_ENABLED:
        ax("xpra.net.mdns")
    if mmap_ENABLED:
        ax("xpra.net.mmap")
    ax("xpra.net.protocol")
    ax("xpra.net.control")
    if qrencode_ENABLED and gtk3_ENABLED:
        ace("xpra.gtk.dialogs.qrcode")
    if quic_ENABLED:
        ax("xpra.net.ayncio")
        ax("xpra.net.quic")
    if rfb_ENABLED:
        ax("xpra.net.rfb")
    if ssh_ENABLED:
        ax("xpra.net.ssh")
        ax("xpra.net.ssh.paramiko")
    if ssl_ENABLED:
        ax("xpra.net.ssl")
    if websockets_ENABLED:
        ax("xpra.net.websockets.headers")
        ax("xpra.net.websockets")
    ax("xpra.net")
    if notifications_ENABLED:
        ax("xpra.notification")
    ace("xpra.platform.dotxpra_common")
    ace("xpra.platform.paths")
    ace("xpra.platform.ui_thread_watcher")
    if LINUX:
        ace("xpra.platform.posix.shadow_server")
    if scripts_ENABLED:
        ax("xpra.scripts")
    if WIN32 and service_ENABLED:
        ace("xpra.platform.win32.service")
    if server_ENABLED or client_ENABLED:
        ax("xpra.auth")
    if server_ENABLED:
        if dbus_ENABLED:
            ax("xpra.server.dbus")
        ax("xpra.server.subsystem")
        if proxy_ENABLED:
            ax("xpra.server.proxy")
        if rfb_ENABLED:
            ax("xpra.server.rfb")
        if shadow_ENABLED:
            ax("xpra.server.shadow")
        if codecs_ENABLED:
            ax("xpra.server.encoder")
        ax("xpra.server.runner")
        ax("xpra.server.source")
        ax("xpra.server.window")
        ax("xpra.server")
    if gtk_x11_ENABLED:
        ax("xpra.x11.gtk")
    if x11_ENABLED:
        ax("xpra.x11")
        ax("xpra.x11.desktop")
        ax("xpra.x11.models")
        ax("xpra.x11.subsystem")
        if server_ENABLED:
            ax("xpra.x11.server")
        if uinput_ENABLED:
            ax("xpra.x11.uinput")
    if wayland_client_ENABLED or wayland_server_ENABLED:
        ax("xpra.wayland")

    ax("xpra.util")
    ace("xpra.common")
    ace("xpra.exit_codes")
    ace("xpra.log")
    ace("xpra.os_util")
    if gstreamer_ENABLED:
        ax("xpra.gstreamer")


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
        compiler_directives |= {
            # "warn.undeclared"       : True,
            # "warn.maybe_uninitialized" : True,
            "warn.unused"           : True,
            "warn.unused_result"    : True,
        }
    if cython_tracing_ENABLED:
        compiler_directives |= {
            "linetrace" : True,
            "binding" : True,
            "profile" : True,
        }

    nthreads = int(os.environ.get("NTHREADS", 0 if (debug_ENABLED or WIN32 or OSX or ARM or RISCV or sys.version_info >= (3, 14)) else os.cpu_count()))
    setup_options["ext_modules"] = cythonize(ext_modules,
                                             nthreads=nthreads,
                                             gdb_debug=debug_ENABLED,
                                             compiler_directives=compiler_directives,
                                             **cythonize_kwargs
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
