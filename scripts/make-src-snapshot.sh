#!/bin/bash

VERSION=$1
if [ -z "${VERSION}" ]; then
	VERSION=`PYTHONPATH="./dev" python -c "from xpra import __version__; print __version__"`
fi
DIR=xpra-${VERSION}
cp -apr src ${DIR}
rm -fr "${DIR}/build"
rm -fr "${DIR}/install"
rm -fr "${DIR}/wimpiggy/lowlevel/bindings.c"
rm -fr "${DIR}/wimpiggy/lowlevel/constants.pxi"
find ${DIR} -name ".svn" -exec rm -fr {} \;
find ${DIR} -name ".pyc" -exec rm -fr {} \;

tar -jcf ${DIR}.tar.bz2 ${DIR} --exclude install --exclude build --exclude dist --exclude Output --exclude deb --exclude MANIFEST --exclude xpra/wait_for_x_server.c --exclude wimpiggy/lowlevel/wimpiggy.lowlevel.bindings.dep --exclude wimpiggy/lowlevel/constants.pxi --exclude wimpiggy/lowlevel/bindings.c --exclude *pyc
ls -al ${DIR}.tar.bz2
rm -fr "${DIR}"
