#!/bin/python
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path
import shlex
from glob import glob
from subprocess import getstatusoutput, check_output, Popen
from shutil import which, rmtree, copyfile, move, copytree

KEY_FILE = "E:\\xpra.pfx"
DIST = "./dist"
LIB_DIR = f"{DIST}/lib"

PYTHON = os.environ.get("PYTHON", "python3")
MINGW_PREFIX = os.environ.get("MINGW_PREFIX", "")
TIMESTAMP_SERVER = "http://timestamp.digicert.com"
# alternative:
# http://timestamp.comodoca.com/authenticode

PROGRAMFILES = "C:\\Program Files"
PROGRAMFILES_X86="C:\\Program Files (x86)"

BUILD_INFO = "xpra/build_info.py"

LOG_DIR = "packaging/MSWindows/"

NPROCS = int(os.environ.get("NPROCS", os.cpu_count()))

BUILD_CUDA_KERNEL = "packaging\\MSWindows\\BUILD_CUDA_KERNEL"


def parse_command_line():
    from argparse import ArgumentParser, BooleanOptionalAction
    ap = ArgumentParser()

    def add(name: str, help: str, default=True):
        ap.add_argument(f"--{name}", default=default, action=BooleanOptionalAction, help=help)
    add("clean", help="clean build directories")
    add("build", help="compile the source")
    add("install", help="run install step")
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
    return args


def debug(message: str) -> None:
    if os.environ.get("XPRA_DEBUG", "0") != "0":
        print(message)


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
        xpra.args.append("--with-Os")
    if not args.cuda:
        xpra.args.append("--without-nvidia")
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
    java = "C:\\Program Files\\Java\\jdk1.8.0_121\\bin\\java.exe"
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
            r, output = getstatusoutput('find /c/Program\\ Files/* -wholename "*/x64/signtool.exe"')
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
            cmd = parts
            debug(f"  {cmd=}")
    return parts


def log_command(cmd: str | list[str], log_filename: str, **kwargs) -> None:
    debug(f"  running {cmd!r} and sending the output to {log_filename!r}")
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


def find_delete(path: str, name: str) -> None:
    check_output(f'find {path} -name "{name}" -exec rm -f {{}} \\;', shell=True)


def rmrf(path: str) -> None:
    if not os.path.exists(path):
        print(f"Warning: {path!r} does not exist")
        return
    rmtree(path)


def clean() -> None:
    print("* cleaning output directories")
    for dirname in ("dist", "build"):
        if os.path.exists(dirname):
            rmtree(dirname)
        os.mkdir(dirname)
    # clean sometimes errors on removing pyd files,
    # so do it with rm instead:
    find_delete("xpra", "*-cpython-*dll")
    find_delete("xpra", "*-cpython-*pyd")
    log_command(f"{PYTHON} ./setup.py clean", "clean.log")
    # clean comtypes cache - it should not be included!
    check_output(command_args("clear_comtypes_cache.exe -y"))
    if os.path.exists(BUILD_INFO):
        os.unlink(BUILD_INFO)


def build_service() -> None:
    print("* Compiling system service shim")
    # ARCH_DIRS = ("x64", "x86")
    raise NotImplementedError()


def version_stuff():
    pass
"""
################################################################################
# Get version information, generate filenames

#record in source tree:
rm xpra/src_info.py xpra/build_info.py >& /dev/null
export BUILD_TYPE="${BUILD_TYPE}"
${PYTHON} "./fs/bin/add_build_info.py" "src" "build" >& /dev/null
if [ "$?" != "0" ]; then
    echo "ERROR: recording build info"
    exit 1
fi

#figure out the full xpra version:
PYTHON_VERSION=`${PYTHON} --version | awk '{print $2}'`
echo "Python version ${PYTHON_VERSION}"
VERSION=`${PYTHON} -c "from xpra import __version__;import sys;sys.stdout.write(__version__)"`
REVISION=`${PYTHON} -c "from xpra.src_info import REVISION;import sys;sys.stdout.write(str(int(REVISION)))"`
ZERO_PADDED_VERSION=`${PYTHON} -c 'from xpra import __version__;print(".".join((__version__.split(".")+["0","0","0"])[:3]))'`".${NUMREVISION}"
LOCAL_MODIFICATIONS=`${PYTHON} -c "from xpra.src_info import LOCAL_MODIFICATIONS;import sys;sys.stdout.write(str(LOCAL_MODIFICATIONS))"`
FULL_VERSION=${VERSION}-r${REVISION}
if [ "${LOCAL_MODIFICATIONS}" != "0" ]; then
    FULL_VERSION="${FULL_VERSION}M"
fi
EXTRA_VERSION=""
if [ "${DO_FULL}" == "0" ]; then
    EXTRA_VERSION="-Light"
fi
echo
echo -n "Xpra${EXTRA_VERSION} ${FULL_VERSION}"
BUILD_ARCH_INFO="-${MSYSTEM_CARCH}"
APPID="Xpra_is1"
BITS="64"
VERSION_BITS="${VERSION}"
echo
echo

INSTALLER_FILENAME="Xpra${EXTRA_VERSION}${BUILD_ARCH_INFO}_Setup_${FULL_VERSION}.exe"
MSI_FILENAME="Xpra${EXTRA_VERSION}${BUILD_ARCH_INFO}_${FULL_VERSION}.msi"
ZIP_DIR="Xpra${EXTRA_VERSION}${BUILD_ARCH_INFO}_${FULL_VERSION}"
ZIP_FILENAME="${ZIP_DIR}.zip"
"""


