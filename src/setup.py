#!/usr/bin/env python

# This file is part of Parti.
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

##############################################################################
# WARNING: please try to keep line numbers unchanged when modifying this file
#  a number of patches will break otherwise.
# FIXME: Cython.Distutils.build_ext leaves crud in the source directory.  (So
# does the make-constants-pxi.py hack.)

import glob
from distutils.core import setup
from distutils.extension import Extension
import subprocess, sys, traceback
import os.path
import stat

import wimpiggy
import parti
import xpra
assert wimpiggy.__version__ == parti.__version__ == xpra.__version__

print(" ".join(sys.argv))

from xpra.platform import XPRA_LOCAL_SERVERS_SUPPORTED
#*******************************************************************************
#NOTE: these variables are defined here to make it easier
#to keep their line number unchanged.
#There are 3 empty lines in between each var so patches
#cannot cause further patches to fail to apply due to context changes.
#*******************************************************************************



clipboard_ENABLED = True



x264_ENABLED = True



vpx_ENABLED = True



webp_ENABLED = True



rencode_ENABLED = True



xdummy_ENABLED = False



server_ENABLED = XPRA_LOCAL_SERVERS_SUPPORTED



#allow some of these flags to be modified on the command line:
filtered_args = []
for arg in sys.argv:
    if arg == "--without-x264":
        x264_ENABLED = False
    elif arg == "--without-vpx":
        vpx_ENABLED = False
    elif arg == "--without-webp":
        webp_ENABLED = False
    elif arg == "--without-rencode":
        rencode_ENABLED = False
    elif arg == "--without-clipboard":
        clipboard_ENABLED = False
    elif arg == "--without-server":
        server_ENABLED = False
    elif arg == "--enable-Xdummy":
        xdummy_ENABLED = True
    else:
        filtered_args.append(arg)
sys.argv = filtered_args
print("build switches: x264=%s, vpx=%s, webp=%s, rencode=%s, extra clipboard=%s, force Xdummy=%s" %
      (x264_ENABLED, vpx_ENABLED, webp_ENABLED, rencode_ENABLED, clipboard_ENABLED, xdummy_ENABLED))


#*******************************************************************************
# build options, these may get modified further down..
#
setup_options = {}
setup_options["name"] = "parti-all"
setup_options["author"] = "Antoine Martin"
setup_options["author_email"] = "antoine@nagafix.co.uk"
setup_options["version"] = parti.__version__
setup_options["url"] = "http://xpra.org/"
setup_options["download_url"] = "http://xpra.org/src/"
setup_options["description"] = "A window manager library, a window manager, and a 'screen for X' utility"

wimpiggy_desc = "A library for writing window managers, using GTK+"
parti_desc = "A tabbing/tiling window manager using GTK+"
xpra_desc = "'screen for X' -- a tool to detach/reattach running X programs"
setup_options["long_description"] = """This package contains several sub-projects:
  wimpiggy:
    %s
  parti:
    %s
  xpra:
    %s""" % (wimpiggy_desc, parti_desc, xpra_desc)

data_files = []
setup_options["data_files"] = data_files
packages = ["wimpiggy", "wimpiggy.lowlevel",
          "parti", "parti.trays", "parti.addons", "parti.scripts",
          "xpra", "xpra.scripts", "xpra.platform",
          ]
setup_options["packages"] = packages
py2exe_excludes = []       #only used on win32
ext_modules = []
cmdclass = {}


#*******************************************************************************
# Utility methods for building with Cython
def cython_version_check(min_version):
    try:
        from Cython.Compiler.Version import version as cython_version
    except ImportError, e:
        sys.exit("ERROR: Cannot find Cython: %s" % e)
    from distutils.version import LooseVersion
    if LooseVersion(cython_version) < LooseVersion(".".join([str(x) for x in min_version])):
        sys.exit("ERROR: Your version of Cython is too old to build this package\n"
                 "You have version %s\n"
                 "Please upgrade to Cython %s or better"
                 % (cython_version, ".".join([str(part) for part in min_version])))

