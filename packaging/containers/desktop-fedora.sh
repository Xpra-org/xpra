#!/bin/bash
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

set -e

DISTRO="${DISTRO:-fedora}"
RELEASE="${RELEASE:-42}"
IMAGE_NAME="${IMAGE_NAME:-apps}"
CONTAINER="$DISTRO-$RELEASE-$IMAGE_NAME"
CLEAN="${CLEAN:-1}"
REPO="${REPO:-xpra-beta}"
TRIM="${TRIM:-1}"
XDISPLAY="${XDISPLAY:-:10}"
TOOLS="${TOOLS:-0}"
FILE_MANAGER="${FILE_MANAGER:-nemo}"
XPRA="${XPRA:-0}"
APPS="${APPS:-libreoffice lxterminal vlc gimp firefox}"
TARGET_USER="${TARGET_USER:-desktop-user}"
TARGET_GROUP="${TARGET_GROUP:-desktop-user}"
TARGET_PASSWORD="${TARGET_PASSWORD:-thepassword}"
TARGET_USER_GROUPS="${TARGET_USER_GROUPS:-audio,pulse,video}"
TARGET_UID="${TARGET_UID:-1000}"
TARGET_GID="${TARGET_GID:-1000}"
TIMEZONE="${TIMEZONE:-Europe/London}"
DESKTOP="${DESKTOP:-winbar}"
# LANG="${LANG:-C}"

run () {
  buildah run $CONTAINER "$@"
}

copy () {
  buildah copy $CONTAINER "$@"
}

install () {
  if [ "${TRIM}" == "1" ]; then
    buildah run $CONTAINER dnf install -y --setopt=install_weak_deps=False "$@"
  else
    buildah run $CONTAINER dnf install -y "$@"
  fi
}

if [ "$1" == "update" ]; then
  run dnf update --refresh -y
else
  if [ "${CLEAN}" == "1" ]; then
    buildah rm $CONTAINER || true
    buildah rmi -f $IMAGE_NAME || true
    buildah from --name $CONTAINER $DISTRO:$RELEASE
  fi
  run dnf update -y

  # add xpra repo:
  install wget
  run dnf config-manager setopt fedora-cisco-openh264.enabled=1
  install https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-${RELEASE}.noarch.rpm https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-${RELEASE}.noarch.rpm
  run wget -O /etc/yum.repos.d/xpra.repo https://raw.githubusercontent.com/Xpra-org/xpra/master/packaging/repos/Fedora/${REPO}.repo

  if [ "${FIREFOX}" == "1" ]; then
    install firefox
  fi

  if [ "${XPRA}" == "1" ]; then
    install xpra-server xpra-client-gtk3 xserver-xorg-video-dummy xpra-codecs xpra-audio-server xpra-codecs-extras xpra-x11 xpra-html5
  fi

  if [ "${TOOLS}" == "1" ]; then
    install xterm strace net-tools iputils
    install glx-utils
    install VirtualGL
    install xprop xrandr xdpyinfo xwininfo
  fi

  install pulseaudio pavucontrol
  install "${FILE_MANAGER}"
  install $APPS

  # install desktop environment last,
  # so we can find the applications installed when creating the cache (winbar does)
  if [ "${DESKTOP}" == "winbar" ] || [ "${DESKTOP}" == "all" ]; then
    install winbar
    # configure winbar:
    buildah run $CONTAINER setpriv --reuid "${TARGET_UID}" --regid "${TARGET_GID}" --init-groups --reset-env winbar --create-cache
    buildah copy $CONTAINER "winbar/settings.conf" "winbar/items.ini" "/home/${TARGET_USER}/.config/winbar/"
    buildah run $CONTAINER winbar --create-cache
  elif [ "${DESKTOP}" == "xfce" ] || [ "${DESKTOP}" == "all" ]; then
    install @xfce-desktop-environment
  elif [ "${DESKTOP}" == "lxde" ] || [ "${DESKTOP}" == "all" ]; then
    install @lxde-desktop
  elif [ "${DESKTOP}" == "lxqt" ] || [ "${DESKTOP}" == "all" ]; then
    install @lxqt-desktop
  elif [ "${DESKTOP}" == "mate" ] || [ "${DESKTOP}" == "all" ]; then
    install @mate-desktop
  elif [ "${DESKTOP}" == "deepin" ] || [ "${DESKTOP}" == "all" ]; then
    install @deepin-desktop
  elif [ "${DESKTOP}" == "budgie" ] || [ "${DESKTOP}" == "all" ]; then
    install @budgie-desktop
  elif [ "${DESKTOP}" == "cinnamon" ] || [ "${DESKTOP}" == "all" ]; then
    install @cinnamon-desktop
  elif [ "${DESKTOP}" == "enlightenment" ] || [ "${DESKTOP}" == "all" ]; then
    install @enlightenment-desktop
  elif [ "${DESKTOP}" == "xterm" ] || [ "${DESKTOP}" == "all" ]; then
    install xterm
  fi

  run deluser --quiet "${TARGET_USER}" || true
  run groupdel "${TARGET_GROUP}" || true
  run rm -fr /home/ubuntu "/home/${TARGET_USER}"
  run groupadd -r -g "${TARGET_GID}" "${TARGET_GROUP}"
  run adduser -uid "${TARGET_UID}" -gid "${TARGET_GID}" --disabled-password --comment "no-comment" --shell /bin/bash "${TARGET_USER}"
  run usermod -aG "${TARGET_USER_GROUPS}" "${TARGET_USER}"
  run sh -c "echo \"${TARGET_USER}:${TARGET_PASSWORD}\" | chpasswd"
  run chown -R "${TARGET_UID}:${TARGET_GID}" "/home/${TARGET_USER}"
  run sh -c "cd /home/${TARGET_USER};setpriv --reuid ${TARGET_UID} --regid ${TARGET_GID} --init-groups --reset-env mkdir -p .config/winbar Documents Downloads Music Pictures Videos Network"
fi

if [ "${DESKTOP}" == "winbar" ] || [ "${DESKTOP}" == "all" ]; then
  DE_COMMAND="winbar"
elif [ "${DESKTOP}" == "xfce" ]; then
  DE_COMMAND="xfce4-session"
elif [ "${DESKTOP}" == "lxde" ]; then
  DE_COMMAND="lxsession"
elif [ "${DESKTOP}" == "lxqt" ]; then
  DE_COMMAND="lxqt-session"
elif [ "${DESKTOP}" == "mate" ]; then
  DE_COMMAND="mate-session"
elif [ "${DESKTOP}" == "deepin" ]; then
  DE_COMMAND="deepin-menu"    # no session manager in Ubuntu?
elif [ "${DESKTOP}" == "budgie" ]; then
  DE_COMMAND="budgie-session"
elif [ "${DESKTOP}" == "cinnamon" ]; then
  DE_COMMAND="cinnamon-session"
elif [ "${DESKTOP}" == "enlightenment" ]; then
  DE_COMMAND="enlightenment"
else
  DE_COMMAND="xterm"
fi

# ugly syntax for arrays of strings with shell variables:
buildah config --entrypoint "[ \"/usr/bin/setpriv\", \"--no-new-privs\", \"--reuid\", \"${TARGET_UID}\", \"--regid\", \"${TARGET_GID}\", \"--init-groups\", \"--reset-env\", \"/bin/bash\", \"-c\", \"XDG_RUNTIME_DIR=/run/user/${TARGET_UID} DISPLAY=${XDISPLAY} ${DE_COMMAND}\" ]" $CONTAINER
buildah commit $CONTAINER $IMAGE_NAME
