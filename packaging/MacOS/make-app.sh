#!/bin/bash

if [ -z "${JHBUILD_PREFIX}" ]; then
	echo "JHBUILD_PREFIX is not set"
	echo "this script must be executed from jhbuild shell"
	exit 1
fi

MACOS_SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
XPRA_SRC_DIR=$(dirname "$(dirname "${MACOS_SCRIPT_DIR}")")

export PYTHON="${PYTHON:-${JHBUILD_PREFIX}/bin/python3}"
PYTHON_MAJOR_VERSION=$($PYTHON -c 'import sys;sys.stdout.write("%s" % sys.version_info[0])')
PYTHON_MINOR_VERSION=$($PYTHON -c 'import sys;sys.stdout.write("%s" % sys.version_info[1])')
SITELIB="${JHBUILD_PREFIX}/lib/python3.${PYTHON_MINOR_VERSION}/site-packages/"

STRIP_DEFAULT="${STRIP_DEFAULT:=1}"
STRIP_GSTREAMER_PLUGINS="${STRIP_GSTREAMER_PLUGINS:=$STRIP_DEFAULT}"
GSTREAMER_VIDEO="${GSTREAMER_VIDEO:=0}"
STRIP_SOURCE="${STRIP_SOURCE:=0}"
STRIP_OPENGL="${STRIP_OPENGL:=$STRIP_DEFAULT}"
CLIENT_ONLY="${CLIENT_ONLY:=0}"
ARCH="${ARCH:=$(arch)}"
if [ "${ARCH}" == "i386" ]; then
	ARCH="x86_64"
fi

DO_TESTS="${DO_TESTS:-0}"
DO_X11="0"

BUILDNO="${BUILDNO:="0"}"
APP_DIR="./image/Xpra.app"
if [ "${GSTREAMER_VIDEO}" == "1" ]; then
	BUILD_ARGS="${BUILD_ARGS} --with-gstreamer_video"
else
	BUILD_ARGS="${BUILD_ARGS} --without-gstreamer_video"
fi
if [ "${CLIENT_ONLY}" == "1" ]; then
	APP_DIR="./image/Xpra-Client.app"
	BUILD_ARGS="${BUILD_ARGS} --without-server --without-shadow --without-proxy"
	DO_TESTS="0"
else
	if [ ! -e "${JHBUILD_PREFIX}/share/xpra/www/" ]; then
		echo "the xpra html5 client must be installed in ${JHBUILD_PREFIX}/share/xpra/www/"
		exit 1
	fi
	if [ -d "/opt/X11" ]; then
		BUILD_ARGS="${BUILD_ARGS} --with-x11 --pkg-config-path=/opt/X11/lib/pkgconfig --pkg-config-path=/opt/X11/share/pkgconfig"
		DO_X11="1"
	fi
fi
pandoc -v >& /dev/null
if [ "$?" != "0" ]; then
	echo "pandoc not found, not building HTML documentation"
	BUILD_ARGS="${BUILD_ARGS} --without-docs"
fi


function log_error() {
  if [ "$?" != "0" ]; then
    echo "ERROR: $1 failed"
    echo " see $2 for details:"
    echo
    tail -n 20 "$2"
    exit 1
  fi
}

echo "*******************************************************************************"
echo "Cleaning"
echo "- jhbuild files and directories"
# Fixing JHBUILD environment if needed
chmod 755 "${JHBUILD_PREFIX}/lib/libpython"*.dylib
if [ ! -d "${JHBUILD_PREFIX}/etc/pango" ]; then
  #avoid error if there is no /etc/pango:
  #(which seems to be the case with newer builds)
  mkdir "${JHBUILD_PREFIX}/etc/pango"
fi
if [ ! -e "${JHBUILD_PREFIX}/lib/charset.alias" ]; then
  #gtk-mac-bundler chokes if this file is missing
  touch "${JHBUILD_PREFIX}/lib/charset.alias"
fi
HICOLOR_INDEX="${JHBUILD_PREFIX}/share/icons/hicolor/index.theme"
if [ ! -e "${HICOLOR_INDEX}" ]; then
  #gtk-mac-bundler chokes if this file is missing
  touch "${HICOLOR_INDEX}"
fi