def cython_add(extension, min_version=(0, 14, 0)):
    #gentoo does weird things, calls --no-compile with build *and* install
    #then expects to find the cython modules!? ie:
    #python2.7 setup.py build -b build-2.7 install --no-compile --root=/var/tmp/portage/x11-wm/xpra-0.7.0/temp/images/2.7
    if "--no-compile" in sys.argv and not ("build" in sys.argv and "install" in sys.argv):
        return
    global ext_modules, cmdclass
    cython_version_check(min_version)
    from Cython.Distutils import build_ext
    ext_modules.append(extension)
    cmdclass = {'build_ext': build_ext}

def add_to_keywords(kw, key, *args):
    values = kw.setdefault(key, [])
    for arg in args:
        values.append(arg)

PYGTK_PACKAGES = ["pygobject-2.0", "gdk-x11-2.0", "gtk+-x11-2.0"]
X11_PACKAGES = ["xtst", "xfixes", "xcomposite", "xdamage", "xrandr"]

# Tweaked from http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/502261
def pkgconfig(*packages_options, **ekw):
    package_names = []
    #find out which package name to use from potentially many options
    #and bail out early with a meaningful error if we can't find any valid options
    for package_options in packages_options:
        #for this package options, find the ones that work
        valid_option = None
        if type(package_options)==str:
            options = [package_options]     #got given just one string
        else:
            assert type(package_options)==list
            options = package_options       #got given a list of options
        for option in options:
            cmd = ["pkg-config", "--exists", option]
            proc = subprocess.Popen(cmd, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            status = proc.wait()
            if status==0:
                valid_option = option
                break
        if not valid_option:
            sys.exit("ERROR: cannot find a valid pkg-config package for %s" % (options,))
        package_names.append(valid_option)
    print("pkgconfig(%s,%s) using package names=%s" % (packages_options, ekw, package_names))
    flag_map = {'-I': 'include_dirs',
                '-L': 'library_dirs',
                '-l': 'libraries'}
    cmd = ["pkg-config", "--libs", "--cflags", "%s" % (" ".join(package_names),)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, _) = proc.communicate()
    status = proc.wait()
    if status!=0:
        sys.exit("ERROR: call to pkg-config ('%s') failed" % " ".join(cmd))
    kw = dict(ekw)
    if sys.version>='3':
        output = output.decode('utf-8')
    for token in output.split():
        if token[:2] in flag_map:
            add_to_keywords(kw, flag_map.get(token[:2]), token[2:])
        else: # throw others to extra_link_args
            add_to_keywords(kw, 'extra_link_args', token)
        for k, v in kw.items(): # remove duplicates
            kw[k] = list(set(v))
    WARN_ALL = True
    if WARN_ALL:
        add_to_keywords(kw, 'extra_compile_args', "-Wall")
        add_to_keywords(kw, 'extra_link_args', "-Wall")
    PIC = True
    if PIC:
        add_to_keywords(kw, 'extra_compile_args', "-fPIC")
    print("pkgconfig(%s,%s)=%s" % (packages_options, ekw, kw))
    return kw


#*******************************************************************************
def get_xorg_conf_and_script():
    if not server_ENABLED:
        return "etc/xpra/client-only/xpra.conf", False
    if xdummy_ENABLED:
        return "etc/xpra/Xdummy/xpra.conf", False
    XORG_BIN = None
    PATHS = os.environ.get("PATH").split(os.pathsep)
    for x in PATHS:
        xorg = os.path.join(x, "Xorg")
        if os.path.isfile(xorg):
            XORG_BIN = xorg
            break
    def Xvfb():
        return "etc/xpra/Xvfb/xpra.conf", False
    if not XORG_BIN:
        print("Xorg not found, cannot detect version or Xdummy support")
        return Xvfb()

    #do live detection
    cmd = ["Xorg", "-version"]
    print("detecting Xorg version using: %s" % str(cmd))
    try:
        proc = subprocess.Popen(cmd, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out, _ = proc.communicate()
        V_LINE = "X.Org X Server "
        xorg_version = None
        for line in out.decode("utf8").splitlines():
            if line.startswith(V_LINE):
                v_str = line[len(V_LINE):]
                xorg_version = [int(x) for x in v_str.split(".")[:2]]
                break
        if not xorg_version:
            print("Xorg version could not be detected, Xdummy support unavailable")
            return Xvfb()
        if xorg_version<[1, 12]:
            print("Xorg version %s is too old, Xdummy support not available" % str(xorg_version))
            return Xvfb()
        print("found valid recent version of Xorg server: %s" % v_str)
        xorg_stat = os.stat(XORG_BIN)
        if (xorg_stat.st_mode & stat.S_ISUID)!=0:
            if (xorg_stat.st_mode & stat.S_IROTH)==0:
                print("Xorg is suid and not readable, Xdummy support unavailable")
                return Xvfb()
            print("%s is suid, using the xpra_Xdummy wrapper" % XORG_BIN)
            return "etc/xpra/xpra_Xdummy/xpra.conf", True
        else:
            print("using Xdummy config file")
            return "etc/xpra/Xdummy/xpra.conf", False
    except Exception, e:
        print("failed to detect Xorg version: %s" % e)
        print("not installing Xdummy support")
        traceback.print_exc()
        return  Xvfb()


#*******************************************************************************
if 'clean' in sys.argv or 'sdist' in sys.argv:
    #clean and sdist don't actually use cython,
    #so skip this (and avoid errors)
    def pkgconfig(*packages_options, **ekw):
        return {}
    #always include all platform code in this case:
    packages += ["xpra.xposix", "xpra.win32", "xpra.darwin"]
    #ensure we remove the files we generate:
    CLEAN_FILES = ["xpra/wait_for_x_server.c",
                   "xpra/vpx/codec.c",
                   "xpra/x264/codec.c",
                   "xpra/rencode/rencode.c",
                   "etc/xpra/xpra.conf",
                   "wimpiggy/lowlevel/constants.pxi",
                   "wimpiggy/lowlevel/bindings.c"]
    if 'clean' in sys.argv:
        CLEAN_FILES.append("xpra/build_info.py")
    for x in CLEAN_FILES:
        filename = os.path.join(os.getcwd(), x.replace("/", os.path.sep))
        if os.path.exists(filename):
            print("removing Cython/build generated file: %s" % x)
            os.unlink(filename)

if "clean" not in sys.argv:
    # Add build info to build_info.py file:
    import add_build_info
    add_build_info.main()



#*******************************************************************************
if sys.platform.startswith("win"):
    # The Microsoft C library DLLs:
    # Unfortunately, these files cannot be re-distributed legally :(
    # So here is the md5sum so you can find the right version:
    # (you can find them in various packages, including Visual Studio 2008,
    # pywin32, etc...)
    import md5
    md5sums = {"Microsoft.VC90.CRT/Microsoft.VC90.CRT.manifest" : "37f44d535dcc8bf7a826dfa4f5fa319b",
               "Microsoft.VC90.CRT/msvcm90.dll"                 : "4a8bc195abdc93f0db5dab7f5093c52f",
               "Microsoft.VC90.CRT/msvcp90.dll"                 : "6de5c66e434a9c1729575763d891c6c2",
               "Microsoft.VC90.CRT/msvcr90.dll"                 : "e7d91d008fe76423962b91c43c88e4eb",
               "Microsoft.VC90.CRT/vcomp90.dll"                 : "f6a85f3b0e30c96c993c69da6da6079e",
               "Microsoft.VC90.MFC/Microsoft.VC90.MFC.manifest" : "17683bda76942b55361049b226324be9",
               "Microsoft.VC90.MFC/mfc90.dll"                   : "462ddcc5eb88f34aed991416f8e354b2",
               "Microsoft.VC90.MFC/mfc90u.dll"                  : "b9030d821e099c79de1c9125b790e2da",
               "Microsoft.VC90.MFC/mfcm90.dll"                  : "d4e7c1546cf3131b7d84b39f8da9e321",
               "Microsoft.VC90.MFC/mfcm90u.dll"                 : "371226b8346f29011137c7aa9e93f2f6",
               }
    # This is where I keep them, you will obviously need to change this value:
    C_DLLs="C:\\"
    for dll_file, md5sum in md5sums.items():
        filename = os.path.join(C_DLLs, *dll_file.split("/"))
        if not os.path.exists(filename) or not os.path.isfile(filename):
            sys.exit("ERROR: DLL file %s is missing or not a file!" % filename)
        sys.stdout.write("* verifying md5sum for %s: " % filename)
        f = open(filename, mode='rb')
        data = f.read()
        f.close()
        m = md5.new()
        m.update(data)
        digest = m.hexdigest()
        assert digest==md5sum, "md5 digest for file %s does not match, expected %s but found %s" % (dll_file, md5sum, digest)
        sys.stdout.write("OK\n")
        sys.stdout.flush()
    # The x264 DLLs which you can grab from here:
    # http://ffmpeg.zeranoe.com/builds/
    # beware that some builds work, others crash.. here is one that is known to work ok:
    # ffmpeg-git-4082198-win32-dev
    # ffmpeg-20120708-git-299387e-win32-dev
    # This is where I keep them, you will obviously need to change this value:
    ffmpeg_path="C:\\ffmpeg-win32-shared"
    ffmpeg_include_dir = "%s\\include" % ffmpeg_path
    ffmpeg_lib_dir = "%s\\lib" % ffmpeg_path
    ffmpeg_bin_dir = "%s\\bin" % ffmpeg_path
    # Same for vpx:
    # http://code.google.com/p/webm/downloads/list
    vpx_PATH="C:\\vpx-vp8-debug-src-x86-win32mt-vs9-v1.1.0"
    vpx_include_dir = "%s\\include" % vpx_PATH
    vpx_lib_dir = "%s\\lib\\Win32" % vpx_PATH
    # Same for PyGTK:
    # http://www.pygtk.org/downloads.html
    gtk2_PATH = "C:\\Python27\\Lib\\site-packages\\gtk-2.0"
    python_include_PATH = "C:\\Python27\\include"
    gtk2runtime_PATH = "%s\\runtime" % gtk2_PATH
    gtk2_lib_dir = "%s\\bin" % gtk2runtime_PATH

    pygtk_include_dir = "%s\\pygtk-2.0" % python_include_PATH
    atk_include_dir = "%s\\include\\atk-1.0" % gtk2runtime_PATH
    gtk2_include_dir = "%s\\include\\gtk-2.0" % gtk2runtime_PATH
    gdkconfig_include_dir = "%s\\lib\\gtk-2.0\\include" % gtk2runtime_PATH
    gdkpixbuf_include_dir = "%s\\include\gdk-pixbuf-2.0" % gtk2runtime_PATH
    gdk_include_dir = "%s\\include\\" % gtk2runtime_PATH
    glib_include_dir = "%s\\include\\glib-2.0" % gtk2runtime_PATH
    glibconfig_include_dir = "%s\\lib\\glib-2.0\\include" % gtk2runtime_PATH
    cairo_include_dir = "%s\\include\\cairo" % gtk2runtime_PATH
    pango_include_dir = "%s\\include\\pango-1.0" % gtk2runtime_PATH

    def pkgconfig(*packages, **ekw):
        def add_to_PATH(bindir):
            if os.environ['PATH'].find(bindir)<0:
                os.environ['PATH'] = bindir + ';' + os.environ['PATH']
            if bindir not in sys.path:
                sys.path.append(bindir)
        kw = dict(ekw)
        if "x264" in packages[0]:
            add_to_PATH(ffmpeg_bin_dir)
            add_to_keywords(kw, 'include_dirs', "win32", ffmpeg_include_dir)
            add_to_keywords(kw, 'libraries', "swscale", "avcodec", "avutil")
            add_to_keywords(kw, 'extra_link_args', "/LIBPATH:%s" % ffmpeg_lib_dir)
        elif "vpx" in packages[0]:
            add_to_PATH(ffmpeg_bin_dir)
            add_to_keywords(kw, 'include_dirs', "win32", vpx_include_dir, ffmpeg_include_dir)
            add_to_keywords(kw, 'libraries', "vpxmt", "vpxmtd", "swscale", "avcodec", "avutil")
            add_to_keywords(kw, 'extra_link_args', "/NODEFAULTLIB:LIBCMT")
            add_to_keywords(kw, 'extra_link_args', "/LIBPATH:%s" % vpx_lib_dir)
            add_to_keywords(kw, 'extra_link_args', "/LIBPATH:%s" % ffmpeg_lib_dir)
        elif "pygobject-2.0" in packages[0]:
            add_to_keywords(kw, 'include_dirs', python_include_PATH,
                            pygtk_include_dir, atk_include_dir, gtk2_include_dir,
                            gdk_include_dir, gdkconfig_include_dir, gdkpixbuf_include_dir,
                            glib_include_dir, glibconfig_include_dir,
                            cairo_include_dir, pango_include_dir)
            #add_to_keywords(kw, 'libraries', "")
            add_to_keywords(kw, 'extra_link_args', "/LIBPATH:%s" % gtk2_lib_dir)
        else:
            sys.exit("ERROR: unknown package config: %s" % str(packages))
        return kw

    import py2exe    #@UnresolvedImport
    assert py2exe is not None
    packages.append("xpra.win32")
    #UI applications (detached from shell: no text output if ran from cmd.exe)
    setup_options["windows"] = [
                    {'script': 'win32/xpra_silent.py',                  'icon_resources': [(1, "win32/xpra_txt.ico")],  "dest_base": "Xpra",},
                    {'script': 'xpra/gtk_view_keyboard.py',             'icon_resources': [(1, "win32/keyboard.ico")],  "dest_base": "GTK_Keyboard_Test",},
                    {'script': 'xpra/scripts/client_launcher.py',       'icon_resources': [(1, "win32/xpra.ico")],      "dest_base": "Xpra-Launcher",},
              ]
    #Console: provide an Xpra_cmd.exe we can run from the cmd.exe shell
    setup_options["console"] = [
                    {'script': 'xpra/scripts/main.py',                  'icon_resources': [(1, "win32/xpra_txt.ico")],  "dest_base": "Xpra_cmd",}
              ]
    py2exe_includes = [ "cairo", "pango", "pangocairo", "atk", "glib", "gobject", "gio", "gtk.keysyms",
                        "Crypto", "Crypto.Cipher",
                        "hashlib",
                        "PIL",
                        "win32con", "win32gui", "win32process", "win32api"]
    WIN32_OPENGL = False    #currently does not work..
    if WIN32_OPENGL:
        #import OpenGL.GL                    #@UnusedImport
        #import OpenGL.platform.win32        #@UnusedImport
        #import OpenGL_accelerate            #@UnusedImport @UnresolvedImport
        #py2exe_includes += ["OpenGL.platform.win32", "OpenGL.GL",
        #                    "OpenGL_accelerate.formathandler",
        #                    "OpenGL.GL.ARB.fragment_program",
        #                    "OpenGL.arrays.ctypesarrays", "OpenGL.arrays.ctypesparameters",
        #                    "OpenGL.arrays.numpymodule",  "OpenGL.arrays.numeric",
        #                    "OpenGL.arrays.nones",
        #                    "OpenGL.arrays.vbo",
        #                    "OpenGL.arrays.lists", "OpenGL.arrays.numbers", "OpenGL.arrays.strings"]
        py2exe_includes += ["ctypes", "platform"]
        py2exe_excludes += ["OpenGL", "OpenGL_accelerate"]
        #for this hack to work, you must add "." to the sys.path
        #so python can load OpenGL from the install directory
        #(further complicated by the fact that "." is the "frozen" path...)
        import OpenGL
        import shutil
        print "*** copy PyOpenGL module ***"
        opengl_dir = os.path.dirname( OpenGL.__file__ )
        try:
            shutil.copytree(
                opengl_dir, os.path.join( "dist", "OpenGL" ),
                ignore = shutil.ignore_patterns( "*.py", "*.pyc", "GLUT", "Tk" ),
            )
        except WindowsError, error:     #@UndefinedVariable
            if not "already exists" in str( error ):
                raise
    setup_options["options"] = {
                                "py2exe": {
                                           "skip_archive"   : False,
                                           "optimize"       : 2,    #2=extra optimization (like python -OO)
                                           "unbuffered"     : True,
                                           "packages"       : packages,
                                           "includes"       : py2exe_includes,
                                           "excludes"       : py2exe_excludes,
                                           "dll_excludes"   : "w9xpopen.exe",
                                        }
                                }
    data_files += [
                   ('', ['COPYING']),
                   ('', ['xpra.README']),
                   ('', ['win32/website.url']),
                   ('', ['etc/xpra/client-only/xpra.conf']),
                   ('icons', glob.glob('icons\\*.*')),
                   ('Microsoft.VC90.CRT', glob.glob('%s\\Microsoft.VC90.CRT\\*.*' % C_DLLs)),
                   ('Microsoft.VC90.MFC', glob.glob('%s\\Microsoft.VC90.MFC\\*.*' % C_DLLs)),
                   ('', glob.glob('%s\\bin\\*.dll' % ffmpeg_path)),
                   ]

    if webp_ENABLED:
        #Note: confusingly, the python bindings are called webm...
        #add the webp DLL to the output:
        webm_DLL = "C:\\libwebp-0.2.0-windows-x86\\bin\\libwebp_a.dll"
        data_files.append(('', [webm_DLL]))
        #and its license:
        data_files.append(('webm', ["xpra/webm/LICENSE"]))


#*******************************************************************************
else:
    data_files += [
                    ("share/man/man1", ["man/xpra.1", "man/xpra_launcher.1", "man/parti.1"]),
                    ("share/parti", ["README", "parti.README"]),
                    ("share/xpra", ["xpra.README", "COPYING"]),
                    ("share/wimpiggy", ["wimpiggy.README"]),
                    ("share/xpra/icons", glob.glob("icons/*")),
                    ("share/applications", ["xpra_launcher.desktop"]),
                    ("share/icons", ["xpra.png"])
                  ]
    if webp_ENABLED:
        data_files.append(('share/xpra/webm', ["xpra/webm/LICENSE"]))

    scripts = ["scripts/xpra", "scripts/xpra_launcher"]
    if sys.platform.startswith("darwin"):
        #change package names (ie: gdk-x11-2.0 -> gdk-2.0, etc)
        PYGTK_PACKAGES = [x.replace("-x11", "") for x in PYGTK_PACKAGES]
        packages.append("xpra.darwin")
    else:
        packages.append("xpra.xposix")
        scripts += ["scripts/parti", "scripts/parti-repl",
                    "scripts/xpra_Xdummy"]  #always include the wrapper in case we need it later, we remove it during the 'install' below step if it isn't actually needed

    #gentoo does weird things, calls --no-compile with build *and* install
    #then expects to find the cython modules!? ie:
    #> python2.7 setup.py build -b build-2.7 install --no-compile --root=/var/tmp/portage/x11-wm/xpra-0.7.0/temp/images/2.7
    #otherwise we use the flags to skip pkgconfig
    if ("--no-compile" in sys.argv or "--skip-build" in sys.argv) and not ("build" in sys.argv and "install" in sys.argv):
        def pkgconfig(*packages_options, **ekw):
            return {}
    if "install" in sys.argv:
        #prepare default [/usr/local]/etc configuration files:
        if sys.prefix == '/usr':
            etc_prefix = '/etc/xpra'
        else:
            etc_prefix = sys.prefix + '/etc/xpra'
        etc_files = ["etc/xpra/xorg.conf"]
        #figure out the version of the Xorg server:
        xorg_conf, use_Xdummy_wrapper = get_xorg_conf_and_script()
        if not use_Xdummy_wrapper and "scripts/xpra_Xdummy" in scripts:
            #if we're not using the wrapper, don't install it
            scripts.remove("scripts/xpra_Xdummy")
        etc_files.append(xorg_conf)
        data_files.append((etc_prefix, etc_files))
    setup_options["scripts"] = scripts


#*******************************************************************************
if server_ENABLED:
    base = os.path.join(os.getcwd(), "wimpiggy", "lowlevel", "constants")
    constants_file = "%s.txt" % base
    pxi_file = "%s.pxi" % base
    if not os.path.exists(pxi_file) or os.path.getctime(pxi_file)<os.path.getctime(constants_file):
        from make_constants_pxi import make_constants_pxi
        print("(re)generating %s" % pxi_file)
        make_constants_pxi(constants_file, pxi_file)
    BINDINGS_LIBS = PYGTK_PACKAGES + X11_PACKAGES
    cython_add(Extension("wimpiggy.lowlevel.bindings",
                ["wimpiggy/lowlevel/bindings.pyx"],
                **pkgconfig(*BINDINGS_LIBS)
                ))
    cython_add(Extension("xpra.wait_for_x_server",
                ["xpra/wait_for_x_server.pyx"],
                **pkgconfig("x11")
                ))
elif sys.platform.startswith("win"):
    py2exe_excludes.append("wimpiggy.lowlevel")



if clipboard_ENABLED:
    packages.append("wimpiggy.gdk")
    cython_add(Extension("wimpiggy.gdk.gdk_atoms",
                ["wimpiggy/gdk/gdk_atoms.pyx"],
                **pkgconfig(*PYGTK_PACKAGES)
                ))
elif sys.platform.startswith("win"):
    py2exe_excludes.append("wimpiggy.gdk")



if x264_ENABLED:
    packages.append("xpra.x264")
    cython_add(Extension("xpra.x264.codec",
                ["xpra/x264/codec.pyx", "xpra/x264/x264lib.c"],
                **pkgconfig("x264", "libswscale", "libavcodec")
                ), min_version=(0, 16))
elif sys.platform.startswith("win"):
    py2exe_excludes.append("xpra.x264")



if vpx_ENABLED:
    packages.append("xpra.vpx")
    cython_add(Extension("xpra.vpx.codec",
                ["xpra/vpx/codec.pyx", "xpra/vpx/vpxlib.c"],
                **pkgconfig(["libvpx", "vpx"], "libswscale", "libavcodec")
                ), min_version=(0, 16))
elif sys.platform.startswith("win"):
    py2exe_excludes.append("xpra.vpx")



if rencode_ENABLED:
    packages.append("xpra.rencode")
    extra_compile_args = []
    if not sys.platform.startswith("win"):
        extra_compile_args.append("-O3")
    else:
        extra_compile_args.append("/Ox")
    cython_add(Extension("xpra.rencode._rencode",
                ["xpra/rencode/rencode.pyx"],
                extra_compile_args=extra_compile_args))
elif sys.platform.startswith("win"):
    py2exe_excludes.append("xpra.rencode")



if webp_ENABLED:
    packages.append("xpra.webm")
elif sys.platform.startswith("win"):
    py2exe_excludes.append("xpra.webm")



if ext_modules:
    setup_options["ext_modules"] = ext_modules
if cmdclass:
    setup_options["cmdclass"] = cmdclass

setup(**setup_options)
