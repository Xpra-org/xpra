#!/usr/bin/env python

# This file is part of Xpra.
# Copyright (C) 2010-2017 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

##############################################################################
# FIXME: Cython.Distutils.build_ext leaves crud in the source directory.  (So
# does the make_constants hack.)

import glob
from distutils.core import setup
from distutils.extension import Extension
import sys
import os.path
from distutils.command.build import build
from distutils.command.install_data import install_data
import shutil

if sys.version<'2.7':
    raise Exception("xpra no longer supports Python 2 versions older than 2.7")
if sys.version[0]=='3' and sys.version<'3.4':
    raise Exception("xpra no longer supports Python 3 versions older than 3.4")
#we don't support versions of Python without the new ssl code:
import ssl
assert ssl.SSLContext, "xpra requires a Python version with ssl.SSLContext support"

print(" ".join(sys.argv))

#*******************************************************************************
# build options, these may get modified further down..
#
import xpra
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
url = "http://xpra.org/"


XPRA_VERSION = xpra.__version__         #@UndefinedVariable
setup_options = {
                 "name"             : "xpra",
                 "version"          : XPRA_VERSION,
                 "license"          : "GPLv2+",
                 "author"           : "Antoine Martin",
                 "author_email"     : "antoine@devloop.org.uk",
                 "url"              : url,
                 "download_url"     : "http://xpra.org/src/",
                 "description"      : description,
                 "long_description" : long_description,
                 "data_files"       : data_files,
                 "py_modules"       : modules,
                 }

WIN32 = sys.platform.startswith("win") or sys.platform.startswith("msys")
OSX = sys.platform.startswith("darwin")
LINUX = sys.platform.startswith("linux")
NETBSD = sys.platform.startswith("netbsd")
FREEBSD = sys.platform.startswith("freebsd")
PYTHON3 = sys.version_info[0] == 3
POSIX = os.name=="posix"
import struct
BITS = struct.calcsize("P")*8


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
            f.write(b"%s: %s\n" % (k, v))
    sys.exit(0)


print("Xpra version %s" % XPRA_VERSION)
#*******************************************************************************
# Most of the options below can be modified on the command line
# using --with-OPTION or --without-OPTION
# only the default values are specified here:
#*******************************************************************************
from xpra.os_util import get_status_output, is_Ubuntu, is_Debian, is_Raspbian, getUbuntuVersion,\
    PYTHON3

PKG_CONFIG = os.environ.get("PKG_CONFIG", "pkg-config")
has_pkg_config = False
#we don't support building with "pkg-config" on win32 with python2:
if PKG_CONFIG:
    v = get_status_output([PKG_CONFIG, "--version"])
    has_pkg_config = v[0]==0 and v[1]
    if has_pkg_config:
        print("found pkg-config version: %s" % v[1].strip("\n\r"))

from Cython.Compiler.Version import version as cython_version

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
    cmd = [PKG_CONFIG]  + [str(x) for x in args]
    return get_status_output(cmd)[0]==0

def pkg_config_version(req_version, pkgname):
    cmd = [PKG_CONFIG, "--modversion", pkgname]
    r, out, _ = get_status_output(cmd)
    if r!=0 or not out:
        return False
    from distutils.version import LooseVersion
    return LooseVersion(out)>=LooseVersion(req_version)

def is_RH():
    try:
        with open("/etc/redhat-release", mode='rb') as f:
            data = f.read()
        return data.startswith("CentOS") or data.startswith("RedHat")
    except:
        pass
    return False

DEFAULT = True
if "--minimal" in sys.argv:
    sys.argv.remove("--minimal")
    DEFAULT = False

from xpra.platform.features import LOCAL_SERVERS_SUPPORTED, SHADOW_SUPPORTED
shadow_ENABLED = SHADOW_SUPPORTED and DEFAULT
server_ENABLED = (LOCAL_SERVERS_SUPPORTED or shadow_ENABLED) and DEFAULT
rfb_ENABLED = server_ENABLED
service_ENABLED = LINUX and server_ENABLED
sd_listen_ENABLED = POSIX and pkg_config_ok("--exists", "libsystemd") and (not is_Ubuntu() or getUbuntuVersion()>[16, 4])
proxy_ENABLED  = DEFAULT
client_ENABLED = DEFAULT

x11_ENABLED = DEFAULT and not WIN32 and not OSX
xinput_ENABLED = x11_ENABLED
uinput_ENABLED = x11_ENABLED
dbus_ENABLED = DEFAULT and x11_ENABLED and not (OSX or WIN32)
gtk_x11_ENABLED = DEFAULT and not WIN32 and not OSX
gtk2_ENABLED = DEFAULT and client_ENABLED and not PYTHON3
gtk3_ENABLED = DEFAULT and client_ENABLED and PYTHON3
opengl_ENABLED = DEFAULT and client_ENABLED
html5_ENABLED = DEFAULT
html5_gzip_ENABLED = DEFAULT
html5_brotli_ENABLED = DEFAULT
minify_ENABLED = html5_ENABLED
pam_ENABLED = DEFAULT and (server_ENABLED or proxy_ENABLED) and POSIX and not OSX and (os.path.exists("/usr/include/pam/pam_misc.h") or os.path.exists("/usr/include/security/pam_misc.h"))

xdg_open_ENABLED        = LINUX and DEFAULT
netdev_ENABLED          = LINUX and DEFAULT
vsock_ENABLED           = LINUX and os.path.exists("/usr/include/linux/vm_sockets.h")
bencode_ENABLED         = DEFAULT
cython_bencode_ENABLED  = DEFAULT
clipboard_ENABLED       = DEFAULT
Xdummy_ENABLED          = None          #None means auto-detect
Xdummy_wrapper_ENABLED  = None          #None means auto-detect
if WIN32 or OSX:
    Xdummy_ENABLED = False
sound_ENABLED           = DEFAULT
printing_ENABLED        = DEFAULT
crypto_ENABLED          = DEFAULT
mdns_ENABLED            = DEFAULT

enc_proxy_ENABLED       = DEFAULT
enc_x264_ENABLED        = DEFAULT and pkg_config_ok("--exists", "x264")
enc_x265_ENABLED        = DEFAULT and pkg_config_ok("--exists", "x265")
pillow_ENABLED          = DEFAULT
webp_ENABLED            = DEFAULT and pkg_config_version("0.5", "libwebp")
jpeg_ENABLED            = DEFAULT and pkg_config_version("1.4", "libturbojpeg")
vpx_ENABLED             = DEFAULT and pkg_config_version("1.4", "vpx")
enc_ffmpeg_ENABLED      = False
#opencv currently broken on 32-bit windows (crashes on load):
webcam_ENABLED          = DEFAULT and not OSX
v4l2_ENABLED            = DEFAULT and (not WIN32 and not OSX and not FREEBSD)
#ffmpeg 3.1 or later is required
dec_avcodec2_ENABLED    = DEFAULT and pkg_config_version("57", "libavcodec")
csc_swscale_ENABLED     = DEFAULT and pkg_config_ok("--exists", "libswscale")
nvenc_ENABLED = DEFAULT and BITS==64 and pkg_config_version("7", "nvenc")
nvfbc_ENABLED = DEFAULT and BITS==64 and pkg_config_ok("--exists", "nvfbc")
cuda_kernels_ENABLED    = DEFAULT
cuda_rebuild_ENABLED    = DEFAULT
csc_libyuv_ENABLED      = DEFAULT and pkg_config_ok("--exists", "libyuv")
example_ENABLED         = DEFAULT

#Cython / gcc / packaging build options:
annotate_ENABLED        = True
warn_ENABLED            = True
strict_ENABLED          = True
PIC_ENABLED             = not WIN32     #ming32 moans that it is always enabled already
debug_ENABLED           = False
verbose_ENABLED         = False
bundle_tests_ENABLED    = False
tests_ENABLED           = False
rebuild_ENABLED         = True

#allow some of these flags to be modified on the command line:
SWITCHES = ["enc_x264", "enc_x265", "enc_ffmpeg",
            "nvenc", "cuda_kernels", "cuda_rebuild", "nvfbc",
            "vpx", "webp", "pillow", "jpeg",
            "v4l2",
            "dec_avcodec2", "csc_swscale",
            "csc_libyuv",
            "bencode", "cython_bencode", "vsock", "netdev", "mdns",
            "clipboard",
            "server", "client", "dbus", "x11", "xinput", "uinput", "sd_listen",
            "gtk_x11", "service",
            "gtk2", "gtk3", "example",
            "html5", "minify", "html5_gzip", "html5_brotli",
            "pam", "xdg_open",
            "sound", "opengl", "printing", "webcam",
            "rebuild",
            "annotate", "warn", "strict",
            "shadow", "proxy", "rfb",
            "debug", "PIC",
            "Xdummy", "Xdummy_wrapper", "verbose", "tests", "bundle_tests"]
if WIN32:
    SWITCHES.append("zip")
    zip_ENABLED = True
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

install = "dist"
rpath = None
ssl_cert = None
ssl_key = None
minifier = None
filtered_args = []
for arg in sys.argv:
    matched = False
    for x in ("rpath", "ssl-cert", "ssl-key", "install"):
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

    #sanity check the flags:
    if clipboard_ENABLED and not server_ENABLED and not gtk2_ENABLED and not gtk3_ENABLED:
        print("Warning: clipboard can only be used with the server or one of the gtk clients!")
        clipboard_ENABLED = False
    if x11_ENABLED and WIN32:
        print("Warning: enabling x11 on MS Windows is unlikely to work!")
    if gtk_x11_ENABLED and not x11_ENABLED:
        print("Error: you must enable x11 to support gtk_x11!")
        exit(1)
    if client_ENABLED and not gtk2_ENABLED and not gtk3_ENABLED:
        print("Warning: client is enabled but none of the client toolkits are!?")
    if DEFAULT and (not client_ENABLED and not server_ENABLED):
        print("Warning: you probably want to build at least the client or server!")
    if DEFAULT and not pillow_ENABLED:
        print("Warning: including Python Pillow is VERY STRONGLY recommended")
    if minify_ENABLED:
        r = get_status_output(["uglifyjs", "--version"])[0]
        if r==0:
            minifier = "uglifyjs"
        else:
            print("Warning: uglifyjs failed and return %i" % r)
            try:
                import yuicompressor
                assert yuicompressor
                minifier = "yuicompressor"
            except ImportError as e:
                print("Warning: yuicompressor module not found, cannot minify")
                minify_ENABLED = False
    if not enc_x264_ENABLED and not vpx_ENABLED:
        print("Warning: no x264 and no vpx support!")
        print(" you should enable at least one of these two video encodings")


