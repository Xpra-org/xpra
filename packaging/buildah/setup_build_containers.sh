#!/bin/bash

die() { echo "$*" 1>&2 ; exit 1; }

buildah --version >& /dev/null
if [ "$?" != "0" ]; then
	die "cannot continue without buildah"
fi

#set to "1" to skip installing many of the dependencies,
#these can be installed automatically during the build instead
MINIMAL=${MINIMAL:-0}
#set to "0" to avoid building the NVIDIA proprietary codecs NVENC and NVJPEG,
#this is only enabled by default on x86_64:
if [ -z "${NVIDIA_CODECS}" ]; then
	if [ `arch` == "x86_64" ]; then
		NVIDIA_CODECS=1
	else
		NVIDIA_CODECS=0
	fi
fi

BUILDAH_DIR=`dirname $(readlink -f $0)`
pushd ${BUILDAH_DIR}

RPM_DISTROS=${RPM_DISTROS:-Fedora:33 Fedora:34 CentOS:7 CentOS:8}
for DISTRO in $RPM_DISTROS; do
	DISTRO_LOWER="${DISTRO,,}"
	if [[ "$DISTRO_LOWER" == "xx"* ]];then
	    echo "skipped $DISTRO"
	    continue
	fi
	IMAGE_NAME="`echo $DISTRO_LOWER | awk -F'/' '{print $1}' | sed 's/:/-/g'`-xpra-build"
	podman image exists $IMAGE_NAME
	if [ "$?" == "0" ]; then
		continue
	fi
	PM="dnf"
	if [ "${DISTRO}" == "CentOS:7" ]; then
		PM="yum"
	fi
	echo
	echo "********************************************************************************"
	echo "creating ${IMAGE_NAME}"
	#docker names are lowercase:
	buildah from --name $IMAGE_NAME $DISTRO_LOWER
	if [ "$?" != "0" ]; then
		echo "Warning: failed to create image $IMAGE_NAME"
		continue
	fi
	if [[ "${DISTRO_LOWER}" == "fedora"* ]]; then
		#first install the config-manager plugin,
		#only enable the repo containing this plugin:
		#(this is more likely to succeed on flaky networks)
		buildah run $IMAGE_NAME dnf install -y dnf-plugins-core --disablerepo='*' --enablerepo='fedora'
		#some repositories are enabled by default,
		#but we don't want to use them
		#(any repository failures would cause problems)
		for repo in fedora-cisco-openh264 fedora-modular updates-modular updates-testing-modular updates-testing-modular-debuginfo updates-testing-modular-source; do
			#buildah run $IMAGE_NAME dnf config-manager --save "--setopt=$repo.skip_if_unavailable=true" $repo
			buildah run $IMAGE_NAME dnf config-manager --set-disabled $repo
		done
	fi
	buildah run $IMAGE_NAME $PM update -y
	buildah run $IMAGE_NAME $PM install -y redhat-rpm-config rpm-build rpmdevtools createrepo_c rsync
	if [ "${PM}" == "dnf" ]; then
		buildah run $IMAGE_NAME dnf install -y 'dnf-command(builddep)'
	fi
	if [ "${MINIMAL}" == "0" ]; then
		buildah run $IMAGE_NAME ${PM} install -y gcc gcc-c++ make cmake
	fi
	if [[ "${DISTRO_LOWER}" == "fedora"* ]]; then
		RNUM=`echo $DISTRO | awk -F: '{print $2}'`
		dnf -y makecache --releasever=$RNUM --setopt=cachedir=/var/cache/dnf/$RNUM
		buildah run $IMAGE_NAME ${PM} install -y rpmspectool
		if [ "${MINIMAL}" == "0" ]; then
			#these are required by the xpra-html5 build:
			buildah run $IMAGE_NAME ${PM} install -y brotli js-jquery desktop-backgrounds-compat
		fi
	else
		#centos8:
		if [ "${PM}" == "dnf" ]; then
			#some of the packages we need for building are in the "PowerTools" repository:
			buildah run $IMAGE_NAME dnf config-manager --set-enabled powertools
			#no "rpmspectool" package on CentOS 8, use setuptools to install it:
			buildah run $IMAGE_NAME dnf install -y python3-setuptools
			buildah run $IMAGE_NAME easy_install-3.6 python-rpm-spec
		fi
		if [ "${MINIMAL}" == "0" ]; then
			#these are required by the xpra-html5 build:
			buildah run $IMAGE_NAME ${PM} install -y brotli centos-backgrounds centos-logos
		fi
	fi
	buildah run $IMAGE_NAME rpmdev-setuptree
	#buildah run dnf clean all

	buildah run $IMAGE_NAME mkdir -p "/src/repo/" "/src/rpm" "/src/debian" "/src/pkgs" "/usr/lib64/xpra/pkgconfig"
	buildah config --workingdir /src $IMAGE_NAME
	buildah copy $IMAGE_NAME "./xpra-build.repo" "/etc/yum.repos.d/"
	buildah run $IMAGE_NAME createrepo_c "/src/repo/"
	if [ "${NVIDIA_CODECS}" == "1" ]; then
		buildah copy $IMAGE_NAME "./nvenc-rpm.pc" "/usr/lib64/pkgconfig/nvenc.pc"
		buildah copy $IMAGE_NAME "./cuda.pc" "/usr/lib64/pkgconfig/cuda.pc"
	fi
	buildah commit $IMAGE_NAME $IMAGE_NAME
