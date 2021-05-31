#!/bin/bash

die() { echo "$*" 1>&2 ; exit 1; }

BASH="bash"
if [ "${DEBUG:-0}" == "1" ]; then
	BASH="bash -x"
fi

#set to "0" to avoid building the NVIDIA proprietary codecs NVENC, NVFBC and NVJPEG,
#this is only enabled by default on x86_64:
if [ -z "${NVIDIA_CODECS}" ]; then
	if [ `arch` == "x86_64" ]; then
		NVIDIA_CODECS=1
	else
		NVIDIA_CODECS=0
	fi
fi

BUILDAH_DIR=`dirname $(readlink -f $0)`
cd ${BUILDAH_DIR}

mkdir cache >& /dev/null
rm -fr cache/ldconfig cache/libX11 cache/debconf

PACKAGING="$BUILDAH_DIR/packaging"
if [ ! -e "${PACKAGING}" ]; then
	#by default, build from the current tree
	#(the parent directory, which contains "debian" and "rpm")
	#this symlink can be changed and will be left alone
	ln -sf "../" "${PACKAGING}"
fi

DO_DOWNLOAD="${DO_DOWNLOAD:-1}"
if [ "${DO_DOWNLOAD}" == "1" ]; then
	./download_source.sh
fi

RPM_DISTROS=${RPM_DISTROS:-Fedora:33 Fedora:34 CentOS:7 CentOS:8}
DEB_DISTROS=${DEB_DISTROS:-Ubuntu:bionic Ubuntu:focal Ubuntu:hirsute Debian:stretch Debian:buster Debian:bullseye Debian:sid}
if [ -z "${DISTROS}" ]; then
	DISTROS="$RPM_DISTROS $DEB_DISTROS"
fi

for DISTRO in $DISTROS; do
	echo
	echo "********************************************************************************"
	#ie: DISTRO_NAME="fedora-33"
	FULL_DISTRO_NAME=`echo ${DISTRO,,} | sed 's/:/-/g'`
	DISTRO_NAME=`echo ${DISTRO,,} | awk -F: '{print $1}'`
	IMAGE_NAME="$FULL_DISTRO_NAME-xpra-build"

	#use a temp image:
	TEMP_IMAGE="$IMAGE_NAME-temp"
	buildah rm "${TEMP_IMAGE}" >& /dev/null
	buildah rmi "${TEMP_IMAGE}" >& /dev/null
	buildah from --pull-never --name  $TEMP_IMAGE $IMAGE_NAME
	if [ "$?" != "0" ]; then
		echo "cannot build $DISTRO: image $IMAGE_NAME is missing or $TEMP_IMAGE already exists?"
		continue
	fi
	echo $DISTRO : $IMAGE_NAME
	buildah run $TEMP_IMAGE mkdir -p /opt /src/repo /src/pkgs src/rpm /src/debian /var/cache/dnf
	echo $DISTRO | egrep -iv "fedora|centos" >& /dev/null
	RPM="$?"
	if [ "${RPM}" == "1" ]; then
		PKGCONFIG="/usr/lib64/pkgconfig"
		REPO_PATH="${BUILDAH_DIR}/repo/"`echo $DISTRO | sed 's+:+/+g'`
		for rpm_list in "./${FULL_DISTRO_NAME}-rpms.txt" "./${DISTRO_NAME}-rpms.txt" "./rpms.txt"; do
			if [ -r "${PACKAGING}/rpm/${rpm_list}" ]; then
				rpm_list_path=`readlink -e ${PACKAGING}/rpm/${rpm_list}`
				echo " using rpm package list from ${rpm_list_path}"
				buildah copy $TEMP_IMAGE "${rpm_list_path}" "/src/rpms.txt"
				break
			fi
		done
		buildah copy $TEMP_IMAGE "./build_rpms.sh" "/src/build.sh"
		echo "RPM: $REPO_PATH"
	else
		PKGCONFIG="/usr/lib/pkgconfig"
		DISTRO_RELEASE=`echo $DISTRO | awk -F: '{print $2}'`
		REPO_PATH="${BUILDAH_DIR}/repo/$DISTRO_RELEASE"
		buildah copy $TEMP_IMAGE "./build_debs.sh" "/src/build.sh"
		echo "DEB: $REPO_PATH"
	fi
	mkdir -p $REPO_PATH >& /dev/null

	if [ "${NVIDIA_CODECS}" == "1" ]; then
		buildah copy $IMAGE_NAME "./nvenc.pc" "${PKGCONFIG}/nvenc.pc"
		buildah copy $IMAGE_NAME "./nvfbc.pc" "${PKGCONFIG}/nvfbc.pc"
		buildah copy $IMAGE_NAME "./nvjpeg.pc" "${PKGCONFIG}/nvjpeg.pc"
		buildah copy $IMAGE_NAME "./cuda.pc" "${PKGCONFIG}/cuda.pc"
	fi

	buildah run \
				--volume ${BUILDAH_DIR}/opt:/opt:ro,z \
				--volume ${BUILDAH_DIR}/pkgs:/src/pkgs:ro,z \
				--volume ${BUILDAH_DIR}/cache:/var/cache:rw,z \
				--volume $REPO_PATH:/src/repo:noexec,nodev,z \
				--volume ${PACKAGING}/rpm:/src/rpm:ro,z \
				--volume ${PACKAGING}/debian:/src/debian:O \
				$TEMP_IMAGE $BASH /src/build.sh
	buildah rm "${TEMP_IMAGE}"
done
