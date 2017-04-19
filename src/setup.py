#!/usr/bin/env python

# This file is part of Xpra.
# Copyright (C) 2010-2016 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

##############################################################################
# FIXME: Cython.Distutils.build_ext leaves crud in the source directory.  (So
# does the make_constants hack.)

import glob
import site
from distutils.core import setup
from distutils.extension import Extension
import sys
import os.path
from distutils.command.build import build
from distutils.command.install_data import install_data
import shutil

if sys.version<'2.6':
    raise Exception("xpra no longer supports Python versions older than 2.6")

from hashlib import md5

print(" ".join(sys.argv))

#*******************************************************************************
# build options, these may get modified further down..
#
import xpra
data_files = []
modules = []
packages = []       #used by py2app and py2exe
excludes = []       #only used by py2exe on win32
ext_modules = []
cmdclass = {}
scripts = []
description = "multi-platform screen and application forwarding system"
long_description = "Xpra is a multi platform persistent remote display server and client for " + \
            "forwarding applications and desktop screens. Also known as 'screen for X11'."
url = "http://xpra.org/"

setup_options = {
                 "name"             : "xpra",
                 "version"          : xpra.__version__,
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
PYTHON3 = sys.version_info[0] == 3


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


from xpra import __version__
print("Xpra version %s" % __version__)
#*******************************************************************************
# Most of the options below can be modified on the command line
# using --with-OPTION or --without-OPTION
# only the default values are specified here:
#*******************************************************************************
from xpra.os_util import get_status_output

PKG_CONFIG = os.environ.get("PKG_CONFIG", "pkg-config")
has_pkg_config = False
#we don't support building with "pkg-config" on win32 with python2:
if PKG_CONFIG and (PYTHON3 or not WIN32):
    pkg_config_version = get_status_output([PKG_CONFIG, "--version"])
    has_pkg_config = pkg_config_version[0]==0 and pkg_config_version[1]
    if has_pkg_config:
        print("found pkg-config version: %s" % pkg_config_version[1].strip("\n\r"))

for arg in list(sys.argv):
    if arg.startswith("--pkg-config-path="):
        pcp = arg[len("--pkg-config-path="):]
        pcps = [pcp] + os.environ.get("PKG_CONFIG_PATH", "").split(os.path.pathsep)
        os.environ["PKG_CONFIG_PATH"] = os.path.pathsep.join([x for x in pcps if x])
        print("using PKG_CONFIG_PATH=%s" % (os.environ["PKG_CONFIG_PATH"], ))
        sys.argv.remove(arg)

def pkg_config_ok(*args, **kwargs):
    if not has_pkg_config:
        return kwargs.get("fallback", False)
    cmd = [PKG_CONFIG]  + [str(x) for x in args]
    return get_status_output(cmd)[0]==0

def pkg_config_version(req_version, pkgname, **kwargs):
    if not has_pkg_config:
        return kwargs.get("fallback", False)
    cmd = [PKG_CONFIG, "--modversion", pkgname]
    r, out, _ = get_status_output(cmd)
    if r!=0 or not out:
        return False
    from distutils.version import LooseVersion
    return LooseVersion(out)>=LooseVersion(req_version)

def check_pyopencl_AMD():
    try:
        import pyopencl
        opencl_platforms = pyopencl.get_platforms()         #@UndefinedVariable
        for platform in opencl_platforms:
            if platform.name.startswith("AMD"):
                print("WARNING: AMD OpenCL icd found, refusing to build OpenCL by default!")
                print(" you must use --with-csc_opencl to force enable it, then deal with the bugs it causes yourself")
                return False
    except:
        pass
    return True

def is_RH():
    try:
        with open("/etc/redhat-release", mode='rb') as f:
            data = f.read()
        return data.startswith("CentOS") or data.startswith("RedHat")
    except:
        pass
    return False

def is_msvc():
    #ugly: assume we want to use visual studio if we find the env var:
    return os.environ.get("VCINSTALLDIR") is not None

DEFAULT = True
if "--minimal" in sys.argv:
    sys.argv.remove("--minimal")
    DEFAULT = False

from xpra.platform.features import LOCAL_SERVERS_SUPPORTED, SHADOW_SUPPORTED
shadow_ENABLED = SHADOW_SUPPORTED and not PYTHON3 and DEFAULT       #shadow servers use some GTK2 code..
server_ENABLED = (LOCAL_SERVERS_SUPPORTED or shadow_ENABLED) and not PYTHON3 and DEFAULT
service_ENABLED = LINUX and server_ENABLED
proxy_ENABLED  = DEFAULT
client_ENABLED = DEFAULT

x11_ENABLED = DEFAULT and not WIN32 and not OSX
dbus_ENABLED = DEFAULT and x11_ENABLED and not (OSX or WIN32)
gtk_x11_ENABLED = DEFAULT and not WIN32 and not OSX
gtk2_ENABLED = DEFAULT and client_ENABLED and not PYTHON3
gtk3_ENABLED = DEFAULT and client_ENABLED and PYTHON3
opengl_ENABLED = DEFAULT and client_ENABLED
html5_ENABLED = DEFAULT
minify_ENABLED = html5_ENABLED
pam_ENABLED = DEFAULT and (server_ENABLED or proxy_ENABLED) and os.name=="posix" and not OSX and (os.path.exists("/usr/include/pam/pam_misc.h") or os.path.exists("/usr/include/security/pam_misc.h"))

vsock_ENABLED           = sys.platform.startswith("linux") and os.path.exists("/usr/include/linux/vm_sockets.h")
bencode_ENABLED         = DEFAULT
cython_bencode_ENABLED  = DEFAULT
clipboard_ENABLED       = DEFAULT and not PYTHON3
Xdummy_ENABLED          = None          #None means auto-detect
Xdummy_wrapper_ENABLED  = None          #None means auto-detect
if WIN32 or OSX:
    Xdummy_ENABLED = False
sound_ENABLED           = DEFAULT
printing_ENABLED        = DEFAULT
crypto_ENABLED          = DEFAULT
mdns_ENABLED            = DEFAULT

enc_proxy_ENABLED       = DEFAULT
enc_x264_ENABLED        = DEFAULT and pkg_config_ok("--exists", "x264", fallback=WIN32)
enc_x265_ENABLED        = DEFAULT and pkg_config_ok("--exists", "x265")
enc_xvid_ENABLED        = DEFAULT and pkg_config_ok("--exists", "xvid")
pillow_ENABLED          = DEFAULT
webp_ENABLED            = False
vpx_ENABLED             = DEFAULT and pkg_config_version("1.3", "vpx", fallback=WIN32)
enc_ffmpeg_ENABLED      = DEFAULT and pkg_config_version("56", "libavcodec")
webcam_ENABLED          = DEFAULT and not OSX
v4l2_ENABLED            = DEFAULT and (not WIN32 and not OSX and not sys.platform.startswith("freebsd"))
#ffmpeg 2 onwards:
dec_avcodec2_ENABLED    = DEFAULT and pkg_config_version("56", "libavcodec", fallback=WIN32)
# some version strings I found:
# Fedora:
# * 19: 54.92.100
# * 20: 55.39.101
# * 21: 55.52.102
# Debian:
# * jessie and sid: (last updated 2014-05-26): 55.34.1
#   (moved to ffmpeg2 style buffer API sometime in early 2014)
# * wheezy: 53.35
csc_swscale_ENABLED     = DEFAULT and pkg_config_ok("--exists", "libswscale", fallback=WIN32)
csc_cython_ENABLED      = DEFAULT
csc_opencv_ENABLED      = DEFAULT and not OSX
if WIN32:
    WIN32_BUILD_LIB_PREFIX = os.environ.get("XPRA_WIN32_BUILD_LIB_PREFIX", "C:\\")
    nvenc7_sdk = WIN32_BUILD_LIB_PREFIX + "Video_Codec_SDK_7.0.1"
    nvapi_path = WIN32_BUILD_LIB_PREFIX + "NVAPI"
    try:
        import pycuda
    except:
        pycuda = None
    nvenc7_ENABLED          = DEFAULT and pycuda and os.path.exists(nvenc7_sdk) and is_msvc()
else:
    nvenc7_ENABLED          = DEFAULT and pkg_config_ok("--exists", "nvenc7")

memoryview_ENABLED      = sys.version>='2.7'
csc_opencl_ENABLED      = DEFAULT and pkg_config_ok("--exists", "OpenCL") and check_pyopencl_AMD()
csc_libyuv_ENABLED      = DEFAULT and memoryview_ENABLED and pkg_config_ok("--exists", "libyuv", fallback=WIN32)

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
SWITCHES = ["enc_x264", "enc_x265", "enc_xvid", "enc_ffmpeg",
            "nvenc7",
            "vpx", "webp", "pillow",
            "v4l2",
            "dec_avcodec2", "csc_swscale",
            "csc_opencl", "csc_cython", "csc_opencv", "csc_libyuv",
            "memoryview",
            "bencode", "cython_bencode", "vsock", "mdns",
            "clipboard",
            "server", "client", "dbus", "x11", "gtk_x11", "service",
            "gtk2", "gtk3",
            "html5", "minify",
            "pam",
            "sound", "opengl", "printing", "webcam",
            "rebuild",
            "annotate", "warn", "strict",
            "shadow", "proxy",
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

rpath = None
ssl_cert = None
ssl_key = None
filtered_args = []
for arg in sys.argv:
    matched = False
    for x in ("rpath", "ssl-cert", "ssl-key"):
        varg = "--%s=" % x
        if arg.startswith(varg):
            value = arg[len(varg):]
            globals()[x.replace("-", "_")] = value
            matched = True
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
    for k in SWITCHES:
        v = switches_info[k]
        print("* %s : %s" % (str(k).ljust(20), {None : "Auto", True : "Y", False : "N"}.get(v, v)))

    #sanity check the flags:
    if clipboard_ENABLED and not server_ENABLED and not gtk2_ENABLED and not gtk3_ENABLED:
        print("Warning: clipboard can only be used with the server or one of the gtk clients!")
        clipboard_ENABLED = False
    if shadow_ENABLED and not server_ENABLED:
        print("Warning: shadow requires server to be enabled!")
        shadow_ENABLED = False
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
    if memoryview_ENABLED and sys.version<"2.7":
        print("Error: memoryview support requires Python version 2.7 or greater")
        exit(1)
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
if DEFAULT:
    external_includes += ["Crypto", "Crypto.Cipher"]
else:
    excludes += ["Crypto", "Crypto.Cipher"]


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
                    "urllib2", "tty",
                    "cookielib", "ftplib", "httplib", "fileinput",
                    "distutils", "setuptools", "doctest"
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
#for distutils / py2app and py2exe
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


def check_md5sums(md5sums):
    print("Verifying md5sums:")
    for filename, md5sum in md5sums.items():
        if not os.path.exists(filename) or not os.path.isfile(filename):
            sys.exit("ERROR: file %s is missing or not a file!" % filename)
        sys.stdout.write("* %s: " % str(filename).ljust(52))
        with open(filename, mode='rb') as f:
            data = f.read()
        m = md5()
        m.update(data)
        digest = m.hexdigest()
        assert digest==md5sum, "md5 digest for file %s does not match, expected %s but found %s" % (filename, md5sum, digest)
        sys.stdout.write("OK\n")
        sys.stdout.flush()

#for pretty printing of options:
def print_option(prefix, k, v):
    if type(v)==dict:
        print("%s* %s:" % (prefix, k))
        for kk,vv in v.items():
            print_option(" "+prefix, kk, vv)
    else:
        print("%s* %s=%s" % (prefix, k, v))
def print_dict(d):
    for k,v in d.items():
        print_option("", k, v)

#*******************************************************************************
# Utility methods for building with Cython
def cython_version_check(min_version):
    try:
        from Cython.Compiler.Version import version as cython_version
    except ImportError as e:
        sys.exit("ERROR: Cannot find Cython: %s" % e)
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
        add_to_keywords(kw, 'extra_compile_args', "-O%i" % optimize)
    ignored_flags = []
    if kw.get("ignored_flags"):
        ignored_flags = kw.get("ignored_flags")
        del kw["ignored_flags"]

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
                if token[:2] in ignored_flags:
                    pass
                elif token[:2] in flag_map:
                    add_to_keywords(kw, flag_map.get(token[:2]), token[2:])
                else: # throw others to extra_link_args
                    add_to_keywords(kw, 'extra_link_args', token)
    if warn_ENABLED:
        if is_msvc():
            add_to_keywords(kw, 'extra_compile_args', "/Wall")
        else:
            add_to_keywords(kw, 'extra_compile_args', "-Wall")
            add_to_keywords(kw, 'extra_link_args', "-Wall")
    if strict_ENABLED:
        if is_msvc():
            add_to_keywords(kw, 'extra_compile_args', "/wd4005")    #macro redifined with vpx vs stdint.h
            add_to_keywords(kw, 'extra_compile_args', "/wd4146")    #MSVC error in __Pyx_PyInt_As_size_t
            add_to_keywords(kw, 'extra_compile_args', "/wd4293")    #MSVC error in __Pyx_PyFloat_DivideObjC
            add_to_keywords(kw, 'extra_compile_args', "/WX")
            add_to_keywords(kw, 'extra_link_args', "/WX")
        else:
            if os.environ.get("CC", "").find("clang")>=0:
                #clang emits too many warnings with cython code,
                #so we can't enable Werror
                eifd = ["-Werror",
                        "-Wno-unneeded-internal-declaration",
                        "-Wno-unknown-attributes",
                        "-Wno-unused-function",
                        "-Wno-self-assign",
                        "-Wno-sometimes-uninitialized"]
            elif get_gcc_version()>=[4, 4]:
                eifd = ["-Werror",
                        #CentOS 6.x gives us some invalid warnings in nvenc, ignore those:
                        #"-Wno-error=uninitialized",
                        #needed on Debian and Ubuntu to avoid this error:
                        #/usr/include/gtk-2.0/gtk/gtkitemfactory.h:47:1: error: function declaration isn't a prototype [-Werror=strict-prototypes]
                        #"-Wno-error=strict-prototypes",
                        ]
                if sys.platform.startswith("netbsd"):
                    #see: http://trac.cython.org/ticket/395
                    eifd += ["-fno-strict-aliasing"]
                elif sys.platform.startswith("freebsd"):
                    eifd += ["-Wno-error=unused-function"]
            else:
                #older versions of OSX ship an old gcc,
                #not much we can do with this:
                eifd = []
            for eif in eifd:
                add_to_keywords(kw, 'extra_compile_args', eif)
    if PIC_ENABLED and not is_msvc():
        add_to_keywords(kw, 'extra_compile_args', "-fPIC")
    if debug_ENABLED:
        if is_msvc():
            add_to_keywords(kw, 'extra_compile_args', '/Zi')
        else:
            add_to_keywords(kw, 'extra_compile_args', '-g')
            add_to_keywords(kw, 'extra_compile_args', '-ggdb')
            if get_gcc_version()>=[4, 8]:
                add_to_keywords(kw, 'extra_compile_args', '-fsanitize=address')
                add_to_keywords(kw, 'extra_link_args', '-fsanitize=address')
    if rpath:
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
        return ["no", "yes"][int(b)]
    start_env = "\n".join("start-env = %s" % x for x in DEFAULT_ENV)
    conf_dir = get_conf_dir(install_dir)
    from xpra.platform.features import DEFAULT_SSH_COMMAND, DEFAULT_PULSEAUDIO_COMMAND, DEFAULT_PULSEAUDIO_CONFIGURE_COMMANDS
    from xpra.platform.paths import get_socket_dirs
    from xpra.scripts.config import get_default_key_shortcuts, get_default_systemd_run, DEFAULT_POSTSCRIPT_PRINTER
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
    if os.name=="posix" and printing_ENABLED:
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
    from xpra.os_util import getUbuntuVersion
    webcam = webcam_ENABLED and not (OSX or getUbuntuVersion()==[16, 10])
    #no python-avahi on RH / CentOS, need dbus module on *nix:
    mdns = mdns_ENABLED and (OSX or WIN32 or (not is_RH() and dbus_ENABLED))
    SUBS = {
            'xvfb_command'          : pretty_cmd(xvfb_command),
            'ssh_command'           : DEFAULT_SSH_COMMAND,
            'key_shortcuts'         : "".join(("key-shortcut = %s\n" % x) for x in get_default_key_shortcuts()),
            'remote_logging'        : "both",
            'start_env'             : start_env,
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
            'pulseaudio'            : bstr(not OSX and not WIN32),
            'pdf_printer'           : pdf,
            'postscript_printer'    : postscript,
            'webcam'                : ["no", "auto"][webcam],
            'printing'              : printing_ENABLED,
            'dbus_control'          : bstr(dbus_ENABLED),
            'mmap'                  : bstr(not OSX and not WIN32),
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
            if f.endswith("osx.conf.in") and not sys.platform.startswith("darwin"):
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
    def pkgconfig(*pkgs_options, **ekw):
        return {}
    #always include everything in this case:
    add_packages("xpra")
    #ensure we remove the files we generate:
    CLEAN_FILES = [
                   "xpra/build_info.py",
                   "xpra/gtk_common/gdk_atoms.c",
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
                   "xpra/net/bencode/cython_bencode.c",
                   "xpra/net/vsock.c",
                   "xpra/codecs/vpx/encoder.c",
                   "xpra/codecs/vpx/decoder.c",
                   "xpra/codecs/vpx/constants.pxi",
                   "xpra/codecs/nvenc7/encoder.c",
                   "xpra/codecs/cuda_common/BGRA_to_NV12.fatbin",
                   "xpra/codecs/cuda_common/BGRA_to_U.fatbin",
                   "xpra/codecs/cuda_common/BGRA_to_V.fatbin",
                   "xpra/codecs/cuda_common/BGRA_to_Y.fatbin",
                   "xpra/codecs/cuda_common/BGRA_to_YUV444.fatbin",
                   "xpra/codecs/enc_x264/encoder.c",
                   "xpra/codecs/enc_x265/encoder.c",
                   "xpra/codecs/enc_ffmpeg/encoder.c",
                   "xpra/codecs/enc_xvid/encoder.c",
                   "xpra/codecs/v4l2/constants.pxi",
                   "xpra/codecs/v4l2/pusher.c",
                   "xpra/codecs/libav_common/av_log.c",
                   "xpra/codecs/webp/encode.c",
                   "xpra/codecs/webp/decode.c",
                   "xpra/codecs/dec_avcodec2/decoder.c",
                   "xpra/codecs/csc_libyuv/colorspace_converter.cpp",
                   "xpra/codecs/csc_swscale/colorspace_converter.c",
                   "xpra/codecs/csc_cython/colorspace_converter.c",
                   "xpra/codecs/xor/cyxor.c",
                   "xpra/codecs/argb/argb.c",
                   "xpra/codecs/nvapi_version.c",
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
    if minify_ENABLED:
        print("minifying html5 client to %s using %s" % (install_dir, minifier))
    else:
        print("copying html5 client to %s" % (install_dir, ))
    for k,files in glob_recurse("html5").items():
        if (k!=""):
            k = os.sep+k
        for f in files:
            src = os.path.join(os.getcwd(), f)
            parts = f.split(os.path.sep)
            if parts[0]=="html5":
                f = os.path.join(*parts[1:])
            if install_dir==".":
                install_dir = os.getcwd()
            dst = os.path.join(install_dir, f)
            ddir = os.path.split(dst)[0]
            if ddir and not os.path.exists(ddir):
                os.makedirs(ddir, 0o755)
            ftype = os.path.splitext(f)[1].lstrip(".")
            if minify_ENABLED and ftype=="js":
                if minifier=="uglifyjs":
                    minify_cmd = ["uglifyjs",
                                  "--screw-ie8",
                                  src,
                                  "-o", dst,
                                  "--compress",
                                  ]
                else:
                    assert minifier=="yuicompressor"
                    assert yuicompressor
                    jar = yuicompressor.get_jar_filename()
                    minify_cmd = ["java", "-jar", jar,
                                  src,
                                  "--nomunge",
                                  "--line-break", "400",
                                  "--type", ftype,
                                  "-o", dst,
                                  ]
                r = get_status_output(minify_cmd)[0]
                if r!=0:
                    print("Error: minify for '%s' returned %i" % (f, r))
                    print(" command: %s" % (minify_cmd,))
                else:
                    print("minified %s" % (f, ))
            else:
                r = -1
            if r!=0:
                shutil.copyfile(src, dst)
                os.chmod(dst, 0o644)


#*******************************************************************************
if WIN32:
    add_packages("xpra.platform.win32")
    remove_packages("xpra.platform.darwin", "xpra.platform.xposix")

    ###########################################################
    #START OF HARDCODED SECTION
    #this should all be done with pkgconfig...
    #but until someone figures this out, the ugly path code below works
    #as long as you install in the same place or tweak the paths.

    #ffmpeg is needed for both swscale and x264:
    libffmpeg_path = ""
    if dec_avcodec2_ENABLED:
        libffmpeg_path = WIN32_BUILD_LIB_PREFIX + "ffmpeg2-win32-bin"
    else:
        if csc_swscale_ENABLED:
            libffmpeg_path = WIN32_BUILD_LIB_PREFIX + "ffmpeg2-win32-bin"
            assert os.path.exists(libffmpeg_path), "no ffmpeg found, cannot use csc_swscale"
    libffmpeg_include_dir   = os.path.join(libffmpeg_path, "include")
    libffmpeg_lib_dir       = os.path.join(libffmpeg_path, "lib")
    libffmpeg_bin_dir       = os.path.join(libffmpeg_path, "bin")
    #x265
    x265_path = WIN32_BUILD_LIB_PREFIX + "x265"
    x265_include_dir    = x265_path
    x265_lib_dir        = x265_path
    x265_bin_dir        = x265_path
    #x264 (direct from build dir.. yuk - sorry!):
    x264_path = WIN32_BUILD_LIB_PREFIX + "x264"
    x264_include_dir    = os.path.join(x264_path, "include")
    x264_lib_dir        = os.path.join(x264_path, "lib")
    x264_bin_dir        = os.path.join(x264_path, "bin")
    # Same for vpx:
    # http://code.google.com/p/webm/downloads/list
    #the path after installing may look like this:
    #vpx_PATH="C:\\vpx-vp8-debug-src-x86-win32mt-vs9-v1.1.0"
    #but we use something more generic, without the version numbers:
    vpx_path = ""
    for v in ("vpx", "vpx-1.5", "vpx-1.4", "vpx-1.3"):
        p = WIN32_BUILD_LIB_PREFIX + v
        if os.path.exists(p) and os.path.isdir(p):
            vpx_path = p
            break
    vpx_include_dir     = os.path.join(vpx_path, "include")
    vpx_lib_dir         = os.path.join(vpx_path, "lib", "Win32")
    vpx_bin_dir         = os.path.join(vpx_path, "lib", "Win32")
    if os.path.exists(os.path.join(vpx_lib_dir, "vpxmd.lib")):
        vpx_lib_names = ["vpxmd"]             #msvc builds only?
    elif os.path.exists(os.path.join(vpx_lib_dir, "vpx.lib")):
        vpx_lib_names = ["vpx"]               #for libvpx 1.3.0
    else:
        vpx_lib_names = ["vpxmt", "vpxmtd"]   #for libvpx 1.1.0

    libyuv_path = WIN32_BUILD_LIB_PREFIX + "libyuv"
    libyuv_include_dir = os.path.join(libyuv_path, "include")
    libyuv_lib_dir = os.path.join(libyuv_path, "lib")
    libyuv_bin_dir = os.path.join(libyuv_path, "bin")
    libyuv_lib_names = ["yuv"]

    # Same for PyGTK / GTK3:
    # http://www.pygtk.org/downloads.html
    if PYTHON3:
        GTK3_DIR = "C:\\GTK3"
        GTK_INCLUDE_DIR = os.path.join(GTK3_DIR, "include")

        #find the gnome python directory
        #(ie: "C:\Python34\Lib\site-packages\gnome")
        #and global include directory
        #(ie: "C:\Python34\include")
        GNOME_DIR = None
        for x in site.getsitepackages():
            t = os.path.join(x, "gnome")
            if os.path.exists(t):
                GNOME_DIR = t
            t = os.path.join(x, "include")
            if os.path.exists(t):
                webp_include_dir = t
        #webp:
        webp_path       = GNOME_DIR
        webp_bin_dir    = GNOME_DIR
        webp_lib_dir    = GNOME_DIR
        webp_lib_names      = ["libwebp"]
    else:
        gtk2_path = "C:\\Python27\\Lib\\site-packages\\gtk-2.0"
        python_include_path = "C:\\Python27\\include"
        gtk2runtime_path        = os.path.join(gtk2_path, "runtime")
        gtk2_lib_dir            = os.path.join(gtk2runtime_path, "bin")
        GTK_INCLUDE_DIR   = os.path.join(gtk2runtime_path, "include")
        #gtk2 only:
        gdkconfig_include_dir   = os.path.join(gtk2runtime_path, "lib", "gtk-2.0", "include")
        glibconfig_include_dir  = os.path.join(gtk2runtime_path, "lib", "glib-2.0", "include")
        pygtk_include_dir       = os.path.join(python_include_path, "pygtk-2.0")
        gtk2_include_dir        = os.path.join(GTK_INCLUDE_DIR, "gtk-2.0")

        #webp:
        webp_path = WIN32_BUILD_LIB_PREFIX + "libwebp-windows-x86"
        webp_include_dir    = webp_path+"\\include"
        webp_lib_dir        = webp_path+"\\lib"
        webp_bin_dir        = webp_path+"\\bin"
        webp_lib_names      = ["libwebp"]

    atk_include_dir         = os.path.join(GTK_INCLUDE_DIR, "atk-1.0")
    gdkpixbuf_include_dir   = os.path.join(GTK_INCLUDE_DIR, "gdk-pixbuf-2.0")
    glib_include_dir        = os.path.join(GTK_INCLUDE_DIR, "glib-2.0")
    cairo_include_dir       = os.path.join(GTK_INCLUDE_DIR, "cairo")
    pango_include_dir       = os.path.join(GTK_INCLUDE_DIR, "pango-1.0")
    #END OF HARDCODED SECTION
    ###########################################################

    #ie: C:\Python3.5\Lib\site-packages\
    site_dir = site.getsitepackages()[1]
    #this is where the win32 gi installer will put things:
    gnome_include_path = os.path.join(site_dir, "gnome")

    #only add the py2exe / cx_freeze specific options
    #if we aren't just building the Cython bits with "build_ext":
    if "build_ext" not in sys.argv:
        #with py2exe and cx_freeze, we don't use py_modules
        del setup_options["py_modules"]
        external_includes += ["win32con", "win32gui", "win32process", "win32api"]
        if PYTHON3:
            from cx_Freeze import setup, Executable     #@UnresolvedImport @Reimport

            #cx_freeze doesn't use "data_files"...
            del setup_options["data_files"]
            #it wants source files first, then where they are placed...
            #one item at a time (no lists)
            #all in its own structure called "include_files" instead of "data_files"...
            def add_data_files(target_dir, files):
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
                print("add_gi(%s)" % str(libs))
                add_dir('lib',      {"girepository-1.0":    ["%s.typelib" % x for x in libs]})
                add_dir('share',    {"gir-1.0" :            ["%s.gir" % x for x in libs]})

            def add_DLLs(*dll_names):
                try:
                    do_add_DLLs(*dll_names)
                except:
                    sys.exit(1)

            def do_add_DLLs(*dll_names):
                print("adding DLLs %s" % ", ".join(dll_names))
                dll_names = list(dll_names)
                dll_files = []
                import re
                version_re = re.compile("\-[0-9\.\-]+$")
                for x in os.listdir(gnome_include_path):
                    pathname = os.path.join(gnome_include_path, x)
                    x = x.lower()
                    if os.path.isdir(pathname) or not x.startswith("lib") or not x.endswith(".dll"):
                        continue
                    nameversion = x[3:-4]                       #strip "lib" and ".dll": "libatk-1.0-0.dll" -> "atk-1.0-0"
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
                        dll_files.append(x)
                        dll_names.remove(dll_name)
                if len(dll_names)>0:
                    print("some DLLs could not be found in '%s':" % gnome_include_path)
                    for x in dll_names:
                        print(" - lib%s*.dll" % x)
                add_data_files("", [os.path.join(gnome_include_path, dll) for dll in dll_files])

            #list of DLLs we want to include, without the "lib" prefix, or the version and extension
            #(ie: "libatk-1.0-0.dll" -> "atk")
            if sound_ENABLED or gtk3_ENABLED:
                add_DLLs('gio', 'girepository', 'glib',
                         'gnutls', 'gobject', 'gthread',
                         'orc', 'stdc++',
                         'proxy',
                         'winpthread',
                         'zzz')
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
                do_add_DLLs('javascriptcoregtk',
                         'gdkglext', 'gtkglext')
            if client_ENABLED and os.environ.get("VCINSTALLDIR"):
                #Visual Studio may link our avcodec2 module against libiconv...
                do_add_DLLs("iconv")
            #this one may be missing in pygi-aio 3.14?
            #ie: libpyglib-gi-2.0-python34
            # pyglib-gi-2.0-python%s%s' % (sys.version_info[0], sys.version_info[1])

            if gtk3_ENABLED:
                add_dir('etc', ["fonts", "gtk-3.0", "pango", "pkcs11"])     #add "dbus-1"?
                add_dir('lib', ["gdk-pixbuf-2.0", "gtk-3.0",
                                "libvisual-0.4", "p11-kit", "pkcs11"])
                add_dir('share', ["fontconfig", "fonts", "glib-2.0",        #add "dbus-1"?
                                  "icons", "p11-kit", "xml",
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
                       "GdkGLExt-3.0", "GtkGLExt-3.0", "GL-1.0",
                       "GdkPixbuf-2.0", "Gdk-3.0", "Gtk-3.0"
                       "HarfBuzz-0.0",
                       "Libproxy-1.0", "libxml2-2.0",
                       "cairo-1.0", "Pango-1.0", "PangoCairo-1.0", "PangoFT2-1.0",
                       "Rsvg-2.0",
                       "win32-1.0")
                add_DLLs('visual', 'curl', 'soup', 'sqlite3', 'openjpeg')

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
                #add the gstreamer plugins we need:
                GST_PLUGINS = ("app",
                               #muxers:
                               "gdp", "matroska", "ogg", "isomp4",
                               "audioparsers", "audiorate", "audioconvert", "audioresample", "audiotestsrc",
                               "coreelements", "directsoundsink", "directsoundsrc",
                               #codecs:
                               "opus", "flac", "lame", "mad", "mpg123", "speex", "faac", "faad",
                               "volume", "vorbis", "wavenc", "wavpack", "wavparse",
                               #untested: a52dec, voaacenc
                               )
                add_dir(os.path.join("lib", "gstreamer-1.0"), [("libgst%s.dll" % x) for x in GST_PLUGINS])
                #END OF SOUND

            if client_ENABLED:
                #pillow links against zlib, but expects the DLL to be named z.dll:
                data_files.append((os.path.join(gnome_include_path, "libzzz.dll"), "z.dll"))

            if server_ENABLED:
                #used by proxy server:
                external_includes += ["multiprocessing"]
            #I am reluctant to add these to py2exe because it figures it out already:
            external_includes += ["encodings"]
            #ensure that cx_freeze won't automatically grab other versions that may lay on our path:
            os.environ["PATH"] = gnome_include_path+";"+os.environ.get("PATH", "")
            bin_excludes = ["MSVCR90.DLL", "MFC100U.DLL", "libsqlite3-0.dll"]
            cx_freeze_options = {
                                "compressed"        : True,
                                "includes"          : external_includes,
                                "packages"          : packages,
                                "include_files"     : data_files,
                                "excludes"          : excludes,
                                "include_msvcr"     : True,
                                "bin_excludes"      : bin_excludes,
                                "create_shared_zip" : zip_ENABLED,
                                }
            setup_options["options"] = {"build_exe" : cx_freeze_options}
            executables = []
            setup_options["executables"] = executables

            def add_exe(script, icon, base_name, base="Console"):
                executables.append(Executable(
                            script                  = script,
                            initScript              = None,
                            #targetDir               = "dist",
                            icon                    = "win32/%s" % icon,
                            targetName              = "%s.exe" % base_name,
                            compress                = True,
                            copyDependentFiles      = True,
                            appendScriptToExe       = False,
                            appendScriptToLibrary   = True,
                            base                    = base))

            def add_console_exe(script, icon, base_name):
                add_exe(script, icon, base_name)
            def add_gui_exe(script, icon, base_name):
                add_exe(script, icon, base_name, base="Win32GUI")
            #END OF cx_freeze SECTION
        else:
            #py2exe recipe for win32com:
            # ModuleFinder can't handle runtime changes to __path__, but win32com uses them
            try:
                # py2exe 0.6.4 introduced a replacement modulefinder.
                # This means we have to add package paths there, not to the built-in
                # one.  If this new modulefinder gets integrated into Python, then
                # we might be able to revert this some day.
                # if this doesn't work, try import modulefinder
                try:
                    import py2exe.mf as modulefinder
                except ImportError:
                    import modulefinder
                import win32com, sys
                for p in win32com.__path__[1:]:
                    modulefinder.AddPackagePath("win32com", p)
                for extra in ["win32com.propsys"]: #,"win32com.mapi"
                    __import__(extra)
                    m = sys.modules[extra]
                    for p in m.__path__[1:]:
                        modulefinder.AddPackagePath(extra, p)
            except ImportError:
                # no build path setup, no worries.
                pass

            import py2exe    #@UnresolvedImport
            assert py2exe is not None
            EXCLUDED_DLLS = list(py2exe.build_exe.EXCLUDED_DLLS) + ["nvcuda.dll",
                            "curand32_55.dll", "curand32_60.dll", "curand32_65.dll",
                            "curand64_55.dll", "curand64_60.dll", "curand64_65.dll", "curand64_70.dll"]
            py2exe.build_exe.EXCLUDED_DLLS = EXCLUDED_DLLS
            py2exe_options = {
                              #"bundle_files"   : 3,
                              "skip_archive"   : not zip_ENABLED,
                              "optimize"       : 0,    #WARNING: do not change - causes crashes
                              "unbuffered"     : True,
                              "compressed"     : zip_ENABLED,
                              "packages"       : packages,
                              "includes"       : external_includes,
                              "excludes"       : excludes,
                              "dll_excludes"   : ["w9xpopen.exe", "tcl85.dll", "tk85.dll", "propsys.dll",
                                #exclude the msys DLLs, as py2exe builds should be using MSVC
                                "msys-2.0.dll", "msys-gcc_s-1.dll", "MSVCP90.dll"],
                             }
            #workaround for setuptools >= 19.3
            add_packages("pkg_resources._vendor.packaging")
            if not zip_ENABLED:
                #the filename is actually ignored because we specify "skip_archive"
                #this places the modules in library/
                setup_options["zipfile"] = "library/foo.zip"
            else:
                setup_options["zipfile"] = "library.zip"
            setup_options["options"] = {"py2exe" : py2exe_options}
            windows = []
            setup_options["windows"] = windows
            console = []
            setup_options["console"] = console

            def add_exe(tolist, script, icon, base_name):
                tolist.append({ 'script'             : script,
                                'icon_resources'    : [(1, "win32/%s" % icon)],
                                "dest_base"         : base_name})
            def add_console_exe(*args):
                add_exe(console, *args)
            def add_gui_exe(*args):
                add_exe(windows, *args)

            # Python2.7 was compiled with Visual Studio 2008:
            # (you can find the DLLs in various packages, including Visual Studio 2008,
            # pywin32, etc...)
            # This is where I keep them, you will obviously need to change this value
            # or make sure you also copy them there:
            C_DLLs = WIN32_BUILD_LIB_PREFIX
            check_md5sums({
               C_DLLs+"Microsoft.VC90.CRT/Microsoft.VC90.CRT.manifest"  : "37f44d535dcc8bf7a826dfa4f5fa319b",
               C_DLLs+"Microsoft.VC90.CRT/msvcm90.dll"                  : "4a8bc195abdc93f0db5dab7f5093c52f",
               C_DLLs+"Microsoft.VC90.CRT/msvcp90.dll"                  : "6de5c66e434a9c1729575763d891c6c2",
               C_DLLs+"Microsoft.VC90.CRT/msvcr90.dll"                  : "e7d91d008fe76423962b91c43c88e4eb",
               C_DLLs+"Microsoft.VC90.CRT/vcomp90.dll"                  : "f6a85f3b0e30c96c993c69da6da6079e",
               C_DLLs+"Microsoft.VC90.MFC/Microsoft.VC90.MFC.manifest"  : "17683bda76942b55361049b226324be9",
               C_DLLs+"Microsoft.VC90.MFC/mfc90.dll"                    : "462ddcc5eb88f34aed991416f8e354b2",
               C_DLLs+"Microsoft.VC90.MFC/mfc90u.dll"                   : "b9030d821e099c79de1c9125b790e2da",
               C_DLLs+"Microsoft.VC90.MFC/mfcm90.dll"                   : "d4e7c1546cf3131b7d84b39f8da9e321",
               C_DLLs+"Microsoft.VC90.MFC/mfcm90u.dll"                  : "371226b8346f29011137c7aa9e93f2f6",
               })
            add_data_files('Microsoft.VC90.CRT', glob.glob(C_DLLs+'Microsoft.VC90.CRT\\*.*'))
            add_data_files('Microsoft.VC90.MFC', glob.glob(C_DLLs+'Microsoft.VC90.MFC\\*.*'))
            if webp_ENABLED and not PYTHON3:
                #add the webp DLL to the output:
                add_data_files('',      [webp_bin_dir+"\\libwebp.dll"])
            if enc_x264_ENABLED:
                add_data_files('', ['%s\\libx264.dll' % x264_bin_dir])
                #find pthread DLL...
                for x in (["C:\\MinGW\\bin"]+os.environ.get("PATH").split(";")):
                    f = os.path.join(x, "pthreadGC2.dll")
                    if os.path.exists(f):
                        add_data_files('', [f])
                        break
            # MS-Windows theme
            add_data_files('etc/gtk-2.0', ['win32/gtkrc'])
            engines_dir = os.path.join(site_dir, 'gtk-2.0/runtime/lib/gtk-2.0/2.10.0/engines')
            add_data_files('lib/gtk-2.0/2.10.0/engines', glob.glob(engines_dir+"/*.dll"))
            hicolor_dir = os.path.join(site_dir, 'gtk-2.0/runtime/share/icons/hicolor')
            add_data_files('share/icons/hicolor', glob.glob(hicolor_dir+"/*.*"))
            #END OF py2exe SECTION

        #UI applications (detached from shell: no text output if ran from cmd.exe)
        if client_ENABLED and (gtk2_ENABLED or gtk3_ENABLED):
            add_gui_exe("scripts/xpra",                         "xpra_txt.ico",     "Xpra")
            add_gui_exe("scripts/xpra_launcher",                "xpra.ico",         "Xpra-Launcher")
            add_gui_exe("xpra/gtk_common/gtk_view_keyboard.py", "keyboard.ico",     "GTK_Keyboard_Test")
            add_gui_exe("xpra/scripts/bug_report.py",           "bugs.ico",         "Bug_Report")
        if gtk2_ENABLED:
            #these need porting..
            add_gui_exe("xpra/gtk_common/gtk_view_clipboard.py","clipboard.ico",    "GTK_Clipboard_Test")
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
        if client_ENABLED:
            add_console_exe("xpra/codecs/loader.py",            "encoding.ico",     "Encoding_info")
            add_console_exe("xpra/platform/paths.py",           "directory.ico",    "Path_info")
            add_console_exe("xpra/platform/features.py",        "features.ico",     "Feature_info")
        if client_ENABLED:
            add_console_exe("xpra/platform/gui.py",             "browse.ico",       "NativeGUI_info")
            add_console_exe("xpra/platform/win32/gui.py",       "loop.ico",         "Events_Test")
        if sound_ENABLED:
            add_console_exe("xpra/sound/gstreamer_util.py",     "gstreamer.ico",    "GStreamer_info")
            #add_console_exe("xpra/sound/src.py",                "microphone.ico",   "Sound_Record")
            #add_console_exe("xpra/sound/sink.py",               "speaker.ico",      "Sound_Play")
        if opengl_ENABLED:
            add_console_exe("xpra/client/gl/gl_check.py",   "opengl.ico",       "OpenGL_check")
        if webcam_ENABLED:
            add_console_exe("xpra/platform/webcam.py",          "webcam.ico",    "Webcam_info")
            add_gui_exe("xpra/scripts/show_webcam.py",          "webcam.ico",    "Webcam_Test")
        if printing_ENABLED:
            add_console_exe("xpra/platform/printing.py",        "printer.ico",     "Print")
            if os.path.exists("C:\\Program Files (x86)\\Ghostgum\\gsview"):
                GSVIEW = "C:\\Program Files (x86)\\Ghostgum\\gsview"
            else:
                GSVIEW = "C:\\Program Files\\Ghostgum\\gsview"
            if os.path.exists("C:\\Program Files (x86)\\gs"):
                GHOSTSCRIPT_PARENT_DIR = "C:\\Program Files (x86)\\gs"
            else:
                GHOSTSCRIPT_PARENT_DIR = "C:\\Program Files\\gs"
            GHOSTSCRIPT = None
            for x in reversed(sorted(os.listdir(GHOSTSCRIPT_PARENT_DIR))):
                f = os.path.join(GHOSTSCRIPT_PARENT_DIR, x)
                if os.path.isdir(f):
                    GHOSTSCRIPT = os.path.join(f, "bin")
                    print("found ghoscript: %s" % GHOSTSCRIPT)
                    break
            assert GHOSTSCRIPT is not None, "cannot find ghostscript installation directory in %s" % GHOSTSCRIPT_PARENT_DIR
            add_data_files('gsview', glob.glob(GSVIEW+'\\*.*'))
            add_data_files('gsview', glob.glob(GHOSTSCRIPT+'\\*.*'))

        #FIXME: how do we figure out what target directory to use?
        #(can't use install data override with py2exe?)
        print("calling build_xpra_conf in-place")
        #building etc files in-place:
        build_xpra_conf(".")
        add_data_files('etc/xpra', glob.glob("etc/xpra/*conf"))
        add_data_files('etc/xpra', glob.glob("etc/xpra/nvenc*.keys"))
        add_data_files('etc/xpra/conf.d', glob.glob("etc/xpra/conf.d/*conf"))
        #build minified html5 client in temporary build dir:
        if "clean" not in sys.argv and html5_ENABLED:
            install_html5("build/www")
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

    if server_ENABLED:
        try:
            import xxhash
            assert xxhash
            external_includes += ["xxhash"]
        except ImportError as e:
            print("Warning: no xxhash module: %s" % e)
            print(" this is required for scrolling detection")

    #FIXME: ugly workaround for building the ugly pycairo workaround on win32:
    #the win32 py-gi installers don't have development headers for pycairo
    #so we hardcode them here instead...
    #(until someone fixes the win32 builds properly)
    PYCAIRO_DIR = WIN32_BUILD_LIB_PREFIX + "pycairo-1.10.0"
    def pycairo_pkgconfig(*pkgs_options, **ekw):
        if "pycairo" in pkgs_options:
            kw = pkgconfig("cairo", **ekw)
            add_to_keywords(kw, 'include_dirs', PYCAIRO_DIR)
            checkdirs(PYCAIRO_DIR)
            return kw
        return exec_pkgconfig(*pkgs_options, **ekw)

    #hard-coded pkgconfig replacement for visual studio:
    #(normally used with python2 / py2exe builds)
    def VC_pkgconfig(*pkgs_options, **ekw):
        kw = dict(ekw)
        #remove optimize flag on win32..
        if kw.get("optimize"):
            add_to_keywords(kw, 'extra_compile_args', "/Ox")
            del kw["optimize"]
        if kw.get("ignored_flags"):
            #we don't handle this keyword here yet..
            del kw["ignored_flags"]
        if strict_ENABLED:
            add_to_keywords(kw, 'extra_compile_args', "/WX")
            add_to_keywords(kw, 'extra_link_args', "/WX")

        if debug_ENABLED:
            #Od will override whatever may be specified elsewhere
            #and allows us to use the debug switches,
            #at the cost of a warning...
            for flag in ('/Od', '/Zi', '/DEBUG', '/RTC1', '/GS'):
                add_to_keywords(kw, 'extra_compile_args', flag)
            add_to_keywords(kw, 'extra_link_args', "/DEBUG")
            kw['cython_gdb'] = True
            add_to_keywords(kw, 'extra_compile_args', "/Ox")

        if strict_ENABLED:
            add_to_keywords(kw, 'extra_compile_args', "/wd4146")    #MSVC error on __Pyx_PyInt_As_size_t
            add_to_keywords(kw, 'extra_compile_args', "/wd4293")    #MSVC error in __Pyx_PyFloat_DivideObjC

        #always add the win32 include dirs for VC,
        #so codecs can find the inttypes.h and stdint.h:
        win32_include_dir = os.path.join(os.getcwd(), "win32")
        add_to_keywords(kw, 'include_dirs', win32_include_dir)
        if len(pkgs_options)==0:
            return kw

        def add_to_PATH(*bindirs):
            for bindir in bindirs:
                if os.environ['PATH'].find(bindir)<0:
                    os.environ['PATH'] = bindir + ';' + os.environ['PATH']
                if bindir not in sys.path:
                    sys.path.append(bindir)
        def add_keywords(path_dirs=[], inc_dirs=[], lib_dirs=[], libs=[], noref=True, nocmt=False):
            checkdirs(*path_dirs)
            add_to_PATH(*path_dirs)
            checkdirs(*inc_dirs)
            for d in inc_dirs:
                add_to_keywords(kw, 'include_dirs', d)
            checkdirs(*lib_dirs)
            for d in lib_dirs:
                add_to_keywords(kw, 'extra_link_args', "/LIBPATH:%s" % d)
            add_to_keywords(kw, 'libraries', *libs)
            if noref:
                add_to_keywords(kw, 'extra_link_args', "/OPT:NOREF")
            if nocmt:
                add_to_keywords(kw, 'extra_link_args', "/NODEFAULTLIB:LIBCMT")
        if "avcodec" in pkgs_options[0]:
            add_keywords([libffmpeg_bin_dir], [libffmpeg_include_dir],
                         [libffmpeg_lib_dir, libffmpeg_bin_dir],
                         ["avcodec", "avutil"])
        elif "avformat" in pkgs_options[0]:
            add_keywords([libffmpeg_bin_dir], [libffmpeg_include_dir],
                         [libffmpeg_lib_dir, libffmpeg_bin_dir],
                         ["avformat", "avutil"])
        elif "swscale" in pkgs_options[0]:
            add_keywords([libffmpeg_bin_dir], [libffmpeg_include_dir],
                         [libffmpeg_lib_dir, libffmpeg_bin_dir],
                         ["swscale", "avutil"])
        elif "avutil" in pkgs_options[0]:
            add_keywords([libffmpeg_bin_dir], [libffmpeg_include_dir],
                         [libffmpeg_lib_dir, libffmpeg_bin_dir],
                         ["avutil"])
        elif "x264" in pkgs_options[0]:
            add_keywords([x264_bin_dir], [x264_include_dir],
                         [x264_lib_dir],
                         ["libx264"])
        elif "x265" in pkgs_options[0]:
            add_keywords([x265_bin_dir], [x265_include_dir],
                         [x265_lib_dir],
                         ["libx265"])
        elif "vpx" in pkgs_options[0]:
            add_to_keywords(kw, 'extra_compile_args', "/wd4005")    #macro redifined with vpx vs stdint.h
            add_keywords([vpx_bin_dir], [vpx_include_dir],
                         [vpx_lib_dir],
                         vpx_lib_names, nocmt=True)
        elif "webp" in pkgs_options[0]:
            add_keywords([webp_bin_dir], [webp_include_dir],
                         [webp_lib_dir],
                         webp_lib_names, nocmt=True)
        elif "libyuv" in pkgs_options[0]:
            add_keywords([libyuv_bin_dir], [libyuv_include_dir],
                         [libyuv_lib_dir],
                         libyuv_lib_names)
        elif ("nvenc7" in pkgs_options[0]):
            for x in ("pycuda", "pytools"):
                if x not in external_includes:
                    external_includes.append(x)
            nvenc_path = nvenc7_sdk
            nvenc_include_dir       = nvenc_path + "\\Samples\\common\\inc"
            nvenc_core_include_dir  = nvenc_path + "\\Samples\\common\\inc"     #FIXME!
            #let's not use crazy paths, just copy the dll somewhere that makes sense:
            nvenc_bin_dir           = nvenc_path + "\\bin\\win32\\release"
            nvenc_lib_names         = []    #not linked against it, we use dlopen!

            #cuda:
            cuda_include_dir    = os.path.join(cuda_path, "include")
            cuda_lib_dir        = os.path.join(cuda_path, "lib", "Win32")
            cuda_bin_dir        = os.path.join(cuda_path, "bin")

            add_keywords([nvenc_bin_dir, cuda_bin_dir], [nvenc_include_dir, nvenc_core_include_dir, cuda_include_dir],
                         [cuda_lib_dir],
                         nvenc_lib_names)
            #prevent py2exe "seems not to be an exe file" error on this DLL and include it ourselves instead:
            #assume 32-bit for now:
            #add_data_files('', ["C:\\Windows\System32\nvcuda.dll"])
            #add_data_files('', ["%s/nvencodeapi.dll" % nvenc_bin_dir])
        elif "nvapi" in pkgs_options[0]:
            nvapi_include_dir       = nvapi_path
            import struct
            if struct.calcsize("P")==4:
                nvapi_lib_names         = ["nvapi"]
                nvapi_lib_dir           = os.path.join(nvapi_path, "x86")
            else:
                nvapi_lib_names         = ["nvapi64"]
                nvapi_lib_dir           = os.path.join(nvapi_path, "amd64")

            add_keywords([], [nvapi_include_dir], [nvapi_lib_dir], nvapi_lib_names)
        elif "pygobject-2.0" in pkgs_options[0]:
            dirs = (python_include_path,
                    pygtk_include_dir, atk_include_dir, gtk2_include_dir,
                    GTK_INCLUDE_DIR, gdkconfig_include_dir, gdkpixbuf_include_dir,
                    glib_include_dir, glibconfig_include_dir,
                    cairo_include_dir, pango_include_dir)
            add_to_keywords(kw, 'include_dirs', *dirs)
            checkdirs(*dirs)
        elif "cairo" in pkgs_options:
            add_to_keywords(kw, 'include_dirs', GTK_INCLUDE_DIR, cairo_include_dir)
            add_to_keywords(kw, 'libraries', "cairo")
            if PYTHON3:
                cairo_library_dir = os.path.join(PYCAIRO_DIR, "lib")
                add_to_keywords(kw, "library_dirs", cairo_library_dir)
            checkdirs(cairo_include_dir)
        elif "pycairo" in pkgs_options:
            kw = pycairo_pkgconfig(*pkgs_options, **ekw)
        else:
            sys.exit("ERROR: unknown package config: %s" % str(pkgs_options))
        print("pkgconfig(%s,%s)=%s" % (pkgs_options, ekw, kw))
        return kw

    if not has_pkg_config:
        #use the hardcoded version above:
        pkgconfig = VC_pkgconfig
    else:
        #FIXME: ugly workaround for building the ugly pycairo workaround on win32:
        #the win32 py-gi installers don't have development headers for pycairo
        #so we hardcode them here instead...
        #(until someone fixes the win32 builds properly)
        pkgconfig = pycairo_pkgconfig


    remove_packages(*external_excludes)
    remove_packages(#not used on win32:
                    "mmap",
                    #we handle GL separately below:
                    "OpenGL", "OpenGL_accelerate",
                    #this is a mac osx thing:
                    "ctypes.macholib")

    if webcam_ENABLED:
        external_includes.append("cv2")

    if opengl_ENABLED:
        #we need numpy for opengl or as a fallback for the Cython xor module
        external_includes.append("numpy")
    else:
        remove_packages("unittest", "difflib",  #avoid numpy warning (not an error)
                        "pydoc")

    if sound_ENABLED:
        if not PYTHON3:
            external_includes += ["pygst", "gst", "gst.extend"]
            add_data_files('', glob.glob('%s\\bin\\*.dll' % libffmpeg_path))
        else:
            #python3: this is part of "gi"?
            pass
    else:
        remove_packages("pygst", "gst", "gst.extend")

    #deal with opengl workaround (as long as we're not just building the extensions):
    if opengl_ENABLED and "build_ext" not in sys.argv:
        #for this hack to work, you must add "." to the sys.path
        #so python can load OpenGL from the install directory
        #(further complicated by the fact that "." is the "frozen" path...)
        import OpenGL, OpenGL_accelerate        #@UnresolvedImport
        print("*** copy PyOpenGL modules ***")
        for module_name, module in {"OpenGL" : OpenGL, "OpenGL_accelerate" : OpenGL_accelerate}.items():
            module_dir = os.path.dirname(module.__file__ )
            try:
                shutil.copytree(
                    module_dir, os.path.join("dist", module_name),
                    ignore = shutil.ignore_patterns("Tk", "AGL", "EGL", "GLX", "GLX.*", "_GLX.*", "GLE", "GLES1", "GLES2", "GLES3")
                )
            except Exception as e:
                if not isinstance(e, WindowsError) or (not "already exists" in str(e)): #@UndefinedVariable
                    raise

    add_data_files('', glob.glob("win32\\bundle-extra\\*"))

    #END OF win32
#*******************************************************************************
else:
    #OSX and *nix:
    scripts += ["scripts/xpra", "scripts/xpra_launcher"]
    add_data_files("share/man/man1",      ["man/xpra.1", "man/xpra_launcher.1"])
    add_data_files("share/xpra",          ["README", "COPYING"])
    add_data_files("share/xpra/icons",    glob.glob("icons/*"))
    add_data_files("share/applications",  ["xdg/xpra_launcher.desktop", "xdg/xpra.desktop"])
    add_data_files("share/mime/packages", ["xdg/application-x-xpraconfig.xml"])
    add_data_files("share/icons",         ["xdg/xpra.png"])
    add_data_files("share/appdata",       ["xdg/xpra.appdata.xml"])

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

            etc_prefix = self.install_dir
            if etc_prefix.endswith("/usr"):
                etc_prefix = etc_prefix[:-3]    #ie: "/" or "/usr/src/rpmbuild/BUILDROOT/xpra-0.18.0-0.20160513r12573.fc23.x86_64/"
            build_xpra_conf(etc_prefix)

            if printing_ENABLED and os.name=="posix":
                #install "/usr/lib/cups/backend" with 0700 permissions:
                xpraforwarder_src = os.path.join("cups", "xpraforwarder")
                cups_backend_dir = os.path.join(self.install_dir, "lib", "cups", "backend")
                self.mkpath(cups_backend_dir)
                xpraforwarder_dst = os.path.join(cups_backend_dir, "xpraforwarder")
                shutil.copyfile(xpraforwarder_src, xpraforwarder_dst)
                os.chmod(xpraforwarder_dst, 0o700)

            if x11_ENABLED:
                #install xpra_Xdummy if we need it:
                xvfb_command = detect_xorg_setup()
                if any(x.find("xpra_Xdummy")>=0 for x in (xvfb_command or [])):
                    bin_dir = os.path.join(self.install_dir, "bin")
                    self.mkpath(bin_dir)
                    dummy_script = os.path.join(bin_dir, "xpra_Xdummy")
                    shutil.copyfile("scripts/xpra_Xdummy", dummy_script)
                    os.chmod(dummy_script, 0o755)
                #install xorg.conf, cuda.conf and nvenc.keys:
                etc_xpra = os.path.join(etc_prefix, "etc", "xpra")
                self.mkpath(etc_xpra)
                for x in ("xorg.conf", "cuda.conf", "nvenc.keys"):
                    shutil.copyfile("etc/xpra/%s" % x, os.path.join(etc_xpra, x))

            if pam_ENABLED:
                etc_pam_d = os.path.join(etc_prefix, "etc", "pam.d")
                self.mkpath(etc_pam_d)
                shutil.copyfile("etc/pam.d/xpra", os.path.join(etc_pam_d, "xpra"))

    # add build_conf to build step
    cmdclass.update({
             'build'        : build_override,
             'build_conf'   : build_conf,
             'install_data' : install_data_override,
             })

    if OSX:
        #pyobjc needs email.parser
        external_includes += ["email", "uu", "urllib", "objc", "cups", "six"]
        #OSX package names (ie: gdk-x11-2.0 -> gdk-2.0, etc)
        PYGTK_PACKAGES += ["gdk-2.0", "gtk+-2.0"]
        add_packages("xpra.platform.darwin")
        remove_packages("xpra.platform.win32", "xpra.platform.xposix")
        #to support GStreamer 1.x we need this:
        modules.append("importlib")
        modules.append("xpra.scripts.gtk_info")
        modules.append("xpra.scripts.show_webcam")
        #always ship xxhash
        modules.append("xxhash")
    else:
        PYGTK_PACKAGES += ["gdk-x11-2.0", "gtk+-x11-2.0"]
        add_packages("xpra.platform.xposix")
        remove_packages("xpra.platform.win32", "xpra.platform.darwin")
        #not supported by all distros, but doesn't hurt to install it anyway:
        add_data_files("/usr/lib/tmpfiles.d", ["tmpfiles.d/xpra.conf"])

    #gentoo does weird things, calls --no-compile with build *and* install
    #then expects to find the cython modules!? ie:
    #> python2.7 setup.py build -b build-2.7 install --no-compile --root=/var/tmp/portage/x11-wm/xpra-0.7.0/temp/images/2.7
    #otherwise we use the flags to skip pkgconfig
    if ("--no-compile" in sys.argv or "--skip-build" in sys.argv) and not ("build" in sys.argv and "install" in sys.argv):
        def pkgconfig(*pkgs_options, **ekw):
            return {}

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

        Plist = {"CFBundleDocumentTypes" : {
                        "CFBundleTypeExtensions"    : ["Xpra"],
                        "CFBundleTypeName"          : "Xpra Session Config File",
                        "CFBundleName"              : "Xpra",
                        "CFBundleTypeRole"          : "Viewer",
                        }}
        #Note: despite our best efforts, py2app will not copy all the modules we need
        #so the make-app.sh script still has to hack around this problem.
        add_modules(*external_includes)
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
    else:
        if service_ENABLED:
            #Linux init service:
            if os.path.exists("/bin/systemctl"):
                add_data_files("/usr/lib/systemd/system/", ["service/xpra.service"])
            else:
                add_data_files("/etc/init.d/", ["service/xpra"])
            if os.path.exists("/etc/sysconfig"):
                add_data_files("/etc/sysconfig/", ["etc/sysconfig/xpra"])
            elif os.path.exists("/etc/default"):
                add_data_files("/etc/default/", ["etc/sysconfig/xpra"])


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
#which file to link against (new-style buffers or old?):
if memoryview_ENABLED:
    bmod = "new"
else:
    assert not PYTHON3
    bmod = "old"
buffers_c = "xpra/buffers/%s_buffers.c" % bmod
inline_c = "xpra/inline.c"
memalign_c = "xpra/buffers/memalign.c"
#convenience grouping for codecs:
membuffers_c = [memalign_c, inline_c, buffers_c]


toggle_packages(dbus_ENABLED, "xpra.dbus")
toggle_packages(mdns_ENABLED, "xpra.net.mdns")
toggle_packages(server_ENABLED or proxy_ENABLED or shadow_ENABLED, "xpra.server", "xpra.server.auth")
toggle_packages(proxy_ENABLED, "xpra.server.proxy")
toggle_packages(server_ENABLED, "xpra.server.window")
toggle_packages(server_ENABLED and shadow_ENABLED, "xpra.server.shadow")
toggle_packages(server_ENABLED or (client_ENABLED and gtk2_ENABLED), "xpra.clipboard")
#cannot use toggle here as py2exe will complain if we try to exclude this module:
if dbus_ENABLED and server_ENABLED:
    add_packages("xpra.server.dbus")
toggle_packages(x11_ENABLED and dbus_ENABLED and server_ENABLED, "xpra.x11.dbus")
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
                ["xpra/x11/bindings/ximage.pyx", buffers_c],
                **pkgconfig("x11", "xcomposite", "xdamage", "xext")
                ))

toggle_packages(gtk_x11_ENABLED, "xpra.x11.gtk_x11")
if gtk_x11_ENABLED:
    toggle_packages(PYTHON3, "xpra.x11.gtk3")
    toggle_packages(not PYTHON3, "xpra.x11.gtk2", "xpra.x11.gtk2.models")
    if PYTHON3:
        #GTK3 display source:
        cython_add(Extension("xpra.x11.gtk3.gdk_display_source",
                    ["xpra/x11/gtk3/gdk_display_source.pyx"],
                    **pkgconfig("gtk+-3.0")
                    ))
    else:
        #below uses gtk/gdk:
        cython_add(Extension("xpra.x11.gtk2.gdk_display_source",
                    ["xpra/x11/gtk2/gdk_display_source.pyx"],
                    **pkgconfig(*PYGTK_PACKAGES)
                    ))
        GDK_BINDINGS_PACKAGES = PYGTK_PACKAGES + ["x11", "xext", "xfixes", "xdamage"]
        cython_add(Extension("xpra.x11.gtk2.gdk_bindings",
                    ["xpra/x11/gtk2/gdk_bindings.pyx"],
                    **pkgconfig(*GDK_BINDINGS_PACKAGES)
                    ))

if client_ENABLED and gtk3_ENABLED:
    #cairo workaround:
    cython_add(Extension("xpra.client.gtk3.cairo_workaround",
                ["xpra/client/gtk3/cairo_workaround.pyx", buffers_c],
                **pkgconfig("pycairo")
                ))

if client_ENABLED or server_ENABLED:
    add_packages("xpra.codecs.argb")
    argb_pkgconfig = pkgconfig(optimize=3)
    cython_add(Extension("xpra.codecs.argb.argb",
                ["xpra/codecs/argb/argb.pyx", buffers_c], **argb_pkgconfig))


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
toggle_packages((client_ENABLED and gtk3_ENABLED) or (PYTHON3 and sound_ENABLED), "gi")
toggle_packages(client_ENABLED and (gtk2_ENABLED or gtk3_ENABLED), "xpra.client.gtk_base")
toggle_packages(client_ENABLED and opengl_ENABLED and gtk2_ENABLED, "xpra.client.gl.gtk2")
toggle_packages(client_ENABLED and opengl_ENABLED and gtk3_ENABLED, "xpra.client.gl.gtk3")
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
#we can't just include "xpra.client.gl" because cx_freeze and py2exe then do the wrong thing
#and try to include both gtk3 and gtk2, and fail hard..
for x in ("gl_check", "gl_colorspace_conversions", "gl_window_backing_base", "gtk_compat"):
    toggle_packages(client_ENABLED and opengl_ENABLED, "xpra.client.gl.%s" % x)

toggle_modules(sound_ENABLED, "xpra.sound")
toggle_modules(sound_ENABLED and not (OSX or WIN32), "xpra.sound.pulseaudio")

toggle_packages(clipboard_ENABLED, "xpra.clipboard")
if clipboard_ENABLED:
    cython_add(Extension("xpra.gtk_common.gdk_atoms",
                ["xpra/gtk_common/gdk_atoms.pyx"],
                **pkgconfig(*PYGTK_PACKAGES)
                ))

toggle_packages(client_ENABLED or server_ENABLED, "xpra.codecs.xor")
if client_ENABLED or server_ENABLED:
    cython_add(Extension("xpra.codecs.xor.cyxor",
                ["xpra/codecs/xor/cyxor.pyx"]+membuffers_c,
                **pkgconfig(optimize=3)))

if server_ENABLED:
    O3_pkgconfig = pkgconfig(optimize=3)
    cython_add(Extension("xpra.server.cystats",
                ["xpra/server/cystats.pyx"],
                **O3_pkgconfig))
    cython_add(Extension("xpra.server.window.region",
                ["xpra/server/window/region.pyx"],
                **O3_pkgconfig))
    cython_add(Extension("xpra.server.window.motion",
                ["xpra/server/window/motion.pyx"]+membuffers_c,
                **O3_pkgconfig))


toggle_packages(enc_proxy_ENABLED, "xpra.codecs.enc_proxy")

toggle_packages(nvenc7_ENABLED, "xpra.codecs.nvenc7")
toggle_packages(nvenc7_ENABLED, "xpra.codecs.cuda_common", "xpra.codecs.nv_util")
if (nvenc7_ENABLED) and WIN32:
    cython_add(Extension("xpra.codecs.nvapi_version",
                ["xpra/codecs/nvapi_version.pyx"],
                **pkgconfig("nvapi")
                ))

if nvenc7_ENABLED:
    #find nvcc:
    path_options = os.environ.get("PATH", "").split(os.path.pathsep)
    if WIN32:
        nvcc_exe = "nvcc.exe"
        #FIXME: we try to use SDK 6.5 x86 first!
        #(so that we can build on 32-bit envs)
        path_options = [
                         "C:\\Program Files (x86)\\NVIDIA GPU Computing Toolkit\\CUDA\\v5.5\\bin",
                         "C:\\Program Files (x86)\\NVIDIA GPU Computing Toolkit\\CUDA\\v6.0\\bin",
                         "C:\\Program Files (x86)\\NVIDIA GPU Computing Toolkit\\CUDA\\v6.5\\bin",
                         "C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v6.5\\bin",
                         "C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v7.0\\bin",
                         "C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v7.5\\bin",
                         "C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v8.0\\bin",
                         ] + path_options
    else:
        nvcc_exe = "nvcc"
        for v in ("-5.5", "-6.0", "-6.5", "-7.0", "-7.5", "-8.0", ""):
            path_options += ["/usr/local/cuda%s/bin" % v, "/opt/cuda%s/bin" % v]
    options = [os.path.join(x, nvcc_exe) for x in path_options]
    if not WIN32:
        #prefer the one we find on the $PATH, if any:
        try:
            code, out, err = get_status_output(["which", nvcc_exe])
            if code==0:
                options.insert(0, out)
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
    kernels = ("BGRA_to_NV12", "BGRA_to_YUV444")
    for kernel in kernels:
        cuda_src = "xpra/codecs/cuda_common/%s.cu" % kernel
        cuda_bin = "xpra/codecs/cuda_common/%s.fatbin" % kernel
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
            cmd += ["-I%s" % os.path.abspath("win32")]
        comp_code_options = [(30, 30), (35, 35)]
        #see: http://docs.nvidia.com/cuda/maxwell-compatibility-guide/#building-maxwell-compatible-apps-using-cuda-6-0
        if version!="0" and version<"5":
            print("CUDA version %s is very unlikely to work")
            print("try upgrading to version 6.5 or later")
        if version>="6":
            comp_code_options.append((50, 50))
        if version>="7":
            comp_code_options.append((52, 52))
        if version>="7.5":
            comp_code_options.append((50, 50))
            comp_code_options.append((52, 52))
            comp_code_options.append((53, 53))
        if version>="8.0":
            comp_code_options.append((60, 60))
            comp_code_options.append((61, 61))
            comp_code_options.append((62, 62))
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
    if nvenc7_ENABLED:
        nvencmodule = "nvenc7"
        nvenc_pkgconfig = pkgconfig(nvencmodule, ignored_flags=["-l", "-L"])
        #don't link against libnvidia-encode, we load it dynamically:
        libraries = nvenc_pkgconfig.get("libraries", [])
        if "nvidia-encode" in libraries:
            libraries.remove("nvidia-encode")
        cython_add(Extension("xpra.codecs.%s.encoder" % nvencmodule,
                             ["xpra/codecs/%s/encoder.pyx" % nvencmodule, buffers_c],
                             **nvenc_pkgconfig))

toggle_packages(enc_x264_ENABLED, "xpra.codecs.enc_x264")
if enc_x264_ENABLED:
    x264_pkgconfig = pkgconfig("x264")
    if get_gcc_version()>=[6, 0]:
        add_to_keywords(x264_pkgconfig, 'extra_compile_args', "-Wno-unused-variable")
    cython_add(Extension("xpra.codecs.enc_x264.encoder",
                ["xpra/codecs/enc_x264/encoder.pyx", buffers_c],
                **x264_pkgconfig))

toggle_packages(enc_x265_ENABLED, "xpra.codecs.enc_x265")
if enc_x265_ENABLED:
    x265_pkgconfig = pkgconfig("x265")
    cython_add(Extension("xpra.codecs.enc_x265.encoder",
                ["xpra/codecs/enc_x265/encoder.pyx", buffers_c],
                **x265_pkgconfig))

toggle_packages(enc_xvid_ENABLED, "xpra.codecs.enc_xvid")
if enc_xvid_ENABLED:
    xvid_pkgconfig = pkgconfig("xvid")
    cython_add(Extension("xpra.codecs.enc_xvid.encoder",
                ["xpra/codecs/enc_xvid/encoder.pyx", buffers_c],
                **xvid_pkgconfig))

toggle_packages(pillow_ENABLED, "xpra.codecs.pillow")
if pillow_ENABLED:
    external_includes += ["PIL", "PIL.Image", "PIL.WebPImagePlugin"]

toggle_packages(webp_ENABLED, "xpra.codecs.webp")
if webp_ENABLED:
    if WIN32 and PYTHON3:
        #python3 gi has webp already, but our codecs somehow end up linking against the mingw version,
        #and at runtime requesting "libwebp-4.dll", which does not exist anywhere!?
        #the installer already bundles a "libwebp-5.dll", so we just duplicate it and hope for the best!
        #TODO: make it link against the gnome-gi one and remove this ugly hack:
        libwebp5 = os.path.join(webp_path, "libwebp-5.dll")
        libwebp4 = os.path.join(webp_path, "libwebp-4.dll")
        if not os.path.exists(libwebp4):
            shutil.copy(libwebp5, libwebp4)
        add_data_files('', [libwebp4, libwebp5])

    webp_pkgconfig = pkgconfig("webp")
    if not OSX:
        cython_add(Extension("xpra.codecs.webp.encode",
                    ["xpra/codecs/webp/encode.pyx", buffers_c],
                    **webp_pkgconfig))
    cython_add(Extension("xpra.codecs.webp.decode",
                ["xpra/codecs/webp/decode.pyx"]+membuffers_c,
                **webp_pkgconfig))

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
                ["xpra/codecs/dec_avcodec2/decoder.pyx"]+membuffers_c,
                **avcodec2_pkgconfig))


toggle_packages(csc_opencl_ENABLED, "xpra.codecs.csc_opencl")
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
                ["xpra/codecs/csc_swscale/colorspace_converter.pyx"]+membuffers_c,
                **swscale_pkgconfig))

