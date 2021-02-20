#!/bin/bash

#sets up distro build images with very basic tools,
# ie: gcc g++
#and 

die() { echo "$*" 1>&2 ; exit 1; }

buildah --version >& /dev/null
if [ "$?" != "0" ]; then
	die "cannot continue without buildah"
fi

#TODO:
# * check for CUDA
# * check for NVENC


BUILDAH_DIR=`dirname $(readlink -f $0)`
pushd ${BUILDAH_DIR}

RPM_DISTROS=${RPM_DISTROS:-Fedora:32 Fedora:33 CentOS:7 CentOS:8}
for DISTRO in $RPM_DISTROS; do
	#DISTRO_DIR_NAME="`echo $DISTRO | sed 's/:/-/g'`-xpra-build"
	#mkdir -p packaging/buildah/repo/Fedora/{32,33,34} >& /dev/null
	DISTRO_LOWER="${DISTRO,,}"
	IMAGE_NAME="`echo $DISTRO_LOWER | sed 's/:/-/g'`-xpra-build"
	podman image exists $IMAGE_NAME
	if [ "$?" != "0" ]; then
		echo "creating ${IMAGE_NAME}"
		#docker names are lowercase:
		buildah from --name $IMAGE_NAME $DISTRO_LOWER
		buildah run $IMAGE_NAME dnf update -y
		buildah run $IMAGE_NAME dnf install -y 'dnf-command(builddep)'
		buildah run $IMAGE_NAME dnf install -y gcc gcc-c++ redhat-rpm-config rpm-build rpmdevtools createrepo_c rsync
		echo $DISTRO | egrep -i "fedora" >& /dev/null
		if [ "$?" == "0" ]; then
			RNUM=`echo $DISTRO | awk -F: '{print $2}'`
			dnf -y makecache --releasever=$RNUM --setopt=cachedir=/var/cache/dnf/$RNUM
			buildah run $IMAGE_NAME dnf install -y rpmspectool
		else
			#some of the packages we need for building are in the "PowerTools" repository:
			buildah run $IMAGE_NAME dnf config-manager --set-enabled powertools
			#no "rpmspectool" package on CentOS 8, use setuptools to install it:
			buildah run $IMAGE_NAME dnf install -y python3-setuptools
			buildah run $IMAGE_NAME easy_install rpmspec
		fi
		buildah run $IMAGE_NAME rpmdev-setuptree
		#buildah run dnf clean all

		buildah run $IMAGE_NAME mkdir /src/pkgs /repo
		buildah config --workingdir /src $IMAGE_NAME
		buildah copy $IMAGE_NAME "./xpra-build.repo" "/etc/yum.repos.d/"
		buildah run $IMAGE_NAME mkdir -p "/src/repo/"
		buildah run $IMAGE_NAME createrepo "/src/repo/"
		buildah run $IMAGE_NAME mkdir -p "/usr/lib64/xpra/pkgconfig"
		buildah copy $IMAGE_NAME "./nvenc-rpm.pc" "/usr/lib64/pkgconfig/nvenc.pc"
		buildah copy $IMAGE_NAME "./cuda.pc" "/usr/lib64/pkgconfig/cuda.pc"
		buildah commit $IMAGE_NAME $IMAGE_NAME
	fi
done

DEB_DISTROS=${DEB_DISTROS:-Ubuntu:xenial Ubuntu:bionic Ubuntu:focal Ubuntu:groovy Ubuntu:hirsute Debian:stretch Debian:buster Debian:bullseye Debian:sid}
for DISTRO in $DEB_DISTROS; do
	#DISTRO_DIR_NAME="`echo $DISTRO | sed 's/:/-/g'`-xpra-build"
	#mkdir -p packaging/buildah/repo/Fedora/{32,33,34} >& /dev/null
	DISTRO_LOWER="${DISTRO,,}"
	IMAGE_NAME="`echo $DISTRO_LOWER | sed 's/:/-/g'`-xpra-build"
	podman image exists $IMAGE_NAME
	if [ "$?" != "0" ]; then
		DISTRO_NAME=`echo $DISTRO | awk -F: '{print $2}'`
		echo "creating ${IMAGE_NAME}"
		#docker names are lowercase:
		buildah from --name $IMAGE_NAME $DISTRO_LOWER
		buildah run $IMAGE_NAME apt-get update
		buildah run $IMAGE_NAME apt-get upgrade -y
		buildah run $IMAGE_NAME apt-get dist-upgrade -y
		buildah run $IMAGE_NAME apt-get install -y gcc g++ debhelper

		buildah run $IMAGE_NAME mkdir -p /src/pkgs /repo
		buildah config --workingdir /src $IMAGE_NAME
		buildah run $IMAGE_NAME bash -c 'echo "deb file:///repo $DISTRO_NAME main" > /etc/apt/sources.list.d/xpra-build.list'
		buildah copy $IMAGE_NAME "./nvenc-deb.pc" "/usr/lib/pkgconfig/nvenc.pc"
		buildah copy $IMAGE_NAME "./cuda.pc" "/usr/lib/pkgconfig/cuda.pc"
		buildah commit $IMAGE_NAME $IMAGE_NAME
	fi
done
