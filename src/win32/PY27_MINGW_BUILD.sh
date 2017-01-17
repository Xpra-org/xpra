#!/bin/bash
# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

ARGS=$@
DO_CLEAN=0
DO_ZIP=0
DO_INSTALLER=1
RUN_INSTALLER=1
DO_MSI=0
DIST="./dist"
BUILD_OPTIONS="--without-enc_x265"


#figure out the full xpra version:
VERSION=`python2.7.exe -c "from xpra import __version__;import sys;sys.stdout.write(__version__)"`
SVN_VERSION=`svnversion`
REVISION=`python -c "x=\"$SVN_VERSION\";y=x.split(\":\");y.reverse();z=y[0];print \"\".join([c for c in z if c in \"0123456789\"])"`
FULL_VERSION=${VERSION}-r${REVISION}
EXTRA_VERSION=""
BUILD_TYPE=""
echo
echo "Xpra${EXTRA_VERSION} ${FULL_VERSION}"
echo

INSTALLER_FILENAME=Xpra${EXTRA_VERSION}${BUILD_TYPE}_Setup_${FULL_VERSION}.exe
MSI_FILENAME=Xpra${EXTRA_VERSION}${BUILD_TYPE}_Setup_${FULL_VERSION}.msi
ZIP_DIR=Xpra${EXTRA_VERSION}${BUILD_TYPE}_${FULL_VERSION}
ZIP_FILENAME=${ZIP_DIR}.zip

TORTOISESVN="/c/Program Files/TortoiseSVN"
if [ ! -e "${TORTOISESVN}" ]; then
	echo "Missing TortoiseSVN!"
	exit 1
fi


echo "* cleaning ${DIST} output directory"
rm -fr ${DIST}/*
mkdir ${DIST} >& /dev/null

if [ "${DO_CLEAN}" == "1" ]; then
	rm -fr build
fi

echo "* Building Python 2.7 Cython modules"
BUILD_LOG="win32/Python2.7-build.log"
python2.7.exe ./setup.py build_ext ${BUILD_OPTIONS} --inplace >& ${BUILD_LOG}
if [ "$?" != "0" ]; then
	echo "ERROR: build failed, see ${BUILD_LOG}:"
	tail -n 20 "${BUILD_LOG}"
	exit 1
fi

# For building Python 3.x Sound sub-app (broken because of cx_Freeze bugs)
#echo "* Building Python 3.4 Cython modules (see win32/Python2.7-build.log)"
#python2.7.exe ./setup.py build_ext ${BUILD_OPTIONS} --inplace >& win32/Python2.7-build.log

echo "* generating installation directory"
CX_FREEZE_LOG="win32/cx_freeze-install.log"
python2.7.exe ./setup.py install_exe --install=${DIST} >& ${CX_FREEZE_LOG}
if [ "$?" != "0" ]; then
	echo "ERROR: build failed, see ${CX_FREEZE_LOG}:"
	tail -n 20 "${CX_FREEZE_LOG}"
	exit 1
fi


if [ -e "${DIST}/OpenGL" ]; then
	echo "* adding PyOpenGL to library.zip"
	pushd "${DIST}" >& /dev/null
	zip -qmor "library.zip" OpenGL
	popd >& /dev/null
	#python2.7.exe win32\move_to_zip.py ${DIST}\library.zip ${DIST} OpenGL
fi

echo "* Generating HTML Manual Page"
groff.exe -mandoc -Thtml < man/xpra.1 > ${DIST}/manual.html

echo "* Adding TortoisePlink"
cp "${TORTOISESVN}/bin/TortoisePlink.exe" "${DIST}/Plink.exe"
rsync -rplogt "${TORTOISESVN}/bin/"*dll "${DIST}/"

cp ${MINGW_PREFIX}/bin/openssl.exe ${DIST}/
cp ${MINGW_PREFIX}/ssl/openssl.cnf ${DIST}/

if [ "${DO_ZIP}" == "1" ]; then
	echo "* Creating ZIP file"
	rm -fr "${ZIP_DIR}" "${ZIP_FILENAME}"
	mkdir "${ZIP_DIR}"
	rsync -rplogt "${DIST}"/* "${ZIP_DIR}"
	zip a -r "${ZIP_FILENAME}" "${ZIP_DIR}"
	ls -la "${ZIP_FILENAME}"
fi

if [ "${DO_INSTALLER}" == "1" ]; then
	INNOSETUP="/c/Program Files/Inno Setup 5/ISCC.exe"
	#INNOSETUP="c/Program Files(x86)/Inno Setup 5/ISCC.exe"
	INNOSETUP_LOG="win32/innosetup.log"
	echo "* Creating the installer using InnoSetup"
	rm -f Xpra_Setup.exe ${INSTALLER_FILENAME} ${INNOSETUP_LOG}
	cp win32/xpra.iss xpra.iss
	"${INNOSETUP}" "xpra.iss" >& "${INNOSETUP_LOG}"
	if [ "$?" != "0" ]; then
		echo "InnoSetup error - see ${INNOSETUP_LOG}"
		tail -n 20 "${INNOSETUP_LOG}"
		exit 1
	fi
	mv "Output\Xpra_Setup.exe" "${INSTALLER_FILENAME}"

	if [ "${RUN_INSTALLER}" == "1" ]; then
		echo "* Finished - running the new installer"
		"`pwd`/${INSTALLER_FILENAME}" "${ARGS}"
	fi
	ls -la "${INSTALLER_FILENAME}"
fi

if [ "${DO_MSI}" == "1" ]; then
	MSIWRAPPER="/c/Program Files/MSI Wrapper/MsiWrapper.exe"
	ZERO_PADDED_VERSION=`python2.7.exe -c 'from xpra import __version__;print(".".join((__version__.split(".")+["0","0","0"])[:4]))'`
	cat "win32\msi.xml" | sed "s/INPUT/${INSTALLER_FILENAME}/g" | sed "s/OUTPUT/${MSI_FILENAME}/g" | sed "s/ZERO_PADDED_VERSION/${ZERO_PADDED_VERSION}/g" | sed "s/FULL_VERSION/${FULL_VERSION}/g" > msi.xml
	"${MSIWRAPPER}" "msi.xml"
fi