#*******************************************************************************
# default sets:

external_includes = ["hashlib",
                     "ctypes", "platform"]


if gtk3_ENABLED or (sound_ENABLED and PYTHON3):
    external_includes += ["gi"]
elif gtk2_ENABLED or x11_ENABLED:
    external_includes += "cairo", "pango", "pangocairo", "atk", "glib", "gobject", "gio", "gtk.keysyms"

external_excludes = [
                    #Tcl/Tk
                    "Tkconstants", "Tkinter", "tcl",
                    #PIL bits that import TK:
                    "_imagingtk", "PIL._imagingtk", "ImageTk", "PIL.ImageTk", "FixTk",
                    #formats we don't use:
                    "GimpGradientFile", "GimpPaletteFile", "BmpImagePlugin", "TiffImagePlugin",
                    #not used:
                    "curses", "pdb",
                    "tty",
                    "setuptools", "doctest"
                    ]
if not html5_ENABLED and not crypto_ENABLED:
    external_excludes += ["ssl", "_ssl"]
if not html5_ENABLED:
    external_excludes += ["BaseHTTPServer", "mimetypes", "mimetools"]

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
add_modules("xpra", "xpra.platform", "xpra.net")
add_modules("xpra.scripts.main")


def add_data_files(target_dir, files):
    #this is overriden below because cx_freeze uses the opposite structure (files first...). sigh.
    assert type(target_dir)==str
    assert type(files) in (list, tuple)
    data_files.append((target_dir, files))


#for pretty printing of options:
def print_option(prefix, k, v):
    if type(v)==dict:
        print("%s* %s:" % (prefix, k))
        for kk,vv in v.items():
            print_option(" "+prefix, kk, vv)
    else:
        print("%s* %s=%s" % (prefix, k, v))

#*******************************************************************************
# Utility methods for building with Cython
def cython_version_check(min_version):
    from distutils.version import LooseVersion
    if LooseVersion(cython_version) < LooseVersion(".".join([str(x) for x in min_version])):
        sys.exit("ERROR: Your version of Cython is too old to build this package\n"
                 "You have version %s\n"
                 "Please upgrade to Cython %s or better"
                 % (cython_version, ".".join([str(part) for part in min_version])))

def cython_add(extension, min_version=(0, 19)):
    #gentoo does weird things, calls --no-compile with build *and* install
    #then expects to find the cython modules!? ie:
    #python2.7 setup.py build -b build-2.7 install --no-compile --root=/var/tmp/portage/x11-wm/xpra-0.7.0/temp/images/2.7
    if "--no-compile" in sys.argv and not ("build" in sys.argv and "install" in sys.argv):
        return
    cython_version_check(min_version)
    from Cython.Distutils import build_ext
    ext_modules.append(extension)
    global cmdclass
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
    if values and value in values:
        values.remove(value)


def checkdirs(*dirs):
    for d in dirs:
        if not os.path.exists(d) or not os.path.isdir(d):
            raise Exception("cannot find a directory which is required for building: '%s'" % d)

PYGTK_PACKAGES = ["pygobject-2.0", "pygtk-2.0"]
#override the pkgconfig file,
#we don't need to link against any of these:
gtk2_ignored_tokens=[("-l%s" % x) for x in
                     ["fontconfig", "freetype", "cairo",
                      "atk-1.0", "pangoft2-1.0", "pango-1.0", "pangocairo-1.0",
                      "gio-2.0", "gdk_pixbuf-2.0"]]

GCC_VERSION = []
def get_gcc_version():
    global GCC_VERSION
    if len(GCC_VERSION)==0:
        cmd = [os.environ.get("CC", "gcc"), "-v"]
        r, _, err = get_status_output(cmd)
        if r==0:
            V_LINE = "gcc version "
            for line in err.splitlines():
                if line.startswith(V_LINE):
                    v_str = line[len(V_LINE):].split(" ")[0]
                    for p in v_str.split("."):
                        try:
                            GCC_VERSION.append(int(p))
                        except:
                            break
                    print("found gcc version: %s" % ".".join([str(x) for x in GCC_VERSION]))
                    break
    return GCC_VERSION

def make_constants_pxi(constants_path, pxi_path, **kwargs):
    constants = []
    with open(constants_path) as f:
        for line in f:
            data = line.split("#", 1)[0].strip()
            # data can be empty ''...
            if not data:
                continue
            # or a pair like 'cFoo "Foo"'...
            elif len(data.split()) == 2:
                (pyname, cname) = data.split()
                constants.append((pyname, cname))
            # or just a simple token 'Foo'
            else:
                constants.append(data)

    with open(pxi_path, "w") as out:
        if constants:
            out.write("cdef extern from *:\n")
            ### Apparently you can't use | on enum's?!
            # out.write("    enum MagicNumbers:\n")
            # for const in constants:
            #     if isinstance(const, tuple):
            #         out.write('        %s %s\n' % const)
            #     else:
            #         out.write('        %s\n' % (const,))
            for const in constants:
                if isinstance(const, tuple):
                    out.write('    unsigned int %s %s\n' % const)
                else:
                    out.write('    unsigned int %s\n' % (const,))

            out.write("constants = {\n")
            for const in constants:
                if isinstance(const, tuple):
                    pyname = const[0]
                else:
                    pyname = const
                out.write('    "%s": %s,\n' % (pyname, pyname))
            out.write("}\n")
            if kwargs:
                out.write("\n\n")

        if kwargs:
            for k, v in kwargs.items():
                out.write('DEF %s = %s\n' % (k, v))


def should_rebuild(src_file, bin_file):
    if not os.path.exists(bin_file):
        return "no file"
    elif rebuild_ENABLED:
        if os.path.getctime(bin_file)<os.path.getctime(src_file):
            return "binary file out of date"
        elif os.path.getctime(bin_file)<os.path.getctime(__file__):
            return "newer build file"
    return None

def make_constants(*paths, **kwargs):
    base = os.path.join(os.getcwd(), *paths)
    constants_file = "%s.txt" % base
    pxi_file = "%s.pxi" % base
    reason = should_rebuild(constants_file, pxi_file)
    if reason:
        if verbose_ENABLED:
            print("(re)generating %s (%s):" % (pxi_file, reason))
        make_constants_pxi(constants_file, pxi_file, **kwargs)


# Tweaked from http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/502261
def exec_pkgconfig(*pkgs_options, **ekw):
    kw = dict(ekw)
    if "optimize" in kw:
        optimize = kw["optimize"]
        del kw["optimize"]
        if type(optimize)==bool:
            optimize = int(optimize)*3
        if not debug_ENABLED:
            add_to_keywords(kw, 'extra_compile_args', "-O%i" % optimize)
    ignored_flags = kw.pop("ignored_flags", [])
    ignored_tokens = kw.pop("ignored_tokens", [])

    if len(pkgs_options)>0:
        package_names = []
        #find out which package name to use from potentially many options
        #and bail out early with a meaningful error if we can't find any valid options
        for package_options in pkgs_options:
            #for this package options, find the ones that work
            valid_option = None
            if type(package_options)==str:
                options = [package_options]     #got given just one string
                if not package_options.startswith("lib"):
                    options.append("lib%s" % package_options)
            else:
                assert type(package_options)==list
                options = package_options       #got given a list of options
            for option in options:
                cmd = ["pkg-config", "--exists", option]
                r, _, _ = get_status_output(cmd)
                if r==0:
                    valid_option = option
                    break
            if not valid_option:
                raise Exception("ERROR: cannot find a valid pkg-config entry for %s using PKG_CONFIG_PATH=%s" % (" or ".join(options), os.environ.get("PKG_CONFIG_PATH", "(empty)")))
            package_names.append(valid_option)
        if verbose_ENABLED and list(pkgs_options)!=list(package_names):
            print("exec_pkgconfig(%s,%s) using package names=%s" % (pkgs_options, ekw, package_names))
        flag_map = {'-I': 'include_dirs',
                    '-L': 'library_dirs',
                    '-l': 'libraries'}
        pkg_config_cmd = ["pkg-config", "--libs", "--cflags", "%s" % (" ".join(package_names),)]
        r, pkg_config_out, err = get_status_output(pkg_config_cmd)
        if r!=0:
            sys.exit("ERROR: call to '%s' failed (err=%s)" % (" ".join(cmd), err))
        env_cflags = os.environ.get("CFLAGS")       #["dpkg-buildflags", "--get", "CFLAGS"]
        env_ldflags = os.environ.get("LDFLAGS")     #["dpkg-buildflags", "--get", "LDFLAGS"]
        for s in (pkg_config_out, env_cflags, env_ldflags):
            if not s:
                continue
            for token in s.split():
                if token in ignored_tokens:
                    pass
                elif token[:2] in ignored_flags:
                    pass
                elif token[:2] in flag_map:
                    add_to_keywords(kw, flag_map.get(token[:2]), token[2:])
                elif token.startswith("-W"):
                    add_to_keywords(kw, 'extra_compile_args', token)
                else:# throw others to extra_link_args
                    add_to_keywords(kw, 'extra_link_args', token)
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
                    "-Wno-unused-command-line-argument",
                    ]
        elif get_gcc_version()>=[4, 4]:
            eifd = ["-Werror"]
            if is_Debian() or is_Ubuntu() or is_Raspbian():
                #needed on Debian and Ubuntu to avoid this error:
                #/usr/include/gtk-2.0/gtk/gtkitemfactory.h:47:1: error: function declaration isn't a prototype [-Werror=strict-prototypes]
                eifd.append("-Wno-error=strict-prototypes")
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
    if PIC_ENABLED:
        add_to_keywords(kw, 'extra_compile_args', "-fPIC")
    if debug_ENABLED:
        add_to_keywords(kw, 'extra_compile_args', '-g')
        add_to_keywords(kw, 'extra_compile_args', '-ggdb')
        if get_gcc_version()>=[4, 8]:
            add_to_keywords(kw, 'extra_compile_args', '-fsanitize=address')
            add_to_keywords(kw, 'extra_link_args', '-fsanitize=address')
    if rpath and kw.get("libraries"):
        insert_into_keywords(kw, "library_dirs", rpath)
        insert_into_keywords(kw, "extra_link_args", "-Wl,-rpath=%s" % rpath)
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
            if dirs[i+1] == "xpra":
                dirs = dirs[i+2:]
        elif "BUILDROOT" in dirs:
            #strip rpm style build root:
            #[$HOME, "rpmbuild", "BUILDROOT", "xpra-$VERSION"] -> []
            dirs = dirs[dirs.index("BUILDROOT")+2:]
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
    if len(dirs)==0 or dirs[0]=="usr" or (install_dir or sys.prefix).startswith(os.path.sep):
        #ie: ["/", "usr"] or ["/", "usr", "local"]
        dirs.insert(0, os.path.sep)
    return dirs

