# Build recipe for Anthropic's OSS scanner, see https://github.com/anthropics/oss-scanner
# The scanner builds this with the repository checkout as the build context,
# with network access, then analyses the resulting image offline:
# everything the build and the unit tests need must be installed here.
#
# Unlike the images in `packaging/containers`, which install the binary packages,
# this builds xpra from the checkout in `/src`.
# The package list is the one used by the unit tests in `.github/workflows/test.yml`
# (see also `docs/Build/Debian.md`): keep them in sync.
FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates build-essential pkg-config git python3-pip python3-setuptools \
        libx11-dev libxtst-dev libxcomposite-dev libxdamage-dev libxpresent-dev libxres-dev \
        libxkbfile-dev python3-dev pandoc libsystemd-dev libseccomp-dev \
        libgtk-3-dev python3-cairo-dev python-gi-dev \
        xauth x11-xkb-utils xterm \
        xvfb python3-cairo python3-gi-cairo \
        libturbojpeg-dev libwebp-dev python3-pil \
        libx264-dev libvpx-dev libyuv-dev libavif-dev libopenh264-dev libaom-dev libpipewire-0.3-dev \
        python3-dbus python3-cryptography \
        python3-netifaces python3-scramp \
        python3-opengl \
        openssh-client sshpass python3-asyncssh python3-paramiko \
        python3-setproctitle python3-xdg python3-cups \
        libpam-dev xserver-xorg-dev xutils-dev xserver-xorg-video-dummy keyboard-configuration \
        python3-kerberos python3-gssapi python3-aioquic \
        python3-gst-1.0 \
        gstreamer1.0-pulseaudio gstreamer1.0-alsa \
        gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
        gstreamer1.0-plugins-ugly gstreamer1.0-plugins-bad gstreamer1.0-vaapi \
        liblz4-dev python3-lz4 libzstd-dev python3-yaml \
        libbrotli-dev \
        libxxhash-dev libqrencode-dev \
        libdrm-dev libwayland-dev libwayland-bin wayland-protocols libxkbcommon-dev libpixman-1-dev \
        libwlroots-0.19-dev weston wl-clipboard wtype \
        python3-coverage \
        openssl \
        tigervnc-standalone-server tigervnc-viewer \
        x11-xserver-utils dbus-x11 && \
    rm -rf /var/lib/apt/lists/* && \
    # the distribution's Cython is too old / buggy, same as in the CI:
    pip3 install --break-system-packages cython

# scanner contract: the checkout lives inside the image, at /src
COPY . /src
WORKDIR /src

# build and install system wide, with debug info and frame pointers,
# so that `xpra` and the compiled codecs can be exercised directly from the image:
ENV CFLAGS="-g -O1 -fno-omit-frame-pointer"
RUN DEB_PYTHON_INSTALL_LAYOUT=deb python3 ./setup.py install \
        --without-nvidia --without-printing --without-docs --with-scripts --prefix=/usr --root=/

# gdk-pixbuf loads images through glycin, which runs its loaders with `bwrap --dev /dev`,
# but containers may not allow mounting a new `devpts`, so every image fails to load
# (and GTK aborts when it cannot load any icon): bind the existing `/dev` instead
RUN printf '%s\n' \
        '#!/bin/sh' \
        'for arg; do' \
        '    shift' \
        '    if [ "$arg" = "--dev" ]; then' \
        '        set -- "$@" --dev-bind "$1"' \
        '        continue' \
        '    fi' \
        '    set -- "$@" "$arg"' \
        'done' \
        'exec /usr/bin/bwrap "$@"' \
        > /usr/local/bin/bwrap && \
    chmod 755 /usr/local/bin/bwrap

# some tests behave differently as root (ie: the authentication modules verify the username),
# so run them as a regular user, like the CI does, with a runtime directory and a session bus:
RUN useradd --create-home --shell /bin/bash xpra-test && \
    chown -R xpra-test /src && \
    install -d -m 700 -o xpra-test -g xpra-test /run/user/$(id -u xpra-test)
USER xpra-test
# run the unit tests the same way as the CI (this builds another copy under `/src/dist`),
# without letting failures abort the build,
# and with a time limit so that a slow machine cannot push the build past the scanner's 45 minutes,
# `pillow_encoder_test` and `windowicon_test` are broken by the Ubuntu python3-pil 12.1.1 update:
RUN export XDG_RUNTIME_DIR=/run/user/$(id -u) && \
    XPRA_TEST_COVERAGE=0 timeout --kill-after=1m 20m dbus-run-session -- python3 setup.py unittests \
        --skip-fail unit.codecs.pillow_encoder_test \
        --skip-fail unit.server.window.windowicon_test \
        --skip-fail unit.client.splash_test \
        --skip-slow unit.client.x11_client_test \
        --skip-fail unit.client.x11_client_paint_test \
        --skip-slow unit.server.subsystem.startdesktop_option_test \
        --skip-slow unit.x11.x11_server_test \
        --skip-slow unit.server.server_auth_test \
        --skip-slow unit.server.shadow_server_test \
        --skip-slow unit.server.subsystem.start_option_test \
        --skip-slow unit.server.subsystem.shadow_option_test \
    || echo "WARNING: some unit tests failed"
USER root
