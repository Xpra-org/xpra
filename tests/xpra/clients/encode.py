# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import struct
import socket
import yaml

FLAGS_YAML = 0x4

encoding = "h264"
encoder = "openh264"
width = 640
height = 480
pixel_format = "YUV420P"


def main(args):
    sockpath = args[1] if len(args) > 1 else "/run/xpra/encoder/socket"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(None)
        sock.connect(sockpath)

        def send(*args) -> None:
            payload = yaml.dump(list(args)).encode("utf-8")
            header = struct.pack(b"!cBBBL", b"P", FLAGS_YAML, 0, 0, len(payload))
            sock.send(header + payload)

        bufs = []

        def parse() -> tuple:
            if not bufs:
                return ()
            data = b"".join(bufs)
            bufs[:] = [data]
            if len(data) <= 8:
                return ()
            _, _, _, index, size = struct.unpack(b"!cBBBL", data[:8])
            assert index == 0
            if len(data) - 8 < size:
                return ()
            payload = data[8:8 + size]
            bufs[:] = [data[8 + size:]]
            return yaml.load(payload, Loader=yaml.SafeLoader)

        def recv() -> tuple:
            while True:
                packet = parse()
                if packet:
                    return packet
                data = sock.recv(1024)
                if not data:
                    return ()
                bufs.append(data)

        send("hello", {"chunks": False, "yaml": True, "version": "6.3", "encoding": {"core": ["rgb32", ]}})
        packet = recv()
        assert packet[0] == "hello"
        packet = recv()
        assert packet[0] == "encodings", f"got {packet[0]!r}"
        packet = recv()
        assert packet[0] == "startup-complete", f"got {packet[0]!r}"
        send("context-request", 0, encoder, encoding, width, height, pixel_format, {})
        packet = recv()
        assert packet[0] == "context-response", f"got {packet[0]!r}"
        metadata = {
            "x": 0,
            "y": 0,
            "width": width,
            "height": height,
            "pixel_format": pixel_format,
            "depth": 24,
            "rowstride": [width, width//2, width//2],
            "planes": 3,
        }
        pixels = [
            b"P"*(width * height),
            b"Q"*(width // 2 * height // 2),
            b"R"*(width // 2 * height // 2),
        ]
        send("context-compress", 0, metadata, pixels, {})
        packet = recv()
        assert packet[0] == "context-data", f"got {packet[0]!r}"
        data = packet[2]
        with open(f"./frame.{encoding}", "wb") as f:
            f.write(data)
        sock.close()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