def get_conf_dir(install_dir, stripbuildroot=True):
    dirs = get_base_conf_dir(install_dir, stripbuildroot)
    dirs.append("etc")
    dirs.append("xpra")
    return os.path.join(*dirs)

def detect_xorg_setup(install_dir=None):
    from xpra.scripts import config
    config.debug = config.warn
    conf_dir = get_conf_dir(install_dir)
    return config.detect_xvfb_command(conf_dir, None, Xdummy_ENABLED, Xdummy_wrapper_ENABLED)

def build_xpra_conf(install_dir):
    #generates an actual config file from the template
    xvfb_command = detect_xorg_setup(install_dir)
    from xpra.platform.features import DEFAULT_ENV
    def bstr(b):
        if b is None:
            return "auto"
        return ["no", "yes"][int(b)]
    start_env = "\n".join("start-env = %s" % x for x in DEFAULT_ENV)
    conf_dir = get_conf_dir(install_dir)
    from xpra.platform.features import DEFAULT_SSH_COMMAND, DEFAULT_PULSEAUDIO_COMMAND, DEFAULT_PULSEAUDIO_CONFIGURE_COMMANDS
    from xpra.platform.paths import get_socket_dirs
    from xpra.scripts.config import get_default_key_shortcuts, get_default_systemd_run, DEFAULT_POSTSCRIPT_PRINTER, DEFAULT_PULSEAUDIO
    #remove build paths and user specific paths with UID ("/run/user/UID/Xpra"):
    socket_dirs = get_socket_dirs()
    if WIN32:
        bind = "Main"
    else:
        if os.getuid()>0:
            #remove any paths containing the uid,
            #osx uses /var/tmp/$UID-Xpra,
            #but this should not be included in the default config for all users!
            #(the buildbot's uid!)
            socket_dirs = [x for x in socket_dirs if x.find(str(os.getuid()))<0]
        bind = "auto"
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
    #Ubuntu 16.10 has opencv builds that conflict with our private ffmpeg
    webcam = webcam_ENABLED and not (OSX or getUbuntuVersion()==[16, 10])
    #no python-avahi on RH / CentOS, need dbus module on *nix:
    mdns = mdns_ENABLED and (OSX or WIN32 or (not is_RH() and dbus_ENABLED))
    SUBS = {
            'xvfb_command'          : pretty_cmd(xvfb_command),
            'ssh_command'           : DEFAULT_SSH_COMMAND,
            'key_shortcuts'         : "".join(("key-shortcut = %s\n" % x) for x in get_default_key_shortcuts()),
            'remote_logging'        : "both",
            'start_env'             : start_env,
            'pulseaudio'            : bstr(DEFAULT_PULSEAUDIO),
            'pulseaudio_command'    : pretty_cmd(DEFAULT_PULSEAUDIO_COMMAND),
            'pulseaudio_configure_commands' : "\n".join(("pulseaudio-configure-commands = %s" % pretty_cmd(x)) for x in DEFAULT_PULSEAUDIO_CONFIGURE_COMMANDS),
            'conf_dir'              : conf_dir,
            'bind'                  : bind,
            'ssl_cert'              : ssl_cert or "",
            'ssl_key'               : ssl_key or "",
            'systemd_run'           : get_default_systemd_run(),
            'socket_dirs'           : "".join(("socket-dirs = %s\n" % x) for x in socket_dirs),
            'log_dir'               : "auto",
            'mdns'                  : bstr(mdns),
            'notifications'         : bstr(OSX or WIN32 or dbus_ENABLED),
            'dbus_proxy'            : bstr(not OSX and not WIN32 and dbus_ENABLED),
            'pdf_printer'           : pdf,
            'postscript_printer'    : postscript,
            'webcam'                : ["no", "auto"][webcam],
            'mousewheel'            : "on",
            'printing'              : printing_ENABLED,
            'dbus_control'          : bstr(dbus_ENABLED),
            'mmap'                  : bstr(True),
            }
    def convert_templates(subdirs=[]):
        dirname = os.path.join(*(["etc", "xpra"] + subdirs))
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
    convert_templates()


#*******************************************************************************
if 'clean' in sys.argv or 'sdist' in sys.argv:
    #clean and sdist don't actually use cython,
    #so skip this (and avoid errors)
    pkgconfig = no_pkgconfig
    #always include everything in this case:
    add_packages("xpra")
    #ensure we remove the files we generate:
    CLEAN_FILES = [
                   "xpra/build_info.py",
                   "xpra/monotonic_time.c",
                   "xpra/gtk_common/gtk2/gdk_atoms.c",
                   "xpra/gtk_common/gtk2/gdk_bindings.c",
                   "xpra/gtk_common/gtk3/gdk_atoms.c",
                   "xpra/x11/gtk2/constants.pxi",
                   "xpra/x11/gtk2/gdk_bindings.c",
                   "xpra/x11/gtk2/gdk_display_source.c",
                   "xpra/x11/gtk3/gdk_display_source.c",
                   "xpra/x11/bindings/constants.pxi",
                   "xpra/x11/bindings/wait_for_x_server.c",
                   "xpra/x11/bindings/keyboard_bindings.c",
                   "xpra/x11/bindings/display_source.c",
                   "xpra/x11/bindings/window_bindings.c",
                   "xpra/x11/bindings/randr_bindings.c",
                   "xpra/x11/bindings/core_bindings.c",
                   "xpra/x11/bindings/posix_display_source.c",
                   "xpra/x11/bindings/ximage.c",
                   "xpra/x11/bindings/xi2_bindings.c",
                   "xpra/platform/win32/propsys.cpp",
                   "xpra/platform/darwin/gdk_bindings.c",
                   "xpra/platform/xposix/sd_listen.c",
                   "xpra/platform/xposix/netdev_query.c",
                   "xpra/net/bencode/cython_bencode.c",
                   "xpra/net/vsock.c",
                   "xpra/buffers/membuf.c",
                   "xpra/codecs/vpx/encoder.c",
                   "xpra/codecs/vpx/decoder.c",
                   "xpra/codecs/nvenc/encoder.c",
                   "xpra/codecs/nvfbc/fbc_capture_linux.cpp",
                   "xpra/codecs/nvfbc/fbc_capture_win.cpp",
                   "xpra/codecs/cuda_common/ARGB_to_NV12.fatbin",
                   "xpra/codecs/cuda_common/ARGB_to_YUV444.fatbin",
                   "xpra/codecs/cuda_common/BGRA_to_NV12.fatbin",
                   "xpra/codecs/cuda_common/BGRA_to_YUV444.fatbin",
                   "xpra/codecs/enc_x264/encoder.c",
                   "xpra/codecs/enc_x265/encoder.c",
                   "xpra/codecs/jpeg/encoder.c",
                   "xpra/codecs/jpeg/decoder.c",
                   "xpra/codecs/enc_ffmpeg/encoder.c",
                   "xpra/codecs/v4l2/constants.pxi",
                   "xpra/codecs/v4l2/pusher.c",
                   "xpra/codecs/libav_common/av_log.c",
                   "xpra/codecs/webp/encode.c",
                   "xpra/codecs/webp/decode.c",
                   "xpra/codecs/dec_avcodec2/decoder.c",
                   "xpra/codecs/csc_libyuv/colorspace_converter.cpp",
                   "xpra/codecs/csc_swscale/colorspace_converter.c",
                   "xpra/codecs/xor/cyxor.c",
                   "xpra/codecs/argb/argb.c",
                   "xpra/codecs/nvapi_version.c",
                   "xpra/gtk_common/gdk_atoms.c",
                   "xpra/client/gtk3/cairo_workaround.c",
                   "xpra/server/cystats.c",
                   "xpra/server/window/region.c",
                   "xpra/server/window/motion.c",
                   "xpra/server/pam.c",
                   "etc/xpra/xpra.conf",
                   #special case for the generated xpra conf files in build (see #891):
                   "build/etc/xpra/xpra.conf"] + glob.glob("build/etc/xpra/conf.d/*.conf")
    for x in CLEAN_FILES:
        p, ext = os.path.splitext(x)
        if ext in (".c", ".cpp", ".pxi"):
            #clean the Cython annotated html files:
            CLEAN_FILES.append(p+".html")
            if WIN32 and ext!=".pxi":
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

from add_build_info import record_build_info, BUILD_INFO_FILE, record_src_info, SRC_INFO_FILE, has_src_info

if "clean" not in sys.argv:
    # Add build info to build_info.py file:
    record_build_info()
    # ensure it is included in the module list if it didn't exist before
    add_modules(BUILD_INFO_FILE)

if "sdist" in sys.argv:
    record_src_info()

if "install" in sys.argv or "build" in sys.argv:
    #if installing from source tree rather than
    #from a source snapshot, we may not have a "src_info" file
    #so create one:
    if not has_src_info():
        record_src_info()
        # ensure it is now included in the module list
        add_modules(SRC_INFO_FILE)


if 'clean' in sys.argv or 'sdist' in sys.argv:
    #take shortcut to skip cython/pkgconfig steps:
    setup(**setup_options)
    sys.exit(0)



def glob_recurse(srcdir):
    m = {}
    for root, _, files in os.walk(srcdir):
        for f in files:
            dirname = root[len(srcdir)+1:]
            filename = os.path.join(root, f)
            m.setdefault(dirname, []).append(filename)
    return m


def install_html5(install_dir="www"):
    from setup_html5 import install_html5 as do_install_html5
    do_install_html5(install_dir, minifier, html5_gzip_ENABLED, html5_brotli_ENABLED, verbose_ENABLED)


