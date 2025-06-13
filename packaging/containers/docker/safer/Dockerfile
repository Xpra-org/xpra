#!/usr/bin/env -S podman build --tag xpra-safer --file

FROM fedora:latest

ARG USERNAME=xpra-user
ARG PASSWORD=default
ARG GROUP=xpra-group
ARG USER_GROUPS=audio,pulse,video
ARG UID=1000
ARG GID=1000
ARG PORT=10000
ARG MODE=seamless

RUN dnf install -y --setopt=install_weak_deps=False wget
RUN wget -O /etc/yum.repos.d/xpra.repo https://raw.githubusercontent.com/Xpra-org/xpra/master/packaging/repos/Fedora/xpra-beta.repo
RUN dnf install -y xpra xpra-audio-server

RUN echo command: groupadd -r -g ${GID} $USERNAME
RUN groupadd -r -g ${GID} ${USERNAME}
RUN adduser -u ${UID} -g ${GID} --shell /bin/bash ${USERNAME}
RUN usermod -aG ${USER_GROUPS} ${USERNAME}
RUN echo "${USERNAME}:${PASSWORD}" | chpasswd
RUN mkdir -m 755 -p /var/lib/dbus && dbus-uuidgen > /var/lib/dbus/machine-id

ENV UID=$UID
ENV GID=$GID
ENV PORT=$PORT
ENV MODE=$MODE

EXPOSE ${PORT}

CMD xpra $MODE --uid $UID --gid $GID --bind-tcp=0.0.0.0:$PORT --bind-quic=0.0.0.0:$PORT --start=xterm --no-daemon

# run this container using:
#podman run -publish 10000:10000/tcp --publish 10000:10000/udp xpra-safer
# access it using your browser:
#xdg-open http://127.0.0.1:10000/
