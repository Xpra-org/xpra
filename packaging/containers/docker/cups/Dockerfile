#!/usr/bin/env -S podman build --tag xpra-cups --file

# a CUPS server for the xpra server running in another container,
# both containers must share the same '/run' volume:
# * xpra adds the client's printers to this CUPS server using `lpadmin` via '/run/cups/cups.sock'
# * the applications print to those printers using the same socket
# * the `xpraforwarder` backend sends the print jobs back to the xpra server using its socket in '/run'

FROM fedora:latest

# the uid and gid of the user running the xpra server, which must match the xpra container,
# this user is allowed to add and remove printers:
ARG USERNAME=xpra-user
ARG GROUP=xpra-group
ARG UID=1000
ARG GID=1000

RUN dnf install -y --setopt=install_weak_deps=False wget
ADD https://raw.githubusercontent.com/Xpra-org/xpra/master/packaging/repos/Fedora/xpra-beta.repo /etc/yum.repos.d/
# `cups-filters` provides the generic PDF printer driver,
# `xpra-filesystem` provides the `xpraforwarder` backend, which uses `xpra print` from `xpra-client`:
RUN dnf install -y --setopt=install_weak_deps=False cups cups-filters xpra-filesystem xpra-client && \
    groupadd -r -g ${GID} ${GROUP} && \
    adduser -u ${UID} -g ${GID} --no-create-home --shell /sbin/nologin ${USERNAME} && \
    # `lpadmin` is authorized using the peer credentials of the socket connection:
    sed -i "s/^SystemGroup .*/SystemGroup root ${GROUP}/" /etc/cups/cups-files.conf && \
    # log to the container's output:
    sed -i -E "s/^#?(ErrorLog|AccessLog|PageLog) .*/\1 stderr/" /etc/cups/cups-files.conf && \
    # only listen on the socket shared with the other containers, without sharing or browsing:
    sed -i -E "/^(Listen|Port) /d; s/^Browsing .*/Browsing No/" /etc/cups/cupsd.conf && \
    echo "Listen /run/cups/cups.sock" >> /etc/cups/cupsd.conf && \
    # the backend must be executable only by root, so that cups runs it as root:
    chmod 700 /usr/lib/cups/backend/xpraforwarder && \
    dnf clean all

# the shared '/run' volume is populated by the xpra container, which must be started first
CMD ["/usr/sbin/cupsd", "-f"]

# run this container using:
#podman run --network none --volume xpra-run:/run xpra-cups