toggle_packages(csc_cython_ENABLED, "xpra.codecs.csc_cython")
if csc_cython_ENABLED:
    csc_cython_pkgconfig = pkgconfig(optimize=3)
    cython_add(Extension("xpra.codecs.csc_cython.colorspace_converter",
                ["xpra/codecs/csc_cython/colorspace_converter.pyx"]+membuffers_c,
                **csc_cython_pkgconfig))

toggle_packages(csc_opencv_ENABLED, "xpra.codecs.csc_opencv")


toggle_packages(vpx_ENABLED, "xpra.codecs.vpx")
if vpx_ENABLED:
    #try both vpx and libvpx as package names:
    kwargs = {"LIBVPX14"    : pkg_config_version("1.4", "vpx") or pkg_config_version("1.4", "libvpx"),
              "ENABLE_VP8"  : True,
              "ENABLE_VP9"  : pkg_config_version("1.3", "vpx") or pkg_config_version("1.3", "libvpx"),
              }
    make_constants("xpra", "codecs", "vpx", "constants", **kwargs)
    vpx_pkgconfig = pkgconfig("vpx")
    cython_add(Extension("xpra.codecs.vpx.encoder",
                ["xpra/codecs/vpx/encoder.pyx"]+membuffers_c,
                **vpx_pkgconfig))
    cython_add(Extension("xpra.codecs.vpx.decoder",
                ["xpra/codecs/vpx/decoder.pyx"]+membuffers_c,
                **vpx_pkgconfig))

toggle_packages(enc_ffmpeg_ENABLED, "xpra.codecs.enc_ffmpeg")
if enc_ffmpeg_ENABLED:
    ffmpeg_pkgconfig = pkgconfig("libavcodec", "libavformat")
    cython_add(Extension("xpra.codecs.enc_ffmpeg.encoder",
                ["xpra/codecs/enc_ffmpeg/encoder.pyx"]+membuffers_c,
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
                ["xpra/codecs/v4l2/pusher.pyx"]+membuffers_c,
                **v4l2_pkgconfig))


toggle_packages(bencode_ENABLED, "xpra.net.bencode")
toggle_packages(bencode_ENABLED and cython_bencode_ENABLED, "xpra.net.bencode.cython_bencode")
if cython_bencode_ENABLED:
    bencode_pkgconfig = pkgconfig(optimize=not debug_ENABLED)
    cython_add(Extension("xpra.net.bencode.cython_bencode",
                ["xpra/net/bencode/cython_bencode.pyx", buffers_c],
                **bencode_pkgconfig))

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
        print("setup options:")
        print_dict(setup_options)
        print("")

    setup(**setup_options)


if __name__ == "__main__":
    main()
