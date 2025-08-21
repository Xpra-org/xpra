# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util.env import envbool

from xpra.x11.bindings.xlib cimport XFree, XAllocClassHint, XSetClassHint, XGetClassHint, Window, XClassHint, Status
from xpra.x11.bindings.core cimport X11CoreBindingsInstance, import_check


import_check("classhint")


cdef class X11ClassHintBindingsInstance(X11CoreBindingsInstance):

    def setClassHint(self, Window xwindow, wmclass: str, wmname: str) -> None:
        self.context_check("setClassHint")
        cdef XClassHint *classhints = XAllocClassHint()
        assert classhints!=NULL
        res_class = wmclass.encode("latin1")
        res_name = wmname.encode("latin1")
        classhints.res_class = res_class
        classhints.res_name = res_name
        XSetClassHint(self.display, xwindow, classhints)
        XFree(classhints)

    def getClassHint(self, Window xwindow) -> Optional[Tuple[str,str]]:
        self.context_check("getClassHint")
        cdef XClassHint *classhints = XAllocClassHint()
        assert classhints!=NULL
        cdef Status s = XGetClassHint(self.display, xwindow, classhints)
        if not s:
            return None
        _name = ""
        _class = ""
        if classhints.res_name!=NULL:
            _name = classhints.res_name[:]
        if classhints.res_class!=NULL:
            _class = classhints.res_class[:]
        XFree(classhints)
        return (_name, _class)


cdef X11ClassHintBindingsInstance singleton = None


def XClassHintBindings() -> X11ClassHintBindingsInstance:
    global singleton
    if singleton is None:
        singleton = X11ClassHintBindingsInstance()
    return singleton
