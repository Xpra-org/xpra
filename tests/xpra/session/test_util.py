# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#@PydevCodeAnalysisIgnore

from tests.xpra.session.test import assert_emits, assert_raises
from xpra.gtk_common.gobject_util import AutoPropGObjectMixin, non_none_list_accumulator
import gobject
import gtk

class NonNoneListAccumulatorTestClass(gobject.GObject):
    __gsignals__ = {
        "foo": (gobject.SIGNAL_RUN_LAST,
                gobject.TYPE_PYOBJECT, (),
                non_none_list_accumulator),
        }
gobject.type_register(NonNoneListAccumulatorTestClass)

class TestNonNoneListAccumulator(object):
    def test_list_accumulator(self):
        obj = NonNoneListAccumulatorTestClass()
        def f(o):
            return "f"
        def g(o):
            return "g"
        def h(o):
            return "h"
        def n(o):
            return None
        obj.connect("foo", f)
        obj.connect("foo", g)
        obj.connect("foo", h)
        obj.connect("foo", n)
        result = obj.emit("foo")
        assert sorted(result) == ["f", "g", "h"]

class APTestClass(AutoPropGObjectMixin, gobject.GObject):
    __gproperties__ = {
        "readwrite": (gobject.TYPE_PYOBJECT,
                      "blah", "baz", gobject.PARAM_READWRITE),
        "readonly": (gobject.TYPE_PYOBJECT,
                      "blah", "baz", gobject.PARAM_READABLE),
        }
gobject.type_register(APTestClass)

class TestAutoPropMixin(object):
    def test_main(self):
        obj = APTestClass()
        assert obj.get_property("readwrite") is None
        def setit(o):
            o.set_property("readwrite", "blah")
        assert_emits(setit, obj, "notify::readwrite")
        assert obj.get_property("readwrite") == "blah"

    def test_readonly(self):
        obj = APTestClass()
        assert obj.get_property("readonly") is None
        assert_raises(TypeError,
                      obj.set_property, "readonly", "blah")
        def setit(o):
            o._internal_set_property("readonly", "blah")
        assert_emits(setit, obj, "notify::readonly")
        assert obj.get_property("readonly") == "blah"

    def test_custom_getset(self):
        class C(APTestClass):
            def __init__(self):
                APTestClass.__init__(self)
                self.custom = 10
            def do_set_property_readwrite(self, name, value):
                assert name == "readwrite"
                self.custom = value
            def do_get_property_readwrite(self, name):
                assert name == "readwrite"
                return self.custom
        gobject.type_register(C)

        c = C()
        assert c.get_property("readwrite") == 10
        c.set_property("readwrite", 3)
        assert c.custom == 3
        assert c.get_property("readwrite") == 3
        def setit(obj):
            obj._internal_set_property("readwrite", 12)
        assert_emits(setit, c, "notify::readwrite")
        assert c.get_property("readwrite") == 12
        c.custom = 15
        assert c.get_property("readwrite") == 15