################################################################################
# Build: clean, build extensions, generate exe directory


def build_cuda_kernels() -> None:
    print("* Building the CUDA kernels")
    for cupath in glob("fs/share/xpra/cuda/*.cu"):
        kname = os.path.basename(cupath)
        cu = os.path.splitext(cupath)[0]
        # ie: "fs/share/xpra/cuda/BGRX_to_NV12.cu" -> "fs/share/xpra/cuda/BGRX_to_NV12"
        fatbin = f"{cu}.fatbin"
        if os.path.exists(fatbin) and os.path.getctime(fatbin) >= os.path.getctime(cupath):
            debug(f"  no need to rebuild {kname!r}")
        else:
            debug(f"  building {kname!r}")
            check_output(f'cmd.exe //c "{BUILD_CUDA_KERNEL}" "${kname}"')


def build_ext(args) -> None:
    print("* Building Cython modules")
    build_args = get_build_args(args) + ["--inplace"]
    if NPROCS > 0:
        build_args += ["-j", str(NPROCS)]
    args_str = " ".join(build_args)
    log_command(f"{PYTHON} ./setup.py build_ext {args_str}", "build.log")


def run_tests() -> None:
    print("* Running unit tests")
    env = os.environ.copy()
    env["PYTHONPATH"] = ".:./tests/unittests"
    env["XPRA_COMMAND"] = "./fs/bin/xpra"
    log_command(f"{PYTHON} ./setup.py unittests", "unittest.log", env=env)


def install_exe() -> None:
    print("* Generating installation directory")
    log_command(f"{PYTHON} ./setup.py install_exe --install={DIST}", "install.log")


def install_docs() -> None:
    print("* Generating the documentation")
    os.mkdir("dist/doc")
    env = os.environ.copy()
    env["PANDOC"] = find_command("pandoc", "PANDOC")
    log_command(f"{PYTHON} ./setup.py doc", "pandoc.log", env=env)


def fixups() -> None:
    print("* Fixups")
    # fix case sensitive mess:
    gi_dir = f"{LIB_DIR}/girepository-1.0"
    os.rename(f"{gi_dir}/Glib-2.0.typelib", f"{gi_dir}/GLib-2.0.typelib.tmp")
    os.rename(f"{gi_dir}/GLib-2.0.typelib.tmp", f"{gi_dir}/GLib-2.0.typelib")

    # fixup cx_Logging, required by the service class before we can patch sys.path to find it:
    if os.path.exists(f"{LIB_DIR}/cx_Logging.pyd"):
        os.rename(f"{LIB_DIR}/cx_Logging.pyd", f"{DIST}/cx_Logging.pyd")
    # fixup cx freeze wrongly including an empty dir:
    if os.path.exists(f"{LIB_DIR}/comtypes/gen"):
        rmtree(f"{LIB_DIR}/comtypes/gen")
    # fixup tons of duplicated DLLs, thanks cx_Freeze!
    """
    pushd ${DIST} > /dev/null || exit 1
#why is it shipping those files??
find lib/ -name "*dll.a" -exec rm {} \\;

#only keep the actual loaders, not all the other crap cx_Freeze put there:
mkdir lib/gdk-pixbuf-2.0/2.10.0/loaders.tmp
mv lib/gdk-pixbuf-2.0/2.10.0/loaders/libpixbufloader-*.dll lib/gdk-pixbuf-2.0/2.10.0/loaders.tmp/
rm -fr lib/gdk-pixbuf-2.0/2.10.0/loaders
mv lib/gdk-pixbuf-2.0/2.10.0/loaders.tmp lib/gdk-pixbuf-2.0/2.10.0/loaders
if [ "${DO_FULL}" == "0" ]; then
    pushd lib/gdk-pixbuf-2.0/2.10.0/loaders || exit 1
    # we only want to keep: jpeg, png, xpm and svg
    for fmt in xbm gif jxl tiff ico tga bmp    ani pnm avif qtif icns heif; do
        rm -f libpixbufloader-${fmt}.dll
    done
    popd
fi
#move libs that are likely to be common to the lib dir:
for prefix in lib avcodec avformat avutil swscale swresample zlib1 xvidcore; do
    find lib/Xpra -name "${prefix}*dll" -exec mv {} ./lib/ \\;
done
#liblz4 ends up in the wrong place and duplicated,
#keep just one copy in ./lib
find lib/lz4 -name "liblz4.dll" -exec mv {} ./lib/ \\;
if [ "${DO_CUDA}" == "0" ]; then
    rm -fr ./lib/pycuda ./lib/cuda* ./lib/libnv*
    rm -f ./etc/xpra/cuda.conf
else
  #keep cuda bits at top level:
  mv lib/cuda* lib/nvjpeg* ./
fi

mv lib/nacl/libsodium*dll ./lib/

"""


