#!/bin/bash
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


echo "WARNING: this script is deprecated and will be removed"
echo "please use BUILD.py instead"
for i in `seq 1 5`; do
  echo -n "."
  sleep 1
done
echo


ARGS=$@
DO_CLEAN=${DO_CLEAN:-1}
DO_ZIP=${DO_ZIP:-0}
DO_INSTALLER=${DO_INSTALLER:-1}
DO_VERPATCH=${DO_VERPATCH:-1}
DO_FULL=${DO_FULL:-1}
RUN_INSTALLER=${RUN_INSTALLER:-1}
DO_MSI=${DO_MSI:-0}
DO_SIGN=${DO_SIGN:-1}
DO_TESTS=${DO_TESTS:-0}
DO_SBOM=${DO_SBOM:-1}

# these are only enabled for "full" builds:
DO_CUDA=${DO_CUDA:-$DO_FULL}
DO_SERVICE=${DO_SERVICE:-$DO_FULL}
DO_DOC=${DO_DOC:-$DO_FULL}
BUNDLE_HTML5=${BUNDLE_HTML5:-$DO_FULL}
BUNDLE_MANUAL=${BUNDLE_MANUAL:-$DO_FULL}
BUNDLE_PUTTY=${BUNDLE_PUTTY:-$DO_FULL}
BUNDLE_OPENSSH=${BUNDLE_OPENSSH:-$DO_FULL}
BUNDLE_OPENSSL=${BUNDLE_OPENSSL:-$DO_FULL}
BUNDLE_PAEXEC=${BUNDLE_PAEXEC:-$DO_FULL}
BUNDLE_NUMPY=${BUNDLE_NUMPY:-$DO_CUDA}
BUNDLE_DESKTOPLOGON=${BUNDLE_DESKTOPLOGON:-$DO_FULL}
ZIP_MODULES=${ZIP_MODULES:-1}

PYTHON=python3

KEY_FILE="E:\\xpra.pfx"
DIST="./dist"

if [ "${DO_FULL}" == "0" ]; then
  BUILD_TYPE="Light"
	BUILD_OPTIONS="${BUILD_OPTIONS} --without-shadow --without-server --without-proxy"
	BUILD_OPTIONS="${BUILD_OPTIONS} --without-dbus"
	BUILD_OPTIONS="${BUILD_OPTIONS} --without-encoders --without-avif --without-gstreamer_video"
	BUILD_OPTIONS="${BUILD_OPTIONS} --without-nvfbc --without-cuda_kernels"
	BUILD_OPTIONS="${BUILD_OPTIONS} --without-csc_cython"
	BUILD_OPTIONS="${BUILD_OPTIONS} --without-webcam"
	BUILD_OPTIONS="${BUILD_OPTIONS} --without-win32_tools"
	BUILD_OPTIONS="${BUILD_OPTIONS} --without-docs"
	BUILD_OPTIONS="${BUILD_OPTIONS} --without-qt6_client"
	BUILD_OPTIONS="${BUILD_OPTIONS} --with-Os"
	shift
else
	BUILD_OPTIONS="${BUILD_OPTIONS} --with-qt6_client"
  BUILD_TYPE="Full"
fi
if [ "${DO_CUDA}" == "0" ]; then
	BUILD_OPTIONS="${BUILD_OPTIONS} --without-nvidia"
fi

################################################################################
# get paths and compilation options:
if [ "${DO_DOC}" == "1" ]; then
	if [ -z "${PANDOC}" ]; then
		PANDOC="pandoc"
	fi
	pandoc --version >& /dev/null
	if [ "$?" != "0" ]; then
		PANDOC="/c/Program Files/Pandoc/pandoc.exe"
		"$PANDOC" --version >& /dev/null
		if [ "$?" != "0" ]; then
			echo "pandoc not found"
			echo " either build with DO_DOC=0 or install pandoc"
			echo " (you can set the 'PANDOC' environment variable to point to it)"
			exit 1
		fi
	fi
fi


PROGRAMFILES_X86="C:\\Program Files (x86)"

if [ "${DO_FULL}" == "0" ]; then
	BUILD_OPTIONS="${BUILD_OPTIONS} --without-server --without-shadow --without-proxy --without-rfb"
fi

if [ "${BUNDLE_HTML5}" == "1" ]; then
	# Make sure we have the HTML5 client
	if [ ! -d "xpra-html5" ]; then
		echo "html5 client not found"
		echo " perhaps run: 'git clone https://github.com/Xpra-org/xpra-html5'"
		exit 1
	fi
	# Find a java interpreter we can use for the html5 minifier
	$JAVA -version >& /dev/null
	if [ "$?" != "0" ]; then
		#try my hard-coded default first to save time:
		export JAVA="C:\Program Files/Java/jdk1.8.0_121/bin/java.exe"
		if [ ! -e "${JAVA}" ]; then
			export JAVA=`find "${PROGRAMFILES}/Java" "${PROGRAMFILES}" "${PROGRAMFILES_X86}" -name "java.exe" 2> /dev/null | head -n 1`
		fi
	fi
