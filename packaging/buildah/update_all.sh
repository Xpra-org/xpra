#!/bin/bash

die() { echo "$*" 1>&2 ; exit 1; }

BUILDAH_DIR=`dirname $(readlink -f $0)`
pushd ${BUILDAH_DIR}

RPM_DISTROS=${RPM_DISTROS:-Fedora:32 Fedora:33 Fedora:34 CentOS:8}
DEB_DISTROS=${DEB_DISTROS:-Ubuntu:xenial Ubuntu:bionic Ubuntu:focal Ubuntu:groovy Ubuntu:hirsute Debian:stretch Debian:buster Debian:bullseye Debian:sid}
if [ -z "${DISTROS}" ]; then
	DISTROS="$RPM_DISTROS $DEB_DISTROS"
fi

for DISTRO in $DISTROS; do
	#ie: DISTRO_NAME="fedora-33"
	FULL_DISTRO_NAME=`echo ${DISTRO,,} | sed 's/:/-/g'`
	DISTRO_NAME=`echo ${DISTRO,,} | awk -F: '{print $1}'`
	IMAGE_NAME="$FULL_DISTRO_NAME-xpra-build"

	TEMP_IMAGE="$IMAGE_NAME-temp"
	buildah image rmi "${TEMP_IMAGE}" >& /dev/null
	buildah from --pull-never --name  $TEMP_IMAGE $IMAGE_NAME
	if [ "$?" != "0" ]; then
		echo "cannot update $DISTRO: image $IMAGE_NAME is missing or $TEMP_IMAGE already exists?"
		continue
	fi
	echo $DISTRO : $IMAGE_NAME
	echo $DISTRO | egrep -iv "fedora|centos" >& /dev/null
	RPM="$?"
	if [ "${RPM}" == "1" ]; then
		buildah run $TEMP_IMAGE dnf update --disablerepo=xpra-local-build -y
	else
		buildah config --env DEBIAN_FRONTEND=noninteractive $IMAGE_NAME
		buildah run $TEMP_IMAGE apt-get update
		buildah run $TEMP_IMAGE apt-get upgrade -y
		buildah run $TEMP_IMAGE apt-get dist-upgrade -y
		buildah run $TEMP_IMAGE apt-get autoremove -y
		buildah copy $TEMP_IMAGE "../debian/control" "/src/control"
		buildah run $TEMP_IMAGE mk-build-deps --install --tool='apt-get -o Debug::pkgProblemResolver=yes --no-install-recommends --yes' /src/control
		buildah run $TEMP_IMAGE apt-get autoremove -y
	fi
	buildah commit $IMAGE_NAME $TEMP_IMAGE
	buildah rm "${TEMP_IMAGE}"
done
