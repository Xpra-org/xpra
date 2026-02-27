#!/bin/bash

if [ -z "${JHBUILD_PREFIX}" ]; then
	echo "JHBUILD_PREFIX is not set"
	echo "this script must be executed from jhbuild shell"
	exit 1
fi

MACOS_SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
XPRA_SRC_DIR=$(dirname "$(dirname "${MACOS_SCRIPT_DIR}")")
LOG_DIR="${MACOS_SCRIPT_DIR}/logs"

export PYTHON="${PYTHON:-${JHBUILD_PREFIX}/bin/python3}"
PYTHON_MAJOR_VERSION=$($PYTHON -c 'import sys;sys.stdout.write("%s" % sys.version_info[0])')
PYTHON_MINOR_VERSION=$($PYTHON -c 'import sys;sys.stdout.write("%s" % sys.version_info[1])')
SITELIB="${JHBUILD_PREFIX}/lib/python3.${PYTHON_MINOR_VERSION}/site-packages/"

STRIP_DEFAULT="${STRIP_DEFAULT:=1}"
STRIP_GSTREAMER="${STRIP_GSTREAMER:=$STRIP_DEFAULT}"
STRIP_GSTREAMER_PLUGINS="${STRIP_GSTREAMER_PLUGINS:=$STRIP_GSTREAMER}"
GSTREAMER_VIDEO="${GSTREAMER_VIDEO:=0}"
STRIP_SOURCE="${STRIP_SOURCE:=0}"
STRIP_OPENGL="${STRIP_OPENGL:=$STRIP_DEFAULT}"
CLIENT_ONLY="${CLIENT_ONLY:=0}"
ARCH="${ARCH:=$(arch)}"
if [ "${ARCH}" == "i386" ]; then
	ARCH="x86_64"
fi
NPROC=$(sysctl -n hw.logicalcpu)

DO_TESTS="${DO_TESTS:-0}"
if [ -z "${DO_X11}" ]; then
  # detect:
  DO_X11="0"
	if [ -d "/opt/X11" ]; then
		DO_X11="1"
	fi
fi

BUILDNO="${BUILDNO:="0"}"
APP_DIR="${MACOS_SCRIPT_DIR}/image/Xpra.app"
if [ "${GSTREAMER_VIDEO}" == "1" ]; then
	BUILD_ARGS="${BUILD_ARGS} --with-gstreamer_video"
else
	BUILD_ARGS="${BUILD_ARGS} --without-gstreamer_video"
fi
if [ "${CLIENT_ONLY}" == "1" ]; then
	APP_DIR="${MACOS_SCRIPT_DIR}/image/Xpra-Client.app"
	BUILD_ARGS="${BUILD_ARGS} --without-server --without-shadow --without-proxy"
	DO_TESTS="0"
	DO_X11="0"
else
	if [ ! -e "${JHBUILD_PREFIX}/share/xpra/www/" ]; then
		echo "the xpra html5 client must be installed in ${JHBUILD_PREFIX}/share/xpra/www/"
		exit 1
	fi
fi
if [ "${DO_X11}" == "1" ]; then
  BUILD_ARGS="${BUILD_ARGS} --with-x11 --pkg-config-path=/opt/X11/lib/pkgconfig --pkg-config-path=/opt/X11/share/pkgconfig"
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
echo "- log directory"
rm -f "${LOG_DIR}/"*.log
rmdir "${LOG_DIR}" 2> /dev/null
mkdir "${LOG_DIR}" || exit 1
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

echo "- ~/Desktop/Xpra.app"
rm -fr "${HOME}/Desktop/Xpra.app"

echo "- clean subcommand"
cd "${XPRA_SRC_DIR}" || exit 1
CLEAN_LOG="${LOG_DIR}/clean.log"
"${PYTHON}" ./setup.py clean >& "${CLEAN_LOG}"
log_error "clean" "${CLEAN_LOG}"

echo "- restore Info.plist files"
cd "${MACOS_SCRIPT_DIR}" || exit 1
git checkout "./Info.plist" "./Xpra_NoDock.app/Contents/Info.plist" >& /dev/null


