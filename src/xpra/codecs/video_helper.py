# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013, 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import copy
from threading import Lock
from xpra.log import Logger
log = Logger("codec", "video")

from xpra.codecs.loader import get_codec

instance = None

#all the modules we know about:
ALL_VIDEO_ENCODER_OPTIONS = ["vpx", "x264", "nvenc"]
ALL_CSC_MODULE_OPTIONS = ["swscale", "cython", "opencl", "nvcuda"]
log("video_helper: ALL_VIDEO_ENCODER_OPTIONS=%s", ALL_VIDEO_ENCODER_OPTIONS)
log("video_helper: ALL_CSC_MODULE_OPTIONS=%s", ALL_CSC_MODULE_OPTIONS)

def get_video_module_name(x):
        if x.find("enc")>=0:
            return x            #ie: "nvenc"
        return "enc_"+x         #ie: "enc_x264"

def get_csc_module_name(x):    
    return "csc_"+x             #ie: "csc_swscale"

#now figure out which modules are actually installed:
DEFAULT_VIDEO_ENCODERS = []
DEFAULT_CSC_MODULES = []
for x in list(ALL_VIDEO_ENCODER_OPTIONS):
    try:
        vmod = get_video_module_name(x)
        v = __import__(vmod, globals(), locals())
        assert v is not None
        DEFAULT_VIDEO_ENCODERS.append(x)
    except Exception, e:
        log("video encoder %s cannot be imported: %s", e)
log("video_helper: DEFAULT_VIDEO_ENCODERS=%s", DEFAULT_VIDEO_ENCODERS)
for x in list(ALL_CSC_MODULE_OPTIONS):
    try:
        cscmod = get_csc_module_name(x)
        v = __import__(cscmod, globals(), locals())
        assert v is not None
        DEFAULT_CSC_MODULES.append(x)
    except Exception, e:
        log("csc module %s cannot be imported: %s", e)
log("video_helper: DEFAULT_CSC_MODULES=%s", DEFAULT_CSC_MODULES)
    

class VideoHelper(object):

    def __init__(self, vspecs={}, cscspecs={}, init=False):
        global DEFAULT_VIDEO_ENCODERS, DEFAULT_CSC_MODULES
        self._video_encoder_specs = vspecs
        self._csc_encoder_specs = cscspecs
        self._video_encoders = DEFAULT_VIDEO_ENCODERS
        self._csc_modules = DEFAULT_CSC_MODULES

        #bits needed to ensure we can initialize just once
        #even when called from multiple threads:
        self._initialized = init
        self._lock = Lock()

    def set_modules(self, video_encoders, csc_modules):
        assert not self._initialized, "too late to set modules, the helper is already initialized!"
        self._video_encoders = video_encoders
        self._csc_modules = csc_modules

    def clone(self, deep=False):
        if not self._initialized:
            self.init()
        if deep:
            ves = copy.deepcopy(self._video_encoder_specs)
            ces = copy.deepcopy(self._csc_encoder_specs)
        else:
            ves = self._video_encoder_specs.copy()
            ces = self._csc_encoder_specs.copy()
        #make a deep copy:
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
        return self._video_encoder_specs.get(encoding, [])

    def get_csc_specs(self, src_format):
        return self._csc_encoder_specs.get(src_format, [])

    def init_video_options(self):
        self.init_video_encoders_options()
        self.init_csc_options()

    def init_video_encoders_options(self):
        for x in self._video_encoders:
            module_name = get_video_module_name(x)  #ie: "enc_x264"
            try:
                self.init_video_encoder_option(module_name)
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
        for x in self._csc_modules:
            module_name = get_csc_module_name(x)    #ie: "csc_swscale"
            try:
                self.init_csc_option(module_name)
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
            log.warn("cannot use %s module %s: %s", csc_type, csc_module, e, exc_info=True)
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
    global debug
    import logging
    logging.basicConfig(format="%(message)s")
    logging.root.setLevel(logging.INFO)
    debug = log.info

    vh = getVideoHelper()
    vh.init()


if __name__ == "__main__":
    main()
