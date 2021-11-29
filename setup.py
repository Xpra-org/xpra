#!/usr/bin/env python3

# This file is part of Xpra.
# Copyright (C) 2010-2021 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

##############################################################################
# FIXME: Cython.Distutils.build_ext leaves crud in the source directory.

import sys
if sys.version_info<(3, 6):
    raise Exception("xpra no longer supports Python versions older than 3.6")

import glob
import shlex
import shutil
import os.path
import subprocess

from distutils.core import setup
from distutils.extension import Extension
from distutils.command.build import build
from distutils.command.install_data import install_data

import xpra
from xpra.os_util import (
    get_status_output, load_binary_file, get_distribution_version_id,
    BITS, WIN32, OSX, LINUX, POSIX, NETBSD, FREEBSD, OPENBSD,
    is_Ubuntu, is_Debian, is_Fedora, is_CentOS, is_RedHat,
    )


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
                 "name"             : "xpra",
                 "version"          : XPRA_VERSION,
                 "license"          : "GPLv2+",
                 "author"           : "Antoine Martin",
                 "author_email"     : "antoine@xpra.org",
                 "url"              : url,
                 "download_url"     : "https://xpra.org/src/",
                 "description"      : description,
                 "long_description" : long_description,
                 "data_files"       : data_files,
                 "py_modules"       : modules,
                 }


if "pkg-info" in sys.argv:
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
    sys.exit(0)


print("Xpra version %s" % XPRA_VERSION)
#*******************************************************************************
# Most of the options below can be modified on the command line
# using --with-OPTION or --without-OPTION
# only the default values are specified here:
#*******************************************************************************

PKG_CONFIG = os.environ.get("PKG_CONFIG", "pkg-config")
has_pkg_config = False
if PKG_CONFIG:
    v = get_status_output([PKG_CONFIG, "--version"])
    has_pkg_config = v[0]==0 and v[1]
    if has_pkg_config:
        print("found pkg-config version: %s" % v[1].strip("\n\r"))
    else:
        print("WARNING: pkg-config not found!")

for arg in list(sys.argv):
    if arg.startswith("--pkg-config-path="):
        pcp = arg[len("--pkg-config-path="):]
        pcps = [pcp] + os.environ.get("PKG_CONFIG_PATH", "").split(os.path.pathsep)
        os.environ["PKG_CONFIG_PATH"] = os.path.pathsep.join([x for x in pcps if x])
        print("using PKG_CONFIG_PATH=%s" % (os.environ["PKG_CONFIG_PATH"], ))
        sys.argv.remove(arg)

def no_pkgconfig(*_pkgs_options, **_ekw):
    return {}

def pkg_config_ok(*args):
    return get_status_output([PKG_CONFIG] + [str(x) for x in args])[0]==0

def pkg_config_version(req_version, pkgname):
    cmd = [PKG_CONFIG, "--modversion", pkgname]
    r, out, _ = get_status_output(cmd)
    if r!=0 or not out:
        return False
    from distutils.version import LooseVersion
    return LooseVersion(out)>=LooseVersion(req_version)

def is_RH():
    try:
        with open("/etc/redhat-release", mode='rb') as rel:
            data = rel.read()
        return data.startswith(b"CentOS") or data.startswith(b"RedHat")
    except (FileNotFoundError, OSError):
        pass
    return False

DEFAULT = True
if "--minimal" in sys.argv:
    sys.argv.remove("--minimal")
    DEFAULT = False
skip_build = "--skip-build" in sys.argv
ARCH = get_status_output(["uname", "-m"])[1]
ARM = ARCH.startswith("arm") or ARCH.startswith("aarch")
print("ARCH=%s" % (ARCH,))

INCLUDE_DIR = os.environ.get("INCLUDE_DIR", os.path.join(sys.prefix, "include"))

from xpra.platform.features import LOCAL_SERVERS_SUPPORTED, SHADOW_SUPPORTED
shadow_ENABLED = SHADOW_SUPPORTED and DEFAULT
server_ENABLED = (LOCAL_SERVERS_SUPPORTED or shadow_ENABLED) and DEFAULT
rfb_ENABLED = DEFAULT
service_ENABLED = LINUX and server_ENABLED
sd_listen_ENABLED = POSIX and pkg_config_ok("--exists", "libsystemd")
proxy_ENABLED  = DEFAULT
client_ENABLED = DEFAULT
scripts_ENABLED = not WIN32
cython_ENABLED = DEFAULT
cython_tracing_ENABLED = False
modules_ENABLED = DEFAULT
data_ENABLED = DEFAULT

x11_ENABLED = DEFAULT and not WIN32 and not OSX
xinput_ENABLED = x11_ENABLED
uinput_ENABLED = x11_ENABLED
dbus_ENABLED = DEFAULT and x11_ENABLED and not (OSX or WIN32)
gtk_x11_ENABLED = DEFAULT and not WIN32 and not OSX
gtk3_ENABLED = DEFAULT and client_ENABLED
opengl_ENABLED = DEFAULT and client_ENABLED
pam_ENABLED = DEFAULT and (server_ENABLED or proxy_ENABLED) and POSIX and not OSX and (os.path.exists(INCLUDE_DIR+"/pam/pam_misc.h") or os.path.exists(INCLUDE_DIR+"/security/pam_misc.h"))

xdg_open_ENABLED        = (LINUX or FREEBSD) and DEFAULT
netdev_ENABLED          = LINUX and DEFAULT
vsock_ENABLED           = LINUX and os.path.exists(INCLUDE_DIR+"/linux/vm_sockets.h")
bencode_ENABLED         = DEFAULT
cython_bencode_ENABLED  = DEFAULT
rencodeplus_ENABLED     = DEFAULT
clipboard_ENABLED       = DEFAULT
Xdummy_ENABLED          = None if POSIX else False  #None means auto-detect
Xdummy_wrapper_ENABLED  = None if POSIX else False  #None means auto-detect
if WIN32 or OSX:
    Xdummy_ENABLED = False
sound_ENABLED           = DEFAULT
printing_ENABLED        = DEFAULT
crypto_ENABLED          = DEFAULT
mdns_ENABLED            = DEFAULT
websockets_ENABLED      = DEFAULT

enc_proxy_ENABLED       = DEFAULT
enc_x264_ENABLED        = DEFAULT and pkg_config_version("0.155", "x264")
#crashes on 32-bit windows:
enc_x265_ENABLED        = (not WIN32) and pkg_config_ok("--exists", "x265")
pillow_ENABLED          = DEFAULT
webp_ENABLED            = DEFAULT and pkg_config_version("0.5", "libwebp")
jpeg_encoder_ENABLED    = DEFAULT and pkg_config_version("1.2", "libturbojpeg")
jpeg_decoder_ENABLED    = DEFAULT and pkg_config_version("1.4", "libturbojpeg")
vpx_ENABLED             = DEFAULT and pkg_config_version("1.4", "vpx")
enc_ffmpeg_ENABLED      = DEFAULT and BITS==64 and pkg_config_version("58.18", "libavcodec")
#opencv currently broken on 32-bit windows (crashes on load):
webcam_ENABLED          = DEFAULT and not OSX and not WIN32
notifications_ENABLED   = DEFAULT
keyboard_ENABLED        = DEFAULT
v4l2_ENABLED            = DEFAULT and (not WIN32 and not OSX and not FREEBSD and not OPENBSD)
#ffmpeg 3.1 or later is required
dec_avcodec2_ENABLED    = DEFAULT and BITS==64 and pkg_config_version("57", "libavcodec")
csc_swscale_ENABLED     = DEFAULT and BITS==64 and pkg_config_ok("--exists", "libswscale")
csc_cython_ENABLED      = DEFAULT
nvjpeg_ENABLED = DEFAULT and not OSX and not ARM and BITS==64 and pkg_config_ok("--exists", "nvjpeg")
nvenc_ENABLED = DEFAULT and not OSX and not ARM and BITS==64 and pkg_config_version("10", "nvenc")
nvfbc_ENABLED = DEFAULT and not OSX and not ARM and BITS==64 and pkg_config_ok("--exists", "nvfbc")
cuda_kernels_ENABLED    = DEFAULT and not OSX
cuda_rebuild_ENABLED    = DEFAULT
csc_libyuv_ENABLED      = DEFAULT and pkg_config_ok("--exists", "libyuv")
example_ENABLED         = DEFAULT

#Cython / gcc / packaging build options:
docs_ENABLED            = DEFAULT
annotate_ENABLED        = DEFAULT
warn_ENABLED            = True
strict_ENABLED          = True
PIC_ENABLED             = not WIN32     #ming32 moans that it is always enabled already
debug_ENABLED           = False
verbose_ENABLED         = False
bundle_tests_ENABLED    = False
tests_ENABLED           = False
rebuild_ENABLED         = not skip_build

#allow some of these flags to be modified on the command line:
SWITCHES = [
    "cython", "cython_tracing",
    "modules", "data",
    "enc_x264", "enc_x265", "enc_ffmpeg",
    "nvenc", "cuda_kernels", "cuda_rebuild", "nvfbc",
    "vpx", "webp", "pillow", "jpeg_encoder", "jpeg_decoder",
    "nvjpeg",
    "v4l2",
    "dec_avcodec2", "csc_swscale",
    "csc_cython", "csc_libyuv",
    "bencode", "cython_bencode", "rencodeplus",
    "vsock", "netdev", "mdns",
    "clipboard",
    "scripts",
    "server", "client", "dbus", "x11", "xinput", "uinput", "sd_listen",
    "gtk_x11", "service",
    "gtk3", "example",
    "pam", "xdg_open",
    "sound", "opengl", "printing", "webcam", "notifications", "keyboard",
    "rebuild",
    "docs",
    "annotate", "warn", "strict",
    "shadow", "proxy", "rfb",
    "debug", "PIC",
    "Xdummy", "Xdummy_wrapper", "verbose", "tests", "bundle_tests",
    ]