fi

SIGNTOOL="${PROGRAMFILES}\\Microsoft SDKs\\Windows\\v7.1\\Bin\\signtool.exe"
if [ ! -e "${SIGNTOOL}" ]; then
	SIGNTOOL="${PROGRAMFILES}\\Microsoft SDKs\\Windows\\v7.1A\\Bin\\signtool.exe"
fi
if [ ! -e "${SIGNTOOL}" ]; then
	SIGNTOOL="${PROGRAMFILES_X86}\\Windows Kits\\8.1\\Bin\\x64\\signtool.exe"
fi
if [ ! -e "${SIGNTOOL}" ]; then
	SIGNTOOL="${PROGRAMFILES_X86}\\Windows Kits\\10\\App Certification Kit\\signtool.exe"
fi
if [ ! -e "${SIGNTOOL}" ]; then
	SIGNTOOL=`find /c/Program\ Files* -wholename "*/x64/signtool.exe"`
fi
if [ -e "${SIGNTOOL}" ]; then
	cp "$SIGNTOOL" ./
fi

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
ZERO_PADDED_VERSION=`${PYTHON} -c 'from xpra import __version__;print(".".join((__version__.split(".")+["0","0","0"])[:3]))'`".${REVISION}"
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
if [ "${MSYSTEM_CARCH}" == "i686" ]; then
	BUILD_ARCH_INFO=""
	DO_CUDA="0"
	APPID="Xpra32bit"
	BITS="32"
	VERSION_BITS="${VERSION} (${BITS}-bit)"
	echo " (32-bit)"
else
	BUILD_ARCH_INFO="-${MSYSTEM_CARCH}"
	APPID="Xpra_is1"
	BITS="64"
	VERSION_BITS="${VERSION}"
fi
echo
echo

INSTALLER_FILENAME="Xpra${EXTRA_VERSION}${BUILD_ARCH_INFO}_Setup_${FULL_VERSION}.exe"
MSI_FILENAME="Xpra${EXTRA_VERSION}${BUILD_ARCH_INFO}_${FULL_VERSION}.msi"
ZIP_DIR="Xpra${EXTRA_VERSION}${BUILD_ARCH_INFO}_${FULL_VERSION}"
ZIP_FILENAME="${ZIP_DIR}.zip"


################################################################################
# Build: clean, build extensions, generate exe directory