echo "*******************************************************************************"
PYVERSIONSTR="${PYTHON_MAJOR_VERSION}.${PYTHON_MINOR_VERSION}"
echo "Building Xpra for Python ${PYVERSIONSTR} using $NPROC logical CPUs"
cd "${XPRA_SRC_DIR}" || exit 1
echo "- regenerate source and build info"
rm -f "xpra/src_info.py" "xpra/build_info.py"
BUILD_INFO_LOG="${LOG_DIR}/build_info.log"
"${PYTHON}" "./fs/bin/add_build_info.py" "src" "build" >& "${BUILD_INFO_LOG}"
log_error "add_build_info" "${BUILD_INFO_LOG}"
VERSION=$(PYTHONPATH="." "${PYTHON}" -c "from xpra import __version__;import sys;sys.stdout.write(__version__)")
REVISION=$(PYTHONPATH="." "${PYTHON}" -c "from xpra import src_info;import sys;sys.stdout.write(str(src_info.REVISION))")
REV_MOD=$(PYTHONPATH="." "${PYTHON}" -c "from xpra import src_info;import sys;sys.stdout.write(['','M'][src_info.LOCAL_MODIFICATIONS>0])")
echo "- version ${VERSION}-${REVISION}${REV_MOD}"

echo -n "- updating metadata:"
for info_plist in "Info.plist" "Xpra_NoDock.app/Contents/Info.plist"; do
	echo -n " $info_plist"
	plist="${MACOS_SCRIPT_DIR}/${info_plist}"
	git checkout "${plist}" >& /dev/null
	sed -i '' -e "s+%VERSION%+$VERSION+g" "${plist}"
	sed -i '' -e "s+%REVISION%+$REVISION$REV_MOD+g" "${plist}"
	sed -i '' -e "s+%BUILDNO%+$BUILDNO+g" "${plist}"
	sed -i '' -e "s+%ARCH%+$ARCH+g" "${plist}"
	if [ "${CLIENT_ONLY}" == "1" ]; then
		sed -i '' -e "s+Xpra+Xpra-Client+g" "${plist}"
		sed -i '' -e "s+org.xpra.xpra+org.xpra.xpra-client+g" "${plist}"
	fi
done
echo

cd "${XPRA_SRC_DIR}" || exit 1
BUILD_EXT_LOG="${LOG_DIR}/build_ext.log"
echo "- build extensions"
echo "./setup.py build_ext ${BUILD_ARGS}" -j $NPROC > "${BUILD_EXT_LOG}"
"${PYTHON}" ./setup.py build_ext ${BUILD_ARGS} -j $NPROC >> "${BUILD_EXT_LOG}" 2>&1
log_error "build_ext" "${BUILD_EXT_LOG}"

INSTALL_LOG="${LOG_DIR}/install.log"
echo "- install locally"
echo "./setup.py install ${BUILD_ARGS}" > "${INSTALL_LOG}"
"${PYTHON}" ./setup.py install ${BUILD_ARGS} >> "${INSTALL_LOG}" 2>&1
log_error "install" "${INSTALL_LOG}"

if [ "${DO_TESTS}" == "1" ]; then
	cd "${XPRA_SRC_DIR}/unittests" || exit 1
	rm -fr ./tmpdir && mkdir ./tmpdir || exit 1
	#make sure the unit tests can run "python3 xpra ...":
	rm -f "./xpra" >& /dev/null
	ln -sf "../fs/bin/xpra" .
	UNITTEST_LOG="${LOG_DIR}/unittest.log"
	echo "- run unit tests (see ${UNITTEST_LOG} - this may take a while)"
	TMPDIR=./tmpdir XPRA_COMMAND="$PYTHON ./xpra" XPRA_NODOCK_COMMAND="$PYTHON ./xpra" XPRA_SOUND_COMMAND="$PYTHON ./xpra" PYTHONPATH=. ./unit/run.py >& "${UNITTEST_LOG}"
	log_error unittests "${UNITTEST_LOG}"
  rm -fr ./tmpdir
  echo "OK"