echo "- current xpra installation"
rm -fr "${SITELIB}/xpra"*
rm -fr "${MACOS_SCRIPT_DIR}/image/"* "${MACOS_SCRIPT_DIR}/dist"
ln -sf "../../dist" "${MACOS_SCRIPT_DIR}/dist"

echo "- build and dist directories"
rm -fr "${XPRA_SRC_DIR}/build/" "${XPRA_SRC_DIR}}/dist"

echo "- clean subcommand"
cd "${XPRA_SRC_DIR}" || exit 1
CLEAN_LOG="${MACOS_SCRIPT_DIR}/clean.log"
"${PYTHON}" ./setup.py clean >& "${CLEAN_LOG}"
log_error "clean" "${CLEAN_LOG}"


echo "*******************************************************************************"
echo "Building Xpra for Python ${PYTHON_MAJOR_VERSION}.${PYTHON_MINOR_VERSION} using $NPROC logical CPUs"
NPROC=$(sysctl -n hw.logicalcpu)
cd "${XPRA_SRC_DIR}" || exit 1
echo "- regenerate source and build info"
rm -f "xpra/src_info.py" "xpra/build_info.py"
BUILD_INFO_LOG="${MACOS_SCRIPT_DIR}/build_info.log"
"${PYTHON}" "./fs/bin/add_build_info.py" "src" "build" >& "${BUILD_INFO_LOG}"
log_error "add_build_info" "${BUILD_INFO_LOG}"
VERSION=$(PYTHONPATH="." "${PYTHON}" -c "from xpra import __version__;import sys;sys.stdout.write(__version__)")
REVISION=$(PYTHONPATH="." "${PYTHON}" -c "from xpra import src_info;import sys;sys.stdout.write(str(src_info.REVISION))")
REV_MOD=$(PYTHONPATH="." "${PYTHON}" -c "from xpra import src_info;import sys;sys.stdout.write(['','M'][src_info.LOCAL_MODIFICATIONS>0])")
echo "- version ${VERSION}-${REVISION}${REV_MOD}"

echo -n "- adding metadata to plist files:"
cd "${MACOS_SCRIPT_DIR}" || exit 1
for plist in "./Info.plist" "./Xpra_NoDock.app/Contents/Info.plist"; do
	echo -n " $plist"
	git checkout $plist >& /dev/null
	sed -i '' -e "s+%VERSION%+$VERSION+g" $plist
	sed -i '' -e "s+%REVISION%+$REVISION$REV_MOD+g" $plist
	sed -i '' -e "s+%BUILDNO%+$BUILDNO+g" $plist
	sed -i '' -e "s+%ARCH%+$ARCH+g" $plist
	if [ "${CLIENT_ONLY}" == "1" ]; then
		sed -i '' -e "s+Xpra+Xpra-Client+g" $plist
		sed -i '' -e "s+org.xpra.xpra+org.xpra.xpra-client+g" $plist
	fi
done
echo

cd "${XPRA_SRC_DIR}" || exit 1
BUILD_EXT_LOG="${MACOS_SCRIPT_DIR}/build_ext.log"
echo "- build extensions"
echo "./setup.py build_ext ${BUILD_ARGS}" -j $NPROC > "${BUILD_EXT_LOG}"
"${PYTHON}" ./setup.py build_ext ${BUILD_ARGS} -j $NPROC >> "${BUILD_EXT_LOG}" 2>&1
log_error "build_ext" "${BUILD_EXT_LOG}"

INSTALL_LOG="${MACOS_SCRIPT_DIR}/install.log"
echo "- install locally"
echo "./setup.py install ${BUILD_ARGS}" > "${INSTALL_LOG}"
"${PYTHON}" ./setup.py install ${BUILD_ARGS} >> "${INSTALL_LOG}" 2>&1
log_error "install" "${INSTALL_LOG}"

