#!/bin/bash

BUILD_NO=1

rm -fr build install
python ./setup.py sdist
PYTHON_SITELIB=`python -c "from distutils.sysconfig import get_python_lib; print(get_python_lib())"`
SOURCES=~/rpmbuild/SOURCES/
DIST="unknown"
grep CentOS /etc/redhat-release
if [ "$?" == "0" ]; then
	SOURCES="/usr/src/redhat/SOURCES/"
	FULL_VERSION=`cat /etc/redhat-release | sed 's/[^0-9\.]//g'`
	MAJOR_VERSION=`echo $FULL_VERSION | sed 's+\..*++g'`
	DIST="el${MAJOR_VERSION}"
fi
cp dist/parti-all-*.tar.gz ${SOURCES}
rpmbuild -ba xpra.spec --define "python_sitelib ${PYTHON_SITELIB}" --define "build_no ${BUILD_NO}" --define "dist .${DIST}" --define "${DIST} 1"