#*******************************************************************************
if WIN32:
    MINGW_PREFIX = os.environ.get("MINGW_PREFIX")
    assert MINGW_PREFIX, "you must run this build from a MINGW environment"
    add_packages("xpra.platform.win32")
    remove_packages("xpra.platform.darwin", "xpra.platform.xposix")

    #this is where the win32 gi installer will put things:
    gnome_include_path = os.environ.get("MINGW_PREFIX")

    #only add the cx_freeze specific options
    #if we aren't just building the Cython bits with "build_ext":
    if "build_ext" not in sys.argv:
        #with cx_freeze, we don't use py_modules
        del setup_options["py_modules"]
        import cx_Freeze                            #@UnresolvedImport
        from cx_Freeze import setup, Executable     #@UnresolvedImport @Reimport
        CX5 = cx_Freeze.version>="5"
        if CX5 and not hasattr(sys, "base_prefix"):
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
            assert type(target_dir)==str
            assert type(files) in (list, tuple)
            for f in files:
                target_file = os.path.join(target_dir, os.path.basename(f))
                data_files.append((f, target_file))

        #pass a potentially nested dictionary representing the tree
        #of files and directories we do want to include
        #relative to gnome_include_path
        def add_dir(base, defs):
            if verbose_ENABLED:
                print("add_dir(%s, %s)" % (base, defs))
            if type(defs) in (list, tuple):
                for sub in defs:
                    if type(sub)==dict:
                        add_dir(base, sub)
                    else:
                        assert type(sub)==str
                        filename = os.path.join(gnome_include_path, base, sub)
                        if os.path.exists(filename):
                            add_data_files(base, [filename])
                        else:
                            print("Warning: missing '%s'" % filename)
            else:
                assert type(defs)==dict
                for d, sub in defs.items():
                    assert type(sub) in (dict, list, tuple)
                    #recurse down:
                    add_dir(os.path.join(base, d), sub)

        #convenience method for adding GI libs and "typelib" and "gir":
        def add_gi(*libs):
            if verbose_ENABLED:
                print("add_gi(%s)" % str(libs))
            add_dir('lib',      {"girepository-1.0":    ["%s.typelib" % x for x in libs]})
            add_dir('share',    {"gir-1.0" :            ["%s.gir" % x for x in libs]})

        def add_DLLs(*dll_names):
            try:
                do_add_DLLs(*dll_names)
            except Exception as e:
                print("Error: failed to add DLLs: %s" % (dll_names, ))
                print(" %s" % e)
                sys.exit(1)

        def do_add_DLLs(*dll_names):
            dll_names = list(dll_names)
            dll_files = []
            import re
            version_re = re.compile("\-[0-9\.\-]+$")
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
                    x = x.lower()
                    if os.path.isdir(dll_path) or not x.startswith("lib") or not x.endswith(".dll"):
                        continue
                    nameversion = x[3:-4]                       #strip "lib" and ".dll": "libatk-1.0-0.dll" -> "atk-1.0-0"
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
            if len(dll_names)>0:
                print("some DLLs could not be found:")
                for x in dll_names:
                    print(" - lib%s*.dll" % x)
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
                     'dbus', 'dbus-glib',
                     'gdk', 'gdk_pixbuf', 'gtk',
                     'cairo-gobject', 'pango', 'pangocairo', 'pangoft2', 'pangowin32',
                     'harfbuzz', 'harfbuzz-gobject',
                     'jasper', 'epoxy',
                     'intl',
                     'p11-kit',
                     'jpeg', 'png16', 'rsvg', 'webp', 'tiff')
            #these are missing in newer aio installers (sigh):
            do_add_DLLs('javascriptcoregtk')
            if opengl_ENABLED:
                do_add_DLLs('gdkglext', 'gtkglext')

        if gtk3_ENABLED:
            add_dir('etc', ["fonts", "gtk-3.0", "pango", "pkcs11"])     #add "dbus-1"?
            add_dir('lib', ["gdk-pixbuf-2.0", "gtk-3.0",
                            "libvisual-0.4", "p11-kit", "pkcs11"])
            add_dir('share', ["fontconfig", "fonts", "glib-2.0",        #add "dbus-1"?
                              "p11-kit", "xml",
                              {"icons"  : ["hicolor"]},
                              {"locale" : ["en"]},
                              {"themes" : ["Default"]}
                             ])
        if gtk3_ENABLED or sound_ENABLED:
            add_dir('lib', ["gio"])
            packages.append("gi")
            add_gi("Gio-2.0", "GIRepository-2.0", "Glib-2.0", "GModule-2.0",
                   "GObject-2.0")
        if gtk3_ENABLED:
            add_gi("Atk-1.0",
                   "fontconfig-2.0", "freetype2-2.0",
                   "GDesktopEnums-3.0", "Soup-2.4",
                   "GdkPixbuf-2.0", "Gdk-3.0", "Gtk-3.0",
                   "HarfBuzz-0.0",
                   "Libproxy-1.0", "libxml2-2.0",
                   "cairo-1.0", "Pango-1.0", "PangoCairo-1.0", "PangoFT2-1.0",
                   "Rsvg-2.0",
                   "win32-1.0")
            if opengl_ENABLED:
                add_gi("GdkGLExt-3.0", "GtkGLExt-3.0", "GL-1.0")
            add_DLLs('visual', 'curl', 'soup', 'openjpeg')
        if server_ENABLED and not PYTHON3:
            add_DLLs('sqlite3')

        if gtk2_ENABLED:
            add_dir('lib',      {
                "gdk-pixbuf-2.0":    {
                    "2.10.0"    :   {
                        "loaders"   :
                            ["libpixbufloader-%s.dll" % x for x in ("ico", "jpeg", "svg", "bmp")]
                        },
                    },
                })

        if sound_ENABLED:
            add_dir("share", ["gst-plugins-bad", "gst-plugins-base", "gstreamer-1.0"])
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
            add_DLLs("faac", "faad", "flac", "mad", "mpg123")
            #add the gstreamer plugins we need:
            GST_PLUGINS = ("app",
                           "cutter",
                           #muxers:
                           "gdp", "matroska", "ogg", "isomp4",
                           "audioparsers", "audiorate", "audioconvert", "audioresample", "audiotestsrc",
                           "coreelements", "directsoundsink", "directsoundsrc", "wasapi",
                           #codecs:
                           "opus", "opusparse", "flac", "lame", "mad", "mpg123", "speex", "faac", "faad",
                           "volume", "vorbis", "wavenc", "wavpack", "wavparse",
                           #untested: a52dec, voaacenc
                           )
            add_dir(os.path.join("lib", "gstreamer-1.0"), [("libgst%s.dll" % x) for x in GST_PLUGINS])
            #END OF SOUND

        if server_ENABLED:
            #used by proxy server:
            external_includes += ["multiprocessing", "setproctitle"]

        external_includes += ["encodings"]
        if client_ENABLED:
            #for parsing "open-command":
            external_includes += ["shlex"]
            #for version check:
            external_includes += [
                                  "ftplib", "fileinput",
                                  ]
            if PYTHON3:
                external_includes += ["urllib", "http.cookiejar", "http.client"]
            else:
                external_includes += ["urllib2", "cookielib", "httplib"]

        if PYTHON3:
            #hopefully, cx_Freeze will fix this horror:
            #(we shouldn't have to deal with DLL dependencies)
            import site
            lib_python = os.path.dirname(site.getsitepackages()[0])
            lib_dynload_dir = os.path.join(lib_python, "lib-dynload")
            add_data_files('', glob.glob("%s/zlib*dll" % lib_dynload_dir))
            for x in ("io", "codecs", "abc", "_weakrefset", "encodings"):
                add_data_files("", glob.glob("%s/%s*" % (lib_python, x)))
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
        if not CX5:
            cx_freeze_options.update({
                            "compressed"        : True,
                            "create_shared_zip" : zip_ENABLED,
                            })
        else:
            #cx_Freeze v5 workarounds:
            if opengl_ENABLED or nvenc_ENABLED or nvfbc_ENABLED:
                add_packages("numpy.core._methods", "numpy.lib.format")

        setup_options["options"] = {"build_exe" : cx_freeze_options}
        executables = []
        setup_options["executables"] = executables

        def add_exe(script, icon, base_name, base="Console"):
            kwargs = {}
            if not CX5:
                kwargs = {
                    "compress"              : True,
                    "copyDependentFiles"    : True,
                    "appendScriptToExe"     : False,
                    "appendScriptToLibrary" : True,
                    }
            executables.append(Executable(
                        script                  = script,
                        initScript              = None,
                        #targetDir               = "dist",
                        icon                    = "win32/%s" % icon,
                        targetName              = "%s.exe" % base_name,
                        base                    = base,
                        **kwargs))

        def add_console_exe(script, icon, base_name):
            add_exe(script, icon, base_name)
        def add_gui_exe(script, icon, base_name):
            add_exe(script, icon, base_name, base="Win32GUI")
        def add_service_exe(script, icon, base_name):
            add_exe(script, icon, base_name, base="Win32Service")

        #UI applications (detached from shell: no text output if ran from cmd.exe)
        if client_ENABLED and (gtk2_ENABLED or gtk3_ENABLED):
            add_gui_exe("scripts/xpra",                         "xpra_txt.ico",     "Xpra")
            add_gui_exe("scripts/xpra_launcher",                "xpra.ico",         "Xpra-Launcher")
            add_gui_exe("xpra/gtk_common/gtk_view_keyboard.py", "keyboard.ico",     "GTK_Keyboard_Test")
            add_gui_exe("xpra/scripts/bug_report.py",           "bugs.ico",         "Bug_Report")
            add_gui_exe("xpra/platform/win32/gdi_screen_capture.py", "screenshot.ico", "Screenshot")
        if server_ENABLED:
            add_gui_exe("scripts/auth_dialog",                  "authentication.ico", "Auth_Dialog")
        if gtk2_ENABLED:
            #these need porting..
            add_gui_exe("xpra/gtk_common/gtk_view_clipboard.py","clipboard.ico",    "GTK_Clipboard_Test")
        if mdns_ENABLED and (gtk2_ENABLED or gtk3_ENABLED):
            add_gui_exe("xpra/client/gtk_base/mdns_gui.py",     "mdns.ico",         "Xpra_Browser")
        #Console: provide an Xpra_cmd.exe we can run from the cmd.exe shell
        add_console_exe("scripts/xpra",                     "xpra_txt.ico",     "Xpra_cmd")
        add_console_exe("xpra/scripts/version.py",          "information.ico",  "Version_info")
        add_console_exe("xpra/net/net_util.py",             "network.ico",      "Network_info")
        if gtk2_ENABLED or gtk3_ENABLED:
            add_console_exe("xpra/scripts/gtk_info.py",         "gtk.ico",          "GTK_info")
            add_console_exe("xpra/gtk_common/keymap.py",        "keymap.ico",       "Keymap_info")
            add_console_exe("xpra/platform/keyboard.py",        "keymap.ico",       "Keyboard_info")
        if client_ENABLED or server_ENABLED:
            add_console_exe("win32/python_execfile.py",         "python.ico",       "Python_execfile")
            add_console_exe("xpra/scripts/config.py",           "gears.ico",        "Config_info")
        if server_ENABLED:
            add_console_exe("xpra/server/auth/sqlite_auth.py",  "sqlite.ico",        "SQLite_auth_tool")
            add_console_exe("xpra/server/auth/win32_auth.py",   "authentication.ico", "System-Auth-Test")
            add_console_exe("win32/service/proxy.py",           "xpra_txt.ico",      "Xpra-Proxy")
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
            add_console_exe("scripts/xpra",                     "speaker.ico",      "Xpra_Audio")
            add_console_exe("xpra/platform/win32/directsound.py", "speaker.ico",      "Audio_Devices")
            #add_console_exe("xpra/sound/src.py",                "microphone.ico",   "Sound_Record")
            #add_console_exe("xpra/sound/sink.py",               "speaker.ico",      "Sound_Play")
        if opengl_ENABLED:
            if PYTHON3:
                add_console_exe("xpra/client/gl/gl_check.py",   "opengl.ico",       "OpenGL_check")
            else:
                add_console_exe("xpra/client/gl/gtk_base/gtkgl_check.py", "opengl.ico", "OpenGL_check")
        if webcam_ENABLED:
            add_console_exe("xpra/platform/webcam.py",          "webcam.ico",    "Webcam_info")
            add_console_exe("xpra/scripts/show_webcam.py",          "webcam.ico",    "Webcam_Test")
        if printing_ENABLED:
            add_console_exe("xpra/platform/printing.py",        "printer.ico",     "Print")
            add_console_exe("xpra/platform/win32/pdfium.py",    "printer.ico",     "PDFIUM_Print")
            add_DLLs("pdfium")  #libpdfium.dll
        if nvenc_ENABLED:
            add_console_exe("xpra/codecs/nv_util.py",                   "nvidia.ico",   "NVidia_info")
        if nvfbc_ENABLED:
            add_console_exe("xpra/codecs/nvfbc/capture.py",             "nvidia.ico",   "NvFBC_capture")
        if nvfbc_ENABLED or nvenc_ENABLED:
            add_console_exe("xpra/codecs/cuda_common/cuda_context.py",  "cuda.ico",     "CUDA_info")

        if example_ENABLED:
            add_gui_exe("xpra/client/gtk_base/example/colors.py",               "encoding.ico",     "Colors")
            add_gui_exe("xpra/client/gtk_base/example/colors_gradient.py",      "encoding.ico",     "Colors-Gradient")
            if not PYTHON3:
                add_gui_exe("xpra/client/gtk_base/example/gl_colors_gradient.py",   "encoding.ico",     "OpenGL-Colors-Gradient")
            add_gui_exe("xpra/client/gtk_base/example/colors_plain.py",         "encoding.ico",     "Colors-Plain")
            add_gui_exe("xpra/client/gtk_base/example/bell.py",                 "bell.ico",         "Bell")
            add_gui_exe("xpra/client/gtk_base/example/transparent_colors.py",   "transparent.ico",  "Transparent-Colors")
            add_gui_exe("xpra/client/gtk_base/example/transparent_window.py",   "transparent.ico",  "Transparent-Window")
            add_gui_exe("xpra/client/gtk_base/example/fontrendering.py",        "font.ico",         "Font-Rendering")

        #FIXME: how do we figure out what target directory to use?
        print("calling build_xpra_conf in-place")
        #building etc files in-place:
        build_xpra_conf(".")
        add_data_files('etc/xpra', glob.glob("etc/xpra/*conf"))
        add_data_files('etc/xpra', glob.glob("etc/xpra/nvenc*.keys"))
        add_data_files('etc/xpra', glob.glob("etc/xpra/nvfbc*.keys"))
        add_data_files('etc/xpra/conf.d', glob.glob("etc/xpra/conf.d/*conf"))
        #build minified html5 client in temporary build dir:
        if "clean" not in sys.argv and html5_ENABLED:
            install_html5(os.path.join(install, "www"), )
            for k,v in glob_recurse("build/www").items():
                if (k!=""):
                    k = os.sep+k
                add_data_files('www'+k, v)

    if client_ENABLED or server_ENABLED:
        add_data_files('',      ['COPYING', 'README', 'win32/website.url'])
        add_data_files('icons', glob.glob('win32\\*.ico') + glob.glob('icons\\*.*'))

    if webcam_ENABLED:
        add_data_files('',      ['win32\\DirectShow.tlb'])
        add_modules("comtypes.gen.stdole", "comtypes.gen.DirectShowLib")

    remove_packages(*external_excludes)
    external_includes.append("mmap")
    remove_packages(#not used on win32:
                    #we handle GL separately below:
                    "OpenGL", "OpenGL_accelerate",
                    #this is a mac osx thing:
                    "ctypes.macholib")

    if webcam_ENABLED:
        external_includes.append("cv2")

    if opengl_ENABLED or nvenc_ENABLED or nvfbc_ENABLED:
        #we need numpy for opengl or as a fallback for the Cython xor module
        external_includes.append("numpy")
    else:
        remove_packages("unittest", "difflib",  #avoid numpy warning (not an error)
                        "pydoc")

    #make sure we don't include the gstreamer 0.10 "pygst" bindings:
    remove_packages("pygst", "gst", "gst.extend")

    #add subset of PyOpenGL modules (only when installing):
    if opengl_ENABLED and ("install_exe" in sys.argv or "install" in sys.argv):
        #for this hack to work, you must add "." to the sys.path
        #so python can load OpenGL from the install directory
        #(further complicated by the fact that "." is the "frozen" path...)
        #but we re-add those two directories to the library.zip as part of the build script
        import OpenGL, OpenGL_accelerate        #@UnresolvedImport
        print("*** copying PyOpenGL modules to %s ***" % install)
        for module_name, module in {"OpenGL" : OpenGL, "OpenGL_accelerate" : OpenGL_accelerate}.items():
            module_dir = os.path.dirname(module.__file__ )
            try:
                shutil.copytree(
                    module_dir, os.path.join(install, module_name),
                    ignore = shutil.ignore_patterns("Tk", "AGL", "EGL", "GLX", "GLX.*", "_GLX.*", "GLE", "GLES1", "GLES2", "GLES3")
                )
            except Exception as e:
                if not isinstance(e, WindowsError) or (not "already exists" in str(e)): #@UndefinedVariable
                    raise

    add_data_files('', glob.glob("win32\\bundle-extra\\*"))
    add_data_files('', ["bell.wav"])

    #END OF win32