if [ "${DO_TESTS}" == "1" ]; then
	cd "${XPRA_SRC_DIR}/unittests" || exit 1
	rm -fr ./tmpdir && mkdir ./tmpdir || exit 1
	#make sure the unit tests can run "python3 xpra ...":
	rm -f ./xpra >& /dev/null
	ln -sf ../fs/bin/xpra .
	UNITTEST_LOG="${MACOS_SCRIPT_DIR}/unittest.log"
	echo "- run unit tests (see ${UNITTEST_LOG} - this may take a while)"
	TMPDIR=./tmpdir XPRA_COMMAND="$PYTHON ./xpra" XPRA_NODOCK_COMMAND="$PYTHON ./xpra" XPRA_SOUND_COMMAND="$PYTHON ./xpra" PYTHONPATH=. ./unit/run.py >& "${UNITTEST_LOG}"
	log_error unittests "${UNITTEST_LOG}"
  rm -fr ./tmpdir
  echo "OK"
fi


echo "*******************************************************************************"
cd "${XPRA_SRC_DIR}" || exit 1
echo "Creating app bundle"
PY2APP_LOG="${MACOS_SCRIPT_DIR}/py2app.log"
echo "- py2app"
echo "XPRA_GI_BLOCK=\"*\" ${PYTHON} ./setup.py py2app ${BUILD_ARGS}" > "${PY2APP_LOG}"
XPRA_GI_BLOCK="*" "${PYTHON}" ./setup.py py2app ${BUILD_ARGS} >> "${PY2APP_LOG}" 2>&1
log_error "py2app" "${PY2APP_LOG}"

echo "- adding AVFoundation"
rsync -rplogt "${SITELIB}/AVFoundation" ./dist/xpra.app/Contents/Resources/lib/python3.${PYTHON_MINOR_VERSION}/
echo "- pkg_resources.py2_warn, gi, cffi"
for m in pkg_resources gi cffi; do
	mpath=$(PYTHONWARNINGS="ignore::UserWarning" python3 -c "import os;import $m;print(os.path.dirname($m.__file__))")
	cp -r "${mpath}" ./dist/xpra.app/Contents/Resources/lib/python3.${PYTHON_MINOR_VERSION}/
done
mpath=$(PYTHONWARNINGS="ignore::UserWarning" python3 -c "import _cffi_backend;print(_cffi_backend.__file__)")
cp "${mpath}" ./dist/xpra.app/Contents/Resources/lib/python3.${PYTHON_MINOR_VERSION}/lib-dynload/

echo "- uvloop"
UVLOOPDIR="./dist/xpra.app/Contents/Resources/lib/python3.${PYTHON_MINOR_VERSION}/uvloop/"
mkdir "${UVLOOPDIR}"
cp "${SITELIB}/uvloop/_noop.py" "${UVLOOPDIR}/"

if [ "${GSTREAMER_VIDEO}" == "0" ]; then
	echo "- remove gstreamer video codec"
	rm -fr "./dist/xpra.app/Contents/Resources/lib/python3.${PYTHON_MINOR_VERSION}/xpra/codecs/gstreamer"
fi


echo "*******************************************************************************"
echo "Creating the application bundle"
cd "${MACOS_SCRIPT_DIR}" || exit 1
BUNDLER_LOG="${MACOS_SCRIPT_DIR}/gtk-mac-bundler.log"
gtk-mac-bundler Xpra.bundle >& "${BUNDLER_LOG}"
log_error "gtk-mac-bundler" "${BUNDLER_LOG}"

# from here on, these directories should exist:
CONTENTS_DIR="${APP_DIR}/Contents"
MACOS_DIR="${CONTENTS_DIR}/MacOS"
RSCDIR="${CONTENTS_DIR}/Resources"
HELPERS_DIR="${CONTENTS_DIR}/Helpers"
LIBDIR="${RSCDIR}/lib"


echo "*******************************************************************************"
echo "make python softlink without version number"
pushd "${MACOS_SCRIPT_DIR}/${LIBDIR}" || exit 1
ln -sf "python3.${PYTHON_MINOR_VERSION}" python
cd python || exit 1
echo "unzip site-packages"
if [ -e "site-packages.zip" ]; then
	unzip -nq site-packages.zip
	rm site-packages.zip
fi
PYZIP="../python3${PYTHON_MINOR_VERSION}.zip"
if [ -e "${PYZIP}" ]; then
	unzip -nq "${PYZIP}"
	rm "${PYZIP}"
fi
popd || exit 1