HELP = "-h" in sys.argv or "--help" in sys.argv
if HELP:
    setup()
    print("Xpra specific build and install switches:")
    for x in SWITCHES:
        d = vars()["%s_ENABLED" % x]
        with_str = "  --with-%s" % x
        without_str = "  --without-%s" % x
        if d is True or d is False:
            default_str = str(d)
        else:
            default_str = "auto-detect"
        print("%s or %s (default: %s)" % (with_str.ljust(25), without_str.ljust(30), default_str))
    print("  --pkg-config-path=PATH")
    print("  --rpath=PATH")
    sys.exit(0)

install = None
rpath = None
ssl_cert = None
ssl_key = None
minifier = None
share_xpra = None
filtered_args = []
for arg in sys.argv:
    matched = False
    for x in ("rpath", "ssl-cert", "ssl-key", "install", "share-xpra"):
        varg = "--%s=" % x
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
        with_str = "--with-%s" % x
        without_str = "--without-%s" % x
        if arg.startswith(with_str+"="):
            vars()["%s_ENABLED" % x] = arg[len(with_str)+1:]
            matched = True
            break
        elif arg==with_str:
            vars()["%s_ENABLED" % x] = True
            matched = True
            break
        elif arg==without_str:
            vars()["%s_ENABLED" % x] = False
            matched = True
            break
    if not matched:
        filtered_args.append(arg)
sys.argv = filtered_args
if "clean" not in sys.argv:
    switches_info = {}
    for x in SWITCHES:
        switches_info[x] = vars()["%s_ENABLED" % x]
    print("build switches:")
    for k in sorted(SWITCHES):
        v = switches_info[k]
        print("* %s : %s" % (str(k).ljust(20), {None : "Auto", True : "Y", False : "N"}.get(v, v)))

    if not cython_ENABLED:
        enc_ffmpeg_ENABLED = enc_x264_ENABLED = enc_x265_ENABLED = nvenc_ENABLED = False
        csc_swscale_ENABLED = csc_libyuv_ENABLED = csc_cython_ENABLED = False
        vpx_ENABLED = nvfbc_ENABLED = dec_avcodec2_ENABLED = False
        webp_ENABLED = jpeg_encoder_ENABLED = jpeg_decoder_ENABLED = False
        server_ENABLED = client_ENABLED = shadow_ENABLED = False
        cython_bencode_ENABLED = rencodeplus_ENABLED = False
        gtk3_ENABLED = False
        x11_ENABLED = False
    #sanity check the flags:
    if clipboard_ENABLED and not server_ENABLED and not gtk3_ENABLED:
        print("Warning: clipboard can only be used with the server or one of the gtk clients!")
        clipboard_ENABLED = False
    if x11_ENABLED and WIN32:
        print("Warning: enabling x11 on MS Windows is unlikely to work!")
    if gtk_x11_ENABLED and not x11_ENABLED:
        print("Error: you must enable x11 to support gtk_x11!")
        exit(1)
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
    cmd = [pandoc, "--from", "markdown", "--to", fmt, "-o", fdst, fsrc]
    if fmt=="html":
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
            print("copying %s -> %s (%s)" % (fsrc, fdst, oct(0o644)))
            os.makedirs(name=dst, mode=0o755, exist_ok=True)
            data = load_binary_file(fsrc)
            with open(fdst, "wb") as f:
                f.write(data)
                os.chmod(fdst, 0o644)
        else:
            print("ignoring '%s'" % fsrc)

def convert_docs(fmt="html"):
    paths = [x for x in sys.argv[2:] if not x.startswith("--")]
    if len(paths)==1 and os.path.isdir(paths[0]):
        convert_doc_dir("docs", paths[0])
    elif paths:
        for x in paths:
            convert_doc(x, "build/%s" % x)
    else:
        convert_doc_dir("docs", "build/docs")


if "doc" in sys.argv:
    convert_docs("html")
    sys.exit(0)

if "pdf-doc" in sys.argv:
    convert_docs("pdf")
    sys.exit(0)

if "unittests" in sys.argv:
    os.execv("./tests/unittests/run", ["run"])



#*******************************************************************************
# default sets:

external_includes = ["hashlib",
                     "ctypes", "platform"]


if gtk3_ENABLED or sound_ENABLED:
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
                    "setuptools", "doctest"
                    "nose", "pytest", "_pytest", "pluggy", "more_itertools", "apipkg", "py", "funcsigs",
                    "Cython", "cython", "pyximport",
                    "pydoc_data",
                    ]
if not crypto_ENABLED:
    external_excludes += ["ssl", "_ssl"]
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
    global packages, modules, excludes
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
    global packages
    for x in pkgs:
        if x not in packages:
            packages.append(x)
    add_modules(*pkgs)

def add_modules(*mods):
    def add(v):
        global modules
        if v not in modules:
            modules.append(v)
    do_add_modules(add, *mods)

def do_add_modules(op, *mods):
    """ adds the packages and any .py module found in the packages to the "modules" list
    """
    global modules
    for x in mods:
        #ugly path stripping:
        if x.startswith("./"):
            x = x[2:]
        if x.endswith(".py"):
            x = x[:-3]
            x = x.replace("/", ".") #.replace("\\", ".")
        pathname = os.path.sep.join(x.split("."))
        #is this a file module?
        f = "%s.py" % pathname
        if os.path.exists(f) and os.path.isfile(f):
            op(x)
        if os.path.exists(pathname) and os.path.isdir(pathname):
            #add all file modules found in this directory
            for f in os.listdir(pathname):
                #make sure we only include python files,
                #and ignore eclipse copies
                if f.endswith(".py") and not f.startswith("Copy ")<0:
                    fname = os.path.join(pathname, f)
                    if os.path.isfile(fname):
                        modname = "%s.%s" % (x, f.replace(".py", ""))
                        op(modname)

def toggle_packages(enabled, *module_names):
    if enabled:
        add_packages(*module_names)
    else:
        remove_packages(*module_names)

def toggle_modules(enabled, *module_names):
    if enabled:
        def op(v):
            global modules
            if v not in modules:
                modules.append(v)
        do_add_modules(op, *module_names)
    else:
        remove_packages(*module_names)


#always included:
if modules_ENABLED:
    add_modules("xpra", "xpra.platform", "xpra.net")
    add_modules("xpra.scripts.main")


def add_data_files(target_dir, files):
    #this is overriden below because cx_freeze uses the opposite structure (files first...). sigh.
    assert isinstance(target_dir, str)
    assert isinstance(files, (list, tuple))
    data_files.append((target_dir, files))


#for pretty printing of options:
def print_option(prefix, k, v):
    if isinstance(v, dict):
        print("%s* %s:" % (prefix, k))
        for kk,vv in v.items():
            print_option(" "+prefix, kk, vv)
    else:
        print("%s* %s=%s" % (prefix, k, v))

#*******************************************************************************
# Utility methods for building with Cython
compiler_directives = {
    "auto_pickle"           : False,
    "language_level"        : 3,
    "cdivision"             : True,
    "always_allow_keywords" : False,
    "unraisable_tracebacks" : True,
    }
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

def add_cython_ext(*args, **kwargs):
    if "--no-compile" in sys.argv and not ("build" in sys.argv and "install" in sys.argv):
        return
    assert cython_ENABLED, "cython compilation is disabled"
    if cython_tracing_ENABLED:
        kwargs["define_macros"] = [
            ('CYTHON_TRACE', 1),
            ('CYTHON_TRACE_NOGIL', 1),
            ]
        extra_compile_args = kwargs.setdefault("extra_compile_args", [])
        extra_compile_args += ["-fpermissive", "-Wno-error"]
    from Cython.Distutils import build_ext
    global cmdclass, ext_modules
    ext_modules.append(Extension(*args, **kwargs))
    cmdclass['build_ext'] = build_ext

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
    while values and value in values:
        values.remove(value)


def checkdirs(*dirs):
    for d in dirs:
        if not os.path.exists(d) or not os.path.isdir(d):
            raise Exception("cannot find a directory which is required for building: '%s'" % d)


GCC_VERSION = []
def get_gcc_version():
    global GCC_VERSION
    if not GCC_VERSION:
        cc = os.environ.get("CC", "gcc")
        r, _, err = get_status_output([cc]+["-v"])
        if r==0:
            V_LINE = "gcc version "
            for line in err.splitlines():
                if line.startswith(V_LINE):
                    v_str = line[len(V_LINE):].split(" ")[0]
                    for p in v_str.split("."):
                        try:
                            GCC_VERSION.append(int(p))
                        except ValueError:
                            break
                    print("found gcc version: %s" % ".".join([str(x) for x in GCC_VERSION]))
                    break
    return GCC_VERSION



