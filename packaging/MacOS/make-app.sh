#!/bin/bash

if [ -z "${JHBUILD_PREFIX}" ]; then
	echo "JHBUILD_PREFIX is not set"
	echo "this script must be executed from jhbuild shell"
	exit 1
fi

export PYTHON="python3"
PYTHON_MAJOR_VERSION=`$PYTHON -c 'import sys;sys.stdout.write("%s" % sys.version_info[0])'`
PYTHON_MINOR_VERSION=`$PYTHON -c 'import sys;sys.stdout.write("%s" % sys.version_info[1])'`

echo "Building Xpra for Python ${PYTHON_MAJOR_VERSION}.${PYTHON_MINOR_VERSION}"

STRIP_DEFAULT="${STRIP_DEFAULT:=1}"
STRIP_GSTREAMER_PLUGINS="${STRIP_GSTREAMER_PLUGINS:=$STRIP_DEFAULT}"
STRIP_SOURCE="${STRIP_SOURCE:=0}"
STRIP_OPENGL="${STRIP_OPENGL:=$STRIP_DEFAULT}"
CLIENT_ONLY="${CLIENT_ONLY:=0}"
ARCH="${ARCH:=`arch`}"
if [ "${ARCH}" == "i386" ]; then
  ARCH="x86_64"
fi

DO_TESTS="${DO_TESTS:-0}"

BUILDNO="${BUILDNO:="0"}"
APP_DIR="./image/Xpra.app"
if [ "${CLIENT_ONLY}" == "1" ]; then
	APP_DIR="./image/Xpra-Client.app"
	BUILD_ARGS="${BUILD_ARGS} --without-server --without-shadow --without-proxy"
	DO_TESTS="0"
else
	if [ ! -e "${JHBUILD_PREFIX}/share/xpra/www/" ]; then
		echo "the xpra html5 client must be installed in ${JHBUILD_PREFIX}/share/xpra/www/"
		exit 1
	fi
fi
pandoc -v >& /dev/null
if [ "$?" != "0" ]; then
	echo "pandoc not found, not building HTML documentation"
	BUILD_ARGS="${BUILD_ARGS} --without-docs"
fi
CONTENTS_DIR="${APP_DIR}/Contents"
MACOS_DIR="${CONTENTS_DIR}/MacOS"
RSCDIR="${CONTENTS_DIR}/Resources"
HELPERS_DIR="${CONTENTS_DIR}/Helpers"
LIBDIR="${RSCDIR}/lib"


