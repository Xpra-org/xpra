#!/usr/bin/env -S podman build --tag xpra-minimal --file

FROM alpine:latest

RUN apk update && apk add --no-cache xpra

EXPOSE 10000

CMD ["xpra", "seamless", "--bind-tcp=0.0.0.0:10000", "--start=xterm", "--no-daemon"]
