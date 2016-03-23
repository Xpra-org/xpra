# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: boundscheck=False, wraparound=False, cdivision=True

from xpra.os_util import bytestostr
from xpra.util import nonl
from xpra.log import Logger
log = Logger("libav")


cdef extern from "../../inline.h":
    pass

cdef extern from "string.h":
    int vsnprintf(char * s, size_t n, const char * format, va_list arg)

cdef extern from "libavutil/log.h":
    ctypedef struct va_list:
        pass
    cdef int AV_LOG_FATAL
    cdef int AV_LOG_ERROR
    cdef int AV_LOG_WARNING
    cdef int AV_LOG_INFO
    cdef int AV_LOG_DEBUG
    #this is the correct signature, but I can't get Cython to play nice with it:
    #ctypedef void (*log_callback)(void *avcl, int level, const char *fmt, va_list vl)
    ctypedef void* log_callback
    void av_log_default_callback(void *avcl, int level, const char *fmt, va_list vl)
    void av_log_set_callback(void *callback)


cdef int ERROR_LEVEL    = AV_LOG_ERROR
cdef int WARNING_LEVEL  = AV_LOG_WARNING
cdef int INFO_LEVEL     = AV_LOG_INFO
cdef int DEBUG_LEVEL    = AV_LOG_DEBUG

def suspend_nonfatal_logging():
    global ERROR_LEVEL, WARNING_LEVEL, INFO_LEVEL, DEBUG_LEVEL
    ERROR_LEVEL    = AV_LOG_FATAL
    WARNING_LEVEL  = AV_LOG_FATAL
    INFO_LEVEL     = AV_LOG_FATAL
    DEBUG_LEVEL    = AV_LOG_FATAL

def resume_nonfatal_logging():
    ERROR_LEVEL    = AV_LOG_ERROR
    WARNING_LEVEL  = AV_LOG_WARNING
    INFO_LEVEL     = AV_LOG_INFO
    DEBUG_LEVEL    = AV_LOG_DEBUG


cdef void log_callback_override(void *avcl, int level, const char *fmt, va_list vl) with gil:
    if level<=ERROR_LEVEL:
        l = log.error
    elif level<=WARNING_LEVEL:
        l = log.warn
    elif level<=INFO_LEVEL:
        l = log.info
    elif level<=DEBUG_LEVEL:
        l = log.debug
    else:
        #don't bother
        return
    #turn it into a string:
    cdef char buffer[256]
    cdef int r
    try:
        r = vsnprintf(buffer, 256, fmt, vl)
        if r<0:
            log.error("av_log: vsnprintf returned %i on format string '%s'", r, fmt)
            return
        s = nonl(bytestostr(buffer[:r]).rstrip("\n\r"))
        if s.startswith("Warning: data is not aligned!"):
            #silence this crap, since there is nothing we can do about it
            l = log.debug
        #l("log_callback_override(%#x, %i, %s, ..)", <unsigned long> avcl, level, fmt)
        l("libav: %s", s)
    except Exception as e:
        log.error("Error in log callback at level %i", level)
        log.error(" on format string '%s':", nonl(fmt))
        log.error(" %s: %s", type(e), e)

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