echo "* Cleaning ${DIST} output directory"
rm -fr ${DIST}/*
mkdir ${DIST} >& /dev/null

if [ "${DO_CLEAN}" == "1" ]; then
	rm -fr "build"
	#clean sometimes errors on removing pyd files,
	#so do it with rm instead:
	find xpra/ -name "*-cpython-*dll" -exec rm -f {} \;
	find xpra/ -name "*.cp*-mingw*.pyd" -exec rm -f {} \;
	CLEAN_LOG="clean.log"
	${PYTHON} ./setup.py clean >& "${CLEAN_LOG}"
	if [ "$?" != "0" ]; then
		echo "ERROR: clean failed, see ${CLEAN_LOG}:"
		tail -n 20 "${CLEAN_LOG}"
		exit 1
	fi
	#clean comtypes cache - it should not be included!
	clear_comtypes_cache.exe -y
fi

if [ "${DO_SERVICE}" == "1" ]; then
	echo "* Compiling system service shim"
	if [ "${BITS}" == "64" ]; then
		ARCH_DIRS="x64 x86"
	else
		ARCH_DIRS="x86"
	fi
	pushd "packaging/MSWindows/service" > /dev/null  || exit 1
	#the proper way would be to run vsvars64.bat
	#but we only want to locate 3 commands,
	#so we find them "by hand":
	rm -f event_log.rc event_log.res MSG00409.bin Xpra-Service.exe
	for KIT_DIR in "C:\Program Files\\Windows Kits" "C:\\Program Files (x86)\\Windows Kits"; do
		for V in 8.1 10; do
			VKIT_BIN_DIR="${KIT_DIR}\\$V\\bin"
			if [ ! -d "${VKIT_BIN_DIR}" ]; then
				continue
			fi
			for B in $ARCH_DIRS; do
				MC="${VKIT_BIN_DIR}\\$B\\mc.exe"
				RC="${VKIT_BIN_DIR}\\$B\\rc.exe"
				if [ ! -e "$MC" ]; then
					#try to find it in a versionned subdir:
					MC=`find "${VKIT_BIN_DIR}" -name "mc.exe" | grep "$B/" | head -n 1`
					RC=`find "${VKIT_BIN_DIR}" -name "rc.exe" | grep "$B/" | head -n 1`
				fi
				if [ -e "$MC" ]; then
					echo "  using SDK $V $B found in:"
					echo "  '$KIT_DIR'"
					#echo "  mc=$MC"
					#echo "  rc=$RC"
					break 3
				fi
			done
		done
	done
	for PF in "C:\\Program Files" "C:\\Program Files (x86)"; do
		for VSV in 14.0 17.0 19.0 2019; do
			LINK="$PF\\Microsoft Visual Studio $VSV\\VC\\bin\\link.exe"
			if  [ -e "${LINK}" ]; then
				break 2
			fi
			VSDIR="$PF\\Microsoft Visual Studio\\$VSV\\BuildTools\\VC\\Tools\\MSVC"
			if [ -d "${VSDIR}" ]; then
				for B in $ARCH_DIRS; do
					LINK=`find "$VSDIR" -name "link.exe" | grep "$B/$B" | head -n 1`
					if  [ -e "${LINK}" ]; then
						break 3
					fi
				done
			fi
			LINK=`find "$PF\\Microsoft Visual Studio" -name "link.exe" | grep -i "Hostx64/x64/link.exe" | sort -n | head -n 1`
			if [ ! -z "${LINK}" ]; then
				break 2
			fi
		done
	done
	#MC="C:\\Program Files\\Windows Kits\\8.1\\bin\\x64\\mc.exe"
	#RC="C:\\Program Files\\Windows Kits\\8.1\\bin\\x64\\mc.exe"
	EVENT_LOG_BUILD_LOG="event_log_build.log"

	#first build the event log definitions:
	"$MC" -U event_log.mc >& "${EVENT_LOG_BUILD_LOG}"
	if [ "$?" != "0" ]; then
		echo "ERROR: service event_log build failed, see ${EVENT_LOG_BUILD_LOG}:"
		tail -n 20 "${EVENT_LOG_BUILD_LOG}"
		exit 1
	fi
	"$RC" event_log.rc > "${EVENT_LOG_BUILD_LOG}"
	if [ "$?" != "0" ]; then
		echo "ERROR: service event_log build failed, see ${EVENT_LOG_BUILD_LOG}:"
		tail -n 20 "${EVENT_LOG_BUILD_LOG}"
		exit 1
	fi
	"$LINK" -dll -noentry -out:event_log.dll event_log.res > "${EVENT_LOG_BUILD_LOG}"
	if [ "$?" != "0" ]; then
		echo "ERROR: service event_log build failed, see ${EVENT_LOG_BUILD_LOG}:"
		tail -n 20 "${EVENT_LOG_BUILD_LOG}"
		exit 1
	fi

	#now build the system service executable:
	g++ -o Xpra-Service.exe Xpra-Service.cpp -Wno-write-strings
	if [ "$?" != "0" ]; then
		echo "ERROR: service build failed"
		exit 1
	fi
	cp -fn Xpra-Service.exe ../../../dist/
	popd > /dev/null
fi

if [ "${DO_CUDA}" == "1" ]; then
	echo "* Building the CUDA kernels"
	BUILD_CUDA_KERNEL="packaging\\MSWindows\\BUILD_CUDA_KERNEL"
	for cupath in `ls fs/share/xpra/cuda/*.cu`; do
		cu=`basename $cupath`
		fatbin="${cupath/.cu/.fatbin}"
		if [[ "$cupath" -nt "$fatbin" ]] || [[ "$BUILD_CUDA_KERNEL" -nt "fatbin" ]]; then
			kname="${cu%.*}"
			cmd.exe //c "${BUILD_CUDA_KERNEL}" "$kname" || exit 1
		fi
	done
else
	BUILD_OPTIONS="${BUILD_OPTIONS} --without-nvenc --without-nvjpeg_encoder --without-nvjpeg_decoder --without-nvfbc"
fi

echo "* Building Cython modules"
BUILD_LOG="packaging/MSWindows/Python3-build.log"
NPROCS=${NPROCS:-`nproc`}
${PYTHON} ./setup.py build_ext ${BUILD_OPTIONS} --inplace -j ${NPROCS} >& ${BUILD_LOG}
if [ "$?" != "0" ]; then
	echo "ERROR: build failed, see ${BUILD_LOG}:"
	tail -n 20 "${BUILD_LOG}"
	exit 1
fi

if [ "${DO_TESTS}" == "1" ]; then
	echo "* Running unit tests"
	UNITTEST_LOG="packaging/MSWindows/unittest.log"
	PYTHONPATH=.:./tests/unittests XPRA_COMMAND="./fs/bin/xpra" ${PYTHON} ./unittests/unit/run.py >& ${UNITTEST_LOG}
	if [ "$?" != "0" ]; then
		echo "ERROR: unittests have failed, see ${UNITTEST_LOG}:"
		tail -n 20 "${UNITTEST_LOG}"
		exit 1
	fi
fi

echo "* Generating installation directory"
CX_FREEZE_LOG="packaging/MSWindows/cx_freeze-install.log"
${PYTHON} ./setup.py install_exe ${BUILD_OPTIONS} --install=${DIST} >& ${CX_FREEZE_LOG}
if [ "$?" != "0" ]; then
	echo "ERROR: build failed, see ${CX_FREEZE_LOG}:"
	tail -n 20 "${CX_FREEZE_LOG}"
	exit 1
fi
if [ "${DO_DOC}" == "1" ]; then
	mkdir ${DIST}/doc
	PANDOC="${PANDOC}" ${PYTHON} ./setup.py doc ${DIST}/doc
fi

#fix case sensitive mess:
mv ${DIST}/lib/girepository-1.0/Glib-2.0.typelib ${DIST}/lib/girepository-1.0/GLib-2.0.typelib.tmp
mv ${DIST}/lib/girepository-1.0/GLib-2.0.typelib.tmp ${DIST}/lib/girepository-1.0/GLib-2.0.typelib

#fixup cx_Logging, required by the service class before we can patch sys.path to find it:
if [ -e "${DIST}/lib/cx_Logging.pyd" ]; then
	mv "${DIST}/lib/cx_Logging.pyd" "${DIST}/"
fi
#fixup cx freeze wrongly including an empty dir:
rm -fr "${DIST}/lib/comtypes/gen"
#fixup tons of duplicated DLLs, thanks cx_Freeze!
pushd ${DIST} > /dev/null || exit 1
#why is it shipping those files??
find lib/ -name "*dll.a" -exec rm {} \;

#only keep the actual loaders, not all the other crap cx_Freeze put there:
mkdir lib/gdk-pixbuf-2.0/2.10.0/loaders.tmp
mv lib/gdk-pixbuf-2.0/2.10.0/loaders/libpixbufloader-*.dll lib/gdk-pixbuf-2.0/2.10.0/loaders.tmp/
rm -fr lib/gdk-pixbuf-2.0/2.10.0/loaders
mv lib/gdk-pixbuf-2.0/2.10.0/loaders.tmp lib/gdk-pixbuf-2.0/2.10.0/loaders
if [ "${DO_FULL}" == "0" ]; then
	pushd lib/gdk-pixbuf-2.0/2.10.0/loaders || exit 1
	# we only want to keep: jpeg, png, xpm and svg
	for fmt in xbm gif jxl tiff ico tga bmp	ani pnm avif qtif icns heif; do
		rm -f libpixbufloader-${fmt}.dll
	done
	popd
fi
#move libs that are likely to be common to the lib dir:
for prefix in lib avcodec avformat avutil swscale swresample zlib1 xvidcore; do
	find lib/Xpra -name "${prefix}*dll" -exec mv {} ./lib/ \;
done
#liblz4 ends up in the wrong place and duplicated,
#keep just one copy in ./lib
find lib/lz4 -name "liblz4.dll" -exec mv {} ./lib/ \;
if [ "${DO_CUDA}" == "0" ]; then
	rm -fr ./lib/pycuda ./lib/cuda* ./lib/libnv*
	rm -f ./etc/xpra/cuda.conf
else
  #keep cuda bits at top level:
  mv lib/cuda* lib/nvjpeg* ./
fi

if [ "${BUNDLE_NUMPY}" == "0" ]; then
	rm -fr ./lib/numpy
else
	rm -fr ./lib/numpy/_pyinstaller
	for x in openblas gfortran quadmath; do
		mv -f ./lib/numpy/core/lib$x*.dll ./lib/
		mv -f ./lib/numpy/linalg/lib$x*.dll ./lib/
	done
	#trim tests from numpy
	pushd ./lib/numpy > /dev/null || exit 1
	rm -fr ./f2py/docs ./tests ./doc
	for x in core distutils f2py lib linalg ma matrixlib oldnumeric polynomial random testing compat fft; do
		rm -fr ./$x/tests
	done
	popd > /dev/null
fi
mv lib/nacl/libsodium*dll ./lib/
#gstreamer uses its own lib dir, so this does not belong in the root:
mv ./libgst*.dll ./lib/gstreamer-1.0/
#but the main gstreamer lib does:
mv ./lib/gstreamer-1.0/libgstreamer*.dll ./lib/
#and the gstreamer support libraries look like plugins but those are actual DLLs:
mv ./lib/gstreamer-1.0/libgst*-1.0-*.dll ./lib/gstreamer-1.0/libwavpack* ./lib/
#gstreamer modules don't have "-" in the DLL name:
mv ./lib/gstreamer-1.0/lib*-?.dll ./lib/
#not needed at all for now:
rm ./lib/libgstbasecamerabinsrc* libgstphotography*

#move most DLLs to /lib
mv *dll lib/
#but keep the core DLLs (python, gcc, etc):
mv lib/msvcrt*dll lib/libpython*dll lib/libgcc*dll lib/libwinpthread*dll ./
#and keep pdfium:
mv lib/*pdfium*.dll ./
pushd lib > /dev/null || exit 1
#remove all the pointless duplication:
for x in `ls *dll`; do
	find ./ -mindepth 2 -name "${x}" -exec rm {} \;
done

rm -f ./libjasper*
# Python modules:
rm -fr ./lib2to3* ./xdg* ./olefile* ./pygtkcompat* keyring/testing ./jaraco* ./p11-kit* ./lz4
#remove codecs we don't need:
rm -f ./libx265* ./libjxl* ./libde265* ./libkvazaar*
if [ "${DO_FULL}" == "0" ]; then
	rm -fr *.dist-info
	# kerberos / gss libs:
	rm -f ./libshishi* ./libgss*
	# no dbus:
	rm -f ./libdbus*
	# no AV1:
    rm -f ./libaom* ./rav1e* ./libdav1d* ./libheif*
    # no avif:
    rm -f ./libavif* ./libSvt*
    # remove h264 encoder:
	rm -f ./libx264*
	# should not be needed:
	rm -f ./libsqlite* ./libp11-kit*
	# extra audio codecs (we just keep vorbis and opus):
	rm -f ./libmp3* ./libwavpack* ./libmpdec* ./libspeex* ./libFLAC* ./libmpg123* ./libfaad* ./libfaac*
	# matching gstreamer modules:
	pushd ./gstreamer-1.0 || exit 1
	rm -f ./libgstflac* ./libgstwavpack* ./libgstspeex* ./libgstwavenc* ./libgstlame* ./libgstmpg123* ./libgstfaac* ./libgstfaad* ./libgstwav*
	rm -f ./libgstaom* ./libgstwinscreencap* ./libgstx264* ./libgstvpx* ./libgstvideo* ./libgstopenh264*
	rm -f ./libgstgdp*
	popd
fi
# these started causing packaging problems with GStreamer 1.24:
pushd ./gstreamer-1.0 || exit 1
rm -f libgstisomp4.*
popd

#remove PIL loaders we don't use:
echo "* removing unnecessary PIL plugins:"
pushd "./PIL" || exit 1
RMP=""
KMP=""
for file_name in `ls *Image*`; do
	plugin_name=`echo $file_name | sed 's+\.py.*++g'`
	echo "$file_name" | egrep "Bmp|Ico|Image.py|ImageChops|ImageCms|ImageWin|ImageChops|ImageColor|ImageDraw|ImageFile|ImageFilter|ImageFont|ImageGrab|ImageMode|ImageOps|ImagePalette|ImagePath|ImageSequence|ImageStat|ImageTransform|Jpeg|Tiff|Png|Ppm|Xpm|WebP" >& /dev/null
	if [ "$?" == "0" ]; then
		KMP="${KMP} $plugin_name"
	else
		RMP="${RMP} $plugin_name"
		rm $file_name
	fi
done
echo " removed: ${RMP}"
echo " kept: ${KMP}"
popd

#remove test bits we don't need:
rm -fr ./future/backports/test ./comtypes/test/ ./ctypes/macholib/fetch_macholib* ./distutils/tests ./distutils/command ./enum/doc ./websocket/tests ./email/test/ ./psutil/tests
rm -fr ./Crypto/SelfTest/*


#not building:
rm -fr cairo/include

#no runtime type checks:
find xpra -name "py.typed" -exec rm {} \;
#remove source:
find xpra -name "*.bak" -exec rm {} \;
find xpra -name "*.orig" -exec rm {} \;
find xpra -name "*.pyx" -exec rm {} \;
find xpra -name "*.c" -exec rm {} \;
find xpra -name "*.cpp" -exec rm {} \;
find xpra -name "*.m" -exec rm {} \;
find xpra -name "constants.txt" -exec rm {} \;
find xpra -name "*.h" -exec rm {} \;
find xpra -name "*.html" -exec rm {} \;
find xpra -name "*.pxd" -exec rm {} \;
find xpra -name "*.cu" -exec rm {} \;

#remove empty directories:
rmdir xpra/*/*/* 2> /dev/null
rmdir xpra/*/* 2> /dev/null
rmdir xpra/* 2> /dev/null

# workaround for zeroconf - just copy it wholesale
# since I have no idea why cx_Freeze struggles with it:
rm -fr zeroconf
ZEROCONF_DIR=`$PYTHON -c "import zeroconf,os;print(os.path.dirname(zeroconf.__file__))"`
cp -apr $ZEROCONF_DIR ./

#leave ./lib
popd > /dev/null
#leave ./dist
popd > /dev/null

if [ "${DO_SBOM}" != "0" ]; then
  ./packaging/MSWindows/BUILD.py sbom
  rm -f ./dist/lib/xpra/build_info*
  cp xpra/build_info.py ./dist/lib/xpra/
fi

pushd dist/lib > /dev/null
#zip up some modules:
if [ "${ZIP_MODULES}" == "1" ]; then
	#these modules contain native code or data files,
	#so they will require special treatment:
	#xpra numpy cryptography PIL nacl cffi gtk gobject glib aioquic pylsqpack > /dev/null
	if [ "${DO_FULL}" == "0" ]; then
		rm -fr test unittest gssapi pynvml ldap ldap3 pyu2f sqlite3 psutil
	else
		zip --move -ur library.zip test unittest gssapi pynvml ldap ldap3 pyu2f sqlite3 psutil
	fi
	zip --move -ur library.zip OpenGL encodings future paramiko html \
			pyasn1 asn1crypto async_timeout \
			certifi OpenSSL pkcs11 keyring \
			ifaddr pyaes browser_cookie3 service_identity \
			re platformdirs attr setproctitle pyvda zipp \
			distutils comtypes email multiprocessing packaging \
			pkg_resources pycparser idna ctypes json \
			http enum winreg copyreg _thread _dummythread builtins importlib \
			logging queue urllib xml xmlrpc pyasn1_modules concurrent collections > /dev/null
fi
#leave ./dist/lib
popd > /dev/null

pushd dist > /dev/null
rm -fr share/xml
rm -fr share/glib-2.0/codegen share/glib-2.0/gdb share/glib-2.0/gettext
rm -fr share/themes/Default/gtk-2.0*
if [ "${DO_FULL}" == "0" ]; then
	# remove extra bits that take up a lot of space:
	rm -fr share/icons/Adwaita/cursors
	rm -fr share/fonts/gsfonts share/fonts/adobe* share/fonts/cantarell
fi

#remove empty icon directories
for i in `seq 4`; do
	find share/icons -type d -exec rmdir {} \; 2> /dev/null
done

if [ "${DO_FULL}" == "0" ]; then
  rm qt.conf
fi

#leave ./dist
popd > /dev/null


echo "* Adding manifest"
sed "s/XPRA_ZERO_PADDED_VERSION/$ZERO_PADDED_VERSION/" packaging/MSWindows/exe.manifest > packaging/MSWindows/exe.manifest.tmp
for exe in Bug_Report Xpra-Launcher Xpra Xpra_cmd; do
  cp packaging/MSWindows/exe.manifest.tmp ./dist/${exe}.exe.manifest
done
if [ "${DO_FULL}" == "1" ]; then
	for exe in GTK_info NativeGUI_info Screenshot Xpra-Shadow; do
	  cp packaging/MSWindows/exe.manifest.tmp ./dist/${exe}.exe.manifest
	done
fi
rm packaging/MSWindows/exe.manifest.tmp


echo "* Generating gdk pixbuf loaders.cache"
gdk-pixbuf-query-loaders.exe "dist/lib/gdk-pixbuf-2.0/2.10.0/loaders/*" | sed 's+".*dist/+"+g' > dist/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache
echo "* Generating icons and theme cache"
for itheme in `ls dist/share/icons/`; do
	gtk-update-icon-cache.exe -t -i "dist/share/icons/${itheme}"
done

if [ "${BUNDLE_MANUAL}" == "1" ]; then
	echo "* Generating HTML Manual Page"
	groff.exe -mandoc -Thtml < ./fs/share/man/man1/xpra.1 > ${DIST}/manual.html
fi

if [ "${BUNDLE_HTML5}" == "1" ]; then
	echo "* Installing the HTML5 client"
	pushd "xpra-html5" || exit 1
	python3 ./setup.py install ../${DIST}/www/
	popd
fi

if [ "${BUNDLE_PUTTY}" == "1" ]; then
	echo "* Adding TortoisePlink"
	TORTOISESVN="/c/Program Files/TortoiseSVN"
	if [ ! -e "${TORTOISESVN}" ]; then
		TORTOISESVN="/c/Program Files (x86)/TortoiseSVN"
		if [ ! -e "${TORTOISESVN}" ]; then
			echo "Missing TortoiseSVN!"
			exit 1
		fi
	fi
	cp -fn "${TORTOISESVN}/bin/TortoisePlink.exe" "${DIST}/Plink.exe"
	for dll in vcruntime140.dll msvcp140.dll vcruntime140_1.dll; do
		cp "/c/Windows/System32/$dll" "${DIST}/"
	done
	#are we meant to include those DLLs?
	#rsync -rplogt "${TORTOISESVN}/bin/"*dll "${DIST}/"
fi

if [ "${BUNDLE_OPENSSH}" == "1" ]; then
	echo "* Adding OpenSSH"
	cp -fn "/usr/bin/ssh.exe" "${DIST}/"
	cp -fn "/usr/bin/sshpass.exe" "${DIST}/"
	cp -fn "/usr/bin/ssh-keygen.exe" "${DIST}/"
	for x in 2.0 gcc_s crypto z gssapi asn1 com_err roken crypt heimntlm krb5 heimbase wind hx509 hcrypto sqlite3; do
		cp -fn /usr/bin/msys-$x*.dll "${DIST}/"
	done
fi

if [ "${BUNDLE_OPENSSL}" == "1" ]; then
	cp -fn "${MINGW_PREFIX}/bin/openssl.exe" "${DIST}/"
	mkdir -p "${DIST}/etc/ssl"
	cp -fn "${MINGW_PREFIX}/etc/ssl/openssl.cnf" "${DIST}/etc/ssl/openssl.cnf"
	#we need those libraries at the top level:
	mv "${DIST}"/lib/libssl-*dll "${DIST}/"
	mv "${DIST}"/lib/libcrypto-*dll "${DIST}/"
fi

if [ "${BUNDLE_PAEXEC}" == "1" ]; then
	cp -fn "${MINGW_PREFIX}/bin/paexec.exe" "${DIST}/"
fi

if [ "${BUNDLE_DESKTOPLOGON}" == "1" ]; then
	for lib in AxMSTSCLib MSTSCLib DesktopLogon; do
		cp -fn "${MINGW_PREFIX}/bin/$lib.dll" "${DIST}/"
	done
fi

if [ "${DO_CUDA}" == "1" ]; then
	#pycuda wants a CUDA_PATH with "/bin" in it:
	mkdir "${DIST}/bin"
fi

if [ "${DO_VERPATCH}" == "1" ]; then
	for exe in `ls dist/*exe | grep -v Plink.exe`; do
		tool_name=`echo $exe | sed 's+dist/++g;s+Xpra_++g;s+Xpra-++g;s+_+ +g;s+-+ +g;s+\.exe++g'`
		verpatch $exe				//s desc "Xpra $tool_name"		//va "${ZERO_PADDED_VERSION}" //s company "xpra.org" //s copyright "(c) xpra.org 2024" //s product "xpra" //pv "${ZERO_PADDED_VERSION}"
	done
	verpatch dist/Xpra_cmd.exe		//s desc "Xpra command line"	//va "${ZERO_PADDED_VERSION}" //s company "xpra.org" //s copyright "(c) xpra.org 2020" //s product "xpra" //pv "${ZERO_PADDED_VERSION}"
	verpatch dist/Xpra.exe			//s desc "Xpra"					//va "${ZERO_PADDED_VERSION}" //s company "xpra.org" //s copyright "(c) xpra.org 2024" //s product "xpra" //pv "${ZERO_PADDED_VERSION}"
	if [ "${DO_FULL}" == "1" ]; then
		verpatch dist/Xpra-Proxy.exe	//s desc "Xpra Proxy Server"	//va "${ZERO_PADDED_VERSION}" //s company "xpra.org" //s copyright "(c) xpra.org 2020" //s product "xpra" //pv "${ZERO_PADDED_VERSION}"
	fi
fi


echo
echo "installation disk usage:"
du -sm "${DIST}"
echo

################################################################################
# packaging: ZIP / EXE / MSI

if [ "${DO_ZIP}" == "1" ]; then
	echo "* Creating ZIP file:"
	rm -fr "${ZIP_DIR}" "${ZIP_FILENAME}"
	mkdir "${ZIP_DIR}"
	rsync -rplogt "${DIST}"/* "${ZIP_DIR}"
	zip -9qmr "${ZIP_FILENAME}" "${ZIP_DIR}"
	echo
	du -sm "${ZIP_FILENAME}"
	echo
fi

if [ "${DO_INSTALLER}" == "1" ]; then
	INNOSETUP="/c/Program Files/Inno Setup 6/ISCC.exe"
	if [ ! -e "${INNOSETUP}" ]; then
		INNOSETUP="/c/Program Files (x86)/Inno Setup 6/ISCC.exe"
		if [ ! -e "${INNOSETUP}" ]; then
			echo "cannot find InnoSetup"
			exit 1
		fi
	fi
	INNOSETUP_LOG="packaging/MSWindows/innosetup.log"
	echo "* Creating the installer using InnoSetup"
	rm -f "Xpra_Setup.exe" "${INSTALLER_FILENAME}" "${INNOSETUP_LOG}"
	cp -fn "packaging/MSWindows/xpra.iss" "xpra.iss"
	if [ "${DO_FULL}" == "0" ]; then
	  #don't run post-install openssl:
	  sed -i"" "s/    PostInstall();/Log('skipped post-install');/g" xpra.iss
		#remove shadow start menu entry
		sed -i"" "s/.*Xpra Shadow Server.*//g" xpra.iss
  fi
  if [ "${DO_DOC}" == "0" ]; then
    # remove link to the manual:
	  sed -i"" "s/.*Command Manual.*//g" xpra.iss
	fi
	sed -i"" "s/AppId=.*/AppId=${APPID}/g" xpra.iss
	sed -i"" "s/AppName=.*/AppName=Xpra ${VERSION_BITS}/g" xpra.iss
	sed -i"" "s/UninstallDisplayName=.*/UninstallDisplayName=Xpra ${VERSION_BITS}/g" xpra.iss
	sed -i"" "s/AppVersion=.*/AppVersion=${FULL_VERSION}/g" xpra.iss
	"${INNOSETUP}" "xpra.iss" >& "${INNOSETUP_LOG}"
	if [ "$?" != "0" ]; then
		echo "InnoSetup error - see ${INNOSETUP_LOG}:"
		tail -n 20 "${INNOSETUP_LOG}"
		#rm "xpra.iss"
		exit 1
	fi
	rm "xpra.iss"
	mv "dist\Xpra_Setup.exe" "${INSTALLER_FILENAME}"

	if [ "${DO_SIGN}" == "1" ]; then
		SIGNTOOL_LOG="packaging/MSWindows/signtool.log"
		echo "* Signing EXE"
		cmd.exe //c signtool.exe sign //v //f "${KEY_FILE}" //t "http://timestamp.digicert.com" "${INSTALLER_FILENAME}" > ${SIGNTOOL_LOG}
		if [ "$?" != 0 ]; then
			echo "signtool command failed, see ${SIGNTOOL_LOG}:"
			cat ${SIGNTOOL_LOG}
		fi
	fi
	echo
	du -sm "${INSTALLER_FILENAME}"
	echo

	if [ "${RUN_INSTALLER}" == "1" ]; then
		echo "* Finished - running the new installer"
		#we need to escape slashes!
		#(this doesn't preserve spaces.. we should use shift instead)
		CMD_ARGS=`echo ${ARGS} | sed 's+/+//+g'`
		"./${INSTALLER_FILENAME}" "${CMD_ARGS}"
	fi
