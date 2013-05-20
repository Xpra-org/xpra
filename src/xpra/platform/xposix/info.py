# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

def get_sys_info():
    info = {}
    try:
        import resource
        for k, constant in {"server"   : "RUSAGE_SELF",
                         "children" : "RUSAGE_CHILDREN",
                         "total"    : "RUSAGE_BOTH"}.items():
            try:
                v = getattr(resource, constant)
            except (NameError, AttributeError):
                continue
            stats = resource.getrusage(v)
            prefix = "memory.%s." % k
            for var in ("utime", "stime", "maxrss",
                        "ixrss", "idrss", "isrss",
                        "minflt", "majflt", "nswap",
                        "inblock", "oublock",
                        "msgsnd", "msgrcv",
                        "nsignals", "nvcsw", "nivcsw"):
                value = getattr(stats, "ru_%s" % var)
                if type(value)==float:
                    value = int(value)
                info[prefix+var] = value
    except:
        from xpra.log import Logger
        log = Logger()
        log.error("error getting memory usage info", exc_info=True)
    return info
