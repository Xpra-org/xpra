#!/usr/bin/env -S podman build --tag xpra-safer-ubuntu --file

ARG RELEASE=resolute

FROM ubuntu:${RELEASE}

ARG RELEASE
ARG REPO=xpra-beta
ARG USERNAME=xpra-user
ARG GROUP=xpra-group
ARG USER_GROUPS=audio,pulse,video
ARG UID=1000
ARG GID=1000
ARG PORT=10000
ARG AUTH_PORT=14500
ARG MODE=seamless
# use Xdummy (Xorg with the dummy video driver) instead of Xvfb, set to 0 to keep Xvfb:
ARG XDUMMY=1

ENV DEBIAN_FRONTEND=noninteractive

# apt needs the CA certificates before it can use the https xpra repository:
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates
ADD --chmod=644 https://xpra.org/xpra.asc /usr/share/keyrings/
ADD --chmod=644 https://raw.githubusercontent.com/Xpra-org/xpra/master/packaging/repos/${RELEASE}/${REPO}.sources /etc/apt/sources.list.d/
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        xpra-server xpra-x11 xpra-codecs xpra-audio-server xpra-html5 \
        python3-aioquic python3-paramiko python3-cryptography \
        dbus dbus-x11 python3-dbus python3-gi-cairo python3-xdg gir1.2-rsvg-2.0 xterm xfonts-base \
        python3-cups cups-client && \
    rm -rf /var/lib/apt/lists/* && \
    { userdel --remove ubuntu 2> /dev/null || true; } && \
    groupadd -r -g ${GID} ${GROUP} && \
    useradd -m -u ${UID} -g ${GID} --shell /bin/bash ${USERNAME} && \
    install -d -m 700 -o ${UID} -g ${GID} /run/user/${UID} && \
    for group in $(echo ${USER_GROUPS} | tr , ' '); do \
        if getent group ${group} > /dev/null; then usermod -aG ${group} ${USERNAME}; fi; \
    done && \
    chmod 644 /etc/xpra/ssl/*.pem && \
    # the printers can be added to the cups server running in the `xpra-cups` container,
    # using its drivers, without probing for them when the server starts:
    printf 'pdf-printer = lsb/usr/cupsfilters/Generic-PDF_Printer-PDF.ppd\npostscript-printer = drv:///sample.drv/generic.ppd\n' \
        > /etc/xpra/conf.d/65_printing_cups_container.conf && \
    # with `--landlock=strict`, `lpadmin` can only connect to the cups socket if this directory exists when the server starts:
    install -d -m 755 /run/cups && \
    # unlike Fedora, Ubuntu's dbus package creates a separate '/var/lib/dbus/machine-id' file,
    # which no longer matches once '/etc/machine-id' is generated, so link it instead:
    { test -s /etc/machine-id || rm -f /etc/machine-id; } && \
    dbus-uuidgen --ensure=/etc/machine-id && \
    ln -sf /etc/machine-id /var/lib/dbus/machine-id
# the package defaults to Xvfb:
RUN if [ "${XDUMMY}" = "1" ]; then \
        apt-get update && \
        apt-get install -y --no-install-recommends xserver-xorg-core xserver-xorg-video-dummy && \
        rm -rf /var/lib/apt/lists/* && \
        xpra set xvfb Xdummy; \
    fi

ENV UID=$UID
ENV GID=$GID
ENV PORT=$PORT
ENV AUTH_PORT=$AUTH_PORT
ENV MODE=$MODE

# "PORT" only listens on the container's loopback interface,
# so it is only reachable from inside the container, its pod, or with `--network=host`:
EXPOSE ${AUTH_PORT}

# "AUTH_PORT" requires the password from the `XPRA_PASSWORD` environment variable:
CMD exec xpra "$MODE" --uid "$UID" --gid "$GID" \
    "--bind-tcp=127.0.0.1:$PORT" "--bind-quic=127.0.0.1:$PORT" \
    "--bind-tcp=0.0.0.0:$AUTH_PORT,auth=env" "--bind-quic=0.0.0.0:$AUTH_PORT,auth=env" \
    --border=red,5 --seccomp=strict --landlock=strict --start=xterm --no-daemon

# run this container using:
#podman run --env XPRA_PASSWORD=thepassword --publish 14500:14500/tcp --publish 14500:14500/udp xpra-safer-ubuntu
# access it using your browser:
#xdg-open http://127.0.0.1:14500/