# Tweaked from http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/502261
def exec_pkgconfig(*pkgs_options, **ekw):
    kw = dict(ekw)
    optimize = kw.pop("optimize", None)
    if optimize and not debug_ENABLED and not cython_tracing_ENABLED:
        if isinstance(optimize, bool):
            optimize = int(optimize)*3
        add_to_keywords(kw, 'extra_compile_args', "-O%i" % optimize)
    ignored_flags = kw.pop("ignored_flags", [])
    ignored_tokens = kw.pop("ignored_tokens", [])

    #for distros that don't patch distutils,
    #we have to add the python cflags:
    if not (is_Fedora() or is_Debian() or is_CentOS() or is_RedHat()):
        import sysconfig
        for cflag in shlex.split(sysconfig.get_config_var('CFLAGS') or ''):
            add_to_keywords(kw, 'extra_compile_args', cflag)

    def add_tokens(s, extra="extra_link_args", extra_map={"-W" : "extra_compile_args"}):
        if not s:
            return
        flag_map = {'-I': 'include_dirs',
                    '-L': 'library_dirs',
                    '-l': 'libraries'}
        for token in shlex.split(s):
            if token in ignored_tokens:
                pass
            elif token[:2] in ignored_flags:
                pass
            elif token[:2] in flag_map:
                if len(token)>2:
                    add_to_keywords(kw, flag_map.get(token[:2]), token[2:])
                else:
                    print("Warning: invalid token '%s'" % token)
            else:
                extra_name = extra_map.get(token, extra)
                add_to_keywords(kw, extra_name, token)

    if pkgs_options:
        pkg_config_cmd = ["pkg-config", "--libs", "--cflags", "%s" % (" ".join(pkgs_options),)]
        if verbose_ENABLED:
            print("pkg_config_cmd=%s" % (pkg_config_cmd,))
        r, pkg_config_out, err = get_status_output(pkg_config_cmd)
        if r!=0:
            sys.exit("ERROR: call to '%s' failed (err=%s)" % (" ".join(pkg_config_cmd), err))
        add_tokens(pkg_config_out)
    if warn_ENABLED:
        add_to_keywords(kw, 'extra_compile_args', "-Wall")
        add_to_keywords(kw, 'extra_link_args', "-Wall")
    if strict_ENABLED:
        if os.environ.get("CC", "").find("clang")>=0:
            #clang emits too many warnings with cython code,
            #so we can't enable Werror without turning off some warnings:
            #this list of flags should allow clang to build the whole source tree,
            #as of Cython 0.26 + clang 4.0. Other version combinations may require
            #(un)commenting other switches.
            eifd = ["-Werror",
                    #"-Wno-unneeded-internal-declaration",
                    #"-Wno-unknown-attributes",
                    #"-Wno-unused-function",
                    #"-Wno-self-assign",
                    #"-Wno-sometimes-uninitialized",
                    #cython adds rpath to the compilation command??
                    #and the "-specs=/usr/lib/rpm/redhat/redhat-hardened-cc1" is also ignored by clang:
                    "-Wno-deprecated-register",
                    "-Wno-unused-command-line-argument",
                    ]
        elif get_gcc_version()>=[4, 4]:
            eifd = ["-Werror"]
            if NETBSD:
                #see: http://trac.cython.org/ticket/395
                eifd += ["-fno-strict-aliasing"]
            elif FREEBSD:
                eifd += ["-Wno-error=unused-function"]
        else:
            #older versions of OSX ship an old gcc,
            #not much we can do with this:
            eifd = []
        for eif in eifd:
            add_to_keywords(kw, 'extra_compile_args', eif)
        remove_from_keywords(kw, 'extra_compile_args', "-fpermissive")
    if PIC_ENABLED:
        add_to_keywords(kw, 'extra_compile_args', "-fPIC")
    if debug_ENABLED:
        add_to_keywords(kw, 'extra_compile_args', '-g')
        add_to_keywords(kw, 'extra_compile_args', '-ggdb')
        if get_gcc_version()>=[4, 8] and not WIN32:
            add_to_keywords(kw, 'extra_compile_args', '-fsanitize=address')
            add_to_keywords(kw, 'extra_link_args', '-fsanitize=address')
    if rpath and kw.get("libraries"):
        insert_into_keywords(kw, "library_dirs", rpath)
        insert_into_keywords(kw, "extra_link_args", "-Wl,-rpath=%s" % rpath)
    add_tokens(os.environ.get("CFLAGS"), "extra_compile_args", {})
    add_tokens(os.environ.get("LDFLAGS"), "extra_link_args", {})
    #add_to_keywords(kw, 'include_dirs', '.')
    if verbose_ENABLED:
        print("exec_pkgconfig(%s,%s)=%s" % (pkgs_options, ekw, kw))
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
    from xpra.scripts import config
    config.debug = config.warn
    conf_dir = get_conf_dir(install_dir)
    return config.detect_xvfb_command(conf_dir, None, Xdummy_ENABLED, Xdummy_wrapper_ENABLED)

