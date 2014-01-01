#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
from xpra.util import nonl
encode, decode = None, None

from xpra.net.bencode.bencode import bencode as p_bencode, bdecode as p_bdecode
from xpra.net.bencode.cython_bencode import bencode as c_bencode, bdecode as c_bdecode

def use_cython():
    global encode, decode
    
    encode = c_bencode
    decode = c_bdecode

def use_python():
    global encode, decode
    encode = p_bencode
    decode = p_bdecode

def plog(x):
    print(x)
def noop(x):
    pass
log = plog

def use_print():
    global log
    log = plog
def use_noop():
    global log
    log = noop
    


def i(s):
    v = nonl(str(s))
    if len(v)<48:
        return v
    return v[:46]+".."


def test_decoding():

    def t(s, value, remainder):
        #log(" "+i(s))
        # Test "one-shot":
        rv, rr = decode(s)
        assert rv == value, "expected value %s but got %s" % (rv, value)
        rrstr = s[rr:]
        assert rrstr == remainder, "expected remainder value %s but got %s" % (remainder, rrstr)
        # With gibberish added:
        g_str = s + "asdf"
        rv, rr = decode(g_str)
        assert rv == value, "expected value %s but got %s" % (rv, value)
        rrstr = g_str[rr:]
        assert rrstr.endswith("asdf")

    #t("l16:configure-windowi2ei555ei340ei649ei381ed9:maximizedi0e6:screeni0e9:maximizedi0eee", [], "")

    t("i12345e", 12345, "")
    t("i-12345e", -12345, "")
    t("i12345eQQQ", 12345, "QQQ")
    t("3:foo", "foo", "")
    t("3:fooQQQ", "foo", "QQQ")
    t("li12e4:asdfi34ee", [12, "asdf", 34], "")
    t("d4:asdf3:foo4:bsdfi1234ee", {"asdf": "foo", "bsdf": 1234}, "")

    t("d4:asdfli1ei2ei3ei4ee5:otheri-55e2:qqd2:qql2:hieee",
      {"asdf": [1, 2, 3, 4], "qq": {"qq": ["hi"]}, "other": -55},
      "")

    t("l0:e", [""], "")

    # Keys do not have to be strings:
    t("di0ei0ee", {0 : 0}, "")

    def te(s, exc):
        #log(" "+s)
        v = None
        try:
            v = decode(s)
        except exc:
            pass
        else:
            assert False, "didn't raise exception, returned: %s for %s" % (v, s)

    te("iie", ValueError)
    te("i0x0e", ValueError)
    t("i0e", 0, "")
    te("i00e", ValueError)

    te("0x2:aa", ValueError)
    te("-1:aa", ValueError)
    te("02:aa", ValueError)


def t(v, encstr=None):
    be = encode(v)
    log("bencode(%s)=%s" % (i(v), i(be)))
    if encstr:
        p = 0
        while p<min(len(encstr), len(be)):
            if encstr[p]!=be[p]:
                break
            p += 1
        assert be==encstr, "expected '%s' but got '%s', strings differ at position %s: expected '%s' but found '%s' (lengths: %s vs %s)" % (encstr, be, p, encstr[p], be[p], len(encstr), len(be))
    restored = decode(be)
    log("decode(%s)=%s" % (i(be), i(restored)))
    rlist = restored[0]
    if len(rlist)!=len(v):
        log("MISMATCH!")
        log("v=%s" % v)
        log("l=%s" % rlist)
    assert len(rlist)==2
    assert rlist[0]==v[0]
    for ok,ov in v[1].items():
        d = rlist[1]
        if ok not in d:
            log("restored dict is missing %s" % ok)
            return rlist
        rv = d.get(ok)
        if rv!=ov:
            log("value for %s does not match: %s vs %s" % (ok, ov, rv))
            return rlist
    return rlist



hello = ["hello", {
                   "__prerelease_version"   : "0.0.7.26",
                   "desktop_size"           : [480,800],
                   "jpeg"                   : 4,
                   "challenge"              : "ba59e4110119264f4a6eaf3adc075ea2c5408550",
                   "challenge_response"     : "ba59e4110119264f4a6eaf3adc075ea2c5408550",
                   }]