#*******************************************************************************
else:
    #OSX and *nix:
    scripts += ["scripts/xpra", "scripts/xpra_launcher", "scripts/xpra_browser", "scripts/udev_product_version", "scripts/xpra_signal_listener"]
    if POSIX and not OSX:
        libexec_scripts = []
        from xpra.os_util import is_Fedora, is_CentOS
        if is_Fedora() or is_CentOS():
            libexec = "libexec"
        else:
            libexec = "lib"
        if xdg_open_ENABLED:
            libexec_scripts += ["scripts/xdg-open", "scripts/gnome-open", "scripts/gvfs-open"]
        if server_ENABLED:
            libexec_scripts.append("scripts/auth_dialog")
        if libexec_scripts:
            add_data_files("%s/xpra/" % libexec, libexec_scripts)
    add_data_files("share/man/man1",      ["man/xpra.1", "man/xpra_launcher.1", "man/xpra_browser.1"])
    add_data_files("share/xpra",          ["README", "COPYING"])
    add_data_files("share/xpra/icons",    glob.glob("icons/*"))
    add_data_files("share/applications",  ["xdg/xpra-launcher.desktop", "xdg/xpra-browser.desktop", "xdg/xpra.desktop"])
    add_data_files("share/mime/packages", ["xdg/application-x-xpraconfig.xml"])
    add_data_files("share/icons",         ["xdg/xpra.png", "xdg/xpra-mdns.png"])
    add_data_files("share/appdata",       ["xdg/xpra.appdata.xml"])
    add_data_files('share/xpra/',         ["bell.wav"])

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
            if html5_ENABLED:
                install_html5(os.path.join(self.install_dir, "share/xpra/www"))
            install_data.run(self)

            root_prefix = self.install_dir.rstrip("/")
            if root_prefix.endswith("/usr"):
                root_prefix = root_prefix[:-4]    #ie: "/" or "/usr/src/rpmbuild/BUILDROOT/xpra-0.18.0-0.20160513r12573.fc23.x86_64/"
            build_xpra_conf(root_prefix)

            def copytodir(src, dst_dir, dst_name=None, chmod=0o644):
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
                shutil.copyfile(src, dst_file)
                if chmod:
                    os.chmod(dst_file, chmod)

            if printing_ENABLED and POSIX:
                #install "/usr/lib/cups/backend" with 0700 permissions:
                copytodir("cups/xpraforwarder", "lib/cups/backend", chmod=0o700)

            if x11_ENABLED:
                #install xpra_Xdummy if we need it:
                xvfb_command = detect_xorg_setup()
                if any(x.find("xpra_Xdummy")>=0 for x in (xvfb_command or [])) or Xdummy_wrapper_ENABLED is True:
                    copytodir("scripts/xpra_Xdummy", "bin", chmod=0o755)
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
                    copytodir("etc/xpra/%s" % x, "/etc/xpra")
                copytodir("etc/X11/xorg.conf.d/90-xpra-virtual.conf", "/etc/X11/xorg.conf.d/")

            if pam_ENABLED:
                copytodir("etc/pam.d/xpra", "/etc/pam.d")

            systemd_dir = "/lib/systemd/system"
            if service_ENABLED:
                #Linux init service:
                if os.path.exists("/bin/systemctl"):
                    if sd_listen_ENABLED:
                        copytodir("service/xpra.service", systemd_dir)
                    else:
                        copytodir("service/xpra-nosocketactivation.service", systemd_dir, dst_name="xpra.service")
                else:
                    copytodir("service/xpra", "/etc/init.d")
                if os.path.exists("/etc/sysconfig"):
                    copytodir("etc/sysconfig/xpra", "/etc/sysconfig")
                elif os.path.exists("/etc/default"):
                    copytodir("etc/sysconfig/xpra", "/etc/default")
            if sd_listen_ENABLED:
                copytodir("service/xpra.socket", systemd_dir)
            if dbus_ENABLED and proxy_ENABLED:
                copytodir("dbus/xpra.conf", "/etc/dbus-1/system.d")


    # add build_conf to build step
    cmdclass.update({
             'build'        : build_override,
             'build_conf'   : build_conf,
             'install_data' : install_data_override,
             })

    if OSX:
        #pyobjc needs email.parser
        external_includes += ["email", "uu", "urllib", "objc", "cups", "six"]
        if not PYTHON3:
            external_includes += ["urllib2"]
        #OSX package names (ie: gdk-x11-2.0 -> gdk-2.0, etc)
        PYGTK_PACKAGES += ["gdk-2.0", "gtk+-2.0"]
        add_packages("xpra.platform.darwin")
        remove_packages("xpra.platform.win32", "xpra.platform.xposix")
        #to support GStreamer 1.x we need this:
        modules.append("importlib")
        modules.append("xpra.scripts.gtk_info")
        modules.append("xpra.scripts.show_webcam")
    else:
        PYGTK_PACKAGES += ["gdk-x11-2.0", "gtk+-x11-2.0"]
        add_packages("xpra.platform.xposix")
        remove_packages("xpra.platform.win32", "xpra.platform.darwin")
        #not supported by all distros, but doesn't hurt to install them anyway:
        for x in ("tmpfiles.d", "sysusers.d"):
            add_data_files("lib/%s" % x, ["%s/xpra.conf" % x])
        if uinput_ENABLED:
            add_data_files("lib/udev/rules.d/", ["udev/rules.d/71-xpra-virtual-pointer.rules"])

    #gentoo does weird things, calls --no-compile with build *and* install
    #then expects to find the cython modules!? ie:
    #> python2.7 setup.py build -b build-2.7 install --no-compile --root=/var/tmp/portage/x11-wm/xpra-0.7.0/temp/images/2.7
    #otherwise we use the flags to skip pkgconfig
    if ("--no-compile" in sys.argv or "--skip-build" in sys.argv) and not ("build" in sys.argv and "install" in sys.argv):
        pkgconfig = no_pkgconfig

    if OSX and "py2app" in sys.argv:
        import py2app    #@UnresolvedImport
        assert py2app is not None

        #don't use py_modules or scripts with py2app, and no cython:
        del setup_options["py_modules"]
        scripts = []
        def cython_add(*args, **kwargs):
            pass

        remove_packages("ctypes.wintypes", "colorsys")
        remove_packages(*external_excludes)

        try:
            from xpra.src_info import REVISION
        except:
            REVISION = "unknown"
        Plist = {
            "CFBundleDocumentTypes" : {
                "CFBundleTypeExtensions"    : ["Xpra"],
                "CFBundleTypeName"          : "Xpra Session Config File",
                "CFBundleName"              : "Xpra",
                "CFBundleTypeRole"          : "Viewer",
                },
            "CFBundleGetInfoString" : "%s-r%s (c) 2012-2017 http://xpra.org/" % (XPRA_VERSION, REVISION),
            "CFBundleIdentifier"            : "org.xpra.xpra",
            }
        #Note: despite our best efforts, py2app will not copy all the modules we need
        #so the make-app.sh script still has to hack around this problem.
        add_modules(*external_includes)
        #needed by python-lz4:
        add_modules("distutils")
        py2app_options = {
            'iconfile'          : '../osx/xpra.icns',
            'plist'             : Plist,
            'site_packages'     : False,
            'argv_emulation'    : True,
            'strip'             : False,
            'includes'          : modules,
            'excludes'          : excludes,
            'frameworks'        : ['CoreFoundation', 'Foundation', 'AppKit'],
            }
        setup_options["options"] = {"py2app": py2app_options}
        setup_options["app"]     = ["xpra/client/gtk_base/client_launcher.py"]

    if OSX:
        #simply adding the X11 path to PKG_CONFIG_PATH breaks things in mysterious ways,
        #so instead we have to query each package seperately and merge the results:
        def osx_pkgconfig(*pkgs_options, **ekw):
            kw = dict(ekw)
            for pkg in pkgs_options:
                saved_pcp = os.environ.get("PKG_CONFIG_PATH")
                if pkg.lower().startswith("x"):
                    os.environ["PKG_CONFIG_PATH"] = "/usr/X11/lib/pkgconfig"
                #print("exec_pkgconfig(%s, %s)", pkg, kw)
                kw = exec_pkgconfig(pkg, **kw)
                os.environ["PKG_CONFIG_PATH"] = saved_pcp
            return kw

        pkgconfig = osx_pkgconfig