def build_xpra_conf(install_dir):
    print("build_xpra_conf(%s)" % install_dir)
    #generates an actual config file from the template
    xvfb_command = detect_xorg_setup(install_dir)
    fake_xinerama = "no"
    if POSIX and not OSX and not (is_Debian() or is_Ubuntu()):
        from xpra.x11.fakeXinerama import find_libfakeXinerama
        fake_xinerama = find_libfakeXinerama() or "auto"
    from xpra.platform.features import DEFAULT_ENV, SOURCE
    def bstr(b):
        if b is None:
            return "auto"
        return "yes" if int(b) else "no"
    start_env = "\n".join("start-env = %s" % x for x in DEFAULT_ENV)
    source = "\n".join("source = %s" % x for x in SOURCE)
    conf_dir = get_conf_dir(install_dir)
    print("get_conf_dir(%s)=%s" % (install_dir, conf_dir))
    from xpra.platform.features import DEFAULT_PULSEAUDIO_CONFIGURE_COMMANDS
    from xpra.platform.paths import get_socket_dirs
    from xpra.scripts.config import (
        xvfb_cmd_str,
        get_default_key_shortcuts, get_default_systemd_run, get_default_pulseaudio_command,
        DEFAULT_POSTSCRIPT_PRINTER, DEFAULT_PULSEAUDIO,
        )
    #remove build paths and user specific paths with UID ("/run/user/UID/Xpra"):
    socket_dirs = get_socket_dirs()
    if POSIX and os.getuid()>0:
        #remove any paths containing the uid,
        #osx uses /var/tmp/$UID-Xpra,
        #but this should not be included in the default config for all users!
        #(the buildbot's uid!)
        socket_dirs = [x for x in socket_dirs if x.find(str(os.getuid()))<0]
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
            print("pdf=%s, postscript=%s" % (pdf, postscript))
        except Exception as e:
            print("could not probe for pdf/postscript printers: %s" % e)
    def pretty_cmd(cmd):
        return " ".join(cmd)
    #OSX doesn't have webcam support yet (no opencv builds on 10.5.x)
    webcam = webcam_ENABLED and not (OSX or WIN32)
    #no python-avahi on RH / CentOS, need dbus module on *nix:
    mdns = mdns_ENABLED and (OSX or WIN32 or (not is_RH() and dbus_ENABLED))
    SUBS = {
            'xvfb_command'          : xvfb_cmd_str(xvfb_command, wrap=True),
            'fake_xinerama'         : fake_xinerama,
            'ssh_command'           : "auto",
            'key_shortcuts'         : "".join(("key-shortcut = %s\n" % x) for x in get_default_key_shortcuts()),
            'remote_logging'        : "both",
            'start_env'             : start_env,
            'pulseaudio'            : bstr(DEFAULT_PULSEAUDIO),
            'pulseaudio_command'    : pretty_cmd(get_default_pulseaudio_command()),
            'pulseaudio_configure_commands' : "\n".join(("pulseaudio-configure-commands = %s" % pretty_cmd(x)) for x in DEFAULT_PULSEAUDIO_CONFIGURE_COMMANDS),
            'conf_dir'              : conf_dir,
            'bind'                  : "auto",
            'ssl_cert'              : ssl_cert or "",
            'ssl_key'               : ssl_key or "",
            'systemd_run'           : get_default_systemd_run(),
            'socket_dirs'           : "".join(("socket-dirs = %s\n" % x) for x in socket_dirs),
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
        print("convert_templates(%s) dirname=%s, target_dir=%s" % (subdirs, dirname, target_dir))
        if not os.path.exists(target_dir):
            try:
                os.makedirs(target_dir)
            except Exception as e:
                print("cannot create target dir '%s': %s" % (target_dir, e))
        for f in sorted(os.listdir(dirname)):
            if f.endswith("osx.conf.in") and not OSX:
                continue
            filename = os.path.join(dirname, f)
            if os.path.isdir(filename):
                convert_templates(subdirs+[f])
                continue
            if not f.endswith(".in"):
                continue
            with open(filename, "r") as f_in:
                template  = f_in.read()
            target_file = os.path.join(target_dir, f[:-len(".in")])
            print("generating %s from %s" % (target_file, f))
            with open(target_file, "w") as f_out:
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
                   "xpra/x11/bindings/wait_for_x_server.c",
                   "xpra/x11/bindings/keyboard_bindings.c",
                   "xpra/x11/bindings/display_source.c",
                   "xpra/x11/bindings/window_bindings.c",
                   "xpra/x11/bindings/randr_bindings.c",
                   "xpra/x11/bindings/res_bindings.c",
                   "xpra/x11/bindings/core_bindings.c",
                   "xpra/x11/bindings/posix_display_source.c",
                   "xpra/x11/bindings/ximage.c",
                   "xpra/x11/bindings/xi2_bindings.c",
                   "xpra/platform/win32/propsys.cpp",
                   "xpra/platform/darwin/gdk_bindings.c",
                   "xpra/platform/xposix/sd_listen.c",
                   "xpra/platform/xposix/netdev_query.c",
                   "xpra/net/bencode/cython_bencode.c",
                   "xpra/net/rencodeplus/rencodeplus.c",
                   "xpra/net/websockets/mask.c",
                   "xpra/net/vsock.c",
                   "xpra/buffers/membuf.c",
                   "xpra/buffers/xxh.c",
                   "xpra/buffers/cyxor.c",
                   "xpra/codecs/vpx/encoder.c",
                   "xpra/codecs/vpx/decoder.c",
                   "xpra/codecs/nvenc/encoder.c",
                   "xpra/codecs/nvfbc/fbc_capture_linux.cpp",
                   "xpra/codecs/nvfbc/fbc_capture_win.cpp",
                   "xpra/codecs/enc_x264/encoder.c",
                   "xpra/codecs/enc_x265/encoder.c",
                   "xpra/codecs/jpeg/encoder.c",
                   "xpra/codecs/jpeg/decoder.c",
                   "xpra/codecs/enc_ffmpeg/encoder.c",
                   "xpra/codecs/v4l2/pusher.c",
                   "xpra/codecs/v4l2/constants.pxi",
                   "xpra/codecs/libav_common/av_log.c",
                   "xpra/codecs/webp/encoder.c",
                   "xpra/codecs/webp/decoder.c",
                   "xpra/codecs/dec_avcodec2/decoder.c",
                   "xpra/codecs/csc_libyuv/colorspace_converter.cpp",
                   "xpra/codecs/csc_swscale/colorspace_converter.c",
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
        CLEAN_FILES += [
            "fs/share/xpra/cuda/XRGB_to_NV12.fatbin",
            "fs/share/xpra/cuda/XRGB_to_YUV444.fatbin",
            "fs/share/xpra/cuda/BGRX_to_NV12.fatbin",
            "fs/share/xpra/cuda/BGRX_to_YUV444.fatbin",
            "fs/share/xpra/cuda/BGRX_to_RGB.fatbin",
            "fs/share/xpra/cuda/RGBX_to_RGB.fatbin",
            ]
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
                print("removing Cython/build generated file: %s" % x)
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
    remove_packages("xpra.platform.darwin", "xpra.platform.xposix")

    #this is where the win32 gi installer will put things:
    gnome_include_path = os.environ.get("MINGW_PREFIX")

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

        #cx_freeze doesn't use "data_files"...
        del setup_options["data_files"]
        #it wants source files first, then where they are placed...
        #one item at a time (no lists)
        #all in its own structure called "include_files" instead of "data_files"...
        def add_data_files(target_dir, files):
            if verbose_ENABLED:
                print("add_data_files(%s, %s)" % (target_dir, files))
            assert isinstance(target_dir, str)
            assert isinstance(files, (list, tuple))
            for f in files:
                target_file = os.path.join(target_dir, os.path.basename(f))
                data_files.append((f, target_file))

        #pass a potentially nested dictionary representing the tree
        #of files and directories we do want to include
        def add_dir(base, defs):
            if verbose_ENABLED:
                print("add_dir(%s, %s)" % (base, defs))
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
                            print("Warning: missing '%s'" % filename)
            else:
                assert isinstance(defs, dict)
                for d, sub in defs.items():
                    assert isinstance(sub, (dict, list, tuple))
                    #recurse down:
                    add_dir(os.path.join(base, d), sub)

        def add_gi_typelib(*libs):
            if verbose_ENABLED:
                print("add_gi_typelib(%s)" % str(libs))
            add_dir('lib',      {"girepository-1.0":    ["%s.typelib" % x for x in libs]})
        def add_gi_gir(*libs):
            if verbose_ENABLED:
                print("add_gi_gir(%s)" % str(libs))
            add_dir('share',    {"gir-1.0" :            ["%s.gir" % x for x in libs]})
        #convenience method for adding GI libs and "typelib" and "gir":
        def add_gi(*libs):
            add_gi_typelib(*libs)
            add_gi_gir(*libs)

        def add_DLLs(*dll_names):
            try:
                do_add_DLLs("lib", *dll_names)
            except Exception as e:
                print("Error: failed to add DLLs: %s" % (dll_names, ))
                print(" %s" % e)
                sys.exit(1)

        def do_add_DLLs(prefix="lib", *dll_names):
            dll_names = list(dll_names)
            dll_files = []
            import re
            version_re = re.compile(r"-[0-9\.-]+$")
            dirs = os.environ.get("PATH").split(os.path.pathsep)
            if os.path.exists(gnome_include_path):
                dirs.insert(0, gnome_include_path)
            if verbose_ENABLED:
                print("add_DLLs: looking for %s in %s" % (dll_names, dirs))
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
                        print("checking %s: %s" % (x, nameversion))
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
                    print(" - %s%s*.dll" % (prefix, x))
            add_data_files("", dll_files)

        #list of DLLs we want to include, without the "lib" prefix, or the version and extension
        #(ie: "libatk-1.0-0.dll" -> "atk")
        if sound_ENABLED or gtk3_ENABLED:
            add_DLLs('gio', 'girepository', 'glib',
                     'gnutls', 'gobject', 'gthread',
                     'orc', 'stdc++',
                     'winpthread',
                     )
        if gtk3_ENABLED:
            add_DLLs('atk',
                     #'dbus', 'dbus-glib',
                     'gdk', 'gdk_pixbuf', 'gtk',
                     'cairo-gobject', 'pango', 'pangocairo', 'pangoft2', 'pangowin32',
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
        if gtk3_ENABLED or sound_ENABLED:
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
            packages.append("qrencode")
            add_DLLs("qrencode")

        if sound_ENABLED:
            add_dir("share", ["gst-plugins-base", "gstreamer-1.0"])
            add_gi("Gst-1.0", "GstAllocators-1.0", "GstAudio-1.0", "GstBase-1.0",
                   "GstTag-1.0")
            add_DLLs('gstreamer', 'orc-test')
            for p in ("app", "audio", "base", "codecparsers", "fft", "net", "video",
                      "pbutils", "riff", "sdp", "rtp", "rtsp", "tag", "uridownloader",
                      #I think 'coreelements' needs those (otherwise we would exclude them):
                      "basecamerabinsrc", "mpegts", "photography",
                      ):
                add_DLLs('gst%s' % p)
            #DLLs needed by the plugins:
            add_DLLs("faac", "faad", "flac", "mpg123")      #"mad" is no longer included?
            #add the gstreamer plugins we need:
            GST_PLUGINS = ("app",
                           "cutter",
                           #muxers:
                           "gdp", "matroska", "ogg", "isomp4",
                           "audioparsers", "audiorate", "audioconvert", "audioresample", "audiotestsrc",
                           "coreelements", "directsound", "directsoundsrc", "wasapi",
                           #codecs:
                           "opus", "opusparse", "flac", "lame", "mpg123", "speex", "faac", "faad",
                           "volume", "vorbis", "wavenc", "wavpack", "wavparse",
                           "autodetect",
                           #no longer available: "mad"
                           #untested: a52dec, voaacenc
                           )
            add_dir(os.path.join("lib", "gstreamer-1.0"), [("libgst%s.dll" % x) for x in GST_PLUGINS])
            #END OF SOUND

        if server_ENABLED:
            #used by proxy server:
            external_includes += ["multiprocessing", "setproctitle"]

        external_includes += ["encodings"]
        external_includes += ["mimetypes"]
        if client_ENABLED:
            #for parsing "open-command":
            external_includes += ["shlex"]
            #for version check:
            external_includes += [
                                  "ftplib", "fileinput",
                                  ]
            external_includes += ["urllib", "http.cookiejar", "http.client"]
            #for websocket browser cookie
            external_includes += ["browser_cookie3", "pyaes", "pbkdf2", "keyring"]

        if dec_avcodec2_ENABLED:
            #why isn't this one picked up automatically?
            add_DLLs("x265")

        #hopefully, cx_Freeze will fix this horror:
        #(we shouldn't have to deal with DLL dependencies)
        import site
        lib_python = os.path.dirname(site.getsitepackages()[0])
        lib_dynload_dir = os.path.join(lib_python, "lib-dynload")
        add_data_files('', glob.glob("%s/zlib*dll" % lib_dynload_dir))
        for x in ("io", "codecs", "abc", "_weakrefset", "encodings"):
            add_data_files("lib/", glob.glob("%s/%s*" % (lib_python, x)))
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
        if nvenc_ENABLED or nvfbc_ENABLED:
            add_packages("numpy.core._methods", "numpy.lib.format")

        setup_options["options"] = {"build_exe" : cx_freeze_options}
        executables = []
        setup_options["executables"] = executables

        def add_exe(script, icon, base_name, base="Console"):
            executables.append(Executable(
                        script                  = script,
                        initScript              = None,
                        #targetDir               = "dist",
                        icon                    = "fs/share/xpra/icons/%s" % icon,
                        targetName              = "%s.exe" % base_name,
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
            add_gui_exe("xpra/platform/win32/scripts/shadow_server.py",       "server-notconnected.ico",    "Xpra-Shadow")
            add_gui_exe("fs/bin/xpra_launcher",                "xpra.ico",         "Xpra-Launcher")
            add_console_exe("fs/bin/xpra_launcher",            "xpra.ico",         "Xpra-Launcher-Debug")
            add_gui_exe("xpra/gtk_common/gtk_view_keyboard.py", "keyboard.ico",     "GTK_Keyboard_Test")
            add_gui_exe("xpra/scripts/bug_report.py",           "bugs.ico",         "Bug_Report")
            add_gui_exe("xpra/platform/win32/gdi_screen_capture.py", "screenshot.ico", "Screenshot")
        if server_ENABLED:
            add_gui_exe("fs/bin/auth_dialog",                  "authentication.ico", "Auth_Dialog")
        if mdns_ENABLED and gtk3_ENABLED:
            add_gui_exe("xpra/client/gtk_base/mdns_gui.py",     "mdns.ico",         "Xpra_Browser")
        #Console: provide an Xpra_cmd.exe we can run from the cmd.exe shell
        add_console_exe("fs/bin/xpra",                     "xpra_txt.ico",     "Xpra_cmd")
        add_console_exe("xpra/scripts/version.py",          "information.ico",  "Version_info")
        add_console_exe("xpra/net/net_util.py",             "network.ico",      "Network_info")
        if gtk3_ENABLED:
            add_console_exe("xpra/scripts/gtk_info.py",         "gtk.ico",          "GTK_info")
            add_console_exe("xpra/gtk_common/keymap.py",        "keymap.ico",       "Keymap_info")
            add_console_exe("xpra/platform/keyboard.py",        "keymap.ico",       "Keyboard_info")
            add_gui_exe("xpra/client/gtk_base/example/tray.py", "xpra.ico",         "SystemTray_Test")
            add_gui_exe("xpra/client/gtk_base/u2f_tool.py",     "authentication.ico", "U2F_Tool")
        if client_ENABLED or server_ENABLED:
            add_console_exe("xpra/platform/win32/scripts/exec.py",     "python.ico", "Python_exec_cmd")
            add_console_exe("xpra/platform/win32/scripts/execfile.py", "python.ico", "Python_execfile_cmd")
            add_console_exe("xpra/platform/win32/scripts/execfile.py", "python.ico", "Python_execfile_gui")
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
        if sound_ENABLED:
            add_console_exe("xpra/sound/gstreamer_util.py",     "gstreamer.ico",    "GStreamer_info")
            add_console_exe("fs/bin/xpra",                     "speaker.ico",      "Xpra_Audio")
            add_console_exe("xpra/platform/win32/directsound.py", "speaker.ico",      "Audio_Devices")
            #add_console_exe("xpra/sound/src.py",                "microphone.ico",   "Sound_Record")
            #add_console_exe("xpra/sound/sink.py",               "speaker.ico",      "Sound_Play")
        if opengl_ENABLED:
            add_console_exe("xpra/client/gl/gl_check.py",   "opengl.ico",       "OpenGL_check")
        if webcam_ENABLED:
            add_console_exe("xpra/platform/webcam.py",          "webcam.ico",    "Webcam_info")
            add_console_exe("xpra/scripts/show_webcam.py",          "webcam.ico",    "Webcam_Test")
        if printing_ENABLED:
            add_console_exe("xpra/platform/printing.py",        "printer.ico",     "Print")
            add_console_exe("xpra/platform/win32/pdfium.py",    "printer.ico",     "PDFIUM_Print")
            do_add_DLLs("", "pdfium")
        if nvenc_ENABLED:
            add_console_exe("xpra/codecs/nv_util.py",                   "nvidia.ico",   "NVidia_info")
        if nvfbc_ENABLED:
            add_console_exe("xpra/codecs/nvfbc/capture.py",             "nvidia.ico",   "NvFBC_capture")
        if nvfbc_ENABLED or nvenc_ENABLED:
            add_console_exe("xpra/codecs/cuda_common/cuda_context.py",  "cuda.ico",     "CUDA_info")

    if ("install_exe" in sys.argv) or ("install" in sys.argv):
        #FIXME: how do we figure out what target directory to use?
        print("calling build_xpra_conf in-place")
        #building etc files in-place:
        if data_ENABLED:
            build_xpra_conf("./fs")
            add_data_files('etc/xpra', glob.glob("fs/etc/xpra/*conf"))
            add_data_files('etc/xpra', glob.glob("fs/etc/xpra/nvenc*.keys"))
            add_data_files('etc/xpra', glob.glob("fs/etc/xpra/nvfbc*.keys"))
            add_data_files('etc/xpra/conf.d', glob.glob("fs/etc/xpra/conf.d/*conf"))

    if data_ENABLED:
        add_data_files("",              ["packaging/MSWindows/website.url"])
        add_data_files("",              ["packaging/MSWindows/DirectShow.tlb"])

    remove_packages(*external_excludes)
    external_includes.append("pyu2f")
    external_includes.append("mmap")
    external_includes.append("comtypes")    #used by webcam and netdev_query
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

    if nvenc_ENABLED or nvfbc_ENABLED:
        external_includes.append("numpy")
    else:
        remove_packages("unittest", "difflib",  #avoid numpy warning (not an error)
                        "pydoc")

    #make sure we don't include the gstreamer 0.10 "pygst" bindings:
    remove_packages("pygst", "gst", "gst.extend")

    #add subset of PyOpenGL modules (only when installing):
    if opengl_ENABLED and "install_exe" in sys.argv:
        #for this hack to work, you must add "." to the sys.path
        #so python can load OpenGL from the install directory
        #(further complicated by the fact that "." is the "frozen" path...)
        #but we re-add those two directories to the library.zip as part of the build script
        import OpenGL
        print("*** copying PyOpenGL modules to %s ***" % install)
        glmodules = {
            "OpenGL" : OpenGL,
            }
        try:
            import OpenGL_accelerate        #@UnresolvedImport
        except ImportError as e:
            print("Warning: missing OpenGL_accelerate module")
            print(" %s" % e)
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
                print("copied %s to %s/%s" % (module_dir, install, module_name))
            except Exception as e:
                if not isinstance(e, WindowsError) or ("already exists" not in str(e)): #@UndefinedVariable
                    raise

    if data_ENABLED:
        add_data_files("share/metainfo",      ["fs/share/metainfo/xpra.appdata.xml"])
        for d in ("http-headers", "content-type", "content-categories"):
            add_data_files("etc/xpra/%s" % d, glob.glob("fs/etc/%s/*" % d))

        add_data_files('', glob.glob("packaging/MSWindows/bundle-extra/*"))

    #END OF win32
#*******************************************************************************
else:
    #OSX and *nix:
    if FREEBSD:
        icons_dir = "icons"
    else:
        icons_dir = "pixmaps"
    if is_Fedora() or is_CentOS() or is_RedHat() or FREEBSD:
        libexec = "libexec"
    else:
        libexec = "lib"
    if LINUX or FREEBSD:
        if scripts_ENABLED:
            scripts += ["fs/bin/xpra_udev_product_version", "fs/bin/xpra_signal_listener"]
        libexec_scripts = []
        if xdg_open_ENABLED:
            libexec_scripts += ["fs/bin/xdg-open", "fs/bin/gnome-open", "fs/bin/gvfs-open"]
        if server_ENABLED:
            libexec_scripts.append("fs/bin/auth_dialog")
        if libexec_scripts:
            add_data_files("%s/xpra/" % libexec, libexec_scripts)
    if data_ENABLED:
        man_path = "share/man"
        icons_dir = "icons"
        if OPENBSD or FREEBSD:
            man_path = "man"
            icons_dir = "pixmaps"
        man_pages = ["fs/share/man/man1/xpra.1", "fs/share/man/man1/xpra_launcher.1"]
        if not OSX:
            man_pages.append("fs/share/man/man1/run_scaled.1")
        add_data_files("%s/man1" % man_path,  man_pages)
        add_data_files("share/applications",  glob.glob("fs/share/applications/*.desktop"))
        add_data_files("share/mime/packages", ["fs/share/mime/packages/application-x-xpraconfig.xml"])
        add_data_files("share/%s" % icons_dir, glob.glob("fs/share/icons/*.png"))
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
            except:
                build_base = self.build_base
            build_xpra_conf(build_base)

    class install_data_override(install_data):
        def run(self):
            print("install_data_override: install_dir=%s" % self.install_dir)
            install_data.run(self)

            root_prefix = self.install_dir.rstrip("/")
            if root_prefix.endswith("/usr"):
                root_prefix = root_prefix[:-4]    #ie: "/" or "/usr/src/rpmbuild/BUILDROOT/xpra-0.18.0-0.20160513r12573.fc23.x86_64/"
            build_xpra_conf(root_prefix)

            def copytodir(src, dst_dir, dst_name=None, chmod=0o644, subs=None):
                #print("copytodir%s" % (src, dst_dir, dst_name, chmod, subs))
                #convert absolute paths:
                if dst_dir.startswith("/"):
                    dst_dir = root_prefix+dst_dir
                else:
                    dst_dir = self.install_dir.rstrip("/")+"/"+dst_dir
                #make sure the target directory exists:
                self.mkpath(dst_dir)
                #generate the target filename:
                filename = os.path.basename(src)
                dst_file = os.path.join(dst_dir, dst_name or filename)
                #copy it
                print("copying %s -> %s (%s)" % (src, dst_dir, oct(chmod)))
                data = load_binary_file(src)
                if subs:
                    for k,v in subs.items():
                        data = data.replace(k, v)
                with open(dst_file, "wb") as f:
                    f.write(data)
                if chmod:
                    print("chmod(%s, %s)" % (dst_file, oct(chmod)))
                    os.chmod(dst_file, chmod)

            def dirtodir(src_dir, dst_dir):
                print("dirtodir(%s, %s)" % (src_dir, dst_dir))
                for f in os.listdir(src_dir):
                    copytodir(os.path.join(src_dir, f), dst_dir)

            if printing_ENABLED and POSIX:
                #install "/usr/lib/cups/backend" with 0700 permissions:
                lib_cups = "lib/cups"
                if FREEBSD:
                    lib_cups = "libexec/cups"
                copytodir("fs/lib/cups/xpraforwarder", "%s/backend" % lib_cups, chmod=0o700)

            if x11_ENABLED:
                #install xpra_Xdummy if we need it:
                xvfb_command = detect_xorg_setup()
                if any(x.find("xpra_Xdummy")>=0 for x in (xvfb_command or [])) or Xdummy_wrapper_ENABLED is True:
                    copytodir("fs/bin/xpra_Xdummy", "bin", chmod=0o755)
                #install xorg*.conf, cuda.conf and nvenc.keys:
                etc_xpra_files = ["xorg.conf"]
                if uinput_ENABLED:
                    etc_xpra_files.append("xorg-uinput.conf")
                if nvenc_ENABLED or nvfbc_ENABLED:
                    etc_xpra_files.append("cuda.conf")
                if nvenc_ENABLED:
                    etc_xpra_files.append("nvenc.keys")
                if nvfbc_ENABLED:
                    etc_xpra_files.append("nvfbc.keys")
                for x in etc_xpra_files:
                    copytodir("fs/etc/xpra/%s" % x, "/etc/xpra")
                copytodir("fs/etc/X11/xorg.conf.d/90-xpra-virtual.conf", "/etc/X11/xorg.conf.d/")

            if pam_ENABLED:
                copytodir("fs/etc/pam.d/xpra", "/etc/pam.d")

            systemd_dir = "/lib/systemd/system"
            if service_ENABLED:
                #Linux init service:
                subs = {}
                if is_RedHat() or is_CentOS() or is_Fedora():
                    cdir = "/etc/sysconfig"
                elif is_Debian() or is_Ubuntu():
                    cdir = "/etc/default"
                elif os.path.exists("/etc/sysconfig"):
                    cdir = "/etc/sysconfig"
                else:
                    cdir = "/etc/default"
                copytodir("fs/etc/sysconfig/xpra", cdir)
                if cdir!="/etc/sysconfig":
                    #also replace the reference to it in the service file below
                    subs[b"/etc/sysconfig"] = cdir.encode()
                if os.path.exists("/bin/systemctl"):
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
                if WIN32 or OSX:
                    #keep everything in our own directory:
                    doc_dir = "%s/share/xpra/doc" % self.install_dir
                else:
                    doc_dir = "%s/share/doc/xpra" % self.install_dir
                convert_doc_dir("./docs", doc_dir)

            if data_ENABLED:
                for d in ("http-headers", "content-type", "content-categories"):
                    dirtodir("fs/etc/xpra/%s" % d, "/etc/xpra/%s" % d)

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
        remove_packages("xpra.platform.win32", "xpra.platform.xposix")
        #to support GStreamer 1.x we need this:
        modules.append("importlib")
        modules.append("mimetypes")
        external_excludes.append("numpy")
    else:
        add_packages("xpra.platform.xposix")
        remove_packages("xpra.platform.win32", "xpra.platform.darwin")
        if data_ENABLED:
            #not supported by all distros, but doesn't hurt to install them anyway:
            if not FREEBSD:
                for x in ("tmpfiles.d", "sysusers.d"):
                    add_data_files("lib/%s" % x, ["fs/lib/%s/xpra.conf" % x])
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
        def add_cython_ext(*_args, **_kwargs):
            pass

        remove_packages("ctypes.wintypes", "colorsys")
        remove_packages(*external_excludes)

        try:
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
            "CFBundleGetInfoString" : "%s-%s (c) 2012-2020 https://xpra.org/" % (XPRA_VERSION, REVISION),
            "CFBundleIdentifier"            : "org.xpra.xpra",
            }
        #Note: despite our best efforts, py2app will not copy all the modules we need
        #so the make-app.sh script still has to hack around this problem.
        add_modules(*external_includes)
        #needed by python-lz4:
        add_modules("distutils")
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


if scripts_ENABLED:
    scripts += ["fs/bin/xpra", "fs/bin/xpra_launcher"]
    if not OSX and not WIN32:
        scripts.append("fs/bin/run_scaled")
toggle_modules(WIN32, "xpra/scripts/win32_service")

if data_ENABLED:
    add_data_files(share_xpra,                      ["README.md", "COPYING"])
    add_data_files(share_xpra,                      ["fs/share/xpra/bell.wav"])
    if LINUX:
        add_data_files(share_xpra,                  ["fs/share/xpra/autostart.desktop"])
    ICONS = glob.glob("fs/share/xpra/icons/*.png")
    if OSX:
        ICONS += glob.glob("fs/share/xpra/icons/*.icns")
    if WIN32:
        ICONS += glob.glob("fs/share/xpra/icons/*.ico")
    add_data_files("%s/icons" % share_xpra,          ICONS)
    add_data_files("%s/css" % share_xpra,            glob.glob("fs/share/xpra/css/*"))


if WIN32 or OSX:
    external_includes.append("ssl")
    external_includes.append("_ssl")


if annotate_ENABLED:
    from Cython.Compiler import Options
    Options.annotate = True
    Options.docstrings = False
    Options.buffer_max_dims = 3


#*******************************************************************************
if modules_ENABLED:
    add_packages("xpra.buffers")
    buffers_pkgconfig = pkgconfig(optimize=3)
    import platform
    if platform.machine()=="i386":
        #this may well be sub-optimal:
        add_to_keywords(buffers_pkgconfig, "extra_compile_args", "-mfpmath=387")
    if cython_ENABLED:
        add_cython_ext("xpra.buffers.membuf",
                       ["xpra/buffers/membuf.pyx", "xpra/buffers/memalign.c"], **buffers_pkgconfig)
        add_cython_ext("xpra.buffers.xxh",
                       ["xpra/buffers/xxh.pyx", "xpra/buffers/xxhash.c"], **buffers_pkgconfig)


toggle_packages(dbus_ENABLED, "xpra.dbus")
toggle_packages(mdns_ENABLED, "xpra.net.mdns")
toggle_packages(websockets_ENABLED, "xpra.net.websockets", "xpra.net.websockets.headers")
toggle_packages(server_ENABLED or proxy_ENABLED, "xpra.server", "xpra.server.auth")
toggle_packages(rfb_ENABLED, "xpra.net.rfb")
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

if OSX:
    quartz_pkgconfig = pkgconfig("gtk+-3.0", "pygobject-3.0")
    add_to_keywords(quartz_pkgconfig, 'extra_compile_args',
                "-ObjC",
                "-framework", "AppKit",
                "-I/System/Library/Frameworks/Cocoa.framework/Versions/A/Headers/",
                "-I/System/Library/Frameworks/AppKit.framework/Versions/C/Headers/")
    add_cython_ext("xpra.platform.darwin.gdk3_bindings",
            ["xpra/platform/darwin/gdk3_bindings.pyx", "xpra/platform/darwin/transparency_glue.m"],
            language="objc",
            **quartz_pkgconfig
            )

toggle_packages(x11_ENABLED, "xpra.x11", "xpra.x11.bindings")
if x11_ENABLED:
    add_cython_ext("xpra.x11.bindings.wait_for_x_server",
                ["xpra/x11/bindings/wait_for_x_server.pyx"],
                **pkgconfig("x11")
                )
    add_cython_ext("xpra.x11.bindings.display_source",
                ["xpra/x11/bindings/display_source.pyx"],
                **pkgconfig("x11")
                )
    add_cython_ext("xpra.x11.bindings.core_bindings",
                ["xpra/x11/bindings/core_bindings.pyx"],
                **pkgconfig("x11")
                )
    add_cython_ext("xpra.x11.bindings.posix_display_source",
                ["xpra/x11/bindings/posix_display_source.pyx"],
                **pkgconfig("x11")
                )

    add_cython_ext("xpra.x11.bindings.randr_bindings",
                ["xpra/x11/bindings/randr_bindings.pyx"],
                **pkgconfig("x11", "xrandr")
                )
    add_cython_ext("xpra.x11.bindings.keyboard_bindings",
                ["xpra/x11/bindings/keyboard_bindings.pyx"],
                **pkgconfig("x11", "xtst", "xfixes", "xkbfile")
                )

    add_cython_ext("xpra.x11.bindings.window_bindings",
                ["xpra/x11/bindings/window_bindings.pyx"],
                **pkgconfig("x11", "xtst", "xfixes", "xcomposite", "xdamage", "xext")
                )
    add_cython_ext("xpra.x11.bindings.ximage",
                ["xpra/x11/bindings/ximage.pyx"],
                **pkgconfig("x11", "xext", "xcomposite")
                )
    add_cython_ext("xpra.x11.bindings.res_bindings",
                ["xpra/x11/bindings/res_bindings.pyx"],
                **pkgconfig("x11", "xres")
                )
if xinput_ENABLED:
    add_cython_ext("xpra.x11.bindings.xi2_bindings",
                ["xpra/x11/bindings/xi2_bindings.pyx"],
                **pkgconfig("x11", "xi")
                )

toggle_packages(gtk_x11_ENABLED, "xpra.x11.gtk_x11")
toggle_packages(server_ENABLED and gtk_x11_ENABLED, "xpra.x11.models")
if gtk_x11_ENABLED:
    add_packages("xpra.x11.gtk3")
    #GTK3 display source:
    add_cython_ext("xpra.x11.gtk3.gdk_display_source",
                ["xpra/x11/gtk3/gdk_display_source.pyx"],
                **pkgconfig("gdk-3.0")
                )
    add_cython_ext("xpra.x11.gtk3.gdk_bindings",
                ["xpra/x11/gtk3/gdk_bindings.pyx", "xpra/x11/gtk3/gdk_x11_macros.c"],
                **pkgconfig("gdk-3.0", "xdamage")
                )

if client_ENABLED and gtk3_ENABLED:
    #cairo workaround:
    add_cython_ext("xpra.client.gtk3.cairo_workaround",
                ["xpra/client/gtk3/cairo_workaround.pyx"],
                **pkgconfig("py3cairo")
                )

if client_ENABLED or server_ENABLED:
    add_packages("xpra.codecs.argb")
    argb_pkgconfig = pkgconfig(optimize=3)
    add_cython_ext("xpra.codecs.argb.argb",
                ["xpra/codecs/argb/argb.pyx"], **argb_pkgconfig)


#build tests, but don't install them:
toggle_packages(tests_ENABLED, "unit")


if bundle_tests_ENABLED:
    #bundle the tests directly (not in library.zip):
    for k,v in glob_recurse("unit").items():
        if k!="":
            k = os.sep+k
        add_data_files("unit"+k, v)

#python-cryptography needs workarounds for bundling:
if crypto_ENABLED and (OSX or WIN32):
    external_includes.append("_ssl")
    external_includes.append("cffi")
    external_includes.append("_cffi_backend")
    external_includes.append("cryptography")
    external_includes.append("idna")
    external_includes.append("idna.idnadata")
    external_includes.append("pkg_resources._vendor.packaging")
    external_includes.append("pkg_resources._vendor.packaging.requirements")
    external_includes.append("pkg_resources._vendor.pyparsing")
    add_modules("cryptography.hazmat.bindings._openssl")
    add_modules("cryptography.hazmat.bindings._constant_time")
    add_modules("cryptography.hazmat.bindings._padding")
    add_modules("cryptography.hazmat.backends.openssl")
    add_modules("cryptography.fernet")
    if WIN32:
        external_includes.append("appdirs")

#special case for client: cannot use toggle_packages which would include gtk3, etc:
if client_ENABLED:
    add_modules("xpra.client")
    add_packages("xpra.client.mixins", "xpra.client.auth")
    add_modules("xpra.scripts.gtk_info", "xpra.scripts.show_webcam", "xpra.scripts.pinentry_wrapper")
if gtk3_ENABLED:
    add_modules("xpra.scripts.bug_report")
toggle_packages((client_ENABLED and gtk3_ENABLED) or sound_ENABLED or server_ENABLED, "xpra.gtk_common")
toggle_packages(client_ENABLED and gtk3_ENABLED, "xpra.client.gtk3")
toggle_packages((client_ENABLED and gtk3_ENABLED) or (sound_ENABLED and WIN32 and MINGW_PREFIX), "gi")
toggle_packages(client_ENABLED and gtk3_ENABLED, "xpra.client.gtk_base")
toggle_packages(client_ENABLED and opengl_ENABLED and gtk3_ENABLED, "xpra.client.gl.gtk3")
toggle_packages(client_ENABLED and gtk3_ENABLED and example_ENABLED, "xpra.client.gtk_base.example")
if client_ENABLED and WIN32 and MINGW_PREFIX:
    propsys_pkgconfig = pkgconfig()
    if debug_ENABLED:
        add_to_keywords(propsys_pkgconfig, 'extra_compile_args', "-DDEBUG")
    add_to_keywords(propsys_pkgconfig, 'extra_link_args', "-luuid", "-lshlwapi", "-lole32", "-static-libgcc")
    add_cython_ext("xpra.platform.win32.propsys",
                ["xpra/platform/win32/propsys.pyx", "xpra/platform/win32/setappid.cpp"],
                language="c++",
                **propsys_pkgconfig)

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

toggle_modules(sound_ENABLED, "xpra.sound")
toggle_modules(sound_ENABLED and not (OSX or WIN32), "xpra.sound.pulseaudio")

toggle_packages(clipboard_ENABLED, "xpra.clipboard")
if clipboard_ENABLED:
    add_cython_ext("xpra.gtk_common.gtk3.gdk_atoms",
                         ["xpra/gtk_common/gtk3/gdk_atoms.pyx"],
                         **pkgconfig("gtk+-3.0")
                         )
toggle_packages(clipboard_ENABLED or gtk3_ENABLED, "xpra.gtk_common.gtk3")
if gtk3_ENABLED:
    add_cython_ext("xpra.gtk_common.gtk3.gdk_bindings",
                ["xpra/gtk_common/gtk3/gdk_bindings.pyx"],
                **pkgconfig("gtk+-3.0", "pygobject-3.0")
                )

O3_pkgconfig = pkgconfig(optimize=3)
if client_ENABLED or server_ENABLED:
    add_cython_ext("xpra.buffers.cyxor",
                ["xpra/buffers/cyxor.pyx"],
                **O3_pkgconfig)
if client_ENABLED or server_ENABLED or shadow_ENABLED:
    add_cython_ext("xpra.rectangle",
                ["xpra/rectangle.pyx"],
                **O3_pkgconfig)

if server_ENABLED or shadow_ENABLED:
    add_cython_ext("xpra.server.cystats",
                ["xpra/server/cystats.pyx"],
                **O3_pkgconfig)
    add_cython_ext("xpra.server.window.motion",
                ["xpra/server/window/motion.pyx"],
                **O3_pkgconfig)

if sd_listen_ENABLED:
    sdp = pkgconfig("libsystemd")
    add_cython_ext("xpra.platform.xposix.sd_listen",
                ["xpra/platform/xposix/sd_listen.pyx"],
                **sdp)


toggle_packages(enc_proxy_ENABLED, "xpra.codecs.enc_proxy")

toggle_packages(nvfbc_ENABLED, "xpra.codecs.nvfbc")
if nvfbc_ENABLED:
    nvfbc_pkgconfig = pkgconfig("nvfbc")
    if WIN32:
        add_to_keywords(nvfbc_pkgconfig, 'extra_compile_args', "-Wno-endif-labels")
    platform = sys.platform.rstrip("0123456789")
    add_cython_ext("xpra.codecs.nvfbc.fbc_capture_%s" % platform,
                         ["xpra/codecs/nvfbc/fbc_capture_%s.pyx" % platform],
                         language="c++",
                         **nvfbc_pkgconfig)

toggle_packages(nvenc_ENABLED, "xpra.codecs.nvenc")
toggle_packages(nvenc_ENABLED or nvfbc_ENABLED, "xpra.codecs.cuda_common")
toggle_packages(nvenc_ENABLED or nvfbc_ENABLED, "xpra.codecs.nv_util")

CUDA_BIN = "%s/cuda" % share_xpra
if (nvenc_ENABLED and cuda_kernels_ENABLED) or nvjpeg_ENABLED:
    #find nvcc:
    from xpra.util import sorted_nicely
    path_options = os.environ.get("PATH", "").split(os.path.pathsep)
    if WIN32:
        external_includes += ["pycuda"]
        nvcc_exe = "nvcc.exe"
        CUDA_DIR = os.environ.get("CUDA_DIR", "C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA")
        path_options += list(reversed(sorted_nicely(glob.glob("%s\\*\\bin" % CUDA_DIR))))
        #pycuda may link against curand, find it and ship it:
        for p in path_options:
            if os.path.exists(p):
                add_data_files("", glob.glob("%s\\curand64*.dll" % p))
                add_data_files("", glob.glob("%s\\cudart64*.dll" % p))
                break
    else:
        nvcc_exe = "nvcc"
        path_options += list(reversed(sorted_nicely(glob.glob("/usr/local/cuda*/bin"))))
        path_options += list(reversed(sorted_nicely(glob.glob("/opt/cuda*/bin"))))
    options = [os.path.join(x, nvcc_exe) for x in path_options]
    def which(cmd):
        try:
            code, out, _ = get_status_output(["command", "-v", cmd])
            if code==0:
                return out
        except:
            pass
        return None
    #prefer the one we find on the $PATH, if any:
    try:
        v = which(nvcc_exe)
        if v and (v not in options):
            options.insert(0, v)
    except:
        pass
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
            version_str = " version %s" % version
        else:
            version = "0"
            version_str = " unknown version!"
        print("found CUDA compiler: %s%s" % (filename, version_str))
        return tuple(int(x) for x in version.split("."))
    for filename in options:
        vnum = get_nvcc_version(filename)
        if vnum:
            nvcc_versions[vnum] = filename
    if nvcc_versions:
        #choose the most recent one:
        version, nvcc = list(reversed(sorted(nvcc_versions.items())))[0]
        if len(nvcc_versions)>1:
            print(" using version %s from %s" % (version, nvcc))
    else:
        version = nvcc = None
    if ((nvenc_ENABLED or nvjpeg_ENABLED) and cuda_kernels_ENABLED):
        assert nvcc_versions, "cannot find nvcc compiler!"
        #first compile the cuda kernels
        #(using the same cuda SDK for both nvenc modules for now..)
        #TODO:
        # * compile directly to output directory instead of using data files?
        # * detect which arches we want to build for? (does it really matter much?)
        kernels = []
        if nvenc_ENABLED:
            kernels += ["XRGB_to_NV12", "XRGB_to_YUV444", "BGRX_to_NV12", "BGRX_to_YUV444"]
        if nvjpeg_ENABLED:
            kernels += ["BGRX_to_RGB", "RGBX_to_RGB"]
        nvcc_commands = []
        for kernel in kernels:
            cuda_src = "fs/share/xpra/cuda/%s.cu" % kernel
            cuda_bin = "fs/share/xpra/cuda/%s.fatbin" % kernel
            if os.path.exists(cuda_bin) and (cuda_rebuild_ENABLED is False):
                continue
            reason = should_rebuild(cuda_src, cuda_bin)
            if not reason:
                continue
            print("rebuilding %s: %s" % (kernel, reason))
            cmd = [nvcc,
                   '-fatbin',
                   #"-cubin",
                   #"-arch=compute_30", "-code=compute_30,sm_30,sm_35",
                   #"-gencode=arch=compute_50,code=sm_50",
                   #"-gencode=arch=compute_52,code=sm_52",
                   #"-gencode=arch=compute_52,code=compute_52",
                   "-c", cuda_src,
                   "-o", cuda_bin]
            #GCC 8.1 has compatibility issues with CUDA 9.2,
            #so revert to C++03:
            if get_gcc_version()>=[8, 1]:
                cmd.append("-std=c++03")
            #GCC 6 uses C++11 by default:
            elif get_gcc_version()>=[6, 0]:
                cmd.append("-std=c++11")
            CL_VERSION = os.environ.get("CL_VERSION")
            if CL_VERSION:
                cmd += ["--use-local-env", "--cl-version", CL_VERSION]
                #-ccbin "C:\Program Files (x86)\Microsoft Visual Studio 10.0\VC\bin\cl.exe"
                cmd += ["--machine", "32"]
            if WIN32:
                #cmd += ["--compiler-bindir", "C:\\msys64\\mingw64\\bin\\g++.exe"]
                #cmd += ["--input-drive-prefix", "/"]
                #cmd += ["--dependency-drive-prefix", "/"]
                cmd += ["-I%s" % os.path.abspath("win32")]
            comp_code_options = []
            if version>=(7, 5):
                comp_code_options.append((52, 52))
                comp_code_options.append((53, 53))
            if version>=(8, 0):
                comp_code_options.append((60, 60))
                comp_code_options.append((61, 61))
                comp_code_options.append((62, 62))
            if version>=(9, 0):
                comp_code_options.append((70, 70))
            if version>=(10, 0):
                comp_code_options.append((75, 75))
            if version>=(11, 0):
                comp_code_options.append((80, 80))
            if version>=(11, 1):
                comp_code_options.append((86, 86))
            for arch, code in comp_code_options:
                cmd.append("-gencode=arch=compute_%s,code=sm_%s" % (arch, code))
            print("CUDA compiling %s (%s)" % (kernel.ljust(16), reason))
            print(" %s" % " ".join("'%s'" % x for x in cmd))
            nvcc_commands.append(cmd)

        #parallel build:
        nvcc_errors = []
        def nvcc_compile(cmd):
            c, stdout, stderr = get_status_output(cmd)
            if c!=0:
                nvcc_errors.append(c)
                print("Error: failed to compile CUDA kernel %s" % kernel)
                print(" using command: %s" % (cmd,))
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

        add_data_files(CUDA_BIN, ["fs/share/xpra/cuda/%s.fatbin" % x for x in kernels])
add_data_files(CUDA_BIN, ["fs/share/xpra/cuda/README.md"])

if nvenc_ENABLED:
    nvencmodule = "nvenc"
    nvenc_pkgconfig = pkgconfig(nvencmodule, ignored_flags=["-l", "-L"])
    if get_gcc_version()<=[8, 0]:
        add_to_keywords(nvenc_pkgconfig, 'extra_compile_args', "-Wno-error=sign-compare")
    #make it possible to build against SDK v10
    add_to_keywords(nvenc_pkgconfig, 'extra_compile_args', "-Wno-error=deprecated-declarations")
    #don't link against libnvidia-encode, we load it dynamically:
    libraries = nvenc_pkgconfig.get("libraries", [])
    if "nvidia-encode" in libraries:
        libraries.remove("nvidia-encode")
    add_cython_ext("xpra.codecs.%s.encoder" % nvencmodule,
                         ["xpra/codecs/%s/encoder.pyx" % nvencmodule],
                         **nvenc_pkgconfig)

toggle_packages(enc_x264_ENABLED, "xpra.codecs.enc_x264")
if enc_x264_ENABLED:
    x264_pkgconfig = pkgconfig("x264")
    add_cython_ext("xpra.codecs.enc_x264.encoder",
                ["xpra/codecs/enc_x264/encoder.pyx"],
                **x264_pkgconfig)

toggle_packages(enc_x265_ENABLED, "xpra.codecs.enc_x265")
if enc_x265_ENABLED:
    x265_pkgconfig = pkgconfig("x265")
    add_cython_ext("xpra.codecs.enc_x265.encoder",
                ["xpra/codecs/enc_x265/encoder.pyx"],
                **x265_pkgconfig)

toggle_packages(pillow_ENABLED, "xpra.codecs.pillow")
if pillow_ENABLED:
    external_includes += ["PIL", "PIL.Image", "PIL.WebPImagePlugin"]

toggle_packages(webp_ENABLED, "xpra.codecs.webp")
if webp_ENABLED:
    webp_pkgconfig = pkgconfig("libwebp")
    add_cython_ext("xpra.codecs.webp.encoder",
                    ["xpra/codecs/webp/encoder.pyx"],
                    **webp_pkgconfig)
    add_cython_ext("xpra.codecs.webp.decoder",
                ["xpra/codecs/webp/decoder.pyx"],
                **webp_pkgconfig)

toggle_packages(nvjpeg_ENABLED, "xpra.codecs.nvjpeg")
if nvjpeg_ENABLED:
    if WIN32:
        nvjpeg_pkgconfig = pkgconfig()
        assert nvcc, "cannot enable nvjpeg without the CUDA path"
        cuda_path = os.path.dirname(nvcc)       #strip nvcc.exe
        cuda_path = os.path.dirname(cuda_path)      #strip /bin/
        cuda_include = os.path.join(cuda_path, "include")
        cuda_bin = os.path.join(cuda_path, "bin")
        add_to_keywords(nvjpeg_pkgconfig, 'extra_compile_args', "-I%s" % cuda_include)
        add_to_keywords(nvjpeg_pkgconfig, 'extra_link_args', "-L%s" % cuda_bin, "-lnvjpeg64_11")
    else:
        nvjpeg_pkgconfig = pkgconfig("nvjpeg")
        assert skip_build or nvjpeg_pkgconfig, "failed to locate nvjpeg pkgconfig"
        cuda_pkgconfig = pkgconfig("cuda")
        assert skip_build or cuda_pkgconfig, "failed to locate cuda pkgconfig"
        for k, v in cuda_pkgconfig.items():
            add_to_keywords(nvjpeg_pkgconfig, k, *v)
    add_cython_ext("xpra.codecs.nvjpeg.encoder",
                         ["xpra/codecs/nvjpeg/encoder.pyx"],
                         **nvjpeg_pkgconfig)

jpeg = jpeg_decoder_ENABLED or jpeg_encoder_ENABLED
toggle_packages(jpeg, "xpra.codecs.jpeg")
if jpeg:
    if jpeg_encoder_ENABLED:
        jpeg_pkgconfig = pkgconfig("libturbojpeg")
        add_cython_ext("xpra.codecs.jpeg.encoder",
                ["xpra/codecs/jpeg/encoder.pyx"],
                **jpeg_pkgconfig)
    if jpeg_decoder_ENABLED:
        jpeg_pkgconfig = pkgconfig("libturbojpeg")
        add_cython_ext("xpra.codecs.jpeg.decoder",
                ["xpra/codecs/jpeg/decoder.pyx"],
                **jpeg_pkgconfig)

#swscale and avcodec2 use libav_common/av_log:
libav_common = dec_avcodec2_ENABLED or csc_swscale_ENABLED
toggle_packages(libav_common, "xpra.codecs.libav_common")
if libav_common:
    avutil_pkgconfig = pkgconfig("libavutil")
    add_cython_ext("xpra.codecs.libav_common.av_log",
                ["xpra/codecs/libav_common/av_log.pyx"],
                **avutil_pkgconfig)


toggle_packages(dec_avcodec2_ENABLED, "xpra.codecs.dec_avcodec2")
if dec_avcodec2_ENABLED:
    avcodec2_pkgconfig = pkgconfig("libavcodec", "libavutil", "libavformat")
    add_cython_ext("xpra.codecs.dec_avcodec2.decoder",
                ["xpra/codecs/dec_avcodec2/decoder.pyx", "xpra/codecs/dec_avcodec2/register_compat.c"],
                **avcodec2_pkgconfig)


toggle_packages(csc_libyuv_ENABLED, "xpra.codecs.csc_libyuv")
if csc_libyuv_ENABLED:
    libyuv_pkgconfig = pkgconfig("libyuv")
    add_cython_ext("xpra.codecs.csc_libyuv.colorspace_converter",
                ["xpra/codecs/csc_libyuv/colorspace_converter.pyx"],
                language="c++",
                **libyuv_pkgconfig)

toggle_packages(csc_swscale_ENABLED, "xpra.codecs.csc_swscale")
if csc_swscale_ENABLED:
    swscale_pkgconfig = pkgconfig("libswscale", "libavutil")
    add_cython_ext("xpra.codecs.csc_swscale.colorspace_converter",
                ["xpra/codecs/csc_swscale/colorspace_converter.pyx"],
                **swscale_pkgconfig)

toggle_packages(csc_cython_ENABLED, "xpra.codecs.csc_cython")
if csc_cython_ENABLED:
    csc_cython_pkgconfig = pkgconfig(optimize=3)
    add_cython_ext("xpra.codecs.csc_cython.colorspace_converter",
                         ["xpra/codecs/csc_cython/colorspace_converter.pyx"],
                         **csc_cython_pkgconfig)

toggle_packages(vpx_ENABLED, "xpra.codecs.vpx")
if vpx_ENABLED:
    vpx_pkgconfig = pkgconfig("vpx")
    add_cython_ext("xpra.codecs.vpx.encoder",
                ["xpra/codecs/vpx/encoder.pyx"],
                **vpx_pkgconfig)
    add_cython_ext("xpra.codecs.vpx.decoder",
                ["xpra/codecs/vpx/decoder.pyx"],
                **vpx_pkgconfig)

toggle_packages(enc_ffmpeg_ENABLED, "xpra.codecs.enc_ffmpeg")
if enc_ffmpeg_ENABLED:
    ffmpeg_pkgconfig = pkgconfig("libavcodec", "libavformat", "libavutil")
    add_cython_ext("xpra.codecs.enc_ffmpeg.encoder",
                ["xpra/codecs/enc_ffmpeg/encoder.pyx"],
                **ffmpeg_pkgconfig)

toggle_packages(v4l2_ENABLED, "xpra.codecs.v4l2")
if v4l2_ENABLED:
    v4l2_pkgconfig = pkgconfig()
    #fugly warning: cython makes this difficult,
    #we have to figure out if "device_caps" exists in the headers:
    videodev2_h = INCLUDE_DIR+"/linux/videodev2.h"
    constants_pxi = "xpra/codecs/v4l2/constants.pxi"
    if not os.path.exists(videodev2_h) or should_rebuild(videodev2_h, constants_pxi):
        ENABLE_DEVICE_CAPS = 0
        if os.path.exists(videodev2_h):
            with open(videodev2_h) as f:
                hdata = f.read()
            ENABLE_DEVICE_CAPS = int(hdata.find("device_caps")>=0)
        with open(constants_pxi, "wb") as f:
            f.write(b"DEF ENABLE_DEVICE_CAPS=%i" % ENABLE_DEVICE_CAPS)
    add_cython_ext("xpra.codecs.v4l2.pusher",
                ["xpra/codecs/v4l2/pusher.pyx"],
                **v4l2_pkgconfig)


toggle_packages(bencode_ENABLED, "xpra.net.bencode")
toggle_packages(bencode_ENABLED and cython_bencode_ENABLED, "xpra.net.bencode.cython_bencode")
if cython_bencode_ENABLED:
    bencode_pkgconfig = pkgconfig(optimize=3)
    add_cython_ext("xpra.net.bencode.cython_bencode",
                ["xpra/net/bencode/cython_bencode.pyx"],
                **bencode_pkgconfig)

toggle_packages(rencodeplus_ENABLED, "xpra.net.rencodeplus.rencodeplus")
if rencodeplus_ENABLED:
    rencodeplus_pkgconfig = pkgconfig(optimize=3)
    add_cython_ext("xpra.net.rencodeplus.rencodeplus",
                ["xpra/net/rencodeplus/rencodeplus.pyx"],
                **rencodeplus_pkgconfig)

toggle_packages(websockets_ENABLED, "xpra.net.websockets.mask")
if websockets_ENABLED:
    websockets_pkgconfig = pkgconfig(optimize=3)
    add_cython_ext("xpra.net.websockets.mask",
                ["xpra/net/websockets/mask.pyx"],
                **websockets_pkgconfig)

if netdev_ENABLED:
    netdev_pkgconfig = pkgconfig()
    add_cython_ext("xpra.platform.xposix.netdev_query",
                ["xpra/platform/xposix/netdev_query.pyx"],
                **netdev_pkgconfig)

if vsock_ENABLED:
    vsock_pkgconfig = pkgconfig()
    add_cython_ext("xpra.net.vsock",
                ["xpra/net/vsock.pyx"],
                **vsock_pkgconfig)

if pam_ENABLED:
    pam_pkgconfig = pkgconfig()
    add_to_keywords(pam_pkgconfig, 'extra_compile_args', "-I%s/pam" % INCLUDE_DIR, "-I%s/security" % INCLUDE_DIR)
    add_to_keywords(pam_pkgconfig, 'extra_link_args', "-lpam", "-lpam_misc")
    add_cython_ext("xpra.server.pam",
                ["xpra/server/pam.pyx"],
                **pam_pkgconfig)


if ext_modules:
    from Cython.Build import cythonize
    #this causes Cython to fall over itself:
    #gdb_debug=debug_ENABLED
    setup_options["ext_modules"] = cythonize(ext_modules,
                                             nthreads=0 if (debug_ENABLED or WIN32 or OSX or ARM) else os.cpu_count(),
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
        try:
            from xpra.util import repr_ellipsized as pv
        except ImportError:
            def pv(v):
                return str(v)
        for k,v in setup_options.items():
            print_option("", k, pv(v))
        print("")

    setup(**setup_options)


if __name__ == "__main__":
    main()
