# This file is part of Parti.
# Copyright (C) 2011 Antoine Martin <antoine@nagafix.co.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.bencode import IncrBDecode, bencode

    
def process(input):
    bd = IncrBDecode()
    bd.add(input)
    return  bd.process()

def test_decoding():
    
    def t(str, value, remainder):
        print str
        # Test "one-shot":
        assert process(str) == (value, remainder)
        # With gibberish added:
        assert process(str + "asdf") == (value, remainder + "asdf")
        # Byte at a time:
        decoder = IncrBDecode()
        for i, c in enumerate(str):
            decoder.add(c)
            retval = decoder.process()
            if retval is not None:
                print retval
                assert retval == (value, "")
                assert str[i + 1:] == remainder
                break

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

    print "------"
    def te(str, exc):
        print str
        try:
            process(str)
        except exc:
            pass
        else:
            assert False, "didn't raise exception"
        try:
            decoder = IncrBDecode()
            for c in str:
                decoder.add(c)
                decoder.process()
        except exc:
            pass
        else:
            assert False, "didn't raise exception"

    te("iie", ValueError)
    te("i0x0e", ValueError)
    t("i0e", 0, "")
    te("i00e", ValueError)

    te("0x2:aa", ValueError)
    te("-1:aa", ValueError)
    te("02:aa", ValueError)

    # Keys must be strings:
    te("di0ei0ee", ValueError)
    te("dli0eei0ee", ValueError)
    te("dd1:a1:aei0ee", ValueError)
    # Keys must be in ascending order:
    te("d1:bi0e1:ai0e1:ci0ee", ValueError)
    te("d1:ai0e1:ci0e1:bi0ee", ValueError)

    te("l5:hellod20:__prerelease_version8:0.0.7.2612:desktop_sizeli480ei800ee4:jpegi40e18:challenge_response40:ba59e4110119264f4a6eaf3adc075ea2c5408550ee", ValueError)
    #no idea why this does not fail if the one above does!:
    #te("l5:hellod20:__prerelease_version8:0.0.7.2618:challenge_response40:ba59e4110119264f4a6eaf3adc075ea2c540855012:desktop_sizeli480ei800ee4:jpegi40eee", ValueError)


def test_encoding():

    def t(v, encstr=None):
        be = bencode(v)
        print "bencode(%s)=%s" % (v, be)
        if encstr:
            assert be==encstr
        restored = process(be)
        print "decode(%s)=%s" % (be, restored)
        list = restored[0]
        assert list==v
        return list

    def test_hello():
        d = {}
        d["__prerelease_version"] = "0.0.7.26"
        #caps.put("deflate", 6);
        d["desktop_size"] = [480,800]
        jpeg = 4
        d["jpeg"] =  jpeg
        challenge = "ba59e4110119264f4a6eaf3adc075ea2c5408550"
        d["challenge_response"] = challenge
        hello = ["hello", d]
        t(hello, "l5:hellod20:__prerelease_version8:0.0.7.2618:challenge_response40:ba59e4110119264f4a6eaf3adc075ea2c540855012:desktop_sizeli480ei800ee4:jpegi4eee")

    test_hello()

def main():
    test_decoding()
    test_encoding()


if __name__ == "__main__":
    main()