def bundle_numpy(bundle: bool) -> None:
    print(f"* numpy: {bundle}")
    lib_numpy = f"{LIB_DIR}/numpy"
    if not bundle:
        rmtree(f"{lib_numpy}")
        return
    for libname in ("openblas", "gfortran", "quadmath"):
        for dll in glob(f"{lib_numpy}/core/lib{libname}*.dll"):
            move(dll, LIB_DIR)
    # trim tests:
    rmrf(f"{lib_numpy}/doc")


def move_lib(frompath: str, todir: str) -> None:
    topath = os.path.join(todir, os.path.basename(frompath))
    if os.path.exists(topath):
        # should compare that they are the same file!
        debug(f"  removing {frompath!r}, already found in {topath!r}")
        os.unlink(frompath)
        return
    debug(f"  moving {frompath!r} to {topath!r}")
    move(frompath, topath)


def fixup_gstreamer() -> None:
    print("* Fixup GStreamer")
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
    print("* Fixup DLLs")
    # move most DLLs to /lib
    # but keep the core DLLs in the root (python, gcc, etc):
    exclude = ("msvcrt", "libpython", "libgcc", "libwinpthread", "pdfium")
    for dll in glob(f"{DIST}/*.dll"):
        if any(dll.find(excl) >= 0 for excl in exclude):
            continue
        move_lib(dll, LIB_DIR)

    # remove all the pointless cx_Freeze duplication:
    for dll in glob(f"{DIST}/*.dll") + glob(f"{LIB_DIR}/*dll"):
        filename = os.path.basename(dll)
        check_output(f'find {LIB_DIR} -mindepth 2 -name "${filename}" -exec rm {{}} \\;', shell=True)


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
    print("* removing unnecessary PIL plugins:")
    KEEP = (
        "Bmp", "Ico", "Jpeg", "Tiff", "Png", "Ppm", "Xpm", "WebP",
        "Image.py", "ImageChops", "ImageCms", "ImageWin", "ImageChops", "ImageColor", "ImageDraw", "ImageFile.py",
        "ImageFilter", "ImageFont", "ImageGrab", "ImageMode", "ImageOps", "ImagePalette", "ImagePath", "ImageSequence",
        "ImageStat", "ImageTransform",
    )
    kept = []
    removed = []
    for filename in glob(f"{LIB_DIR}/PIL/*Image*"):
        if any(filename.find(keep) >= 0 for keep in KEEP):
            kept.append(os.path.basename(filename))
            continue
        removed.append(os.path.basename(filename))
        os.unlink(filename)
    print(f" removed: {removed}")
    print(f" kept: {kept}")


def trim_python_libs() -> None:
    print("* removing unnecessary Python modules")
    # remove test bits we don't need:
    delete_libs(
        "future/backports/test",
        "comtypes/test/",
        "ctypes/macholib/fetch_macholib*",
        "distutils/tests",
        "distutils/command",
        "enum/doc",
        "websocket/tests",
        "email/test",
        "psutil/tests",
        "Crypto/SelfTest/*",
        # no need for headers:
        "cairo/include",
    )
    print("* removing unnecessary files")
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


def rm_empty_dirs() -> None:
    print("* Removing empty directories")
    os.system("rmdir xpra/*/*/* 2> /dev/null")
    os.system("rmdir xpra/*/* 2> /dev/null")
    os.system("rmdir xpra/* 2> /dev/null")


