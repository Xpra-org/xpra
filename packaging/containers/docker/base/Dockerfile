#!/usr/bin/env -S podman build --tag xpra-base --file

FROM fedora:latest

RUN dnf install -y --setopt=install_weak_deps=False wget
RUN wget -O /etc/yum.repos.d/xpra.repo https://raw.githubusercontent.com/Xpra-org/xpra/master/packaging/repos/Fedora/xpra-beta.repo
RUN dnf install -y xpra xpra-audio-server

EXPOSE 10000

CMD ["xpra", "seamless", "--bind-tcp=0.0.0.0:10000", "--bind-quic=0.0.0.0:10000", "--start=xterm", "--no-daemon", "--env=XPRA_NO_ROOT_WARNING=1"]
