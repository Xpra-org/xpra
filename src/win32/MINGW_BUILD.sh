#!/bin/bash
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

ARGS=$@
DO_CLEAN=${DO_CLEAN:-0}
DO_CUDA=${DO_CUDA:-1}
DO_ZIP=${DO_ZIP:-0}
DO_INSTALLER=${DO_INSTALLER:-1}
DO_TESTS=${DO_TESTS:-1}
DO_VERPATCH=${DO_VERPATCH:-1}
DO_SERVICE=${DO_SERVICE:-0}
RUN_INSTALLER=${RUN_INSTALLER:-1}
DO_MSI=${DO_MSI:-0}
DO_SIGN=${DO_SIGN:-1}
BUNDLE_OPENGL=${BUNDLE_OPENGL:-1}
BUNDLE_PUTTY=${BUNDLE_PUTTY:-1}
BUNDLE_OPENSSL=${BUNDLE_OPENSSL:-1}

PYTHON=${PYTHON:-python2}

KEY_FILE="E:\\xpra.pfx"
DIST="./dist"
BUILD_OPTIONS="--without-enc_x265 --without-cuda_rebuild"

CLIENT_ONLY="0"
if [ "$1" == "CLIENT" ]; then
	CLIENT_ONLY="1"
	DO_TESTS="0"
	DO_SERVICE="0"
	shift
fi

################################################################################
# get paths and compilation options:
PROGRAMFILES_X86="C:\\Program Files (x86)"

if [ "${CLIENT_ONLY}" == "1" ]; then
	BUILD_OPTIONS="${BUILD_OPTIONS} --without-server --without-shadow --without-proxy --without-html5 --without-rfb"
else
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

SIGNTOOL="${PROGRAMFILES}\\Microsoft SDKs\\Windows\\v7.1A\\Bin\\signtool"
if [ ! -e "${SIGNTOOL}" ]; then
	SIGNTOOL="${PROGRAMFILES_X86}\\Windows Kits\\8.1\\Bin\\x64\\signtool"
fi

################################################################################
# Get version information, generate filenames

#record in source tree:
rm xpra/src_info.py xpra/build_info.py >& /dev/null
${PYTHON} add_build_info.py >& /dev/null
if [ "$?" != "0" ]; then
	echo "ERROR: recording build info"
	exit 1
fi

#figure out the full xpra version:
PYTHON_VERSION=`${PYTHON} --version | awk '{print $2}'`
PYTHON_MAJOR_VERSION=`${PYTHON} -c 'import sys;print(sys.version_info[0])'`
echo "Python${PYTHON_MAJOR_VERSION} version ${PYTHON_VERSION}"
VERSION=`${PYTHON} -c "from xpra import __version__;import sys;sys.stdout.write(__version__)"`
REVISION=`${PYTHON} -c "from xpra.src_info import REVISION;import sys;sys.stdout.write(str(REVISION))"`
NUMREVISION=`${PYTHON} -c "from xpra.src_info import REVISION;import sys;sys.stdout.write(str(REVISION).rstrip('M'))"`
ZERO_PADDED_VERSION=`${PYTHON} -c 'from xpra import __version__;print(".".join((__version__.split(".")+["0","0","0"])[:3]))'`".${NUMREVISION}"
LOCAL_MODIFICATIONS=`${PYTHON} -c "from xpra.src_info import LOCAL_MODIFICATIONS;import sys;sys.stdout.write(str(LOCAL_MODIFICATIONS))"`
FULL_VERSION=${VERSION}-r${REVISION}
if [ "${LOCAL_MODIFICATIONS}" != "0" ]; then
	FULL_VERSION="${FULL_VERSION}M"
fi
EXTRA_VERSION=""
if [ "${CLIENT_ONLY}" == "1" ]; then
	EXTRA_VERSION="-Client"
	DO_CUDA="0"
