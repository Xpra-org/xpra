#!/bin/bash

BUILD_NO=1

rm -fr build install
rm -f xpra/wait_for_x_server.c
rm -f wimpiggy/lowlevel/bindings.c
python ./setup.py sdist
SOURCES=~/rpmbuild/SOURCES/
grep CentOS /etc/redhat-release
if [ "$?" == "0" ]; then
	SOURCES="/usr/src/redhat/SOURCES/"
fi
cp dist/parti-all-*.tar.gz ${SOURCES}
PYTHON_SITELIB=`python -c "from distutils.sysconfig import get_python_lib; print get_python_lib()"`
rpmbuild -ba xpra.spec --define "python_sitelib ${PYTHON_SITELIB}" --define "build_no ${BUILD_NO}" ${EXTRA_ARGS} --define "include_egg 1"