hello_output = "l5:hellod12:desktop_sizeli480ei800ee9:challenge40:ba59e4110119264f4a6eaf3adc075ea2c540855020:__prerelease_version8:0.0.7.264:jpegi4e18:challenge_response40:ba59e4110119264f4a6eaf3adc075ea2c5408550ee"
def test_encoding_hello():
    log("test_hello()")
    t(hello, hello_output)
    log("")

large_hello = ["hello", {
            'start_time': 1325786122,
            'resize_screen': False, 'bell': True, 'desktop_size': [800, 600], 'modifiers_nuisance': True,
            'actual_desktop_size': [3840, 2560], 'encodings': ['rgb24', 'jpeg', 'png'],
            'ping': True, 'damage_sequence': True, 'packet_size': True,
            'encoding': 'rgb24', 'platform': 'linux2', 'clipboard': True, 'cursors': True,
            'raw_keycodes_feature': True, 'focus_modifiers_feature': True, '__prerelease_version': '0.0.7.33',
            'notifications': True, 'png_window_icons': True,
            }]
large_hello_output = "l5:hellod19:actual_desktop_sizeli3840ei2560ee7:cursorsi1e4:belli1e12:desktop_sizeli800ei600ee10:start_timei1325786122e8:encoding5:rgb244:pingi1e15:damage_sequencei1e11:packet_sizei1e8:platform6:linux220:__prerelease_version8:0.0.7.339:clipboardi1e20:raw_keycodes_featurei1e13:resize_screeni0e9:encodingsl5:rgb244:jpeg3:pnge23:focus_modifiers_featurei1e18:modifiers_nuisancei1e13:notificationsi1e16:png_window_iconsi1eee"
def test_encoding_large_hello():
    log("test_large_hello()")
    t(large_hello, large_hello_output)

nested_dicts = ['some_new_feature_we_may_add', {"with_a_nested_dict" : {"containing_another_dict" : ["with", "nested", "arrays", ["in", ["it", "going", [["deep", 0, -1]]]]]}}]
nested_dicts_output = "l27:some_new_feature_we_may_addd18:with_a_nested_dictd23:containing_another_dictl4:with6:nested6:arraysl2:inl2:it5:goingll4:deepi0ei-1eeeeeeeee"
def test_nested_dicts():
    t(nested_dicts, nested_dicts_output)
    log("")


def test_random():
    log("test_random()")
    import binascii
    u = "6c343a6472617769316569333731656931356569366569313365353a726762333231343a7801fbff7f1490130200099e36d8693265693234656431303a7267625f666f726d6174343a52474258343a7a6c69626931656565"
    s = binascii.unhexlify(u)
    decode(s)
    log("")

def get_test_data_dict():
    try:
        from xpra.x11.gtk_x11 import gdk_display_source             #@UnusedImport
        from xpra.x11.bindings.keyboard_bindings import X11KeyboardBindings        #@UnresolvedImport
        keyboard_bindings = X11KeyboardBindings()
        return keyboard_bindings.get_keycode_mappings()
    except ImportError, e:
        log("cannot use X11 keyboard data as test data: %s" % e);
        return {"foo" : "bar"}
test_dict = get_test_data_dict()

def test_large_dict():
    log("test_large_dict()")
    b = encode(test_dict)
    log("bencode(%s)=%s" % (i(test_dict), i(b)))
    d = decode(b)
    log("bdecode(%s)=%s" % (i(b), i(d)))
    log("")

def test_compare_cython():
    log("test_compare_cython()")
    #suspend logging:
    use_noop()
    results = {}
    for n,x in {"python" : use_python, "cython" : use_cython}.items():
        x()
        start = time.time()
        for i in xrange(200):
            test_large_dict()
            test_random()
            test_decoding()
            test_encoding_hello()
            test_encoding_large_hello()
            test_nested_dicts()
        end = time.time()
        results[n] = int(1000.0*(end-start))
    use_print()
    log("results: %s (in milliseconds)" % results)


def main():
    for x in (use_python, use_cython):
        log("main: testing with %s" % x)
        x()
        test_random()
        test_decoding()
        test_encoding_hello()
        test_encoding_large_hello()
        test_nested_dicts()
        test_large_dict()

    test_compare_cython()


if __name__ == "__main__":
    main()