def zip_modules(full: bool) -> None:
    print("* zipping up some Python modules")
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

    # workaround for zeroconf - just copy it wholesale
    # since I have no idea why cx_Freeze struggles with it:
    delete_libs("zeroconf")
    try:
        import zeroconf
    except ImportError:
        print("Warning: zeroconf not found for %s" % sys.version)
    else:
        ZEROCONF_DIR = os.path.dirname(zeroconf.__file__)
        copytree(ZEROCONF_DIR, LIB_DIR)


def setup_share(full: bool) -> None:
    print("* Deleting unnecessary share/ files")
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
    print("* Removing empty icon directories")
    # remove empty icon directories
    for _ in range(4):
        os.system(f"find {DIST}/share/icons -type d -exec rmdir {{}} \\; 2> /dev/null")


def add_manifest() -> None:
    print("* Adding manifest")
    EXES = [
        "Bug_Report", "Xpra-Launcher", "Xpra", "Xpra_cmd",
        # these are only included in full builds:
        "GTK_info", "NativeGUI_info", "Screenshot", "Xpra-Shadow",
    ]
    for exe in EXES:
        if os.path.exists(f"{DIST}/{exe}.exe"):
            copyfile("packaging/MSWindows/exe.manifest", f"{DIST}/{exe}.exe.manifest")


def gen_caches() -> None:
    print("* Generating gdk pixbuf loaders.cache")
    cmd = 'gdk-pixbuf-query-loaders.exe "lib/gdk-pixbuf-2.0/2.10.0/loaders/*"'
    with open(f"{LIB_DIR}/gdk-pixbuf-2.0/2.10.0/loaders.cache", "w") as cache:
        if Popen(cmd, cwd=os.path.abspath(DIST), stdout=cache, shell=True).wait() != 0:
            raise RuntimeError("gdk-pixbuf-query-loaders.exe failed")
    print("* Generating icons and theme cache")
    for itheme in glob(f"{DIST}/share/icons/*"):
        os.system(f"gtk-update-icon-cache.exe -t -i {itheme!r}")


def bundle_manual() -> None:
    print("* Generating HTML Manual Page")
    os.system("groff.exe -mandoc -Thtml < ./fs/share/man/man1/xpra.1 > ${DIST}/manual.html")


def bundle_html5() -> None:
    print("* Installing the HTML5 client")
    www = os.path.abspath(os.path.join(DIST, "www"))
    log_command(f"{PYTHON} ./setup.py install {www!r}", "html5.log", cwd=f"{DIST}/xpra-html5")


def bundle_putty() -> None:
    print("* Adding TortoisePlink")
    tortoiseplink = find_command("TortoisePlink", "TORTOISEPLINK",
                                 "/c/Program Files/TortoiseSVN/TortoisePlink.exe")
    copyfile(tortoiseplink, f"{DIST}/Plink.exe")
    for dll in ("vcruntime140.dll", "msvcp140.dll", "vcruntime140_1.dll"):
        copyfile(f"/c/Windows/System32/{dll}", f"{DIST}/{dll}")


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
    print("* Bundling OpenSSH")
    for exe in ("ssh", "sshpass", "ssh-keygen"):
        copyfile(f"/usr/bin/{exe}.exe", f"{DIST}/{exe}.exe")
    msys_dlls = tuple(
        f"/usr/bin/msys-{dllname}*.dll" for dllname in (
            "2.0", "gcc_s", "crypto", "z", "gssapi", "asn1", "com_err", "roken",
            "crypt", "heimntlm", "krb5", "heimbase", "wind", "hx509", "hcrypto", "sqlite3",
        )
    )
    bundle_dlls(*msys_dlls)


def bundle_openssl() -> None:
    print("* Bundling OpenSSL")
    copyfile(f"{MINGW_PREFIX}/bin/openssl.exe", f"{DIST}/openssl.exe")
    os.mkdir(f"{DIST}/etc/ssl")
    copyfile(f"{MINGW_PREFIX}/etc/ssl/openssl.cnf", f"{DIST}/etc/ssl/openssl.cnf")
    # we need those libraries at the top level:
    bundle_dlls(f"{LIB_DIR}/libssl-*", f"{LIB_DIR}/libcrypto-*")


def bundle_paxec() -> None:
    print("* Bundling paexec")
    copyfile(f"{MINGW_PREFIX}/bin/paexec.exe", f"{DIST}/paexec.exe")


def bundle_desktoplogon() -> None:
    print("* Bundling desktoplogon")
    dl_dlls = tuple(f"{MINGW_PREFIX}/bin/{dll}" for dll in ("AxMSTSCLib", "MSTSCLib", "DesktopLogon"))
    bundle_dlls(*dl_dlls)


