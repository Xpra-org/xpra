#!/usr/bin/env python
# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013, 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from threading import Lock
from xpra.log import Logger
log = Logger("codec", "video")

from xpra.codecs.loader import get_codec

instance = None

#all the modules we know about:
ALL_VIDEO_ENCODER_OPTIONS = ["vpx", "x264", "nvenc"]
ALL_CSC_MODULE_OPTIONS = ["swscale", "cython", "opencl", "nvcuda"]
PREFERRED_ENCODER_ORDER = ["nvenc", "x264", "vpx"]
log("video_helper: ALL_VIDEO_ENCODER_OPTIONS=%s", ALL_VIDEO_ENCODER_OPTIONS)
log("video_helper: ALL_CSC_MODULE_OPTIONS=%s", ALL_CSC_MODULE_OPTIONS)


def get_video_module_name(x):
        if x.find("enc")>=0:
            return x            #ie: "nvenc" or "enc_vpx"
        return "enc_"+x         #ie: "enc_x264"

def get_csc_module_name(x):
    return "csc_"+x             #ie: "csc_swscale"


def get_DEFAULT_VIDEO_ENCODERS():
    """ returns all the video encoders installed """
    encoders = []
    for x in list(ALL_VIDEO_ENCODER_OPTIONS):
        mod = get_video_module_name(x)
        c = get_codec(mod)
        if c:
            encoders.append(x)
    return encoders

def get_DEFAULT_CSC_MODULES():
    """ returns all the csc modules installed """
    csc = []
    for x in list(ALL_CSC_MODULE_OPTIONS):
        mod = get_csc_module_name(x)
        c = get_codec(mod)
        if c:
            csc.append(x)
    return csc


class VideoHelper(object):

    def __init__(self, vspecs={}, cscspecs={}, init=False):
        self._video_encoder_specs = vspecs
        self._csc_encoder_specs = cscspecs
        self.video_encoders = get_DEFAULT_VIDEO_ENCODERS()
        self.csc_modules = get_DEFAULT_CSC_MODULES()

        #bits needed to ensure we can initialize just once
        #even when called from multiple threads:
        self._initialized = init
        self._lock = Lock()

    def set_modules(self, video_encoders, csc_modules):
        assert not self._initialized, "too late to set modules, the helper is already initialized!"
        self.video_encoders = [x for x in video_encoders if x in get_DEFAULT_VIDEO_ENCODERS()]
        self.csc_modules = [x for x in csc_modules if x in get_DEFAULT_CSC_MODULES()]

    def clone(self):
        if not self._initialized:
            self.init()
        #manual deep-ish copy: make new dictionaries and lists,
        #but keep the same codec specs:
        ves = {}
        for enc, d in self._video_encoder_specs.items():
            for ifmt, l in d.items():
                for cspec in l:
                    ves.setdefault(enc, {}).setdefault(ifmt, []).append(cspec)
        ces = {}
        for ifmt, l in self._csc_encoder_specs.items():
            for ofmt, cspec in l:
                ces.setdefault(ifmt, []).append((ofmt, cspec))
        return VideoHelper(ves, ces, True)

    def get_info(self):
        d = {}
        for in_csc, specs in self._csc_encoder_specs.items():
            for out_csc, spec in specs:
                d.setdefault("csc."+in_csc+"_to_"+out_csc, []).append(spec.codec_type)
        for encoding, encoder_specs in self._video_encoder_specs.items():
            for in_csc, specs in encoder_specs.items():
                for spec in specs:
                    d.setdefault("encoding."+in_csc+"_to_"+encoding, []).append(spec.codec_type)
        return d

    def init(self):
        try:
            self._lock.acquire()
            #check again with lock held (in case of race):
            if self._initialized:
                return
            self.init_video_encoders_options()
            self.init_csc_options()
            self._initialized = True
        finally:
            self._lock.release()

    def get_encodings(self):
        return self._video_encoder_specs.keys()

    def get_encoder_specs(self, encoding):
        return self._video_encoder_specs.get(encoding, {})

    def get_csc_specs(self, src_format):
        return self._csc_encoder_specs.get(src_format, [])

    def init_video_options(self):
        self.init_video_encoders_options()
        self.init_csc_options()

    def init_video_encoders_options(self):
        for x in self.video_encoders:
            try:
                mod = get_video_module_name(x)
                self.init_video_encoder_option(mod)
            except:
                log.warn("init_video_encoders_options() cannot add %s encoder", x, exc_info=True)
        log("init_video_encoders_options() video encoder specs: %s", self._video_encoder_specs)

    def init_video_encoder_option(self, encoder_name):
        encoder_module = get_codec(encoder_name)
        log("init_video_encoder_option(%s) module=%s", encoder_name, encoder_module)
        if not encoder_module:
            return
        encoder_type = encoder_module.get_type()
        try:
            encoder_module.init_module()
        except Exception, e:
            log.warn("cannot use %s module %s: %s", encoder_type, encoder_module, e, exc_info=True)
            return
        colorspaces = encoder_module.get_colorspaces()
        log("init_video_encoder_option(%s) %s input colorspaces=%s", encoder_module, encoder_type, colorspaces)
        encodings = encoder_module.get_encodings()
        log("init_video_encoder_option(%s) %s encodings=%s", encoder_module, encoder_type, encodings)
        for encoding in encodings:
            for colorspace in colorspaces:
                spec = encoder_module.get_spec(encoding, colorspace)
                self.add_encoder_spec(encoding, colorspace, spec)

    def add_encoder_spec(self, encoding, colorspace, spec):
        self._video_encoder_specs.setdefault(encoding, {}).setdefault(colorspace, []).append(spec)


    def init_csc_options(self):
        for x in self.csc_modules:
            try:
                mod = get_csc_module_name(x)
                self.init_csc_option(mod)
            except:
                log.warn("init_csc_options() cannot add %s csc", x, exc_info=True)
        log("init_csc_options() csc specs: %s", self._csc_encoder_specs)
        for src_format, specs in sorted(self._csc_encoder_specs.items()):
            log("%s - %s options:", src_format, len(specs))
            d = {}
            for dst_format, spec in sorted(specs):
                d.setdefault(dst_format, set()).add(spec.info())
            for dst_format, specs in sorted(d.items()):
                log(" * %s via: %s", dst_format, sorted(list(specs)))

    def init_csc_option(self, csc_name):
        csc_module = get_codec(csc_name)
        log("init_csc_option(%s) module=%s", csc_name, csc_module)
        if csc_module is None:
            return
        csc_type = csc_module.get_type()
        try:
            csc_module.init_module()
        except Exception, e:
            log.warn("cannot use %s module %s: %s", csc_type, csc_module, e)
            return
        in_cscs = csc_module.get_input_colorspaces()
        for in_csc in in_cscs:
            out_cscs = csc_module.get_output_colorspaces(in_csc)
            log("init_csc_option(..) %s.get_output_colorspaces(%s)=%s", csc_module.get_type(), in_csc, out_cscs)
            for out_csc in out_cscs:
                spec = csc_module.get_spec(in_csc, out_csc)
                self.add_csc_spec(in_csc, out_csc, spec)

    def add_csc_spec(self, in_csc, out_csc, spec):
        item = out_csc, spec
        self._csc_encoder_specs.setdefault(in_csc, []).append(item)


instance = VideoHelper()
def getVideoHelper():
    global instance
    return instance



def main():
    from xpra.codecs.loader import log as loader_log
    loader_log.enable_debug()
    log.enable_debug()
    vh = getVideoHelper()
    vh.init()


if __name__ == "__main__":
    main()
