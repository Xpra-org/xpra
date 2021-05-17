#!/bin/bash

die() { echo "$*" 1>&2 ; exit 1; }

DO_XPRA=${DO_XPRA:-1}
DO_XPRA_HTML5=${DO_XPRA_HTML5:-1}

BASH="bash"
if [ "${DEBUG:-0}" == "1" ]; then
	BASH="bash -x"
fi

BUILDAH_DIR=`dirname $(readlink -f $0)`
pushd ${BUILDAH_DIR}

if [ "${DO_XPRA}" == "1" ]; then
	#go make a snapshot:
	pushd ../..
	rm -f pkgs/xpra-*.tar.xz
	python3 ./setup.py sdist --formats=xztar || die "failed to create xpra source snapshot"
	mv dist/xpra-*.tar.xz ./packaging/buildah/pkgs/
	popd
fi

if [ "${DO_XPRA_HTML5}" == "1" ]; then
	if [ -e "html5" ]; then
		rm -f pkgs/xpra-html5-*.tar.xz
		pushd html5
		python3 ./setup.py sdist --formats=xztar || die "failed to create xpra-html5 source snapshot"
		popd
		cp html5/dist/xpra-html5-*.tar.xz ./pkgs/
		cp html5/packaging/rpm/xpra-html5.spec ../rpm/
	else
		echo "html5 directory not found"
		echo " skipped creating a source snapshot"
	fi
fi

DO_DOWNLOAD="${DO_DOWNLOAD:-1}"
if [ "${DO_DOWNLOAD}" == "1" ]; then
	./download_source.sh
fi

RPM_DISTROS=${RPM_DISTROS:-Fedora:32 Fedora:33 Fedora:34 CentOS:8}
DEB_DISTROS=${DEB_DISTROS:-Ubuntu:bionic Ubuntu:focal Ubuntu:groovy Ubuntu:hirsute Debian:stretch Debian:buster Debian:bullseye Debian:sid}
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
		REPO_PATH="${BUILDAH_DIR}/repo/"`echo $DISTRO | sed 's+:+/+g'`
		for rpm_list in "./${FULL_DISTRO_NAME}-rpms.txt" "./${DISTRO_NAME}-rpms.txt" "./rpms.txt"; do
			if [ -r "${rpm_list}" ]; then
				echo " using rpm package list from ${rpm_list}"
				buildah copy $TEMP_IMAGE "$rpm_list" "/src/rpms.txt"
				break
			fi
		done
		buildah copy $TEMP_IMAGE "./build_rpms.sh" "/src/build.sh"
		echo "RPM: $REPO_PATH"
	else
		DISTRO_RELEASE=`echo $DISTRO | awk -F: '{print $2}'`
		REPO_PATH="${BUILDAH_DIR}/repo/$DISTRO_RELEASE"
		buildah copy $TEMP_IMAGE "./build_debs.sh" "/src/build.sh"
		echo "DEB: $REPO_PATH"
	fi
	mkdir -p $REPO_PATH >& /dev/null
	buildah run \
				--volume ${BUILDAH_DIR}/opt:/opt:ro,z \
				--volume $REPO_PATH:/src/repo:noexec,nodev,z \
				--volume ${BUILDAH_DIR}/pkgs:/src/pkgs:ro,z \
				--volume ${BUILDAH_DIR}/../rpm:/src/rpm:ro,z \
				--volume ${BUILDAH_DIR}/../debian:/src/debian:O \
				$TEMP_IMAGE $BASH /src/build.sh
	#			--volume /var/cache/dnf:/var/cache/dnf:O \
	#buildah run \
	#			--volume $REPO_PATH:/src/repo:noexec,nodev,z \
	#			--volume ${BUILDAH_DIR}/opt:/opt:ro,z \
	#			--volume ${BUILDAH_DIR}/pkgs:/src/pkgs:ro,z \
	#			--volume ${BUILDAH_DIR}/../rpm:/src/rpm:ro,z \
	#			--volume ${BUILDAH_DIR}/../debian:/src/debian:ro,z \
	#			--volume /var/cache/dnf:/var/cache/dnf:O \
	#			$TEMP_IMAGE bash
	buildah rm "${TEMP_IMAGE}"
done