fi

if [ "${DO_MSI}" == "1" ]; then
	MSIWRAPPER="/c/Program Files/MSI Wrapper/MsiWrapper.exe"
	if [ ! -e "${MSIWRAPPER}" ]; then
		MSIWRAPPER="/c/Program Files (x86)/MSI Wrapper/MsiWrapper.exe"
		if [ ! -e "${MSIWRAPPER}" ]; then
			echo "cannot find MSI Wrapper"
			exit 1
		fi
	fi
	#we need to quadruple escape backslashes
	#as they get interpreted by the shell and sed, multiple times:
	CWD=`pwd | sed 's+/\([a-zA-Z]\)/+\1:\\\\\\\\+g; s+/+\\\\\\\\+g'`
	echo "CWD=${CWD}"
	cat "packaging\\MSWindows\\msi.xml" | sed "s+\$CWD+${CWD}+g" | sed "s+\$INPUT+${INSTALLER_FILENAME}+g" | sed "s+\$OUTPUT+${MSI_FILENAME}+g" | sed "s+\$ZERO_PADDED_VERSION+${ZERO_PADDED_VERSION}+g" | sed "s+\$FULL_VERSION+${FULL_VERSION}+g" > msi.xml
	"${MSIWRAPPER}"
	if [ "${DO_SIGN}" == "1" ]; then
		SIGNTOOL_LOG="packaging/MSWindows/signtool.log"
		echo "* Signing MSI"
		cmd.exe //c signtool.exe sign //v //f "${KEY_FILE}" //t "http://timestamp.comodoca.com/authenticode" "${MSI_FILENAME}" > ${SIGNTOOL_LOG}
		if [ "$?" != 0 ]; then
			echo "signtool command failed, see ${SIGNTOOL_LOG}:"
			cat ${SIGNTOOL_LOG}
		fi
	fi
	echo
	du -sm "${MSI_FILENAME}"
	echo
fi