echo "*******************************************************************************"
echo "Deleting existing xpra modules and temporary directories"
PYTHON_PREFIX=`python3-config --prefix`
PYTHON_PACKAGES=`ls -d ${PYTHON_PREFIX}/lib/python3*/site-packages | sort | tail -n 1`
rm -fr "${PYTHON_PACKAGES}/xpra"*
rm -fr image/* dist
ln -sf ../../dist ./dist
rm -fr "$PYTHON_PACKAGES/xpra"

echo
echo "*******************************************************************************"
echo "Building and installing locally"
pushd ../../

rm -f xpra/src_info.py xpra/build_info.py
${PYTHON} "./fs/bin/add_build_info.py" "src" "build"
rm -fr build/* dist/*
${PYTHON} ./setup.py clean
NPROC=`sysctl -n hw.logicalcpu`
echo "found $NPROC logical CPUs"
BUILD_EXT_LOG=`pwd`/build_ext.log
echo "./setup.py build_ext ${BUILD_ARGS}" -j $NPROC
echo " (see ${BUILD_EXT_LOG} for details - this may take a minute or two)"
${PYTHON} ./setup.py build_ext ${BUILD_ARGS} -j $NPROC >& ${BUILD_EXT_LOG}
if [ "$?" != "0" ]; then
	popd
	echo "ERROR: build_ext failed"
	echo
	tail -n 20 ${BUILD_EXT_LOG}
	exit 1
fi
INSTALL_LOG=`pwd`/install.log
echo "./setup.py install ${BUILD_ARGS}"
echo " (see ${INSTALL_LOG} for details)"
${PYTHON} ./setup.py install ${BUILD_ARGS} >& ${INSTALL_LOG}
if [ "$?" != "0" ]; then
	popd
	echo "ERROR: install failed"
	echo
	tail -n 20 ${INSTALL_LOG}
	exit 1
fi
#get the version and build info from the python build records:
export PYTHONPATH="."
VERSION=`${PYTHON} -c "from xpra import __version__;import sys;sys.stdout.write(__version__)"`
REVISION=`${PYTHON} -c "from xpra import src_info;import sys;sys.stdout.write(str(src_info.REVISION))"`
REV_MOD=`${PYTHON} -c "from xpra import src_info;import sys;sys.stdout.write(['','M'][src_info.LOCAL_MODIFICATIONS>0])"`
echo "OK"

if [ "${DO_TESTS}" == "1" ]; then
	pushd ./unittests
	rm -fr ./tmpdir
	mkdir ./tmpdir
	#make sure the unit tests can run "python3 xpra ...":
	rm -f ./xpra >& /dev/null
	ln -sf ../fs/bin/xpra .
	UNITTEST_LOG=`pwd`/unittest.log
	echo "running unit tests (see ${UNITTEST_LOG} - this may take a minute or two)"
	TMPDIR=./tmpdir XPRA_COMMAND="$PYTHON ./xpra" XPRA_NODOCK_COMMAND="$PYTHON ./xpra" XPRA_SOUND_COMMAND="$PYTHON ./xpra" PYTHONPATH=. ./unit/run.py >& ${UNITTEST_LOG}
	if [ "$?" != "0" ]; then
		rm -fr ./tmpdir
		popd
		echo "ERROR: unit tests failed, see ${UNITTEST_LOG}:"
		tail -n 20 ${UNITTEST_LOG}
		exit 1
	else
		rm -fr ./tmpdir
		echo "OK"
	fi
	popd
fi

echo
echo "*******************************************************************************"
echo "py2app step:"
PY2APP_LOG=`pwd`/py2app.log
echo "./setup.py py2app ${BUILD_ARGS}"
echo " (see ${PY2APP_LOG} for details - this may take a minute or two)"
${PYTHON} ./setup.py py2app ${BUILD_ARGS} >& ${PY2APP_LOG}
if [ "$?" != "0" ]; then
	echo "ERROR: py2app failed"
	echo
	tail -n 20 ${PY2APP_LOG}
	exit 1
fi
echo "py2app forgets AVFoundation, do it by hand:"
rsync -rplogt ${JHBUILD_PREFIX}/lib/python3.${PYTHON_MINOR_VERSION}/site-packages/AVFoundation ./dist/xpra.app/Contents/Resources/lib/python3.${PYTHON_MINOR_VERSION}/
echo "fixup pkg_resources.py2_warn, gi, cffi: force include the whole packages"
for m in pkg_resources gi cffi; do
	mpath=`python3 -c "import os;import $m;print(os.path.dirname($m.__file__))"`
	cp -r $mpath ./dist/xpra.app/Contents/Resources/lib/python3.${PYTHON_MINOR_VERSION}/
done
mpath=`python3 -c "import _cffi_backend;print(_cffi_backend.__file__)"`
cp $mpath ./dist/xpra.app/Contents/Resources/lib/python3.${PYTHON_MINOR_VERSION}/lib-dynload/

echo "OK"
popd
echo "py2app forgets uvloop._noop"
UVLOOPDIR="./dist/xpra.app/Contents/Resources/lib/python3.${PYTHON_MINOR_VERSION}/uvloop/"
mkdir ${UVLOOPDIR}
cp ${JHBUILD_PREFIX}/lib/python3.${PYTHON_MINOR_VERSION}/site-packages/uvloop/_noop.py ${UVLOOPDIR}/

echo
echo "*******************************************************************************"
echo "Fixing permissions on libpython dylib"
if [ ! -z "${JHBUILD_PREFIX}" ]; then
	chmod 755 "${JHBUILD_PREFIX}/lib/"libpython*.dylib
fi
#avoid error if there is no /etc/pango:
#(which seems to be the case with newer builds)
if [ ! -d "${JHBUILD_PREFIX}/etc/pango" ]; then
	mkdir "${JHBUILD_PREFIX}/etc/pango"
fi

echo
echo "*******************************************************************************"
echo "modifying Info.plist files with:"
echo " VERSION=\"${VERSION}\" REVISION=\"${REVISION}${REV_MOD}\""
echo " BUILDNO=\"${BUILDNO}\" ARCH=\"{$ARCH}\""
for plist in "./Info.plist" "./Xpra_NoDock.app/Contents/Info.plist"; do
  echo "modifying $plist"
  git checkout $plist
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
echo "*******************************************************************************"
echo "calling 'gtk-mac-bundler Xpra.bundle' in `pwd`"
if [ ! -e "JHBUILD_PREFIX}/lib/charset.alias" ]; then
	#gtk-mac-bundler chokes if this file is missing
	touch "${JHBUILD_PREFIX}/lib/charset.alias"
fi
if [ ! -e "JHBUILD_PREFIX}/share/icons/hicolor/index.theme" ]; then
	#gtk-mac-bundler chokes if this file is missing
	touch "${JHBUILD_PREFIX}/share/icons/hicolor/index.theme"
fi
gtk-mac-bundler Xpra.bundle
if [ "$?" != "0" ]; then
	echo "ERROR: gtk-mac-bundler failed"
	exit 1
fi

echo
echo "*******************************************************************************"
echo "make python softlink without version number"
pushd ${LIBDIR} || exit 1
ln -sf python3.${PYTHON_MINOR_VERSION} python
cd python
echo "unzip site-packages"
if [ -e "site-packages.zip" ]; then
	unzip -nq site-packages.zip
	rm site-packages.zip
fi
if [ -e "../python3${PYTHON_MINOR_VERSION}.zip" ]; then
	unzip -nq ../python3${PYTHON_MINOR_VERSION}.zip
	rm ../python3${PYTHON_MINOR_VERSION}.zip
fi
popd

echo
echo "*******************************************************************************"
echo "Add xpra/server/python scripts"
rsync -pltv ./Helpers/* "${HELPERS_DIR}/"
#we dont need the wrappers that may have been installed by distutils:
rm -f ${MACOS_DIR}/*bin

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
# dyld: Library not loaded: @executable_path/../Resources/lib/libgstreamer-1.0.0.dylib
pushd $RSCDIR/libexec
ln -sf ../../Resources ./Resources
popd
#fix for:
# /Applications/Xpra.app/Contents/Resources/bin/../Resources/lib/gdk-pixbuf-2.0/2.10.0/loaders/libpixbufloader-svg.so
pushd $RSCDIR
ln -sf ../Resources ./Resources
popd

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

echo
echo "*******************************************************************************"
echo "include all xpra modules found: "
find $PYTHON_PACKAGES/xpra/* -type d -maxdepth 0 -exec basename {} \;
rsync -rpl $PYTHON_PACKAGES/xpra/* $LIBDIR/python/xpra/
echo "removing files that should not be installed in the first place (..)"
for x in "*.html" "*.c" "*.cpp" "*.pyx" "*.pxd" "constants.pxi" "constants.txt"; do
	echo "removing $x:"
	find $LIBDIR/python/xpra/ -name "$x" -print -exec rm "{}" \; | sed "s+$LIBDIR/python/xpra/++g" | xargs -L 1 echo "* "
done
#should be redundant:
if [ "${CLIENT_ONLY}" == "1" ]; then
	for x in "server" "x11"; do
		rm -fr "$LIBDIR/python/xpra/$x"
	done
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
for app in Xpra_NoDock.app; do
	SUB_APP="${APP_DIR}/Contents/${app}"
	rsync -rplvtog ${app} ${APP_DIR}/Contents/
	ln -sf ../../Resources ${SUB_APP}/Contents/Resources
	ln -sf ../../MacOS ${SUB_APP}/Contents/MacOS
	ln -sf ../../Helpers ${SUB_APP}/Contents/Helpers
done


echo
echo "*******************************************************************************"
echo "Hacks"
echo " * macos notifications API look for Info.plist in the wrong place"
cp ${CONTENTS_DIR}/Info.plist ${RSCDIR}/bin/
#no idea why I have to do this by hand
echo " * add all OpenGL"
rsync -rpl $PYTHON_PACKAGES/OpenGL* $LIBDIR/python/
if [ "$STRIP_OPENGL" == "1" ]; then
	#then remove what we know we don't need:
	pushd $LIBDIR/python/OpenGL
	for x in GLE Tk EGL GLES3 GLUT WGL GLX GLES1 GLES2; do
		rm -fr ./$x
		rm -fr ./raw/$x
	done
	popd
fi
pushd $LIBDIR/python
echo " * zipping OpenGL"
zip --move -q -r site-packages.zip OpenGL
popd
echo " * add gobject-introspection (py2app refuses to do it)"
rsync -rpl $PYTHON_PACKAGES/gi $LIBDIR/python/
mkdir $LIBDIR/girepository-1.0
GI_MODULES="Gst GObject GLib GModule Gtk Gdk GtkosxApplication HarfBuzz GL Gio Pango freetype2 cairo Atk"
for t in ${GI_MODULES}; do
	rsync -rpl ${JHBUILD_PREFIX}/lib/girepository-1.0/$t*typelib $LIBDIR/girepository-1.0/
done
echo " * add Adwaita theme"
#gtk-mac-bundler doesn't do it properly, so do it ourselves:
rsync -rpl ${JHBUILD_PREFIX}/share/icons/Adwaita ${RSCDIR}/share/icons/
echo " * move GTK css"
mv ${RSCDIR}/share/xpra/css ${RSCDIR}/
#unused py2app scripts:
rm ${RSCDIR}/__boot__.py ${RSCDIR}/__error__.sh
echo " * fixup pixbuf loader"
#executable_path is now automatically inserted?
sed -i '' -e "s+@executable_path/++g" "${RSCDIR}/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache"

echo " * docs"
if [ -d "${JHBUILD_PREFIX}/share/doc/xpra" ]; then
	mkdir -p ${RSCDIR}/share/doc/xpra
	rsync -rplogt ${JHBUILD_PREFIX}/share/doc/xpra/* ${RSCDIR}/share/doc/xpra/
fi

if [ "$STRIP_SOURCE" == "1" ]; then
	echo "removing py if we have the pyc:"
	#only remove ".py" source if we have a binary ".pyc" for it:
	for x in `find $LIBDIR -name "*.py" -type f`; do
		d="`dirname $x`"
		f="`basename $x`"
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
pushd ${CONTENTS_DIR}
ln -sf Resources/lib Frameworks
pushd Resources/lib
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
	PLUGINS="app audio coreelements cutter removesilence faac faad flac oss osxaudio speex volume vorbis wav lame opus ogg gdp isomp4 matroska videoconvert x264 vpx"
	#video sink for testing:
	PLUGINS="${PLUGINS} autodetect osxvideo"
	#video support:
	PLUGINS="${PLUGINS} vpx x264 aom openh264 videoconvert videorate videoscale libav"
	for x in $PLUGINS; do
		echo "* keeping "$x
		mv ${GST_PLUGIN_DIR}/libgst${x}* ${KEEP}/
	done
	rm -fr ${GST_PLUGIN_DIR}
	mv ${KEEP} ${GST_PLUGIN_DIR}
fi
echo -n "GStreamer plugins shipped: "
ls ${GST_PLUGIN_DIR} | xargs
popd	#${CONTENTS_DIR}
popd	#"Resources/lib"

echo
echo "*******************************************************************************"
echo "Add the manual in HTML format (since we cannot install the man page properly..)"
groff -mandoc -Thtml < ../../fs/share/man/man1/xpra.1 > ${RSCDIR}/share/manual.html
groff -mandoc -Thtml < ../../fs/share/man/man1/xpra_launcher.1 > ${RSCDIR}/share/launcher-manual.html

echo
echo "*******************************************************************************"
echo "adding version \"$VERSION\" and revision \"$REVISION$REV_MOD\" to Info.plist files"
sed -i '' -e "s+%VERSION%+$VERSION+g" "${CONTENTS_DIR}/Xpra_NoDock.app/Contents/Info.plist"
sed -i '' -e "s+%REVISION%+$REVISION$REV_MOD+g" "${CONTENTS_DIR}/Xpra_NoDock.app/Contents/Info.plist"
sed -i '' -e "s+%BUILDNO%+$BUILDNO+g" "${CONTENTS_DIR}/Xpra_NoDock.app/Contents/Info.plist"
if [ "${CLIENT_ONLY}" == "1" ]; then
	sed -i '' -e "s+Xpra+Xpra-Client+g" "${CONTENTS_DIR}/Xpra_NoDock.app/Contents/Info.plist"
	sed -i '' -e "s+org.xpra.xpra+org.xpra.xpra-client+g" "${CONTENTS_DIR}/Xpra_NoDock.app/Contents/Info.plist"
fi

echo
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
pushd $LIBDIR/python/PIL
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
popd

echo
echo "*******************************************************************************"
echo "De-duplicate dylibs"
pushd $LIBDIR
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
echo "Done"
echo "*******************************************************************************"
echo

# restore files we modified:
git checkout "./Info.plist" "./Xpra_NoDock.app/Contents/Info.plist"