def add_cuda_bin() -> None:
    # pycuda wants a CUDA_PATH with "/bin" in it:
    os.mkdir(f"{DIST}/bin")


def verpatch() -> None:
    ZERO_PADDED_VERSION = None
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
    print("installation disk usage:")
    os.system(f"du -sm ${DIST!r}")
    print()


################################################################################
# packaging: ZIP / EXE / MSI

def create_zip() -> None:
    print("* Creating ZIP file:")
    ZIP_DIR = f"Xpra{EXTRA_VERSION}{BUILD_ARCH_INFO}_{FULL_VERSION}"
    ZIP_FILENAME = f"{ZIP_DIR}.zip"
    if os.path.exists(ZIP_DIR):
        rmtree(ZIP_DIR)
    if os.path.exists(ZIP_FILENAME):
        os.unlink(ZIP_FILENAME)

    os.mkdir(ZIP_DIR)
    copytree(DIST, ZIP_DIR)
    check_output(f"zip -9qmr {ZIP_FILENAME!r} ${ZIP_DIR!r}")
    print()
    os.system("du -sm ${ZIP_FILENAME!r}")
    print()


def create_installer(args) -> None:
    print("* Creating the installer using InnoSetup")
    innosetup = find_command("innosetup", "INNOSETUP",
                             "/c/Program Files/Inno Setup 6/ISCC.exe",
                             "/c/Program Files (x86)/Inno Setup 6/ISCC.exe",
                             )
    SETUP_EXE = "Xpra_Setup.exe"
    INSTALLER_FILENAME = "foo"
    VERSION = "foo"
    FULL_VERSION = "foo"
    XPRA_ISS = "xpra.iss"
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

    log_command(f"{innosetup} {XPRA_ISS}", INNOSETUP_LOG)
    os.unlink(XPRA_ISS)

    os.rename(f"{DIST}/SETUP_EXE", f"{INSTALLER_FILENAME}")


def sign_file(filename: str) -> None:
    log_command(f'signtool.exe sign //v //f {KEY_FILE} //t "{TIMESTAMP_SERVER}" "${filename}"', "signtool.log")


def sign_installer() -> None:
    print("* Signing EXE")
    sign_file(INSTALLER_FILENAME)
    print()
    os.system(f"du -sm ${INSTALLER_FILENAME!r}")
    print()


def run_installer() -> None:
    print("* Finished - running the new installer")
    # we need to escape slashes!
    # (this doesn't preserve spaces.. we should use shift instead)
    os.system(f"./{INSTALLER_FILENAME}")


def create_msi() -> None:
    msiwrapper = find_command("msiwrapper", "MSIWRAPPER",
                              "/c/Program Files/MSI Wrapper/MsiWrapper.exe")
    # we need to quadruple escape backslashes!
    # as they get interpreted by the shell and sed, multiple times:
    # CWD = os.getcwd()   #`pwd | sed 's+/\([a-zA-Z]\)/+\1:\\\\\\\\+g; s+/+\\\\\\\\+g'`
    # print(f"CWD={CWD}")
    # cat "packaging\\MSWindows\\msi.xml" | sed "s+\$CWD+${CWD}+g" | sed "s+\$INPUT+${INSTALLER_FILENAME}+g" | sed "s+\$OUTPUT+${MSI_FILENAME}+g" | sed "s+\$ZERO_PADDED_VERSION+${ZERO_PADDED_VERSION}+g" | sed "s+\$FULL_VERSION+${FULL_VERSION}+g" > msi.xml
    #"${MSIWRAPPER}"


def sign_msi() -> None:
    print("* Signing MSI")
    sign_file(MSI_FILENAME)
    print()
    os.system(f"du -sm {MSI_FILENAME}")
    print()


def build(args) -> None:
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

    fixups()
    bundle_numpy(args.numpy)
    fixup_gstreamer()
    fixup_dlls()
    trim_pillow()
    trim_python_libs()
    rm_empty_dirs()
    if args.zip_modules:
        zip_modules(args.full)
    setup_share(args.full)
    add_manifest()
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
    if args.desktoplogon:
        bundle_desktoplogon()
    if args.cuda:
        add_cuda_bin()

    verpatch()
    show_diskusage()
    if args.zip:
        create_zip()
    if args.installer:
        create_installer(args)
        if args.sign:
            sign_installer()
        if args.run:
            run_installer()
    if args.msi:
        create_msi()
        if args.sign:
            sign_msi()


def main():
    args = parse_command_line()
    build(args)


if __name__ == "__main__":
    main()
