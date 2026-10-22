#!/bin/bash

MACOS_SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
cd "${MACOS_SCRIPT_DIR}" || exit 1

PYTHON="${PYTHON:=python3}"
LIGHT="${LIGHT:=0}"
if [ "${LIGHT}" == "1" ]; then
  APP_NAME="Xpra-Light"
else
  APP_NAME="Xpra"
fi
APP_DIR="./image/${APP_NAME}.app"

echo
echo "*******************************************************************************"
if [ ! -d "${APP_DIR}" ]; then
	echo "${APP_DIR} is missing - cannot continue"
	exit 1
fi

#get the version, build info and sbom data from the python build records in the app bundle:
export PYTHONPATH="${APP_DIR}/Contents/Resources/lib/python/"
VERSION=$(${PYTHON} -c "from xpra import __version__;import sys;sys.stdout.write(__version__)")
REVISION=$(${PYTHON} -c "from xpra import src_info;import sys;sys.stdout.write(str(src_info.REVISION))")
REV_MOD=$(${PYTHON} -c "from xpra import src_info;import sys;sys.stdout.write(['','M'][src_info.LOCAL_MODIFICATIONS>0])")
BUILD_INFO="${BUILD_INFO}-$(uname -m)"

#same name as the DMG and PKG files:
SBOM_FILENAME="${APP_NAME}${BUILD_INFO}-${VERSION}-r${REVISION}${REV_MOD}.json"
rm -f "./image/${SBOM_FILENAME}" >& /dev/null
echo "Making ${SBOM_FILENAME}"

if ! ${PYTHON} -c "import cyclonedx, packageurl" >& /dev/null; then
	echo "cyclonedx is missing, cannot export the SBOM"
	echo " to install it, run:"
	echo " ${PYTHON} -m pip install cyclonedx-python-lib packageurl-python"
	exit 1
fi
if ! ${PYTHON} -c "from xpra.build_info import packages;assert packages" >& /dev/null; then
	echo "the app bundle does not contain any SBOM package data"
	echo " check the build_info.log from make-app.sh"
	exit 1
fi

${PYTHON} -W ignore::DeprecationWarning "../MSWindows/cyclonedx_sbom.py" "./image/${SBOM_FILENAME}" || exit 1
ditto "./image/${SBOM_FILENAME}" "${HOME}/Desktop/"
