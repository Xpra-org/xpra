#!/bin/bash

BUILDAH_DIR=`dirname $(readlink -f $0)`
pushd ${BUILDAH_DIR}

function specver() {
	V=`rpmspec -q --qf "%{version}\n" "$1" 2> /dev/null | sort -u`
	if [ "$?" != "0" ]; then
		exit 1
	fi
	if [ "$V" == "" ]; then
		exit 1
	fi
	echo $V
}
function fetch() {
	SPECFILE=$1
	SPECNAME=`basename $SPECFILE`
	VERSION=$(specver $SPECFILE)
	if [ -z "${VERSION}" ]; then
		echo "no version found in $SPECNAME"
		exit 1
	fi
	URLS=`rpmspec -P $SPECFILE | grep "^Source.*:" | awk '{print $2}'`
	if [ -z "${URLS}" ]; then
		echo "no Source URLs found in $SPECNAME"
		return
	fi
	for URL in $URLS; do
		FILENAME=`echo $URL | awk -F/ '{print $NF}'`
		if [ -e "${FILENAME}" ]; then
			echo "found ${FILENAME}"
		else
			echo "downloading $FILENAME from ${URL}"
			curl --output "${FILENAME}" -L "${URL}"
		fi
	done
}
SPECS=`ls packaging/rpm/*.spec | sed 's/.spec//g'`
pushd pkgs
for SPEC in $SPECS; do
	fetch "${BUILDAH_DIR}/$SPEC.spec"
done
popd