if html5_ENABLED:
    if WIN32 or OSX:
        external_includes.append("websockify")
        external_includes.append("numpy")
        external_includes.append("ssl")
        external_includes.append("_ssl")
        if not PYTHON3:
            external_includes.append("mimetypes")
            external_includes.append("mimetools")
            external_includes.append("BaseHTTPServer")


if annotate_ENABLED:
    from Cython.Compiler import Options
    Options.annotate = True


#*******************************************************************************
buffers_c = "xpra/buffers/buffers.c"
memalign_c = "xpra/buffers/memalign.c"
xxhash_c = "xpra/buffers/xxhash.c"
membuffers_c = [memalign_c, buffers_c, xxhash_c]

add_packages("xpra.buffers")
buffers_pkgconfig = pkgconfig(optimize=3)
cython_add(Extension("xpra.buffers.membuf",
            ["xpra/buffers/membuf.pyx"]+membuffers_c, **buffers_pkgconfig))


toggle_packages(dbus_ENABLED, "xpra.dbus")
toggle_packages(mdns_ENABLED, "xpra.net.mdns")
toggle_packages(server_ENABLED or proxy_ENABLED, "xpra.server", "xpra.server.auth")
toggle_packages(rfb_ENABLED, "xpra.server.rfb")
toggle_packages(proxy_ENABLED, "xpra.server.proxy")
toggle_packages(server_ENABLED, "xpra.server.window")
toggle_packages(shadow_ENABLED, "xpra.server.shadow")
toggle_packages(server_ENABLED or client_ENABLED, "xpra.clipboard")
toggle_packages(x11_ENABLED and dbus_ENABLED and server_ENABLED, "xpra.x11.dbus")

#cannot use toggle here as cx_Freeze will complain if we try to exclude this module:
if dbus_ENABLED and server_ENABLED:
    add_packages("xpra.server.dbus")

if OSX and not PYTHON3:
    quartz_pkgconfig = pkgconfig(*PYGTK_PACKAGES)
    add_to_keywords(quartz_pkgconfig, 'extra_compile_args',
                    "-I/System/Library/Frameworks/Cocoa.framework/Versions/A/Headers/Cocoa.h",
                    '-ObjC',
                    '-mmacosx-version-min=10.10')
    add_to_keywords(quartz_pkgconfig, 'extra_link_args',
                    '-framework', 'Foundation',
                    '-framework', 'AppKit',
                    )
    cython_add(Extension("xpra.platform.darwin.gdk_bindings",
                ["xpra/platform/darwin/gdk_bindings.pyx", "xpra/platform/darwin/nsevent_glue.m"],
                language="objc",
                **quartz_pkgconfig
                ))

monotonic_time_pkgconfig = pkgconfig()
if not OSX and not WIN32:
    add_to_keywords(monotonic_time_pkgconfig, 'extra_link_args', "-lrt")
cython_add(Extension("xpra.monotonic_time",
            ["xpra/monotonic_time.pyx", "xpra/monotonic_ctime.c"],
            **monotonic_time_pkgconfig
            ))


toggle_packages(x11_ENABLED, "xpra.x11", "xpra.x11.bindings")
if x11_ENABLED:
    make_constants("xpra", "x11", "bindings", "constants")
    make_constants("xpra", "x11", "gtk2", "constants")

    cython_add(Extension("xpra.x11.bindings.wait_for_x_server",
                ["xpra/x11/bindings/wait_for_x_server.pyx"],
                **pkgconfig("x11")
                ))
    cython_add(Extension("xpra.x11.bindings.display_source",
                ["xpra/x11/bindings/display_source.pyx"],
                **pkgconfig("x11")
                ))
    cython_add(Extension("xpra.x11.bindings.core_bindings",
                ["xpra/x11/bindings/core_bindings.pyx"],
                **pkgconfig("x11")
                ))
    cython_add(Extension("xpra.x11.bindings.posix_display_source",
                ["xpra/x11/bindings/posix_display_source.pyx"],
                **pkgconfig("x11")
                ))

    cython_add(Extension("xpra.x11.bindings.randr_bindings",
                ["xpra/x11/bindings/randr_bindings.pyx"],
                **pkgconfig("x11", "xrandr")
                ))
    cython_add(Extension("xpra.x11.bindings.keyboard_bindings",
                ["xpra/x11/bindings/keyboard_bindings.pyx"],
                **pkgconfig("x11", "xtst", "xfixes", "xkbfile")
                ))

    cython_add(Extension("xpra.x11.bindings.window_bindings",
                ["xpra/x11/bindings/window_bindings.pyx"],
                **pkgconfig("x11", "xtst", "xfixes", "xcomposite", "xdamage", "xext")
                ))
    cython_add(Extension("xpra.x11.bindings.ximage",
                ["xpra/x11/bindings/ximage.pyx"],
                **pkgconfig("x11", "xext", "xcomposite")
                ))
if xinput_ENABLED:
    cython_add(Extension("xpra.x11.bindings.xi2_bindings",
                ["xpra/x11/bindings/xi2_bindings.pyx"],
                **pkgconfig("x11", "xi")
                ))

toggle_packages(gtk_x11_ENABLED, "xpra.x11.gtk_x11")
if gtk_x11_ENABLED:
    toggle_packages(PYTHON3, "xpra.x11.gtk3")
    toggle_packages(not PYTHON3, "xpra.x11.gtk2", "xpra.x11.gtk2.models")
    if PYTHON3:
        #GTK3 display source:
        cython_add(Extension("xpra.x11.gtk3.gdk_display_source",
                    ["xpra/x11/gtk3/gdk_display_source.pyx"],
                    **pkgconfig("gdk-3.0")
                    ))
    else:
        #GTK2:
        cython_add(Extension("xpra.x11.gtk2.gdk_display_source",
                    ["xpra/x11/gtk2/gdk_display_source.pyx"],
                    **pkgconfig(*PYGTK_PACKAGES, ignored_tokens=gtk2_ignored_tokens)
                    ))
        GDK_BINDINGS_PACKAGES = PYGTK_PACKAGES + ["x11", "xext", "xfixes", "xdamage"]
        cython_add(Extension("xpra.x11.gtk2.gdk_bindings",
                    ["xpra/x11/gtk2/gdk_bindings.pyx"],
                    **pkgconfig(*GDK_BINDINGS_PACKAGES, ignored_tokens=gtk2_ignored_tokens)
                    ))

