# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from math import sqrt
from typing import Any
from time import sleep, monotonic
from collections.abc import Sequence

from xpra.os_util import gi_import
from xpra.common import FULL_INFO
from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.server.window import batch_config
from xpra.server.core import ClientException
from xpra.codecs.video import getVideoHelper
from xpra.codecs.constants import VideoSpec
from xpra.net.compression import use
from xpra.server.background_worker import add_work_item
from xpra.util.objects import typedict
from xpra.util.str_fn import csv, bytestostr
from xpra.util.env import envint
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("encoding")
proxylog = Logger("proxy")
statslog = Logger("stats")

MIN_PIXEL_RECALCULATE = envint("XPRA_MIN_PIXEL_RECALCULATE", 2000)


class EncodingsMixin(StubSourceMixin):
    """
    Store information about the client's support for encodings.
    Runs the encode thread.
    """

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        return bool(caps.strtupleget("encodings")) or caps.boolget("windows")

    def init_state(self) -> None:
        # contains default values, some of which may be supplied by the client:
        self.default_batch_config = batch_config.DamageBatchConfig()
        self.global_batch_config = self.default_batch_config.clone()  # global batch config

        self.encoding = ""  # the default encoding for all windows
        self.encodings: Sequence[str] = ()  # all the encodings supported by the client
        self.core_encodings: Sequence[str] = ()
        self.full_csc_modes = dict()
        self.window_icon_encodings: Sequence[str] = ()
        self.rgb_formats: Sequence[str] = ("RGB",)
        self.encoding_options = typedict()
        self.icons_encoding_options = typedict()
        self.default_encoding_options = typedict()
        self.auto_refresh_delay: int = 0

        self.lz4 = use("lz4")

        # for managing the recalculate_delays work:
        self.calculate_window_pixels: dict[int, int] = {}
        self.calculate_window_ids: set[int] = set()
        self.calculate_timer = 0
        self.calculate_last_time: float = 0

        self.video_helper = getVideoHelper()
        self.cuda_device_context = None

    def init_from(self, _protocol, server) -> None:
        self.server_core_encodings = server.core_encodings
        self.server_encodings = server.encodings
        self.default_encoding = server.default_encoding
        self.scaling_control = server.scaling_control
        self.default_quality = server.default_quality
        self.default_min_quality = server.default_min_quality
        self.default_speed = server.default_speed
        self.default_min_speed = server.default_min_speed

    def reinit_encodings(self, server) -> None:
        self.server_core_encodings = server.core_encodings
        self.server_encodings = server.encodings

    def cleanup(self) -> None:
        self.cancel_recalculate_timer()
        if self.cuda_device_context:
            self.queue_encode((False, self.free_cuda_device_context, ()))
        # Warning: this mixin must come AFTER the window mixin!
        # to make sure that it is safe to add the end of queue marker:
        # (all window sources will have stopped queuing data)
        self.queue_encode(None)

    def free_cuda_device_context(self) -> None:
        cdd = self.cuda_device_context
        if cdd:
            self.cuda_device_context = None
            cdd.free()

    def all_window_sources(self) -> tuple:
        # we can't assume that the window mixin is loaded:
        window_sources = getattr(self, "window_sources", {})
        return tuple(window_sources.values())

    def get_caps(self) -> dict[str, str | int]:
        caps: dict[str, str | int] = {}
        if "encodings" in self.wants and self.encoding:
            caps["encoding"] = self.encoding
        if "features" in self.wants:
            caps["auto_refresh_delay"] = self.auto_refresh_delay
        return caps

    def threaded_init_complete(self, server) -> None:
        if "encodings" not in self.wants:
            return
        # by now, all the codecs have been initialized
        d = server.get_encoding_info()
        if FULL_INFO > 1:
            from xpra.codecs.loader import codec_versions
            # codec_versions: dict[str, tuple[Any, ...]] = {}
            for codec, version in codec_versions.items():
                d[codec] = {"version": version}
        self.send_async("encodings", {"encodings": d})
        # only print encoding info when not using mmap:
        if getattr(self, "mmap_size", 0) == 0:
            self.print_encoding_info()

    def recalculate_delays(self) -> None:
        """ calls update_averages() on `ServerSource.statistics` (`GlobalStatistics`)
            and `WindowSource.statistics` (`WindowPerformanceStatistics`) for each window id in calculate_window_ids,
            this runs in the worker thread.
        """
        self.calculate_timer = 0
        if self.is_closed():
            return
        now = monotonic()
        self.calculate_last_time = now
        p = self.protocol
        if not p or p.is_closed():
            return
        conn = p._conn
        if not conn:
            return
        # we can't assume that 'self' is a full ClientConnection object:
        stats = getattr(self, "statistics", None)
        if stats:
            stats.bytes_sent.append((now, conn.output_bytecount))
            stats.update_averages()
        self.update_bandwidth_limits()
        wids = tuple(self.calculate_window_ids)  # make a copy so we don't clobber new wids
        focus = self.get_focus()
        sources = self.window_sources.items()
        maximized_wids = tuple(wid for wid, source in sources if source is not None and source.maximized)
        fullscreen_wids = tuple(wid for wid, source in sources if source is not None and source.fullscreen)
        log("recalculate_delays() wids=%s, focus=%s, maximized=%s, fullscreen=%s",
            wids, focus, maximized_wids, fullscreen_wids)
        for wid in wids:
            # this is safe because we only add to this set from other threads:
            self.calculate_window_ids.remove(wid)
            self.calculate_window_pixels.pop(wid, None)
            ws = self.window_sources.get(wid)
            if ws is None:
                continue
            with log.trap_error("Error calculating delays for window %s", wid):
                ws.statistics.update_averages()
                ws.calculate_batch_delay(wid == focus,
                                         len(fullscreen_wids) > 0 and wid not in fullscreen_wids,
                                         len(maximized_wids) > 0 and wid not in maximized_wids)
                ws.reconfigure()
            if self.is_closed():
                return
            # allow other threads to run
            # (ideally this would be a low priority thread)
            sleep(0)
        # calculate weighted average as new global default delay:
        wdimsum, wdelay, tsize, tcount = 0, 0, 0, 0
        for ws in tuple(self.window_sources.values()):
            if ws.batch_config.last_updated <= 0:
                continue
            w, h = ws.window_dimensions
            tsize += w * h
            tcount += 1
            time_w = 2.0 + (now - ws.batch_config.last_updated)  # add 2 seconds to even things out
            weight = int(w * h * time_w)
            wdelay += ws.batch_config.delay * weight
            wdimsum += weight
        if wdimsum > 0 and tcount > 0:
            # weighted delay:
            delay = wdelay // wdimsum
            self.global_batch_config.last_delays.append((now, delay))
            self.global_batch_config.delay = delay
            # store the delay as a normalized value per megapixel,
            # so we can adapt it to different window sizes:
            avg_size = tsize // tcount
            ratio = sqrt(1000000.0 / avg_size)
            normalized_delay = int(delay * ratio)
            self.global_batch_config.delay_per_megapixel = normalized_delay
            log("delay_per_megapixel=%i, delay=%i, for wdelay=%i, avg_size=%i, ratio=%.2f",
                normalized_delay, delay, wdelay, avg_size, ratio)

    def may_recalculate(self, wid: int, pixel_count: int) -> None:
        if wid in self.calculate_window_ids:
            return  # already scheduled
        v = self.calculate_window_pixels.get(wid, 0) + pixel_count
        self.calculate_window_pixels[wid] = v
        if v < MIN_PIXEL_RECALCULATE:
            return  # not enough pixel updates
        statslog("may_recalculate(%i, %i) total %i pixels, scheduling recalculate work item", wid, pixel_count, v)
        self.calculate_window_ids.add(wid)
        if self.calculate_timer:
            # already due
            return
        delta = monotonic() - self.calculate_last_time
        RECALCULATE_DELAY = 1.0  # 1s
        if delta > RECALCULATE_DELAY:
            add_work_item(self.recalculate_delays)
        else:
            delay = int(1000 * (RECALCULATE_DELAY - delta))
            self.calculate_timer = GLib.timeout_add(delay, add_work_item, self.recalculate_delays)

    def cancel_recalculate_timer(self) -> None:
        ct = self.calculate_timer
        if ct:
            self.calculate_timer = 0
            GLib.source_remove(ct)

    def parse_client_caps(self, c: typedict) -> None:
        # batch options:

        def batch_value(prop, default, minv=None, maxv=None):
            assert default is not None

            def parse_batch_int(value, varname):
                if value is not None:
                    try:
                        return int(value)
                    except (TypeError, ValueError):
                        log.error("Error: invalid value '%s' for batch option %s", value, varname)
                return None

            # from client caps first:
            cpname = f"batch.{prop}"
            v = parse_batch_int(c.get(cpname), cpname)
            # try env:
            if v is None:
                evname = f"XPRA_BATCH_{prop.upper()}"
                v = parse_batch_int(os.environ.get(evname), evname)
            # fallback to default:
            if v is None:
                v = default
            if minv is not None:
                v = max(minv, v)
            if maxv is not None:
                v = min(maxv, v)
            assert v is not None
            return v

        # general features:
        self.lz4 = c.boolget("lz4", False) and use("lz4")
        self.brotli = c.boolget("brotli", False) and use("brotli")
        log("compressors: lz4=%s, brotli=%s", self.lz4, self.brotli)

        delay = batch_config.START_DELAY
        dbc = self.default_batch_config
        dbc.always = bool(batch_value("always", dbc.always))
        dbc.min_delay = batch_value("min_delay", dbc.min_delay, 0, 1000)
        dbc.max_delay = batch_value("max_delay", dbc.max_delay, 1, 15000)
        dbc.max_events = batch_value("max_events", dbc.max_events)
        dbc.max_pixels = batch_value("max_pixels", dbc.max_pixels)
        dbc.time_unit = batch_value("time_unit", dbc.time_unit, 1)
        dbc.delay = batch_value("delay", delay, dbc.min_delay)
        log("default batch config: %s", dbc)
        self.vrefresh = c.intget("vrefresh", -1)

        # encodings:
        self.encodings = c.strtupleget("encodings")
        self.core_encodings = c.strtupleget("encodings.core", self.encodings)
        self.full_csc_modes = c.dictget("full_csc_modes") or {}
        log("encodings=%s, core_encodings=%s", self.encodings, self.core_encodings)
        # we can't assume that the window mixin is loaded,
        # or that the ui_client flag exists:
        send_ui = getattr(self, "ui_client", True) and getattr(self, "send_windows", True)
        if send_ui and not self.core_encodings:
            raise ClientException("client failed to specify any supported encodings")
        self.window_icon_encodings = c.strtupleget("encodings.window-icon", ())
        # try both spellings for older versions:
        for x in ("encodings", "encoding",):
            self.rgb_formats = c.strtupleget(x + ".rgb_formats", self.rgb_formats)
        # skip all other encoding related settings if we don't send pixels:
        if not send_ui:
            log("windows/pixels forwarding is disabled for this client")
        else:
            self.parse_encoding_caps(c)

    def parse_encoding_caps(self, c: typedict) -> None:
        v = c.get("encoding")
        if isinstance(v, dict):
            self.encoding_options.update(v)
        self.set_encoding(c.strget("encoding"), None)
        # encoding options (filter):
        # 1: these properties are special cased here because we
        # defined their name before the "encoding." prefix convention,
        # or because we want to pass default values (ie: lz4):
        for k, ek in {
            "initial_quality": "initial_quality",
            "quality": "quality",
        }.items():
            if k in c:
                self.encoding_options[ek] = c.intget(k)
        for k, ek in {
            "lz4": "rgb_lz4",
        }.items():
            if k in c:
                self.encoding_options[ek] = c.boolget(k)
        # 2: standardized encoding options:
        for k in c.keys():
            k = bytestostr(k)
            if k.startswith("theme.") or k.startswith("encoding.icons."):
                self.icons_encoding_options[k.replace("encoding.icons.", "").replace("theme.", "")] = c.get(k)
            elif k.startswith("encoding."):
                stripped_k = k[len("encoding."):]
                if stripped_k in ("transparency",
                                  "rgb_lz4",
                                  ):
                    v = c.boolget(k)
                elif stripped_k in (
                        "initial_quality", "initial_speed",
                        "min-quality", "quality",
                        "min-speed", "speed",
                ):
                    v = c.intget(k)
                else:
                    v = c.get(k)
                self.encoding_options[stripped_k] = v
        log("encoding options: %s", self.encoding_options)
        log("icons encoding options: %s", self.icons_encoding_options)

        # handle proxy video: add proxy codec to video helper:
        pv = self.encoding_options.boolget("proxy.video")
        proxylog("proxy.video=%s", pv)
        if pv:
            # enabling video proxy:
            with proxylog.trap_error("Error parsing proxy video"):
                self.parse_proxy_video()

        sc = self.encoding_options.get("scaling.control", self.scaling_control)
        if sc is not None:
            self.default_encoding_options["scaling.control"] = sc
        q = self.encoding_options.intget("quality", self.default_quality)  # 0.7 onwards:
        if q > 0:
            self.default_encoding_options["quality"] = q
        mq = self.encoding_options.intget("min-quality", self.default_min_quality)
        if mq > 0 and (q <= 0 or q > mq):
            self.default_encoding_options["min-quality"] = mq
        s = self.encoding_options.intget("speed", self.default_speed)
        if s > 0:
            self.default_encoding_options["speed"] = s
        ms = self.encoding_options.intget("min-speed", self.default_min_speed)
        if ms > 0 and (s <= 0 or s > ms):
            self.default_encoding_options["min-speed"] = ms
        log("default encoding options: %s", self.default_encoding_options)
        self.auto_refresh_delay = c.intget("auto_refresh_delay", 0)

        # are we going to need a cuda context?
        if getattr(self, "mmap_enabled", False):
            # not with mmap!
            return
        common_encodings = tuple(x for x in self.encodings if x in self.server_encodings)
        from xpra.codecs.loader import has_codec
        want_cuda_device = any((
            has_codec("nvenc") and ("h264" in self.core_encodings or "h265" in self.core_encodings),
            "jpeg" in common_encodings and has_codec("enc_nvjpeg"),
        ))
        if want_cuda_device:
            cudalog = Logger("cuda")
            try:
                # pylint: disable=import-outside-toplevel
                from xpra.codecs.nvidia.cuda.context import get_device_context
            except ImportError as e:
                cudalog(f"unable to import cuda context: {e}")
                return None
            try:
                self.cuda_device_context = get_device_context(self.encoding_options)
                cudalog("cuda_device_context=%s", self.cuda_device_context)
            except Exception as e:
                cudalog("failed to get a cuda device context using encoding options %s",
                        self.encoding_options, exc_info=True)
                cudalog.error("Error: failed to allocate a CUDA context:")
                cudalog.estr(e)
                cudalog.error(" NVJPEG and NVENC will not be available")

    def print_encoding_info(self) -> None:
        log("print_encoding_info() core-encodings=%s, server-core-encodings=%s",
            self.core_encodings, self.server_core_encodings)
        others = tuple(x for x in self.core_encodings
                       if x in self.server_core_encodings and x != self.encoding)
        if self.encoding == "auto":
            s = "automatic picture encoding enabled"
        elif self.encoding == "stream":
            s = "streaming mode enabled"
        else:
            s = f"using {self.encoding!r} as primary encoding"
        if others:
            log.info(f" {s}, also available:")
            log.info("  " + csv(others))
        else:
            log.warn(f" {s}")
            log.warn("  no other encodings are available!")

    def parse_proxy_video(self) -> None:
        self.wait_for_threaded_init()
        proxy_video_encodings = self.encoding_options.get("proxy.video.encodings")
        proxylog("parse_proxy_video() proxy.video.encodings=%s", proxy_video_encodings)
        if not proxy_video_encodings:
            return
        from xpra.codecs.proxy.encoder import Encoder  # pylint: disable=import-outside-toplevel
        cloned = False
        for encoding, colorspace_specs in proxy_video_encodings.items():
            for colorspace, spec_props in colorspace_specs.items():
                for spec_prop in spec_props:
                    # make a new spec based on spec_props:
                    spec_prop = typedict(spec_prop)
                    input_colorspace = spec_prop.strget("input_colorspace")
                    output_colorspaces = spec_prop.strtupleget("output_colorspaces")
                    if not input_colorspace or not output_colorspaces:
                        log.warn("Warning: invalid proxy video encoding '%s':", encoding)
                        log.warn(" missing colorspace attributes")
                        continue
                    spec = VideoSpec(codec_class=Encoder,
                                     has_lossless_mode=spec_prop.boolget("has_lossless_mode", False),
                                     input_colorspace=input_colorspace,
                                     output_colorspaces=output_colorspaces,
                                     codec_type="proxy", encoding=encoding,
                                     )
                    for k, v in spec_prop.items():
                        if k.startswith("_") or not hasattr(spec, k):
                            log.warn("Warning: invalid proxy codec attribute '%s'", k)
                            continue
                        setattr(spec, k, v)
                    proxylog("parse_proxy_video() adding: %s / %s / %s", encoding, colorspace, spec)
                    if not cloned:
                        # if we "proxy video", we will modify the video helper to add
                        # new encoders, so we must make a deep copy to preserve the original
                        # which may be used by other clients (other ServerSource instances)
                        self.video_helper = getVideoHelper().clone()
                        cloned = True
                    self.video_helper.add_encoder_spec(encoding, colorspace, spec)

    ######################################################################
    # Functions used by the server to request something
    # (window events, stats, user requests, etc)
    #
    def set_auto_refresh_delay(self, delay: int, window_ids) -> None:
        if window_ids is not None:
            wss = (self.window_sources.get(wid) for wid in window_ids)
        else:
            wss = self.all_window_sources()
        for ws in wss:
            if ws is not None:
                ws.set_auto_refresh_delay(delay)

    def set_encoding(self, encoding: str, window_ids, strict=False) -> None:
        """ Changes the encoder for the given 'window_ids',
            or for all windows if 'window_ids' is None.
        """
        log("set_encoding(%s, %s, %s)", encoding, window_ids, strict)
        if encoding and encoding not in ("auto", "stream"):
            # old clients (v0.9.x and earlier) only supported 'rgb24' as 'rgb' mode:
            if encoding == "rgb24":
                encoding = "rgb"
            if encoding not in self.encodings:
                log.warn(f"Warning: client specified {encoding!r} encoding,")
                log.warn(" but it only supports: " + csv(self.encodings))
            if encoding not in self.server_encodings:
                log.error(f"Error: encoding {encoding!r} is not supported by this server")
                log.error(" server encodings: " + csv(self.server_encodings))
                encoding = ""
        if not encoding:
            encoding = "auto"
        if window_ids is not None:
            wss = [self.window_sources.get(wid) for wid in window_ids]
        else:
            wss = self.all_window_sources()
        # if we're updating all the windows, reset global stats too:
        if set(wss).issuperset(self.all_window_sources()):
            log("resetting global stats")
            # we can't assume that 'self' is a full ClientConnection object:
            stats = getattr(self, "statistics", None)
            if stats:
                stats.reset()
            self.global_batch_config = self.default_batch_config.clone()
        for ws in wss:
            if ws is not None:
                ws.set_new_encoding(encoding, strict)
        if not window_ids:
            self.encoding = encoding

    def get_info(self) -> dict[str, Any]:
        einfo = {
            "default": self.default_encoding or "",
            "defaults": dict(self.default_encoding_options),
            "client-defaults": dict(self.encoding_options),
        }
        ieo = dict(self.icons_encoding_options)
        ieo.pop("default.icons", None)
        info: dict[str, Any] = {
            "auto_refresh": self.auto_refresh_delay,
            "lz4": self.lz4,
            "encodings": {
                "": self.encodings,
                "core": self.core_encodings,
                "window-icon": self.window_icon_encodings,
            },
            "icons": ieo,
            "encoding": einfo,
        }
        return info

    def set_min_quality(self, min_quality: int) -> None:
        for ws in tuple(self.all_window_sources()):
            ws.set_min_quality(min_quality)

    def set_max_quality(self, max_quality: int) -> None:
        for ws in tuple(self.all_window_sources()):
            ws.set_max_quality(max_quality)

    def set_quality(self, quality: int) -> None:
        for ws in tuple(self.all_window_sources()):
            ws.set_quality(quality)

    def set_min_speed(self, min_speed: int) -> None:
        for ws in tuple(self.all_window_sources()):
            ws.set_min_speed(min_speed)

    def set_max_speed(self, max_speed: int) -> None:
        for ws in tuple(self.all_window_sources()):
            ws.set_max_speed(max_speed)

    def set_speed(self, speed: int) -> None:
        for ws in tuple(self.all_window_sources()):
            ws.set_speed(speed)

    def make_batch_config(self, wid: int, window):
        config = self.default_batch_config.clone()
        config.wid = wid
        # scale initial delay based on window size
        # (the global value is normalized to 1MPixel)
        # but use sqrt to smooth things and prevent excesses
        # (ie: a 4MPixel window, will start at 2 times the global delay)
        # (ie: a 0.5MPixel window will start at 0.7 times the global delay)
        dpm = self.global_batch_config.delay_per_megapixel
        w, h = window.get_dimensions()
        if dpm >= 0:
            ratio = sqrt(1000000.0 / (w * h))
            config.delay = max(config.min_delay, min(config.max_delay, int(dpm * sqrt(ratio))))
        log("make_batch_config(%i, %s) global delay per megapixel=%i, new window delay for %ix%i=%s",
            wid, window, dpm, w, h, config.delay)
        return config
