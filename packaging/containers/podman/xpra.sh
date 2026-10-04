#!/bin/bash
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

set -e

DISTRO="${DISTRO:-fedora}"
RELEASE="${RELEASE:-latest}"
IMAGE_NAME="xpra"
CONTAINER="$DISTRO-$RELEASE-$IMAGE_NAME"
CLEAN="${CLEAN:-1}"
REPO="${REPO:-xpra-beta}"
XDISPLAY="${XDISPLAY:-:10}"
SEAMLESS="${SEAMLESS:-1}"
PORT="${PORT:-10000}"
AUDIO="${AUDIO:-1}"
CODECS="${CODECS:-1}"
TOOLS="${TOOLS:-0}"
TARGET_USER="${TARGET_USER:-xpra-user}"
TARGET_PASSWORD="${TARGET_PASSWORD:-thepassword}"
# the "pulse" group only exists when pulseaudio is installed:
if [ "${AUDIO}" == "1" ]; then
  TARGET_USER_GROUPS="${TARGET_USER_GROUPS:-audio,pulse,video,xpra}"
else
  TARGET_USER_GROUPS="${TARGET_USER_GROUPS:-audio,video,xpra}"
fi
TARGET_UID="${TARGET_UID:-1000}"
TARGET_GID="${TARGET_GID:-1000}"
DEBUG="${DEBUG:-none}"

run () {
  buildah run $CONTAINER "$@"
}

copy () {
  buildah copy $CONTAINER "$@"
}

install () {
  if [ "${TRIM}" == "1" ]; then
    run dnf install -y --setopt=install_weak_deps=False "$@"
  else
    run dnf install -y "$@"
  fi
}

if [ "$1" == "update" ]; then
  run dnf update --refresh -y
else
  if [ "${CLEAN}" == "1" ]; then
    buildah rm $CONTAINER || true
    buildah rmi -f $IMAGE_NAME || true
    buildah from --pull=newer --name $CONTAINER $DISTRO:$RELEASE
  fi
  # the distribution's major version number, ie: "latest" -> "44"
  VERSION_ID=$(run sh -c '. /etc/os-release;echo ${VERSION_ID%%.*}')
  if [ "${DISTRO}" == "fedora" ]; then
    RPMFUSION_DIR="fedora"
    REPO_DIR="Fedora"
    EXTRA_PACKAGES="python3-uvloop python3-aioquic python3-zeroconf"
  else
    # almalinux, rockylinux: dependencies come from EPEL and CRB
    install -y epel-release dnf-plugins-core
    run dnf config-manager --set-enabled crb
    RPMFUSION_DIR="el"
    REPO_DIR="${DISTRO}"
    if [ "${VERSION_ID}" -ge 10 ]; then
      EXTRA_PACKAGES="python3-uvloop python3-aioquic"
    else
      EXTRA_PACKAGES=""
    fi
  fi
  install -y "https://download1.rpmfusion.org/free/${RPMFUSION_DIR}/rpmfusion-free-release-${VERSION_ID}.noarch.rpm"
  run dnf update -y
  install -y wget "--setopt=install_weak_deps=False"
  run wget -O "/etc/yum.repos.d/${REPO}.repo" "https://raw.githubusercontent.com/Xpra-org/xpra/master/packaging/repos/${REPO_DIR}/${REPO}.repo"
  install -y xpra-filesystem xpra-server xpra-x11 xpra-html5 python3-pyxdg ${EXTRA_PACKAGES} dbus-daemon dbus-x11 dbus-tools desktop-backgrounds-compat libjxl-utils python3-cups cups-filters cups-pdf --setopt=install_weak_deps=False
  if [ "${AUDIO}" == "1" ]; then
    install -y xpra-audio-server
  fi
  if [ "${CODECS}" == "1" ]; then
    install -y xpra-codecs
  fi

  if [ "${TOOLS}" == "1" ]; then
    install -y strace xterm xclip net-tools lsof xpra-client socat mesa-demos xdpyinfo VirtualGL pavucontrol --setopt=install_weak_deps=False
  fi

  run groupdel "${TARGET_GROUP}" || true
  run userdel -r "${TARGET_USER}" || true
  run groupadd -r -g "${TARGET_GID}" "${TARGET_USER}"
  run adduser -u "${TARGET_UID}" -g "${TARGET_GID}" --shell /bin/bash "${TARGET_USER}"
  run usermod -aG "${TARGET_USER_GROUPS}" "${TARGET_USER}"
  run sh -c "echo \"${TARGET_USER}:${TARGET_PASSWORD}\" | chpasswd"

  # dbus setup
  run sh -c "mkdir -m 755 -p /var/lib/dbus;dbus-uuidgen > /var/lib/dbus/machine-id"
  copy "../fs/etc/dbus-1/system.d/allow-all.conf" /etc/dbus-1/system.d/
fi

# just use the system-wide ssl certificate:
run sh -c "chmod 644 /etc/xpra/ssl/*.pem"

# save space:
# (`buildah run` does not use a shell, so we need one to expand the globs)
run sh -c "rm -fr /var/cache/*dnf* /var/log/dnf*.log* /var/log/README /var/yp /var/preserve /var/opt /var/nis /var/log/journal /var/log/private /var/local /var/lib/systemd /var/lib/selinux/tmp /var/games /var/kerberos /var/db"

# to only use the display from the 'xvfb' container
# set `--use-display=yes`:
if [ "${SEAMLESS}" == "1" ]; then
  MODE="seamless"
else
  MODE="desktop"
fi
buildah config --entrypoint "/usr/bin/xpra ${MODE} --uid ${TARGET_UID} --gid ${TARGET_GID} ${XDISPLAY} --bind-quic=0.0.0.0:${PORT} --bind-tcp=0.0.0.0:${PORT} --no-daemon --use-display=auto --dbus=no --system-tray=no --ssh-upgrade=no --env=XPRA_POWER_EVENTS=0 -d ${DEBUG}" $CONTAINER
buildah commit $CONTAINER $IMAGE_NAME
