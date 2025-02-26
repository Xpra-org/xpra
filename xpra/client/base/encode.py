# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Sequence, Any

from xpra.client.base.command import HelloRequestClient
from xpra.codecs.pillow.decoder import get_encodings, decompress
from xpra.exit_codes import ExitCode
from xpra.net.common import PacketType
from xpra.util.io import load_binary_file
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("client", "encoding")

EXT_ALIASES = {"jpg": "jpeg"}


def get_client_base_classes() -> tuple[type, ...]:
    from xpra.client.base import features

    classes: list[type] = []
    # Warning: MmapClient must come first,
    # so it is initialized by the time HelloRequestClient creates the hello packet
    if features.mmap:
        from xpra.client.mixins.mmap import MmapClient
        classes.append(MmapClient)
    classes.append(HelloRequestClient)
    return tuple(classes)


CLIENT_BASES = get_client_base_classes()
ClientBaseClass = type('ClientBaseClass', CLIENT_BASES, {})


class EncodeClient(ClientBaseClass):
    """
    Sends the file(s) to the server for encoding,
    saves the result in the current working directory
    this requires a server version 6.3 or later
    """

    def __init__(self, options, filenames: Sequence[str]):
        if not filenames:
            raise ValueError("please specify some filenames to encode")
        for cc in CLIENT_BASES:
            args = (options, ) if cc == HelloRequestClient else ()
            cc.__init__(self, *args)
        self.filenames = list(filenames)
        self.add_packets("encode-response", "encodings")
        self.decompress = decompress
        self.encoding_options = {}
        self.encodings = get_encodings()

    def init(self, opts) -> None:
        if opts.mmap.lower() == "auto":
            opts.mmap = "yes"
        for cc in CLIENT_BASES:
            cc.init(self, opts)
        if opts.encoding and opts.encoding not in self.encodings:
            self.encodings = tuple(list(self.encodings) + [opts.encoding])
        self.encoding_options = {
            "options": self.encodings,
            "core": self.encodings,
            "setting": opts.encoding,
        }
        for attr, value in {
            "quality": opts.quality,
            "min-quality": opts.min_quality,
            "speed": opts.speed,
            "min-speed": opts.min_speed,
        }.items():
            if value > 0:
                self.encoding_options[attr] = value

    def setup_connection(self, conn) -> None:
        for cc in CLIENT_BASES:
            cc.setup_connection(self, conn)

    def server_connection_established(self, c: typedict) -> bool:
        for cc in CLIENT_BASES:
            if not cc.parse_server_capabilities(self, c):
                return False
        # this will call do_command()
        return super().server_connection_established(c)

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
        hello = {}
        for cc in CLIENT_BASES:
            hello.update(cc.get_caps(self))
        hello = {
            "request": "encode",
            "ui_client": True,
            "encoding": self.encoding_options,
        }
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
        ext = EXT_ALIASES.get(ext, ext)
        if ext not in self.encodings:
            log.warn(f"Warning: {ext!r} format is not supported")
            log.warn(" use %s", " or ".join(self.encodings))
            self.quit(ExitCode.UNSUPPORTED)
            return
        img_data = load_binary_file(filename)
        options = typedict()
        rgb_format, raw_data, width, height, rowstride = self.decompress(ext, img_data, options)
        # video encoders prefer BGRA pixel order:
        if rgb_format == "RGBA":
            from xpra.codecs.argb.argb import rgba_to_bgra
            raw_data = rgba_to_bgra(raw_data)
            rgb_format = "BGRX"
        elif rgb_format == "RGB":
            from xpra.codecs.argb.argb import rgb_to_bgrx
            raw_data = rgb_to_bgrx(raw_data)
            rgb_format = "BGRX"
            rowstride = rowstride * 4 // 3
        encoding = "rgb"
        encode_options = {}
        if self.compression_level > 0:
            from xpra.net.lz4.lz4 import compress
            data = compress(raw_data)
            encode_options["lz4"] = 1
            log("lz4 compressed from %i bytes down to %i", len(raw_data), len(data))
        else:
            log("sending uncompressed")
            data = raw_data

        mmap_write_area = getattr(self, "mmap_write_area", None)
        if mmap_write_area and mmap_write_area.enabled:
            mmap_data = mmap_write_area.write_data(data)
            log("mmap_write_area=%s, mmap_data=%s", mmap_write_area.get_info(), mmap_data)
            encoding = "mmap"
            data = b""
            encode_options["chunks"] = mmap_data

        metadata = {"filename": filename}
        self.send("encode", encoding, rgb_format, data, width, height, rowstride, encode_options, metadata)