toggle_packages(not PYTHON3 and (gtk2_ENABLED or gtk_x11_ENABLED), "xpra.gtk_common.gtk2")
if not PYTHON3 and (gtk2_ENABLED or gtk_x11_ENABLED):
    cython_add(Extension("xpra.gtk_common.gtk2.gdk_bindings",
                ["xpra/gtk_common/gtk2/gdk_bindings.pyx"],
                **pkgconfig(*PYGTK_PACKAGES, ignored_tokens=gtk2_ignored_tokens)
                ))

if client_ENABLED and gtk3_ENABLED:
    #cairo workaround:
    if OSX:
        pycairo = "py3cairo"
    else:
        pycairo = "pycairo"
    cython_add(Extension("xpra.client.gtk3.cairo_workaround",
                ["xpra/client/gtk3/cairo_workaround.pyx"],
                **pkgconfig(pycairo)
                ))

if client_ENABLED or server_ENABLED:
    add_packages("xpra.codecs.argb")
    argb_pkgconfig = pkgconfig(optimize=3)
    cython_add(Extension("xpra.codecs.argb.argb",
                ["xpra/codecs/argb/argb.pyx"], **argb_pkgconfig))


#build tests, but don't install them:
toggle_packages(tests_ENABLED, "unit")


if bundle_tests_ENABLED:
    #bundle the tests directly (not in library.zip):
    for k,v in glob_recurse("unit").items():
        if (k!=""):
            k = os.sep+k
        add_data_files("unit"+k, v)

#python-cryptography needs workarounds for bundling:
if crypto_ENABLED and (OSX or WIN32):
    external_includes.append("_ssl")
    external_includes.append("cffi")
    external_includes.append("_cffi_backend")
    external_includes.append("cryptography")
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
    add_modules("xpra.client", "xpra.client.notifications")
toggle_packages((client_ENABLED and (gtk2_ENABLED or gtk3_ENABLED)) or (PYTHON3 and sound_ENABLED) or server_ENABLED, "xpra.gtk_common")
toggle_packages(client_ENABLED and gtk2_ENABLED, "xpra.client.gtk2")
toggle_packages(client_ENABLED and gtk3_ENABLED, "xpra.client.gtk3")
toggle_packages((client_ENABLED and gtk3_ENABLED) or (sound_ENABLED and WIN32 and (MINGW_PREFIX or PYTHON3)), "gi")
toggle_packages(client_ENABLED and (gtk2_ENABLED or gtk3_ENABLED), "xpra.client.gtk_base")
toggle_packages(client_ENABLED and opengl_ENABLED and gtk2_ENABLED, "xpra.client.gl.gtk2")
toggle_packages(client_ENABLED and opengl_ENABLED and gtk3_ENABLED, "xpra.client.gl.gtk3")
toggle_packages(client_ENABLED and (gtk2_ENABLED or gtk3_ENABLED) and example_ENABLED, "xpra.client.gtk_base.example")
if client_ENABLED and WIN32 and MINGW_PREFIX:
    propsys_pkgconfig = pkgconfig()
    if debug_ENABLED:
        add_to_keywords(propsys_pkgconfig, 'extra_compile_args', "-DDEBUG")
    add_to_keywords(propsys_pkgconfig, 'extra_link_args', "-luuid", "-lshlwapi", "-lole32", "-static-libgcc")
    cython_add(Extension("xpra.platform.win32.propsys",
                ["xpra/platform/win32/propsys.pyx", "xpra/platform/win32/setappid.cpp"],
                language="c++",
                **propsys_pkgconfig))

if client_ENABLED or server_ENABLED:
    add_modules("xpra.codecs")
toggle_packages(client_ENABLED or server_ENABLED, "xpra.keyboard")
if client_ENABLED or server_ENABLED:
    add_modules("xpra.scripts.config", "xpra.scripts.exec_util", "xpra.scripts.fdproxy", "xpra.scripts.version")
if server_ENABLED or proxy_ENABLED:
    add_modules("xpra.scripts.server")
if WIN32 and client_ENABLED and (gtk2_ENABLED or gtk3_ENABLED):
    add_modules("xpra.scripts.gtk_info")

toggle_packages(not WIN32, "xpra.platform.pycups_printing")
#we can't just include "xpra.client.gl" because cx_freeze then do the wrong thing
#and tries to include both gtk3 and gtk2, and fails hard..
for x in ("gl_check", "gl_colorspace_conversions", "gl_window_backing_base", "gl_drivers"):
    toggle_packages(client_ENABLED and opengl_ENABLED, "xpra.client.gl.%s" % x)
toggle_packages(client_ENABLED and opengl_ENABLED and (gtk2_ENABLED or gtk3_ENABLED), "xpra.client.gl.gtk_base")


toggle_modules(sound_ENABLED, "xpra.sound")
toggle_modules(sound_ENABLED and not (OSX or WIN32), "xpra.sound.pulseaudio")

toggle_packages(clipboard_ENABLED, "xpra.clipboard")
if clipboard_ENABLED:
    if PYTHON3:
        cython_add(Extension("xpra.gtk_common.gtk3.gdk_atoms",
                             ["xpra/gtk_common/gtk3/gdk_atoms.pyx"],
                             **pkgconfig("gtk+-3.0")
                             ))
    else:
        cython_add(Extension("xpra.gtk_common.gtk2.gdk_atoms",
                             ["xpra/gtk_common/gtk2/gdk_atoms.pyx"],
                             **pkgconfig(*PYGTK_PACKAGES, ignored_tokens=gtk2_ignored_tokens)
                             ))

toggle_packages(client_ENABLED or server_ENABLED, "xpra.codecs.xor")
if client_ENABLED or server_ENABLED:
    cython_add(Extension("xpra.codecs.xor.cyxor",
                ["xpra/codecs/xor/cyxor.pyx"],
                **pkgconfig(optimize=3)))

if server_ENABLED or shadow_ENABLED:
    O3_pkgconfig = pkgconfig(optimize=3)
    cython_add(Extension("xpra.server.cystats",
                ["xpra/server/cystats.pyx"],
                **O3_pkgconfig))
    cython_add(Extension("xpra.server.window.region",
                ["xpra/server/window/region.pyx"],
                **O3_pkgconfig))
    cython_add(Extension("xpra.server.window.motion",
                ["xpra/server/window/motion.pyx"],
                **O3_pkgconfig))

if sd_listen_ENABLED:
    sdp = pkgconfig("libsystemd")
    cython_add(Extension("xpra.platform.xposix.sd_listen",
                ["xpra/platform/xposix/sd_listen.pyx"],
                **sdp))


toggle_packages(enc_proxy_ENABLED, "xpra.codecs.enc_proxy")

toggle_packages(nvfbc_ENABLED, "xpra.codecs.nvfbc")
if nvfbc_ENABLED:
    nvfbc_pkgconfig = pkgconfig("nvfbc")
    #add_to_keywords(nvfbc_pkgconfig, 'extra_compile_args', "-Wno-endif-labels")
    platform = sys.platform.rstrip("0123456789")
    cython_add(Extension("xpra.codecs.nvfbc.fbc_capture_%s" % platform,
                         ["xpra/codecs/nvfbc/fbc_capture_%s.pyx" % platform],
                         language="c++",
                         **nvfbc_pkgconfig))

toggle_packages(nvenc_ENABLED, "xpra.codecs.nvenc")
toggle_packages(nvenc_ENABLED or nvfbc_ENABLED, "xpra.codecs.cuda_common")
toggle_packages(nvenc_ENABLED or nvfbc_ENABLED, "xpra.codecs.nv_util")

if nvenc_ENABLED and cuda_kernels_ENABLED:
    #find nvcc:
    path_options = os.environ.get("PATH", "").split(os.path.pathsep)
    if WIN32:
        nvcc_exe = "nvcc.exe"
        path_options = [
                         "C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v9.0\\bin",
                         "C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v8.0\\bin",
                         "C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v7.5\\bin",
                         ] + path_options
        #pycuda may link against curand, find it and ship it:
        for p in path_options:
            if os.path.exists(p):
                add_data_files("", glob.glob("%s\\curand64*.dll" % p))
                break
    else:
        nvcc_exe = "nvcc"
        for v in ("", "-9.0", "-8.0", "-7.5"):
            path_options += ["/usr/local/cuda%s/bin" % v, "/opt/cuda%s/bin" % v]
    options = [os.path.join(x, nvcc_exe) for x in path_options]
    def which(cmd):
        try:
            code, out, _ = get_status_output(["which", cmd])
            if code==0:
                return out
        except:
            pass
    #prefer the one we find on the $PATH, if any:
    try:
        v = which(nvcc_exe)
        if v and (v not in options):
            options.insert(0, v)
    except:
        pass
    nvcc_versions = {}
    for filename in options:
        if not os.path.exists(filename):
            continue
        code, out, err = get_status_output([filename, "--version"])
        if code==0:
            vpos = out.rfind(", V")
            if vpos>0:
                version = out[vpos+3:].strip("\n")
                version_str = " version %s" % version
            else:
                version = "0"
                version_str = " unknown version!"
            print("found CUDA compiler: %s%s" % (filename, version_str))
            nvcc_versions[version] = filename
    assert nvcc_versions, "cannot find nvcc compiler!"
    #choose the most recent one:
    version, nvcc = list(reversed(sorted(nvcc_versions.items())))[0]
    if len(nvcc_versions)>1:
        print(" using version %s from %s" % (version, nvcc))
    if WIN32:
        cuda_path = os.path.dirname(nvcc)           #strip nvcc.exe
        cuda_path = os.path.dirname(cuda_path)      #strip /bin/
    #first compile the cuda kernels
    #(using the same cuda SDK for both nvenc modules for now..)
    #TODO:
    # * compile directly to output directory instead of using data files?
    # * detect which arches we want to build for? (does it really matter much?)
    kernels = ("ARGB_to_NV12", "ARGB_to_YUV444", "BGRA_to_NV12", "BGRA_to_YUV444")
    for kernel in kernels:
        cuda_src = "xpra/codecs/cuda_common/%s.cu" % kernel
        cuda_bin = "xpra/codecs/cuda_common/%s.fatbin" % kernel
        if os.path.exists(cuda_bin) and (cuda_rebuild_ENABLED is False):
            continue
        reason = should_rebuild(cuda_src, cuda_bin)
        if not reason:
            continue
        cmd = [nvcc,
               '-fatbin',
               #"-cubin",
               #"-arch=compute_30", "-code=compute_30,sm_30,sm_35",
               #"-gencode=arch=compute_50,code=sm_50",
               #"-gencode=arch=compute_52,code=sm_52",
               #"-gencode=arch=compute_52,code=compute_52",
               "-c", cuda_src,
               "-o", cuda_bin]
        #GCC 6 uses C++11 by default:
        if get_gcc_version()>=[6, 0]:
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
        comp_code_options = [(30, 30), (35, 35)]
        #see: http://docs.nvidia.com/cuda/maxwell-compatibility-guide/#building-maxwell-compatible-apps-using-cuda-6-0
        if version!="0" and version<"7.5":
            print("CUDA version %s is very unlikely to work")
            print("try upgrading to version 7.5 or later")
        if version>="7.5":
            comp_code_options.append((50, 50))
            comp_code_options.append((52, 52))
            comp_code_options.append((53, 53))
        if version>="8.0":
            comp_code_options.append((60, 60))
            comp_code_options.append((61, 61))
            comp_code_options.append((62, 62))
        if version>="9.0":
            comp_code_options.append((70, 70))
        for arch, code in comp_code_options:
            cmd.append("-gencode=arch=compute_%s,code=sm_%s" % (arch, code))
        print("CUDA compiling %s (%s)" % (kernel.ljust(16), reason))
        print(" %s" % " ".join("'%s'" % x for x in cmd))
        c, stdout, stderr = get_status_output(cmd)
        if c!=0:
            print("Error: failed to compile CUDA kernel %s" % kernel)
            print(stdout or "")
            print(stderr or "")
            sys.exit(1)
    CUDA_BIN = "share/xpra/cuda"
    if WIN32:
        CUDA_BIN = "CUDA"
    add_data_files(CUDA_BIN, ["xpra/codecs/cuda_common/%s.fatbin" % x for x in kernels])

