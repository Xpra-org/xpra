#!/bin/bash

VERSION=$1
if [ -z "${VERSION}" ]; then
	VERSION=`PYTHONPATH="./src" python -c "from xpra import __version__; print(__version__)"`
fi
DIR=xpra-${VERSION}
cp -apr src ${DIR}
rm -fr "${DIR}/build"
rm -fr "${DIR}/install"
rm -fr "${DIR}/wimpiggy/lowlevel/bindings.c"
rm -fr "${DIR}/wimpiggy/lowlevel/constants.pxi"
find ${DIR} -name ".svn" -exec rm -fr {} \; 2>&1 | grep -v "No such file or directory"
find ${DIR} -name ".pyc" -exec rm -fr {} \;

SVN_REVISION=`svn info src | grep '^Revision: ' | awk -F'Revision: ' '{print $2}'`
for module in xpra wimpiggy parti; do
	file="${DIR}/${module}/__init__.py"
	echo "adding svn revision ${SVN_REVISION} to ${file}"
	sed -i -e "s+unknown+${SVN_REVISION}+" "${file}"
done

tar -jcf ${DIR}.tar.bz2 ${DIR} --exclude install --exclude build --exclude dist --exclude Output --exclude deb --exclude MANIFEST --exclude xpra/wait_for_x_server.c --exclude wimpiggy/lowlevel/wimpiggy.lowlevel.bindings.dep --exclude wimpiggy/lowlevel/constants.pxi --exclude wimpiggy/lowlevel/bindings.c --exclude *pyc
ls -al ${DIR}.tar.bz2
rm -fr "${DIR}"