fi


echo "*******************************************************************************"
cd "${XPRA_SRC_DIR}" || exit 1
echo "Creating app bundle"
PY2APP_LOG="${LOG_DIR}/py2app.log"
echo "- py2app"
echo "XPRA_GI_BLOCK=\"*\" ${PYTHON} ./setup.py py2app ${BUILD_ARGS}" > "${PY2APP_LOG}"
XPRA_GI_BLOCK="*" "${PYTHON}" ./setup.py py2app ${BUILD_ARGS} >> "${PY2APP_LOG}" 2>&1
log_error "py2app" "${PY2APP_LOG}"

echo "- gtk-mac-bundler"
cd "${MACOS_SCRIPT_DIR}" || exit 1
BUNDLER_LOG="${LOG_DIR}/gtk-mac-bundler.log"
gtk-mac-bundler Xpra.bundle >& "${BUNDLER_LOG}"
log_error "gtk-mac-bundler" "${BUNDLER_LOG}"

# restore files we modified:
git checkout "./Info.plist" "./Xpra_NoDock.app/Contents/Info.plist" >& /dev/null

# from here on, these directories should exist:
CONTENTS_DIR="${APP_DIR}/Contents"
MACOS_DIR="${CONTENTS_DIR}/MacOS"
FRAMEWORKS_DIR="${CONTENTS_DIR}/Frameworks"
RSCDIR="${CONTENTS_DIR}/Resources"
HELPERS_DIR="${CONTENTS_DIR}/Helpers"
LIBDIR="${RSCDIR}/lib"

echo "- dylibs and bin/ to Frameworks/"
mv "${RSCDIR}/lib/"*dylib "${FRAMEWORKS_DIR}/"
rm -fr "${RSCDIR}/lib/cairo"
mv "${RSCDIR}/bin/"* "${FRAMEWORKS_DIR}/bin/"

echo "*******************************************************************************"
echo "Python"
PYZIP="${RSCDIR}/lib/python3${PYTHON_MINOR_VERSION}.zip"
if [ -e "${PYZIP}" ]; then
  echo "- unzip $(basename ${PYZIP})"
  cd "${RSCDIR}/lib/python3.${PYTHON_MINOR_VERSION}" || exit 1
	unzip -nq "${PYZIP}"
	rm "${PYZIP}"
fi
echo "- symlink"
PYDIR="${RSCDIR}/lib/python"
ln -sf "python3.${PYTHON_MINOR_VERSION}" "${PYDIR}"
echo "- keep lib-dynload in Frameworks"
mv "${PYDIR}/lib-dynload" "${FRAMEWORKS_DIR}/"
ln -sf "../../../Frameworks/lib-dynload" "${PYDIR}/lib-dynload"

echo "- include all xpra modules"
rsync -rplt "${SITELIB}/xpra" "${PYDIR}/"
echo "- remove other platforms"
for platform in "win32" "posix"; do
  rm -fr "${PYDIR}/xpra/platform/${platform}"
done
if [ "${CLIENT_ONLY}" == "1" ]; then
  echo "- remove server components"
	for x in "server" "x11"; do
		rm -fr "${PYDIR}/xpra/$x"
	done
fi
if [ "${GSTREAMER_VIDEO}" == "0" ]; then
	echo "- remove gstreamer video codec"
	rm -fr "${PYDIR}/xpra/codecs/gstreamer"
fi

for module in "AVFoundation" "pkg_resources" "gi" "cffi" "OpenGL"; do
  echo "- ${module}"
	rsync -rplt "${SITELIB}/${module}" "${PYDIR}/"
done
if [ "$STRIP_OPENGL" == "1" ]; then
  echo "  remove unused OpenGL modules"
	#then remove what we know we don't need:
	for x in GLE Tk EGL GLES3 GLUT WGL GLX GLES1 GLES2; do
		rm -fr "${PYDIR}/OpenGL/${x}"
		rm -fr "${PYDIR}/OpenGL/raw/${x}"
	done
