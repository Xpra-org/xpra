#!/bin/bash
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

set -e

DISTRO="${DISTRO:-ubuntu}"
RELEASE="${RELEASE:-plucky}"
IMAGE_NAME="${IMAGE_NAME:-apps}"
CONTAINER="$DISTRO-$RELEASE-$IMAGE_NAME"
CLEAN="${CLEAN:-1}"
REPO="${REPO:-xpra-beta}"
TRIM="${TRIM:-1}"
XDISPLAY="${XDISPLAY:-:10}"
SEAMLESS="${SEAMLESS:-1}"
TOOLS="${TOOLS:-0}"
FILE_MANAGER="${FILE_MANAGER:-nemo}"
XPRA="${XPRA:-0}"
APPS="${APPS:-libreoffice lxterminal vlc gimp}"
FIREFOX="${FIREFOX:-1}"
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
    run apt-get install -y --no-install-recommends "$@"
  else
    run apt-get install -y "$@"
  fi
}

if [ "$1" == "update" ]; then
  run apt-get update
  run apt-get dist-upgrade -y
else
  if [ "${CLEAN}" == "1" ]; then
    buildah rm $CONTAINER || true
    buildah rmi -f $IMAGE_NAME || true
    buildah from --name $CONTAINER $DISTRO:$RELEASE
  fi
  run apt-get update

  copy "../fs/etc/default/keyboard" "../fs/etc/default/locale" "/etc/default/"
  run sh -c "echo $TIMEZONE > /etc/timezone;ln -sf /usr/share/zoneinfo/$TIMEZONE /etc/localtime"

  # add xpra repo:
  install adduser wget ca-certificates
  run wget -O "/usr/share/keyrings/xpra.asc" "https://xpra.org/xpra.asc"
  run wget -O "/etc/apt/sources.list.d/${REPO}.sources" "https://raw.githubusercontent.com/Xpra-org/xpra/master/packaging/repos/${RELEASE}/${REPO}.sources"
  run apt-get update

  if [ "${FIREFOX}" == "1" ]; then
    copy "../fs/etc/apt/preferences.d/mozilla-firefox" "/etc/apt/preferences.d/"
    install software-properties-common
    run add-apt-repository -y ppa:mozillateam/ppa
    install firefox
  fi

  if [ "${XPRA}" == "1" ]; then
    install xpra-server xpra-client-gtk3 xserver-xorg-video-dummy xpra-codecs xpra-audio-server xpra-codecs-extras xpra-x11 xpra-html5
  fi

  if [ "${TOOLS}" == "1" ]; then
    # add some applications:
    install xterm strace net-tools iputils-ping
    # toys useful for testing video encoders, costs ~30MB:
    install mesa-utils
    run sh -c "wget https://github.com/VirtualGL/virtualgl/releases/download/3.1.3/virtualgl_3.1.3_amd64.deb;apt-get install ./virtualgl_3.1.3_amd64.deb -y;rm virtualgl*.deb"
    # xrandr, xdpyinfo etc, costs ~15MB:
    install x11-xserver-utils x11-utils vulkan-tools
  fi

  install pulseaudio pavucontrol
  install "${FILE_MANAGER}"
  install $APPS

  # install desktop environment last,
  # so we can find the applications installed when creating the cache (winbar does)
  if [ "${DESKTOP}" == "winbar" ] || [ "${DESKTOP}" == "all" ]; then
    install winbar
    # configure winbar:
    run setpriv --reuid "${TARGET_UID}" --regid "${TARGET_GID}" --init-groups --reset-env winbar --create-cache
    copy "../fs/winbar/settings.conf" "winbar/items.ini" "/home/${TARGET_USER}/.config/winbar/"
    run winbar --create-cache
  fi
  if [ "${DESKTOP}" == "xfce4" ] || [ "${DESKTOP}" == "all" ]; then
    install xfce4
  fi
  if [ "${DESKTOP}" == "lxde" ] || [ "${DESKTOP}" == "all" ]; then
    install lxde lxpanel
  fi
  if [ "${DESKTOP}" == "lxqt" ] || [ "${DESKTOP}" == "all" ]; then
    install lxqt-session lxqt-panel lxqt
  fi
  if [ "${DESKTOP}" == "mate" ] || [ "${DESKTOP}" == "all" ]; then
    install mate-desktop mate-desktop-environment mate-control-center mate-hud mate-media
  fi
  if [ "${DESKTOP}" == "deepin" ] || [ "${DESKTOP}" == "all" ]; then
    install deepin-calculator deepin-image-viewer deepin-menu deepin-music deepin-notifications deepin-terminal
  fi
  if [ "${DESKTOP}" == "budgie" ] || [ "${DESKTOP}" == "all" ]; then
    install budgie-desktop budgie-desktop-environment budgie-desktop-view budgie-previews budgie-session budgie-control-center
  fi
  if [ "${DESKTOP}" == "cinnamon" ] || [ "${DESKTOP}" == "all" ]; then
    install cinnamon-desktop-environment nemo cinnamon-session
  fi
  if [ "${DESKTOP}" == "enlightenment" ] || [ "${DESKTOP}" == "all" ]; then
    install enlightenment eterm terminology
  fi
  if [ "${DESKTOP}" == "xterm" ] || [ "${DESKTOP}" == "all" ]; then
    install xterm
  fi

  # remove the default "ubuntu" user, and add our one:
  run deluser --quiet "ubuntu" || true
  run groupdel "ubuntu" || true
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


# default DE commands:
# ie: "mate" -> "mate-"
# overriden for "lxde" -> "lx" for "lxsession" and "lxpanel"
DE_COMMAND_PREFIX="${DESKTOP}-"
if [ "${DESKTOP}" == "lxde" ]; then
  DE_COMMAND_PREFIX="lx"
fi

if [ "${SEAMLESS}" == "1" ]; then
  DE_COMMAND="${DE_COMMAND_PREFIX}-panel"
else
  DE_COMMAND="${DE_COMMAND_PREFIX}-session"
fi

# known issues:
# * xfce4-panel keeps moving!

if [ "${DESKTOP}" == "winbar" ] || [ "${DESKTOP}" == "all" ]; then
  DE_COMMAND="winbar"
elif [ "${DESKTOP}" == "xfce4" ]; then
  echo "${DESKTOP} known issue: panel keeps moving"
elif [ "${DESKTOP}" == "deepin" ]; then
  DE_COMMAND="deepin-menu"    # no session manager in Ubuntu?
elif [ "${DESKTOP}" == "enlightenment" ]; then
  if [ "${SEAMLESS}" == "1" ]; then
    echo "no seamless mode with ${DESKTOP}"
    DE_COMMAND="xterm"
  else
    DE_COMMAND="enlightenment"
  fi
elif [ "${DESKTOP}" == "xterm" ]; then
  DE_COMMAND="xterm"
fi

# ugly syntax for arrays of strings with shell variables:
buildah config --entrypoint "[ \"/usr/bin/setpriv\", \"--no-new-privs\", \"--reuid\", \"${TARGET_UID}\", \"--regid\", \"${TARGET_GID}\", \"--init-groups\", \"--reset-env\", \"/bin/bash\", \"-c\", \"XDG_RUNTIME_DIR=/run/user/${TARGET_UID} DISPLAY=${XDISPLAY} ${DE_COMMAND}\" ]" $CONTAINER
buildah commit $CONTAINER $IMAGE_NAME
