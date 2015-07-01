# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: boundscheck=False, wraparound=False, cdivision=True

from xpra.os_util import bytestostr
from xpra.util import nonl
from xpra.log import Logger
log = Logger("libav")


cdef extern from "string.h":
    int vsnprintf(char * s, size_t n, const char * format, va_list arg)

cdef extern from "libavutil/log.h":
    ctypedef struct va_list:
        pass
    cdef int AV_LOG_ERROR
    cdef int AV_LOG_WARNING
    cdef int AV_LOG_INFO
    cdef int AV_LOG_DEBUG
    #this is the correct signature, but I can't get Cython to play nice with it:
    #ctypedef void (*log_callback)(void *avcl, int level, const char *fmt, va_list vl)
    ctypedef void* log_callback
    void av_log_default_callback(void *avcl, int level, const char *fmt, va_list vl)
    void av_log_set_callback(void *callback)


cdef void log_callback_override(void *avcl, int level, const char *fmt, va_list vl) with gil:
    if level<=AV_LOG_ERROR:
        l = log.error
    elif level<=AV_LOG_WARNING:
        l = log.warn
    elif level<=AV_LOG_INFO:
        l = log.info
    elif level<=AV_LOG_DEBUG:
        l = log.debug
    else:
        #don't bother
        return
    #turn it into a string:
    cdef char buffer[256]
    cdef int r
    r = vsnprintf(buffer, 256, fmt, vl)
    if r<0:
        log.error("av_log: vsnprintf returned %s on format string '%s'", r, fmt)
        return
    s = nonl(bytestostr(buffer[:r]).rstrip("\n\r"))
    if s.startswith("Warning: data is not aligned!"):
        #silence this crap, since there is nothing we can do about it
        l = log.debug
    #l("log_callback_override(%#x, %i, %s, ..)", <unsigned long> avcl, level, fmt)
    l("libav: %s", s)

cdef int nesting_level = 0

cdef override_logger():
    global nesting_level
    cdef void *cb = <void*> log_callback_override
    if nesting_level==0:
        av_log_set_callback(cb)
    nesting_level += 1

cdef restore_logger():
    global nesting_level
    nesting_level -= 1
    if nesting_level==0:
        av_log_set_callback(<void*> av_log_default_callback)