done

DEB_DISTROS=${DEB_DISTROS:-Ubuntu:bionic Ubuntu:focal Ubuntu:hirsute Debian:stretch Debian:buster Debian:bullseye Debian:sid}
for DISTRO in $DEB_DISTROS; do
	#DISTRO_DIR_NAME="`echo $DISTRO | sed 's/:/-/g'`-xpra-build"
	#mkdir -p packaging/buildah/repo/Fedora/{32,33,34} >& /dev/null
	DISTRO_LOWER="${DISTRO,,}"
	if [[ "$DISTRO_LOWER" == "xx"* ]];then
	    echo "skipped $DISTRO"
	    continue
	fi
	IMAGE_NAME="`echo $DISTRO_LOWER | sed 's/:/-/g'`-xpra-build"
	podman image exists $IMAGE_NAME
	if [ "$?" == "0" ]; then
		continue
	fi
	echo
	echo "********************************************************************************"
	echo "creating ${IMAGE_NAME}"
	#docker names are lowercase:
	buildah from --name $IMAGE_NAME $DISTRO_LOWER
	buildah config --env DEBIAN_FRONTEND=noninteractive $IMAGE_NAME
	buildah run $IMAGE_NAME apt-get update
	buildah run $IMAGE_NAME apt-get upgrade -y
	buildah run $IMAGE_NAME apt-get dist-upgrade -y
	echo "${DISTRO}" | grep Ubuntu > /dev/null
	if [ "$?" == "0" ]; then
		#the codecs require the "universe" repository:
		buildah run $IMAGE_NAME apt-get install -y software-properties-common
		buildah run $IMAGE_NAME add-apt-repository universe -y
		buildah run $IMAGE_NAME apt-get update
	fi
	#this is only used for building xpra,
	#so add as many dependencies already:
	#buildah run $IMAGE_NAME apt-get install -y gcc g++ debhelper devscripts
	buildah run $IMAGE_NAME apt-get install -y devscripts equivs lsb-release perl findutils
	if [ "${MINIMAL}" == "0" ]; then
		buildah copy $IMAGE_NAME "../debian/control" "/src/control"
		buildah run $IMAGE_NAME mk-build-deps --install --tool='apt-get -o Debug::pkgProblemResolver=yes --no-install-recommends --yes' /src/control
		#used by the html5 client:
		buildah run $IMAGE_NAME apt-get install -y uglifyjs brotli brotli libjs-jquery libjs-jquery-ui gnome-backgrounds
	fi
	buildah run $IMAGE_NAME apt-get autoremove -y
	#or we could do this explicitly:
	#buildah run $IMAGE_NAME apt-get install -y gcc g++ debhelper devscripts dh-python dh-systemd \
	#	libx11-dev libvpx-dev libxcomposite-dev libxdamage-dev libxtst-dev libxkbfile-dev \
	#   libx264-dev libavcodec-dev libavformat-dev libswscale-dev \
	#	libgtk-3-dev \
	#	python3-dev python3-cairo-dev python-gi-dev \
	#	cython3 libsystemd-dev libpam-dev \
	#	pandoc
	buildah run $IMAGE_NAME mkdir -p "/src/repo/" "/src/rpm" "/src/debian" "/src/pkgs"
	buildah config --workingdir /src $IMAGE_NAME
	#we don't need a local repo yet:
	#DISTRO_NAME=`echo $DISTRO | awk -F: '{print $2}'`
	#buildah run $IMAGE_NAME bash -c 'echo "deb file:///repo $DISTRO_NAME main" > /etc/apt/sources.list.d/xpra-build.list'
	if [ "${NVIDIA_CODECS}" == "1" ]; then
		buildah copy $IMAGE_NAME "./nvenc-deb.pc" "/usr/lib/pkgconfig/nvenc.pc"
		buildah copy $IMAGE_NAME "./cuda.pc" "/usr/lib/pkgconfig/cuda.pc"
	fi
	buildah commit $IMAGE_NAME $IMAGE_NAME
done
