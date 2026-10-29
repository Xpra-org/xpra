#!/usr/bin/env -S podman build --tag xpra-base --file

FROM fedora:latest

RUN dnf install -y --setopt=install_weak_deps=False wget
ADD https://raw.githubusercontent.com/Xpra-org/xpra/master/packaging/repos/Fedora/xpra-beta.repo /etc/yum.repos.d/
RUN dnf install -y xpra xpra-audio-server && \
    # the printers can be added to the cups server running in the `xpra-cups` container,
    # using its drivers, without probing for them when the server starts:
    printf 'pdf-printer = lsb/usr/cupsfilters/Generic-PDF_Printer-PDF.ppd\npostscript-printer = drv:///sample.drv/generic.ppd\n' \
        > /etc/xpra/conf.d/65_printing_cups_container.conf

EXPOSE 10000

CMD ["xpra", "seamless", "--bind-tcp=0.0.0.0:10000", "--bind-quic=0.0.0.0:10000", "--start=xterm", "--no-daemon", "--env=XPRA_NO_ROOT_WARNING=1"]

# run this container using:
#podman run --publish 10000:10000/tcp --publish 10000:10000/udp xpra-base
# access it using your browser:
#xdg-open http://127.0.0.1:10000/