echo "*******************************************************************************"
echo "Add xpra/server/python scripts"
cd "${MACOS_SCRIPT_DIR}" || exit 1
rsync -pltv ./Helpers/* "${HELPERS_DIR}/"
#we dont need the wrappers that may have been installed by distutils:
rm -f "${MACOS_DIR}/*bin"

#ensure that every wrapper has a "python" executable to match:
#(see PythonExecWrapper for why we need this "exec -a" workaround)
for x in `ls "$HELPERS_DIR" | egrep -v "Python|gst-plugin-scanner"`; do
	#replace underscore with space in actual binary filename:
	target="$RSCDIR/bin/`echo $x | sed 's+_+ +g'`"
	if [ ! -e "$target" ]; then
		#symlinks don't work for us here (osx uses the referent as program name)
		#and hardlinks could cause problems, so we duplicate the file:
		cp "$RSCDIR/bin/python" "$target"
	fi
done
#fix for:
# /Applications/Xpra.app/Contents/Resources/bin/../Resources/lib/gdk-pixbuf-2.0/2.10.0/loaders/libpixbufloader-svg.so
pushd "${RSCDIR}" || exit 1
ln -sf ../Resources ./Resources
popd || exit 1

# launcher needs to be in main ("MacOS" dir) since it is launched from the custom Info.plist:
# and overwrite the "Xpra" script generated by py2app with our custom one:
cp ./Helpers/Launcher ./Helpers/Xpra ${MACOS_DIR}
rm -f ${MACOS_DIR}/Xpra-bin >& /dev/null
if [ "${CLIENT_ONLY}" == "1" ]; then
	rm -f "${HELPERS_DIR}/Shadow"
	rm -f "${RSCDIR}/bin/Shadow"
fi
# Add the icon:
cp ./*.icns ${RSCDIR}/


echo "*******************************************************************************"
echo "include all xpra modules found: "
rsync -rpl "${SITELIB}/xpra/"* "${LIBDIR}/python/xpra/"
echo "removing files that should not be installed in the first place (..)"
for x in "*.html" "*.c" "*.cpp" "*.pyx" "*.pxd" "constants.pxi" "constants.txt"; do
	echo "removing $x:"
	find "${LIBDIR}/python/xpra/" -name "$x" -print -exec rm "{}" \; | sed "s+${LIBDIR}/python/xpra/++g" | xargs -L 1 echo "* "
done
#should be redundant:
if [ "${CLIENT_ONLY}" == "1" ]; then
	for x in "server" "x11"; do
		rm -fr "$LIBDIR/python/xpra/$x"
	done
fi

if [ "${DO_X11}" == "1" ]; then
	for cmd in "Xvfb" "glxgears" "glxinfo" "oclock" "setxkbmap" "uxterm" "xauth" "xcalc" "xclock" "xdpyinfo" "xev" "xeyes" "xhost" "xkill" "xload" "xlsclients" "xmodmap" "xprop" "xrandr" "xrdb" "xset" "xterm" "xwininfo"; do
		cp "/opt/X11/bin/${cmd}" "${RSCDIR}/bin/"
	done
	for lib in "libGL" "libICE" "libOSMesa" "libX11" "libXRes" "libXau" "libXaw" "libXcomposite" "libXcursor" "libXdamage" "libXext" "libXfixes" "libXfont" "libXpm" "libXpresent" "libXrandr" "libXrender" "libXt" "libXtst" "libxkbfile" "libxshmfence"; do
		cp "/opt/X11/lib/${lib}".* "${RSCDIR}/lib/"
	done
	cp -r "/opt/X11/lib/dri" "${RSCDIR}/lib/"
fi

echo
echo "*******************************************************************************"
echo "Ship default config files"
#the build / install step should have placed them here:
rsync -rplogtv ../../build/etc/xpra ${RSCDIR}/etc/
if [ "${CLIENT_ONLY}" == "0" ]; then
	#add the launch agent file
	mkdir ${RSCDIR}/LaunchAgents
	cp ./org.xpra.Agent.plist ${RSCDIR}/LaunchAgents/
fi


echo
echo "*******************************************************************************"
echo "Xpra_NoDock: same app contents but without a dock icon"
SUB_APP_NAME="Xpra_NoDock.app"
SUB_APP="${APP_DIR}/Contents/${SUB_APP_NAME}"
rsync -rpltog "${SUB_APP_NAME}" "${APP_DIR}/Contents/"
ln -sf ../../Frameworks "${SUB_APP}/Contents/Frameworks"
ln -sf ../../Resources "${SUB_APP}/Contents/Resources"
ln -sf ../../MacOS "${SUB_APP}/Contents/MacOS"
ln -sf ../../Helpers "${SUB_APP}/Contents/Helpers"


echo
echo "*******************************************************************************"
echo "Hacks"
echo " * macos notifications API look for Info.plist in the wrong place"
cp ${CONTENTS_DIR}/Info.plist ${RSCDIR}/bin/
#no idea why I have to do this by hand
echo " * add all OpenGL"
rsync -rpl "${SITELIB}/OpenGL"* "${LIBDIR}/python/"
if [ "$STRIP_OPENGL" == "1" ]; then
	#then remove what we know we don't need:
	pushd "${LIBDIR}/python/OpenGL" || exit 1
	for x in GLE Tk EGL GLES3 GLUT WGL GLX GLES1 GLES2; do
		rm -fr ./$x
		rm -fr ./raw/$x
	done
	popd || exit 1
fi
pushd "${LIBDIR}/python" || exit 1
echo " * zipping OpenGL"
zip --move -q -r site-packages.zip OpenGL
popd || exit 1
echo " * add gobject-introspection (py2app refuses to do it)"
rsync -rpl "${SITELIB}/gi" "${LIBDIR}/python/"
mkdir "${LIBDIR}/girepository-1.0"
GI_MODULES="Gst GObject GLib GModule Gtk Gdk GtkosxApplication HarfBuzz GL Gio Pango freetype2 cairo Atk"
for t in ${GI_MODULES}; do
	rsync -rpl "${JHBUILD_PREFIX}/lib/girepository-1.0/$t"*typelib "${LIBDIR}/girepository-1.0/"
done
echo " * add Adwaita theme"
#gtk-mac-bundler doesn't do it properly, so do it ourselves:
rsync -rpl "${JHBUILD_PREFIX}/share/icons/Adwaita" "${RSCDIR}/share/icons/"
echo " * move GTK css"
mv "${RSCDIR}/share/xpra/css" "${RSCDIR}/"
#unused py2app scripts:
rm "${RSCDIR}/__boot__.py" "${RSCDIR}/__error__.sh"
echo " * fixup pixbuf loader"
#executable_path is now automatically inserted?
sed -i '' -e "s+@executable_path/++g" "${RSCDIR}/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache"

echo " * docs"
if [ -d "${JHBUILD_PREFIX}/share/doc/xpra" ]; then
	mkdir -p "${RSCDIR}/share/doc/xpra"
	rsync -rplogt "${JHBUILD_PREFIX}/share/doc/xpra/"* "${RSCDIR}/share/doc/xpra/"
fi

if [ "$STRIP_SOURCE" == "1" ]; then
	echo "removing py if we have the pyc:"
	#only remove ".py" source if we have a binary ".pyc" for it:
	for x in `find $LIBDIR -name "*.py" -type f`; do
		d="$(dirname $x)"
		f="$(basename $x)"
		if [ -r "$d/${f}c" ]; then
			#echo "* $x"
			rm "${x}"
		fi
	done
fi
#always strip the cython html reports:
echo "removing html cython report"
find $LIBDIR/python/xpra/ -name "*.html" -exec rm {} \;


#gst bits expect to find dylibs in Frameworks!?
pushd "${CONTENTS_DIR}" || exit 1
mv Resources/lib Frameworks
ln -sf ../Frameworks Resources/lib
pushd "Resources/lib" || exit 1
if [ "$STRIP_GSTREAMER_PLUGINS" == "1" ]; then
	echo "removing extra gstreamer dylib deps:"
	for x in check photography; do
		echo "* removing "$x
		rm libgst${x}*
	done
fi
echo "removing extra gstreamer plugins:"
echo " * GStreamer"
GST_PLUGIN_DIR="./gstreamer-1.0"
if [ "$STRIP_GSTREAMER_PLUGINS" == "1" ]; then
	KEEP="./gstreamer-1.0.keep"
	mkdir ${KEEP}
	PLUGINS="app audio coreelements cutter removesilence faac faad flac oss osxaudio speex volume vorbis wav lame opus ogg gdp isomp4 matroska"
	#video sink for testing:
	PLUGINS="${PLUGINS} autodetect osxvideo"
	if [ "${GSTREAMER_VIDEO}" == "1" ]; then
		#video support:
		PLUGINS="${PLUGINS} vpx x264 aom openh264 videoconvert videorate videoscale libav"
	fi
	for x in $PLUGINS; do
		echo "* keeping "$x
		mv "${GST_PLUGIN_DIR}/libgst${x}"* "${KEEP}/"
	done
	rm -fr "${GST_PLUGIN_DIR}"
	mv ${KEEP} "${GST_PLUGIN_DIR}"
fi
echo -n "GStreamer plugins shipped: "
ls ${GST_PLUGIN_DIR} | xargs
popd || exit 1	#${CONTENTS_DIR}
popd || exit 1	#"Resources/lib"

echo
echo "*******************************************************************************"
echo "Add the manual in HTML format (since we cannot install the man page properly..)"
groff -mandoc -Thtml < ../../fs/share/man/man1/xpra.1 > ${RSCDIR}/share/manual.html
groff -mandoc -Thtml < ../../fs/share/man/man1/xpra_launcher.1 > ${RSCDIR}/share/launcher-manual.html


echo "*******************************************************************************"
echo "Clean unnecessary files"
pwd
ls image
#better do this last ("rsync -C" may omit some files we actually need)
find ./image -name ".svn" | xargs rm -fr
#not sure why these get bundled at all in the first place!
find ./image -name "*.la" -exec rm -f {} \;

echo "*******************************************************************************"
echo "Remove extra Pillow plugins"
pushd "${LIBDIR}/python/PIL" || exit 1
RMP=""
KMP=""
for file_name in `ls *Image*`; do
	plugin_name=`echo $file_name | sed 's+\.py.*++g'`
		echo "$file_name" | egrep "Bmp|Ico|Image.py|ImageChops|ImageCms|ImageChops|ImageColor|ImageDraw|ImageFile|ImageFilter|ImageFont|ImageGrab|ImageMode|ImageOps|ImagePalette|ImagePath|ImageSequence|ImageStat|ImageTransform|Jpeg|Tiff|Png|Ppm|Xpm|WebP" >& /dev/null
	if [ "$?" == "0" ]; then
		KMP="${KMP} $plugin_name"
	else
		RMP="${RMP} $plugin_name"
		rm $file_name
	fi
done
echo " removed: ${RMP}"
echo " kept: ${KMP}"
popd || exit 1

echo
echo "*******************************************************************************"
echo "De-duplicate dylibs"
pushd "${LIBDIR}" || exit 1
for x in `ls *dylib | grep -v libgst | sed 's+[0-9\.]*\.dylib++g' | sed 's+-$++g' | sort -u`; do
	COUNT=`ls *dylib | grep $x | wc -l`
	if [ "${COUNT}" -gt "1" ]; then
		FIRST=`ls $x* | sort -n | head -n 1`
		for f in `ls $x* | grep -v $FIRST`; do
			cmp -s $f $FIRST
			if [ "$?" == "0" ]; then
				echo "(re)symlinking $f to $FIRST"
				rm $f
				ln -sf $FIRST $f
			fi
		done
	fi
done
#gstreamer dylibs are easier
#all of them look like this: libgstXYZ-1.0.0.dylib / libgstXYZ-1.0.dylib
for x in `ls libgst*-1.0.0.dylib`; do
	SHORT="`echo $x | sed 's/1.0.0/1.0/g'`"
	cmp -s "$x" "$SHORT"
	if [ "$?" == "0" ]; then
		echo "(re)symlinking $SHORT to $x"
		rm $SHORT
		ln -sf $x $SHORT
	fi
done
popd


echo
echo "*******************************************************************************"
echo "copying application image to Desktop"
rsync --delete -rplogt "${APP_DIR}" ~/Desktop/
echo

# restore files we modified:
git checkout "./Info.plist" "./Xpra_NoDock.app/Contents/Info.plist" >& /dev/null
