# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Sequence, Any

from xpra.client.base.command import HelloRequestClient
from xpra.client.mixins.mmap import MmapClient
from xpra.exit_codes import ExitCode
from xpra.net.common import PacketType
from xpra.util.io import load_binary_file
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("client", "encoding")


class EncodeClient(HelloRequestClient, MmapClient):
    """
    Sends the file(s) to the server for encoding,
    saves the result in the current working directory
    this requires a server version 6.3 or later
    """

    def __init__(self, options, filenames: Sequence[str]):
        if not filenames:
            raise ValueError("please specify some filenames to encode")
        HelloRequestClient.__init__(self, options)
        MmapClient.__init__(self)
        self.filenames = list(filenames)
        self.add_packets("encode-response", "encodings")
        from xpra.codecs.pillow.decoder import get_encodings, decompress
        self.encodings = get_encodings()
        self.decompress = decompress
        encodings = ("png", "jpeg")
        self.encoding_options = {
            "options": encodings,
            "core": encodings,
            "setting": options.encoding,
        }
        for attr, value in {
            "quality": options.quality,
            "min-quality": options.min_quality,
            "speed": options.speed,
            "min-speed": options.min_speed,
        }.items():
            if value > 0:
                self.encoding_options[attr] = value

    def init(self, opts) -> None:
        if opts.mmap.lower() == "auto":
            opts.mmap = "yes"
        HelloRequestClient.init(self, opts)
        MmapClient.init(self, opts)

    def setup_connection(self, conn):
        # must do mmap first to ensure the mmap areas are initialized:
        MmapClient.setup_connection(self, conn)
        # because HelloRequestClient will call get_caps() to retrieve them
        return HelloRequestClient.setup_connection(self, conn)

    def client_type(self) -> str:
        return "encoder"

    def _process_encodings(self, packet: PacketType) -> None:
        encodings = typedict(packet[1]).dictget("encodings", {}).get("core", ())
        common = tuple(set(self.encodings) & set(encodings))
        log("server encodings=%s, common=%s", encodings, common)

    def _process_encode_response(self, packet: PacketType) -> None:
        encoding, data, options, width, height, bpp, stride, metadata = packet[1:9]
        log("encode-response: %8s %6i bytes, %5ix%-5i %ibits, stride=%i, options=%s, metadata=%s",
            encoding, len(data), width, height, bpp, stride, options, metadata)
        filename = typedict(metadata).strget("filename")
        if not filename:
            log.error("Error: 'filename' is missing from the metadata")
            self.quit(ExitCode.NO_DATA)
            return
        save_as = os.path.splitext(os.path.basename(filename))[0] + f".{encoding}"
        with open(save_as, "wb") as f:
            f.write(data)
        log.info(f"saved %i bytes to {save_as!r}", len(data))
        if not self.filenames:
            self.quit(ExitCode.OK)
            return
        self.send_encode()

    def hello_request(self) -> dict[str, Any]:
        hello = {
            "request": "encode",
            "ui_client": True,
            "encoding": self.encoding_options,
        }
        hello.update(MmapClient.get_caps(self))
        log(f"{hello=}")
        return hello

    def do_command(self, caps: typedict) -> None:
        log(f"{caps=}")
        self._protocol.large_packets.append("encode")
        self.send_encode()

    def send_encode(self):
        filename = self.filenames.pop(0)
        log(f"send_encode() {filename=!r}")
        ext = filename.split(".")[-1]
        if ext not in self.encodings:
            log.warn(f"Warning: {ext!r} format is not supported")
            log.warn(" use %s", " or ".join(self.encodings))
            self.quit(ExitCode.UNSUPPORTED)
            return
        img_data = load_binary_file(filename)
        options = typedict()
        rgb_format, raw_data, width, height, rowstride = self.decompress(ext, img_data, options)
        encoding = "rgb"
        encode_options = {}
        if self.mmap_write_area and self.mmap_write_area.enabled:
            mmap_data = self.mmap_write_area.write_data(raw_data)
            log("mmap_write_area=%s, mmap_data=%s", self.mmap_write_area.get_info(), mmap_data)
            encoding = "mmap"
            data = b""
            encode_options["chunks"] = mmap_data
        elif self.compression_level > 0:
            from xpra.net.lz4.lz4 import compress
            data = compress(raw_data)
            encode_options["lz4"] = 1
            log("lz4 compressed from %i bytes down to %i", len(raw_data), len(data))
        else:
            log("sending uncompressed")
            data = raw_data

        metadata = {"filename": filename}
        self.send("encode", encoding, rgb_format, data, width, height, rowstride, encode_options, metadata)
