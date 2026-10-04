#!/usr/bin/env -S podman build --tag xpra-minimal --file

FROM alpine:latest

RUN apk update && \
    apk add --no-cache xpra xterm && \
    mkdir /usr/share/xpra/www && \
    cd /usr/share/xpra/www && \
    wget https://xpra.org/src/xpra-html5-20.tar.xz && \
    html5_dir="$(tar -Jtf xpra-html5-20.tar.xz | sed -n '1s|/.*|/html5|p')" && \
    tar -Jxf xpra-html5-20.tar.xz "$html5_dir" --strip-components=2 && \
    rm -f xpra-html5-20.tar.xz

EXPOSE 10000

CMD ["xpra", "seamless", "--bind-tcp=0.0.0.0:10000", "--start=xterm", "--no-daemon"]

# run this container using:
#podman run --publish 10000:10000/tcp --publish 10000:10000/udp xpra-base
# access it using your browser:
#xdg-open http://127.0.0.1:10000/
