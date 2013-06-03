#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.codecs.video_enc_pipeline import VideoEncoderPipeline



def test_load():
    #NOTE: we assume that the scores:
    # - make nvenc less desirable at HQ (maybe not?)
    # - make cuda csc beat swscale
    encoding_options = {"uses_swscale" : False,
                        "csc_atoms" : True,
                        "client_options" : True}
    vep = VideoEncoderPipeline(("vpx", "x264"), encoding_options)
    assert vep
    #get_encoding_paths_options(self, pixel_format, encoding, width, height,
    #                              min_quality, quality, min_speed, speed)

    if False:   #RGB modes are disabled!
        print("")
        print("* checking that direct enc_x264 wins at high quality")
        scores = vep.get_encoding_paths_options("x264", 1024, 768, "BGRA", 40, 100, 40, 100)
        assert len(scores)>0
        best = scores[0]
        print("best=%s" % str(best))
        assert best[1]==None and best[2]=="BGRA", "err: should not be using csc! (%s, %s)" % (best[1], best[2])
        assert str(best[3]).find("enc_x264")>0, "err: encoder is not enc_x264: %s" % best[3]

    print("")
    print("* checking that low quality uses YUV420P as-is")
    scores = vep.get_encoding_paths_options("x264", 1024, 768, "YUV420P", 40, 100, 40, 100)
    print("scores=%s" % str(scores))
    assert len(scores)>0
    best = scores[0]
    assert best[1]==None and best[2]=="YUV420P", "err: should not be using csc! (%s, %s)" % (best[1], best[2])
    assert best[2]=="YUV420P", "low quality does not use YUV420P: %s" % best[2]

    print("")
    print("* checking that low quality converts BGRA to YUV420P")
    scores = vep.get_encoding_paths_options("x264", 1024, 768, "BGRA", 40, 100, 40, 100)
    print("scores=%s" % str(scores))
    assert len(scores)>0
    best = scores[0]
    assert best[1]!=None, "err: we should be using csc! (%s, %s)" % (best[1], best[2])
    assert best[2]=="YUV420P", "low quality does not use YUV420P: %s" % best[2]

    print("* test vpx converts everything to YUV420P")
    for x in ("BGRA", "BGRX", "RGB", "BGR", "XRGB", "BGRX"):
        print("")
        print("vpx / %s:" % x)
        scores = vep.get_encoding_paths_options("vpx", 1024, 768, x, 40, 100, 40, 100)
        print("scores=%s" % str(scores))
        assert len(scores)>0, "could not find scores for %s" % x
        best = scores[0]
        assert best[2]=="YUV420P", "vpx should always use YUV420P but found: %s" % best[2]


def main():
    import logging
    import sys
    logging.root.setLevel(logging.DEBUG)
    logging.root.addHandler(logging.StreamHandler(sys.stderr))
    test_load()


if __name__ == "__main__":
    main()