fi
echo "  zipping up OpenGL"
pushd "${PYDIR}" > /dev/null || exit 1
zip --move -q -r site-packages.zip OpenGL
popd > /dev/null || exit 1

echo "- pillow plugins"
RMP=""
KMP=""
PILLOW_KEEP="Bmp|Ico|ImageChops|ImageCms|ImageChops|ImageColor|ImageDraw|ImageFile|ImageFilter|ImageFont|ImageGrab|ImageMode|ImageOps|ImagePalette|ImagePath|ImageSequence|ImageStat|ImageTransform|Jpeg|Tiff|Png|Ppm|Xpm|WebP"
pushd "${PYDIR}/PIL" > /dev/null || exit 1
for file_name in *Image*; do
	plugin_name="${file_name%.pyc}"
  if [ "${plugin_name}" = "Image" ]; then
		KMP="${KMP} $plugin_name"
  elif [[ "${plugin_name}" =~ $PILLOW_KEEP ]]; then
		KMP="${KMP} $plugin_name"
	else
		RMP="${RMP} $plugin_name"
		rm "${file_name}"
	fi
done
popd > /dev/null || exit 1
echo "  removed: ${RMP}"
echo "  kept: ${KMP}"

echo "- cffi backend"
mpath=$(PYTHONWARNINGS="ignore::UserWarning" python3 -c "import _cffi_backend;print(_cffi_backend.__file__)")
cp "${mpath}" "${PYDIR}/lib-dynload/"
echo "- uvloop"
cp "${SITELIB}/uvloop/_noop.py" "${PYDIR}/uvloop/"

