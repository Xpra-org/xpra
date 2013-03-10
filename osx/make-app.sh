#!/bin/sh

echo "*******************************************************************************"
echo "Deleting existing xpra modules and temporary directories"
PYTHON_PREFIX=`python-config --prefix`
PYTHON_PACKAGES=`ls -d ${PYTHON_PREFIX}/lib/python*/site-packages`
rm -fr "${PYTHON_PACKAGES}/xpra"
rm -fr "${PYTHON_PACKAGES}/wimpiggy"
rm -fr "${PYTHON_PACKAGES}/parti"
rm -fr image/* dist/*

echo
echo "*******************************************************************************"
echo "Building and installing"
pushd ../src
./setup.py clean
./setup.py install
if [ "$?" != "0" ]; then
	echo "ERROR: install failed"
	exit 1
fi
popd
echo
echo "*******************************************************************************"
echo "pyapp"
./setup.py py2app
if [ "$?" != "0" ]; then
	echo "ERROR: py2app failed"
	exit 1
fi

IMAGE_DIR="./image/Xpra.app"
CONTENTS_DIR="${IMAGE_DIR}/Contents"
MACOS_DIR="${CONTENTS_DIR}/MacOS"
RSCDIR="${CONTENTS_DIR}/Resources"
HELPERS_DIR="${CONTENTS_DIR}/Helpers"
LIBDIR="${RSCDIR}/lib"
UNAME_ARCH=`uname -p`
ARCH="x86"
if [ "${UNAME_ARCH}" == "powerpc" ]; then
	ARCH="ppc"
fi
export ARCH

echo
echo "*******************************************************************************"
echo "Fixing permissions on file we will need to relocate"
if [ ! -z "${JHBUILD_PREFIX}" ]; then
	chmod 755 "${JHBUILD_PREFIX}/lib/"libpython*.dylib
fi

echo
echo "*******************************************************************************"
echo "calling 'gtk-mac-bundler Xpra.bundle' in `pwd`"
gtk-mac-bundler Xpra.bundle
if [ "$?" != "0" ]; then
	echo "ERROR: gtk-mac-bundler failed"
	exit 1
fi

echo
echo "*******************************************************************************"
echo "unzip site-packages and make python softlink without version number"
pushd ${LIBDIR} || exit 1
ln -sf python* python
cd python
unzip -nq site-packages.zip
rm site-packages.zip
popd

echo
echo "*******************************************************************************"
echo "moving pixbuf loaders to a place that will *always* work"
mv ${RSCDIR}/lib/gdk-pixbuf-2.0/*/loaders/* ${RSCDIR}/lib/
echo "remove now empty loaders dir"
rmdir ${RSCDIR}/lib/gdk-pixbuf-2.0/2.10.0/loaders
rmdir ${RSCDIR}/lib/gdk-pixbuf-2.0/2.10.0
rmdir ${RSCDIR}/lib/gdk-pixbuf-2.0
echo "fix gdk-pixbuf.loaders"
LOADERS="${RSCDIR}/etc/gtk-2.0/gdk-pixbuf.loaders"
sed -i -e 's+@executable_path/../Resources/lib/gdk-pixbuf-2.0/.*/loaders/++g' "${LOADERS}"

echo
echo "*******************************************************************************"
echo "Add xpra/server/python scripts"
cp ./Python "${HELPERS_DIR}/"
cp ./xpra "${HELPERS_DIR}/"
cp ./SSH_ASKPASS "${HELPERS_DIR}/"
# copy "python" as "xpra" and "Xpra_Launcher" so we can have a process that is not called "python"...
cp "${RSCDIR}/bin/python" "${RSCDIR}/bin/Xpra"
cp "${RSCDIR}/bin/python" "${RSCDIR}/bin/Xpra_Launcher"
#we dont need the wrapper installed by distutils:
rm "${MACOS_DIR}/Xpra_Launcher-bin"

# launcher needs to be in main ("MacOS" dir) since it is launched from the custom Info.plist:
cp Xpra_Launcher ${MACOS_DIR}
# Add the icon:
cp ./*.icns ${RSCDIR}/

# Add Xpra share (for icons)
rsync -rplog $XDG_DATA_DIRS/xpra/* ${RSCDIR}/share/xpra/

echo
echo "*******************************************************************************"
echo "Hacks"
#HACKS
#no idea why I have to do this by hand
#add gtk .so
rsync -rpl $PYTHON_PACKAGES/gtk-2.0/* $LIBDIR/
#add pygtk .py
PYGTK_LIBDIR="$LIBDIR/pygtk/2.0/"
rsync -rpl $PYTHON_PACKAGES/pygtk* $PYGTK_LIBDIR
rsync -rpl $PYTHON_PACKAGES/cairo $PYGTK_LIBDIR
#gst bits expect to find dylibs in Frameworks!?
pushd ${CONTENTS_DIR}
ln -sf Resources/lib Frameworks
popd

echo
echo "*******************************************************************************"
echo "Clean unnecessary files"
pwd
ls image
#better do this last ("rsync -C" may omit some files we actually need)
find ./image -name ".svn" | xargs rm -fr
#not sure why these get bundled at all in the first place!
find ./image -name "*.la" -exec rm -f {} \;

echo
echo "*******************************************************************************"
echo "copying application image to Desktop"
rsync -rplogt "${IMAGE_DIR}" ~/Desktop/
