#!/usr/bin/env -S podman build --tag xpra-safer --file

FROM fedora:latest

ARG USERNAME=xpra-user
ARG GROUP=xpra-group
ARG USER_GROUPS=audio,pulse,video
ARG UID=1000
ARG GID=1000
ARG PORT=10000
ARG AUTH_PORT=14500
ARG MODE=seamless

RUN dnf install -y --setopt=install_weak_deps=False wget
ADD https://raw.githubusercontent.com/Xpra-org/xpra/master/packaging/repos/Fedora/xpra-beta.repo /etc/yum.repos.d/
RUN dnf install -y xpra xpra-audio-server && \
    groupadd -r -g ${GID} ${GROUP} && \
    adduser -u ${UID} -g ${GID} --shell /bin/bash ${USERNAME} && \
    for group in $(echo ${USER_GROUPS} | tr , ' '); do \
        if getent group ${group} > /dev/null; then usermod -aG ${group} ${USERNAME}; fi; \
    done && \
    chmod 644 /etc/xpra/ssl/*.pem && \
    { test -s /etc/machine-id || rm -f /etc/machine-id; } && \
    dbus-uuidgen --ensure=/etc/machine-id

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
    --start=xterm --no-daemon

# run this container using:
#podman run --env XPRA_PASSWORD=thepassword --publish 14500:14500/tcp --publish 14500:14500/udp xpra-safer
# access it using your browser:
#xdg-open http://127.0.0.1:14500/