if nvenc_ENABLED:
    nvencmodule = "nvenc"
    nvenc_pkgconfig = pkgconfig(nvencmodule, ignored_flags=["-l", "-L"])
    #don't link against libnvidia-encode, we load it dynamically:
    libraries = nvenc_pkgconfig.get("libraries", [])
    if "nvidia-encode" in libraries:
        libraries.remove("nvidia-encode")
    if PYTHON3 and get_gcc_version()>=[6, 2]:
        #with gcc 6.2 on Fedora:
        #xpra/codecs/nvenc/encoder.c: In function '__Pyx_PyInt_LshiftObjC':
        #xpra/codecs/nvenc/encoder.c:45878:34: error: comparison between signed and unsigned integer expressions [-Werror=sign-compare]
        #    if (unlikely(!(b < sizeof(long)*8 && a == x >> b)) && a) {
        add_to_keywords(nvenc_pkgconfig, 'extra_compile_args', "-Wno-sign-compare")
    cython_add(Extension("xpra.codecs.%s.encoder" % nvencmodule,
                         ["xpra/codecs/%s/encoder.pyx" % nvencmodule],
                         **nvenc_pkgconfig))

toggle_packages(enc_x264_ENABLED, "xpra.codecs.enc_x264")
if enc_x264_ENABLED:
    x264_pkgconfig = pkgconfig("x264")
    if get_gcc_version()>=[6, 0]:
        add_to_keywords(x264_pkgconfig, 'extra_compile_args', "-Wno-unused-variable")
    cython_add(Extension("xpra.codecs.enc_x264.encoder",
                ["xpra/codecs/enc_x264/encoder.pyx"],
                **x264_pkgconfig))

toggle_packages(enc_x265_ENABLED, "xpra.codecs.enc_x265")
if enc_x265_ENABLED:
    x265_pkgconfig = pkgconfig("x265")
    cython_add(Extension("xpra.codecs.enc_x265.encoder",
                ["xpra/codecs/enc_x265/encoder.pyx"],
                **x265_pkgconfig))

toggle_packages(pillow_ENABLED, "xpra.codecs.pillow")
if pillow_ENABLED:
    external_includes += ["PIL", "PIL.Image", "PIL.WebPImagePlugin"]

toggle_packages(webp_ENABLED, "xpra.codecs.webp")
if webp_ENABLED:
    webp_pkgconfig = pkgconfig("webp")
    cython_add(Extension("xpra.codecs.webp.encode",
                    ["xpra/codecs/webp/encode.pyx"],
                    **webp_pkgconfig))
    cython_add(Extension("xpra.codecs.webp.decode",
                ["xpra/codecs/webp/decode.pyx"],
                **webp_pkgconfig))

toggle_packages(jpeg_ENABLED, "xpra.codecs.jpeg")
if jpeg_ENABLED:
    jpeg_pkgconfig = pkgconfig("libturbojpeg")
    cython_add(Extension("xpra.codecs.jpeg.encoder",
                ["xpra/codecs/jpeg/encoder.pyx"],
                **jpeg_pkgconfig))
    cython_add(Extension("xpra.codecs.jpeg.decoder",
                ["xpra/codecs/jpeg/decoder.pyx"],
                **jpeg_pkgconfig))

#swscale and avcodec2 use libav_common/av_log:
libav_common = dec_avcodec2_ENABLED or csc_swscale_ENABLED
toggle_packages(libav_common, "xpra.codecs.libav_common")
if libav_common:
    avutil_pkgconfig = pkgconfig("avutil")
    cython_add(Extension("xpra.codecs.libav_common.av_log",
                ["xpra/codecs/libav_common/av_log.pyx"],
                **avutil_pkgconfig))


toggle_packages(dec_avcodec2_ENABLED, "xpra.codecs.dec_avcodec2")
if dec_avcodec2_ENABLED:
    avcodec2_pkgconfig = pkgconfig("avcodec", "avutil")
    cython_add(Extension("xpra.codecs.dec_avcodec2.decoder",
                ["xpra/codecs/dec_avcodec2/decoder.pyx"],
                **avcodec2_pkgconfig))


toggle_packages(csc_libyuv_ENABLED, "xpra.codecs.csc_libyuv")
if csc_libyuv_ENABLED:
    libyuv_pkgconfig = pkgconfig("libyuv")
    cython_add(Extension("xpra.codecs.csc_libyuv.colorspace_converter",
                ["xpra/codecs/csc_libyuv/colorspace_converter.pyx"],
                language="c++",
                **libyuv_pkgconfig))

toggle_packages(csc_swscale_ENABLED, "xpra.codecs.csc_swscale")
if csc_swscale_ENABLED:
    swscale_pkgconfig = pkgconfig("swscale", "avutil")
    cython_add(Extension("xpra.codecs.csc_swscale.colorspace_converter",
                ["xpra/codecs/csc_swscale/colorspace_converter.pyx"],
                **swscale_pkgconfig))


toggle_packages(vpx_ENABLED, "xpra.codecs.vpx")
if vpx_ENABLED:
    vpx_pkgconfig = pkgconfig("vpx")
    cython_add(Extension("xpra.codecs.vpx.encoder",
                ["xpra/codecs/vpx/encoder.pyx"],
                **vpx_pkgconfig))
    cython_add(Extension("xpra.codecs.vpx.decoder",
                ["xpra/codecs/vpx/decoder.pyx"],
                **vpx_pkgconfig))

toggle_packages(enc_ffmpeg_ENABLED, "xpra.codecs.enc_ffmpeg")
if enc_ffmpeg_ENABLED:
    ffmpeg_pkgconfig = pkgconfig("libavcodec", "libavformat", "libavutil")
    cython_add(Extension("xpra.codecs.enc_ffmpeg.encoder",
                ["xpra/codecs/enc_ffmpeg/encoder.pyx"],
                **ffmpeg_pkgconfig))

toggle_packages(v4l2_ENABLED, "xpra.codecs.v4l2")
if v4l2_ENABLED:
    v4l2_pkgconfig = pkgconfig()
    #fuly warning: cython makes this difficult,
    #we have to figure out if "device_caps" exists in the headers:
    ENABLE_DEVICE_CAPS = False
    if os.path.exists("/usr/include/linux/videodev2.h"):
        hdata = open("/usr/include/linux/videodev2.h").read()
        ENABLE_DEVICE_CAPS = hdata.find("device_caps")>=0
    kwargs = {"ENABLE_DEVICE_CAPS" : ENABLE_DEVICE_CAPS}
    make_constants("xpra", "codecs", "v4l2", "constants", **kwargs)
    cython_add(Extension("xpra.codecs.v4l2.pusher",
                ["xpra/codecs/v4l2/pusher.pyx"],
                **v4l2_pkgconfig))


toggle_packages(bencode_ENABLED, "xpra.net.bencode")
toggle_packages(bencode_ENABLED and cython_bencode_ENABLED, "xpra.net.bencode.cython_bencode")
if cython_bencode_ENABLED:
    bencode_pkgconfig = pkgconfig(optimize=not debug_ENABLED)
    cython_add(Extension("xpra.net.bencode.cython_bencode",
                ["xpra/net/bencode/cython_bencode.pyx"],
                **bencode_pkgconfig))

if netdev_ENABLED:
    netdev_pkgconfig = pkgconfig()
    cython_add(Extension("xpra.platform.xposix.netdev_query",
                ["xpra/platform/xposix/netdev_query.pyx"],
                **netdev_pkgconfig))

if vsock_ENABLED:
    vsock_pkgconfig = pkgconfig()
    cython_add(Extension("xpra.net.vsock",
                ["xpra/net/vsock.pyx"],
                **vsock_pkgconfig))

if pam_ENABLED:
    pam_pkgconfig = pkgconfig()
    add_to_keywords(pam_pkgconfig, 'extra_compile_args', "-I/usr/include/pam", "-I/usr/include/security")
    add_to_keywords(pam_pkgconfig, 'extra_link_args', "-lpam", "-lpam_misc")
    cython_add(Extension("xpra.server.pam",
                ["xpra/server/pam.pyx"],
                **pam_pkgconfig))


if ext_modules:
    from Cython.Build import cythonize
    #this causes Cython to fall over itself:
    #gdb_debug=debug_ENABLED
    setup_options["ext_modules"] = cythonize(ext_modules, gdb_debug=False)
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
        except:
            def pv(v):
                return str(v)
        for k,v in setup_options.items():
            print_option("", k, pv(v))
        print("")

    setup(**setup_options)


if __name__ == "__main__":
    main()