fi
echo
echo -n "Xpra${EXTRA_VERSION} ${FULL_VERSION}"
if [ "${MSYSTEM_CARCH}" == "i686" ]; then
	BUILD_TYPE=""
	DO_CUDA="0"
else
	BUILD_TYPE="-${MSYSTEM_CARCH}"
	echo " (64-bit)"
fi
if [ "${PYTHON_MAJOR_VERSION}" == "3" ]; then
	BUILD_TYPE="-Python3${BUILD_TYPE}"
fi
echo
echo

INSTALLER_FILENAME="Xpra${EXTRA_VERSION}${BUILD_TYPE}_Setup_${FULL_VERSION}.exe"
MSI_FILENAME="Xpra${EXTRA_VERSION}${BUILD_TYPE}_${FULL_VERSION}.msi"
ZIP_DIR="Xpra${EXTRA_VERSION}${BUILD_TYPE}_${FULL_VERSION}"
ZIP_FILENAME="${ZIP_DIR}.zip"


################################################################################
# Build: clean, build extensions, generate exe directory

echo "* Cleaning ${DIST} output directory"
rm -fr ${DIST}/*
mkdir ${DIST} >& /dev/null

if [ "${DO_CLEAN}" == "1" ]; then
	rm -fr "build"
fi

if [ "${DO_SERVICE}" == "1" ]; then
	echo "* Compiling system service shim"
	pushd "win32/service" > /dev/null
	rm -f event_log.rc event_log.res MSG00409.bin Xpra-Service.exe
	WINDOWS_KITS="C:\Program Files (x86)\\Windows Kits"
	if [ -d "C:\\Program Files\\Windows Kits" ]; then
		WINDOWS_KITS="C:\Program Files\\Windows Kits"
	fi
	MC="${WINDOWS_KITS}\\8.1\\bin\\x86\\mc.exe"
	RC="${WINDOWS_KITS}\\8.1\\bin\\x86\\rc.exe"
	LINK="C:\\Program Files\\Microsoft Visual Studio 14.0\\VC\\bin\\link.exe"
	if  [ ! -e "${LINK}" ]; then
		LINK="C:\\Program Files (x86)\\Microsoft Visual Studio 14.0\\VC\\bin\\link.exe"
	fi
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
	cp -fn Xpra-Service.exe ../../dist/
	popd > /dev/null
fi

if [ "${DO_CUDA}" == "1" ]; then
	echo "* Building CUDA kernels"
	cmd.exe //c "win32\\BUILD_CUDA_KERNEL" BGRA_to_NV12 || exit 1
	cmd.exe //c "win32\\BUILD_CUDA_KERNEL" BGRA_to_YUV444 || exit 1
	cmd.exe //c "win32\\BUILD_CUDA_KERNEL" ARGB_to_NV12 || exit 1
	cmd.exe //c "win32\\BUILD_CUDA_KERNEL" ARGB_to_YUV444 || exit 1
fi

echo "* Building Python ${PYTHON_MAJOR_VERSION} Cython modules"
BUILD_LOG="win32/Python${PYTHON_MAJOR_VERSION}-build.log"
${PYTHON} ./setup.py build_ext ${BUILD_OPTIONS} --inplace >& ${BUILD_LOG}
if [ "$?" != "0" ]; then
	echo "ERROR: build failed, see ${BUILD_LOG}:"
	tail -n 20 "${BUILD_LOG}"
	exit 1
fi

if [ "${DO_TESTS}" == "1" ]; then
	echo "* Running unit tests"
	UNITTEST_LOG="win32/unittest.log"
	PYTHONPATH=.:./unittests ${PYTHON} ./unittests/unit/run.py >& ${UNITTEST_LOG}
	if [ "$?" != "0" ]; then
		echo "ERROR: unittests have failed, see ${UNITTEST_LOG}:"
		tail -n 20 "${UNITTEST_LOG}"
		exit 1
	fi
fi

# For building Python 3.x Sound sub-app (broken because of cx_Freeze bugs)
#echo "* Building Python 3.4 Cython modules (see win32/Python${PYTHON_MAJOR_VERSION}-build.log)"
#${PYTHON} ./setup.py build_ext ${BUILD_OPTIONS} --inplace >& win32/Python${PYTHON_MAJOR_VERSION}-build.log

echo "* Generating installation directory"
CX_FREEZE_LOG="win32/cx_freeze-install.log"
${PYTHON} ./setup.py install_exe ${BUILD_OPTIONS} --install=${DIST} >& ${CX_FREEZE_LOG}
if [ "$?" != "0" ]; then
	echo "ERROR: build failed, see ${CX_FREEZE_LOG}:"
	tail -n 20 "${CX_FREEZE_LOG}"
	exit 1
fi
#fixup cx_Logging, required by the service class before we can patch sys.path to find it:
if [ -e "${DIST}/lib/cx_Logging.pyd" ]; then
	mv "${DIST}/lib/cx_Logging.pyd" "${DIST}/"
fi

if [ "${BUNDLE_OPENGL}" == "1" ]; then
	if [ -e "${DIST}/OpenGL" ]; then
		pushd "${DIST}" >& /dev/null
		if [ "${PYTHON_MAJOR_VERSION}" == "3" ]; then
			echo "* Adding PyOpenGL to lib dir"
			mv "OpenGL" "lib/"
		else
			echo "* Adding PyOpenGL to library.zip"
			zip -qmor "library.zip" OpenGL
		fi
		popd >& /dev/null
	fi
fi

echo "* Generating gdk pixbuf loaders.cache"
gdk-pixbuf-query-loaders.exe "dist/lib/gdk-pixbuf-2.0/2.10.0/loaders/*" | sed 's+".*dist/+"+g' > dist/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache

echo "* Generating HTML Manual Page"
groff.exe -mandoc -Thtml < man/xpra.1 > ${DIST}/manual.html

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
	#are we meant to include those DLLs?
	#rsync -rplogt "${TORTOISESVN}/bin/"*dll "${DIST}/"
fi

if [ "${BUNDLE_OPENSSL}" == "1" ]; then
	cp -fn "${MINGW_PREFIX}/bin/openssl.exe" "${DIST}/"
	#use the old filename so we don't have to change the xpra.iss and the py2exe+MSVC build system:
	cp -fn "${MINGW_PREFIX}/ssl/openssl.cnf" "${DIST}/openssl.cfg"
fi

if [ "${DO_VERPATCH}" == "1" ]; then
	for exe in `ls dist/*exe | grep -v Plink.exe`; do
		tool_name=`echo $exe | sed 's+dist/++g;s+Xpra_++g;s+Xpra-++g;s+_+ +g;s+-+ +g;s+\.exe++g'`
		verpatch $exe				//s desc "Xpra $tool_name"		//va "${ZERO_PADDED_VERSION}" //s company "xpra.org" //s copyright "(c) xpra.org 2017" //s product "xpra" //pv "${ZERO_PADDED_VERSION}"
	done
	verpatch dist/Xpra_cmd.exe 		//s desc "Xpra command line"	//va "${ZERO_PADDED_VERSION}" //s company "xpra.org" //s copyright "(c) xpra.org 2017" //s product "xpra" //pv "${ZERO_PADDED_VERSION}"
	verpatch dist/Xpra-Proxy.exe	//s desc "Xpra Proxy Server"	//va "${ZERO_PADDED_VERSION}" //s company "xpra.org" //s copyright "(c) xpra.org 2017" //s product "xpra" //pv "${ZERO_PADDED_VERSION}"
	verpatch dist/Xpra.exe 			//s desc "Xpra" 				//va "${ZERO_PADDED_VERSION}" //s company "xpra.org" //s copyright "(c) xpra.org 2017" //s product "xpra" //pv "${ZERO_PADDED_VERSION}"
fi

################################################################################
# packaging: ZIP / EXE / MSI

if [ "${DO_ZIP}" == "1" ]; then
	echo "* Creating ZIP file:"
	rm -fr "${ZIP_DIR}" "${ZIP_FILENAME}"
	mkdir "${ZIP_DIR}"
	rsync -rplogt "${DIST}"/* "${ZIP_DIR}"
	zip -qmr "${ZIP_FILENAME}" "${ZIP_DIR}"
	ls -la "${ZIP_FILENAME}"
fi

if [ "${DO_INSTALLER}" == "1" ]; then
	INNOSETUP="/c/Program Files/Inno Setup 5/ISCC.exe"
	if [ ! -e "${INNOSETUP}" ]; then
		INNOSETUP="/c/Program Files (x86)/Inno Setup 5/ISCC.exe"
		if [ ! -e "${INNOSETUP}" ]; then
			echo "cannot find InnoSetup"
			exit 1
		fi
	fi
	INNOSETUP_LOG="win32/innosetup.log"
	echo "* Creating the installer using InnoSetup"
	rm -f "Xpra_Setup.exe" "${INSTALLER_FILENAME}" "${INNOSETUP_LOG}"
	cp -fn "win32/xpra.iss" "xpra.iss"
	if [ "${MSYSTEM_CARCH}" == "x86_64" ]; then
		cat "win32/xpra.iss" | sed '/\(ArchitecturesInstallIn64BitMode\|ArchitecturesInstallIn64BitMode\)/ s/=.*/=x64/g' | sed '/\(AppName=\|AppVerName=\|DefaultGroupName=\)/ s/\r$/ (64-bit)\r/g' | sed 's/ArchitecturesAllowed=.*/ArchitecturesAllowed=x64/g' > "xpra.iss"
	fi
	if [ "${CLIENT_ONLY}" == "1" ]; then
		#remove shadow start menu entry
		sed -i"" "s/.*Xpra Shadow Server.*//g" xpra.iss
	fi
	"${INNOSETUP}" "xpra.iss" >& "${INNOSETUP_LOG}"
	if [ "$?" != "0" ]; then
		echo "InnoSetup error - see ${INNOSETUP_LOG}:"
		tail -n 20 "${INNOSETUP_LOG}"
		rm "xpra.iss"
		exit 1
	fi
	rm "xpra.iss"
	mv "dist\Xpra_Setup.exe" "${INSTALLER_FILENAME}"

	if [ "${DO_SIGN}" == "1" ]; then
		SIGNTOOL_LOG="win32/signtool.log"
		echo "* Signing EXE"
		cmd.exe //c "${SIGNTOOL}" sign //v //f "${KEY_FILE}" //t "http://timestamp.comodoca.com/authenticode" "${INSTALLER_FILENAME}" > ${SIGNTOOL_LOG}
		if [ "$?" != 0 ]; then
			echo "signtool command failed, see ${SIGNTOOL_LOG}:"
			cat ${SIGNTOOL_LOG}
		fi
	fi
	ls -la "${INSTALLER_FILENAME}"

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
	cat "win32\msi.xml" | sed "s/INPUT/${INSTALLER_FILENAME}/g" | sed "s/OUTPUT/${MSI_FILENAME}/g" | sed "s/ZERO_PADDED_VERSION/${ZERO_PADDED_VERSION}/g" | sed "s/FULL_VERSION/${FULL_VERSION}/g" > msi.xml
	"${MSIWRAPPER}" "msi.xml"
	if [ "${DO_SIGN}" == "1" ]; then
		SIGNTOOL_LOG="win32/signtool.log"
		echo "* Signing MSI"
		cmd.exe //c "${SIGNTOOL}" sign //v //f "${KEY_FILE}" //t "http://timestamp.comodoca.com/authenticode" "${MSI_FILENAME}" > ${SIGNTOOL_LOG}
		if [ "$?" != 0 ]; then
			echo "signtool command failed, see ${SIGNTOOL_LOG}:"
			cat ${SIGNTOOL_LOG}
		fi
	fi
fi