echo "- add xpra/server/python helper scripts"
rsync -plt "${MACOS_SCRIPT_DIR}/Helpers/"* "${HELPERS_DIR}/"
# we dont need the wrappers that may have been installed by distutils:
rm -f "${MACOS_DIR}/*bin"
# ensure they all have a symlink to the Python interpreter for each helper
# (using the "pretty" name, converting underscores to spaces)
for helper in "${HELPERS_DIR}/"*; do
  filename=$(basename "${helper}")
  name=${filename//_/ }
  ln -sf "./Python" "${FRAMEWORKS_DIR}/bin/${name}"
done

# overwrite the "Xpra" script generated by py2app with our custom one:
cp "${MACOS_SCRIPT_DIR}/Helpers/Xpra" "${MACOS_DIR}/"
rm -f "${MACOS_DIR}/Xpra-bin" >& /dev/null
if [ "${CLIENT_ONLY}" == "1" ]; then
	rm -f "${HELPERS_DIR}/Shadow"
	rm -f "${FRAMEWORKS_DIR}/bin/Shadow"
fi

echo "- remove executable bit from python scripts"
find "${MACOS_SCRIPT_DIR}" -type f -perm +111 -name "*.py" -exec chmod -x {} \;

echo "*******************************************************************************"
echo "Add components"
echo "- icon"
cp "${MACOS_SCRIPT_DIR}/"*.icns "${RSCDIR}/"
#the build / install step should have placed them here:
echo "- config files"
rsync -rplt "${XPRA_SRC_DIR}/build/etc/xpra" "${RSCDIR}/etc/"
if [ "${CLIENT_ONLY}" == "0" ]; then
	#add the launch agent file
	mkdir "${RSCDIR}/LaunchAgents"
	cp "${MACOS_SCRIPT_DIR}/org.xpra.Agent.plist" "${RSCDIR}/LaunchAgents/"
fi

if [ "${DO_X11}" == "1" ]; then
  echo "- X11 libraries and binaries"
  mkdir "${FRAMEWORKS_DIR}/X11"
  mkdir "${FRAMEWORKS_DIR}/X11/bin"
	for cmd in "Xvfb" "glxgears" "glxinfo" "oclock" "setxkbmap" "uxterm" "xauth" "xcalc" "xclock" "xdpyinfo" "xev" "xeyes" "xhost" "xkill" "xload" "xlsclients" "xmodmap" "xprop" "xrandr" "xrdb" "xset" "xterm" "xwininfo"; do
		cp "/opt/X11/bin/${cmd}" "${FRAMEWORKS_DIR}/X11/bin"
	done
  mkdir "${FRAMEWORKS_DIR}/X11/lib"
	for lib in "libGL" "libICE" "libOSMesa" "libX11" "libXRes" "libXau" "libXaw" "libXcomposite" "libXcursor" "libXdamage" "libXext" "libXfixes" "libXfont" "libXpm" "libXpresent" "libXrandr" "libXrender" "libXt" "libXtst" "libxkbfile" "libxshmfence"; do
		rsync -rplt "/opt/X11/lib/${lib}".* "${FRAMEWORKS_DIR}/X11/lib/"
	done
  mkdir "${FRAMEWORKS_DIR}/X11/lib/dri"
	cp "/opt/X11/lib/dri/"* "${FRAMEWORKS_DIR}/X11/lib/dri/"
fi

echo "- gobject-introspection"
mkdir "${RSCDIR}/lib/girepository-1.0"
TYPELIB_DIR="${RSCDIR}/lib/girepository-1.0"
GIR_SOURCE_DIR="$JHBUILD_PREFIX/share/gir-1.0"
TEMP_GIR_DIR="${MACOS_SCRIPT_DIR}/xpra-gir-fixed-$$"
mkdir "$TEMP_GIR_DIR"
for name in Gst-1.0 GObject-2.0 GLib-2.0 GModule-2.0 Gtk-3.0 Gdk-3.0 GdkPixbuf-2.0 GtkosxApplication-1.0 HarfBuzz-0.0 GL-1.0 Gio-2.0 Pango-1.0 freetype2-2.0 cairo-1.0 Atk-1.0; do
  gir_source="$GIR_SOURCE_DIR/$name.gir"
  gir_fixed="$TEMP_GIR_DIR/$name.gir"
  sed -E 's|/[^,]*/([^/,]+\.dylib)|\1|g' "$gir_source" > "$gir_fixed"
  g-ir-compiler --includedir="$TEMP_GIR_DIR" --output="${TYPELIB_DIR}/${name}.typelib" "${gir_fixed}"
done
rm -fr "$TEMP_GIR_DIR"

echo "- Adwaita theme"
#gtk-mac-bundler doesn't do it properly, so do it ourselves:
rsync -rpl "${JHBUILD_PREFIX}/share/icons/Adwaita" "${RSCDIR}/share/icons/"

echo "- docs"
if [ -d "${JHBUILD_PREFIX}/share/doc/xpra" ]; then
	mkdir -p "${RSCDIR}/share/doc/xpra"
	rsync -rplt "${JHBUILD_PREFIX}/share/doc/xpra/"* "${RSCDIR}/share/doc/xpra/"
fi

echo "- add the manual in HTML format"
groff -mandoc -Thtml < "${XPRA_SRC_DIR}/fs/share/man/man1/xpra.1" > "${RSCDIR}/share/manual.html"
groff -mandoc -Thtml < "${XPRA_SRC_DIR}/fs/share/man/man1/xpra_launcher.1" > "${RSCDIR}/share/launcher-manual.html"

echo "*******************************************************************************"
echo "Hacks"

echo "- move GTK css"
ln -sf "share/xpra/css" "${RSCDIR}/css"

echo "- de-duplicate dylibs"
pushd "${FRAMEWORKS_DIR}" > /dev/null || exit 1
for dylib in *dylib; do
  if [[ -L "${dylib}" ]]; then
    continue
  fi
  # remove extension
  noext="${dylib%.dylib}"
  # shorten it:
  while [[ "$noext" =~ \.[0-9]+ ]]; do
    shorter="${noext%.*}"
    if [ -e "${shorter}.dylib" ]; then
        rm "${shorter}.dylib"
        ln -sf "${dylib}" "${shorter}.dylib"
    fi
    noext="${shorter}"
  done
done


function change_prefix() {
  filename="$1"
  old_prefix="$2"
  new_prefix="$3"

  # Process each line from otool -L output
  otool -L "$filename" | tail -n +2 | while IFS= read -r line; do
    # Extract the library path (first field)
    lib_path=$(echo "$line" | awk '{print $1}')

    # Check if it contains the old prefix
    if [[ $lib_path == *"$old_prefix"* ]]; then
      # Replace the prefix
      new_path="${lib_path/$old_prefix/$new_prefix}"
      install_name_tool -change "$lib_path" "$new_path" "$filename"
    fi
  done
}

# Add rpath to Python interpreter
install_name_tool -add_rpath "@executable_path/.." "${FRAMEWORKS_DIR}/bin/Python"

old_rpath="@executable_path/../Resources/lib/"
new_rpath="@executable_path/../"
echo "- fixing executable id / rpath"
echo "  Frameworks"
cd "${FRAMEWORKS_DIR}" || exit 1
for dylib in *.dylib; do
  codesign --remove-signature "${dylib}"
done
# fix "id":
for dylib in *.dylib; do
  if [[ -L "${dylib}" ]]; then
    continue
  fi
  install_name_tool -id "@loader_path/${dylib}" "${dylib}"
done
# fix rpath:
for dylib in *.dylib; do
  if [[ -L "${dylib}" ]]; then
    continue
  fi
  change_prefix "${dylib}" "${old_rpath}" "@loader_path/"
done

if [ "${DO_X11}" == "1" ]; then
  echo "  X11"
  cd "${FRAMEWORKS_DIR}/X11/bin" || exit 1
  for bin in *; do
    codesign --remove-signature "${bin}"
    change_prefix "${bin}" "/opt/X11/lib/" "@executable_path/../lib/"
  done
  cd "${FRAMEWORKS_DIR}/X11/lib" || exit 1
  for dylib in *.dylib; do
    codesign --remove-signature "${dylib}"
    change_prefix "${dylib}" "/opt/X11/lib/" "@loader_path/"
  done
fi
echo "- python interpreter"
for bin in "${FRAMEWORKS_DIR}/bin/"*; do
  codesign --remove-signature "${bin}"
  change_prefix "${bin}" "${old_rpath}" "@executable_path/../"
done
echo "- bcrypt"
BCRYPT_SO="lib-dynload/bcrypt/_bcrypt.so"
codesign --remove-signature "${PYDIR}/${BCRYPT_SO}"
install_name_tool -id "@executable_path/../Frameworks/python3.${PYTHON_MINOR_VERSION}/${BCRYPT_SO}" "${PYDIR}/${BCRYPT_SO}"
echo "- zlib"
mv "${RSCDIR}/zlib"*.so "${FRAMEWORKS_DIR}/lib-dynload/"
echo "- rpath for python shared objects"
find "${PYDIR}/" "${FRAMEWORKS_DIR}/lib-dynload/" -name "*.so" -print0 | while IFS='' read -r -d $'\0' file; do
    codesign --remove-signature "${file}"
    change_prefix "${file}" "${old_rpath}" "${new_rpath}"
    change_prefix "${file}" "${JHBUILD_PREFIX}/lib" "${new_rpath}"
    # Get all dylib dependencies
    otool -L "${file}" | grep -E "@executable_path.*\.dylib" | awk '{print $1}' | while read dep; do
      # Extract just the library name
      libname=$(basename "$dep")
      # Change to @rpath
      install_name_tool -change "$dep" "@rpath/$libname" "${file}"
    done
done
popd > /dev/null || exit 1


echo "*******************************************************************************"
echo "Cleanup"
echo "- static libaries"
#not sure why these get bundled at all in the first place!
find "${CONTENTS_DIR}" -name "*.la" -exec rm -f {} \;
echo "- header files"
rm -fr "${RSCDIR}/include"
echo "- unused scripts"
rm "${RSCDIR}/main.py" "${RSCDIR}/site.pyc"

echo "- unwanted files in python modules"
for x in "*.html" "*.c" "*.cpp" "*.pyx" "*.pxd" "constants.pxi" "constants.txt"; do
	find "${LIBDIR}/python/xpra/" -name "$x" -exec rm "{}" \;
done

if [ "$STRIP_SOURCE" == "1" ]; then
	echo "- prefer .pyc to .py"
	#only remove ".py" source if we have a binary ".pyc" for it:
	for x in "${LIBDIR}"/**/*.py; do
		d="$(dirname $x)"
		f="$(basename $x)"
		if [ -r "$d/${f}c" ]; then
			#echo "* $x"
			rm "${x}"
		fi
	done
fi

echo "- unused py2app scripts"
rm "${RSCDIR}/__boot__.py" "${RSCDIR}/__error__.sh"

if [ "$STRIP_GSTREAMER" == "1" ]; then
	echo "- extra gstreamer dylib deps"
	GST_DYLIBS="app audio base codecparsers codecs gl net pbutils reamer riff tag"
	# not sure: allocators mse play player rtp rtsp sctp sdp webrtc
	if [ "${GSTREAMER_VIDEO}" == "1" ]; then
    GST_DYLIBS="${GST_DYLIBS} mpegts stmse video"
	fi
	echo "  keeping: ${GST_DYLIBS}"
	KEEP="${FRAMEWORKS_DIR}/gst.temp"
	mkdir "${KEEP}" || exit 1
	for x in ${GST_DYLIBS}; do
		mv "${FRAMEWORKS_DIR}/libgst${x}"* "${KEEP}/"
	done
	rm -fr "${FRAMEWORKS_DIR}/libgst"*
	mv "${KEEP}/"* "${FRAMEWORKS_DIR}/"
	rm -fr "${KEEP}"
fi
KMP=""
if [ "$STRIP_GSTREAMER_PLUGINS" == "1" ]; then
  echo "- extra gstreamer plugins"
  GST_PLUGIN_DIR="${RSCDIR}/lib/gstreamer-1.0"
	KEEP="${RSCDIR}/lib/gstreamer-1.0.keep"
	mkdir "${KEEP}" || exit 1
	PLUGINS="app applemedia audioconvert audiolatency audioparsers audiorate audioresample audiotestsrc coreelements cutter faac flac gdp isomp4 matroska ogg opus opusparse oss4 osxaudio removesilence speex volume vorbis wavenc wavparse"
	if [ "${GSTREAMER_VIDEO}" == "1" ]; then
    # video sink for testing:
    PLUGINS="${PLUGINS} autodetect osxvideo"
		# video support:
		PLUGINS="${PLUGINS} vpx x264 aom openh264 videoconvert videorate videoscale libav"
	fi
	for x in $PLUGINS; do
		KMP="${KMP} $x"
		mv "${GST_PLUGIN_DIR}/libgst${x}.dylib" "${KEEP}/"
	done
	RMP="$(ls "${GST_PLUGIN_DIR}" | xargs | sed 's/libgst//g' | sed 's/.dylib//g')"
	rm -fr "${GST_PLUGIN_DIR}"
	mv "${KEEP}" "${GST_PLUGIN_DIR}"
	for x in $PLUGINS; do
	  filename="libgst${x}.dylib"
	  dylib="${GST_PLUGIN_DIR}/${filename}"
    install_name_tool -id "@loader_path/${filename}" "${dylib}"
    change_prefix "${dylib}" "${old_rpath}" "@loader_path/../../../Frameworks/"
	done
fi
echo "  removed:${RMP}"
echo "  kept:${KMP}"


echo "*******************************************************************************"
echo "Adding Xpra_NoDock app bundle"
SUB_APP_NAME="Xpra_NoDock.app"
rsync -rplt "${MACOS_SCRIPT_DIR}/${SUB_APP_NAME}" "${APP_DIR}/Contents/"
SUB_APP="${APP_DIR}/Contents/${SUB_APP_NAME}"
ln -sf "../../Frameworks" "${SUB_APP}/Contents/Frameworks"
ln -sf "../../Resources" "${SUB_APP}/Contents/Resources"
ln -sf "../../MacOS" "${SUB_APP}/Contents/MacOS"
ln -sf "../../Helpers" "${SUB_APP}/Contents/Helpers"
