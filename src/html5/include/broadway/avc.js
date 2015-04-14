/**
 * Requires: avc-codec.js
 **/

assert (Module);

var Avc = (function avc() {
    'use strict';

    var MAX_STREAM_BUFFER_LENGTH = 1024 * 1024,
        HEAP8 = Module.HEAP8,
        HEAPU8 = Module.HEAPU8,
        HEAP16 = Module.HEAP16,
        HEAP32 = Module.HEAP32,
        _h264bsdClip = Module._get_h264bsdClip(),
        patches = {
            "filter": {
                name: "_h264bsdFilterPicture",
                display: "Filter Picture",
                original: "Original_h264bsdFilterPicture",
                options: {
                none: {display: "None", fn: function () {}},
                original: {display: "Original", fn: null},
                }
            },
            "filterHorLuma": {
                name: "_FilterHorLuma",
                display: "Filter Hor Luma",
                original: "OriginalFilterHorLuma",
                options: {
                none: {display: "None", fn: function () {}},
                original: {display: "Original", fn: null},
                optimized: {display: "Optimized", fn: OptimizedFilterHorLuma}
                }
            },
            "filterVerLumaEdge": {
                name: "_FilterVerLumaEdge",
                display: "Filter Ver Luma Edge",
                original: "OriginalFilterVerLumaEdge",
                options: {
                none: {display: "None", fn: function () {}},
                original: {display: "Original", fn: null},
                optimized: {display: "Optimized", fn: OptimizedFilterVerLumaEdge}
                }
            },
            "getBoundaryStrengthsA": {
                name: "_GetBoundaryStrengthsA",
                display: "Get Boundary Strengths",
                original: "OriginalGetBoundaryStrengthsA",
                options: {
                none: {display: "None", fn: function () {}},
                original: {display: "Original", fn: null},
                optimized: {display: "Optimized", fn: OptimizedGetBoundaryStrengthsA}
                }
            }
        },
        origFn = {};

    function clip(x, y, z) {
        return z < x ? x : (z > y ? y : z);
    }

    function OptimizedGetBoundaryStrengthsA($mb, $bS) {
        var $totalCoeff = $mb + 28;

        var tc0 = HEAP16[$totalCoeff + 0 >> 1];
        var tc1 = HEAP16[$totalCoeff + 2 >> 1];
        var tc2 = HEAP16[$totalCoeff + 4 >> 1];
        var tc3 = HEAP16[$totalCoeff + 6 >> 1];
        var tc4 = HEAP16[$totalCoeff + 8 >> 1];
        var tc5 = HEAP16[$totalCoeff + 10 >> 1];
        var tc6 = HEAP16[$totalCoeff + 12 >> 1];
        var tc7 = HEAP16[$totalCoeff + 14 >> 1];
        var tc8 = HEAP16[$totalCoeff + 16 >> 1];
        var tc9 = HEAP16[$totalCoeff + 18 >> 1];
        var tc10 = HEAP16[$totalCoeff + 20 >> 1];
        var tc11 = HEAP16[$totalCoeff + 22 >> 1];
        var tc12 = HEAP16[$totalCoeff + 24 >> 1];
        var tc13 = HEAP16[$totalCoeff + 26 >> 1];
        var tc14 = HEAP16[$totalCoeff + 28 >> 1];
        var tc15 = HEAP16[$totalCoeff + 30 >> 1];

        HEAP32[$bS + 32 >> 2] = tc2 || tc0 ? 2 : 0;
        HEAP32[$bS + 40 >> 2] = tc3 || tc1 ? 2 : 0;
        HEAP32[$bS + 48 >> 2] = tc6 || tc4 ? 2 : 0;
        HEAP32[$bS + 56 >> 2] = tc7 || tc5 ? 2 : 0;
        HEAP32[$bS + 64 >> 2] = tc8 || tc2 ? 2 : 0;
        HEAP32[$bS + 72 >> 2] = tc9 || tc3 ? 2 : 0;
        HEAP32[$bS + 80 >> 2] = tc12 || tc6 ? 2 : 0;
        HEAP32[$bS + 88 >> 2] = tc13 || tc7 ? 2 : 0;
        HEAP32[$bS + 96 >> 2] = tc10 || tc8 ? 2 : 0;
        HEAP32[$bS + 104 >> 2] = tc11 || tc9 ? 2 : 0;
        HEAP32[$bS + 112 >> 2] = tc14 || tc12 ? 2 : 0;
        HEAP32[$bS + 120 >> 2] = tc15 || tc13 ? 2 : 0;

        HEAP32[$bS + 12 >> 2] = tc1 || tc0 ? 2 : 0;
        HEAP32[$bS + 20 >> 2] = tc4 || tc1 ? 2 : 0;
        HEAP32[$bS + 28 >> 2] = tc5 || tc4 ? 2 : 0;
        HEAP32[$bS + 44 >> 2] = tc3 || tc2 ? 2 : 0;
        HEAP32[$bS + 52 >> 2] = tc6 || tc3 ? 2 : 0;
        HEAP32[$bS + 60 >> 2] = tc7 || tc6 ? 2 : 0;
        HEAP32[$bS + 76 >> 2] = tc9 || tc8 ? 2 : 0;
        HEAP32[$bS + 84 >> 2] = tc12 || tc9 ? 2 : 0;
        HEAP32[$bS + 92 >> 2] = tc13 || tc12 ? 2 : 0;
        HEAP32[$bS + 108 >> 2] = tc11 || tc10 ? 2 : 0;
        HEAP32[$bS + 116 >> 2] = tc14 || tc11 ? 2 : 0;
        HEAP32[$bS + 124 >> 2] = tc15 || tc14 ? 2 : 0;
    }

    function OptimizedFilterVerLumaEdge ($data, bS, $thresholds, imageWidth) {
        var delta, tc, tmp;
        var p0, q0, p1, q1, p2, q2;
        var tmpFlag;
        var $clp = _h264bsdClip + 512;
        var alpha = HEAP32[$thresholds + 4 >> 2];
        var beta = HEAP32[$thresholds + 8 >> 2];
        var val;

        if (bS < 4) {
            tmp = tc = HEAPU8[HEAP32[$thresholds >> 2] + (bS - 1)] & 255;
            for (var i = 4; i > 0; i--) {
                p1 = HEAPU8[$data + -2] & 255;
                p0 = HEAPU8[$data + -1] & 255;
                q0 = HEAPU8[$data] & 255;
                q1 = HEAPU8[$data + 1] & 255;
                if (
                    (Math.abs(p0 - q0) < alpha) &&
                    (Math.abs(p1 - p0) < beta) &&
                    (Math.abs(q1 - q0) < beta)
                ) {
                    p2 = HEAPU8[$data - 3] & 255;
                    if (Math.abs(p2 - p0) < beta) {
                        val = (p2 + ((p0 + q0 + 1) >> 1) - (p1 << 1)) >> 1;
                        HEAP8[$data - 2] = p1 + clip(-tc, tc, val);
                        tmp++;
                    }

                    q2 = HEAPU8[$data + 2] & 255;
                    if (Math.abs(q2 - q0) < beta) {
                        val = (q2 + ((p0 + q0 + 1) >> 1) - (q1 << 1)) >> 1;
                        HEAP8[$data + 1] = (q1 + clip(-tc, tc, val));
                        tmp++;
                    }

                    val = ((((q0 - p0) << 2) + (p1 - q1) + 4) >> 3);
                    delta = clip(-tmp, tmp, val);

                    p0 = HEAPU8[$clp + (p0 + delta)] & 255;
                    q0 = HEAPU8[$clp + (q0 - delta)] & 255;
                    tmp = tc;
                    HEAP8[$data - 1] = p0;
                    HEAP8[$data] = q0;

                    $data += imageWidth;
                }
            }
        } else {
            origFn.OriginalFilterVerLumaEdge($data, bS, $thresholds, imageWidth);
        }
    }

   /**
    * Filter all four successive horizontal 4-pixel luma edges. This can be
    * done when bS is equal to all four edges.
    */
    function OptimizedFilterHorLuma ($data, bS, $thresholds, imageWidth) {
        var delta, tc, tmp;
        var p0, q0, p1, q1, p2, q2;
        var tmpFlag;
        var $clp = _h264bsdClip + 512;
        var alpha = HEAP32[$thresholds + 4 >> 2];
        var beta = HEAP32[$thresholds + 8 >> 2];
        var val;

        if (bS < 4) {
            tmp = tc = HEAPU8[HEAP32[$thresholds >> 2] + (bS - 1)] & 255;
            for (var i = 16; i > 0; i--) {
                p1 = HEAPU8[$data + (-imageWidth << 1)] & 255;
                p0 = HEAPU8[$data + -imageWidth] & 255;
                q0 = HEAPU8[$data] & 255;
                q1 = HEAPU8[$data + imageWidth] & 255;

                if (
                    (Math.abs(p0 - q0) < alpha) &&
                    (Math.abs(p1 - p0) < beta) &&
                    (Math.abs(q1 - q0) < beta)
                ) {
                    p2 = HEAPU8[$data + (-imageWidth * 3)] & 255;
                    if (Math.abs(p2 - p0) < beta) {
                        val = (p2 + ((p0 + q0 + 1) >> 1) - (p1 << 1)) >> 1;
                        HEAP8[$data + (-imageWidth << 1)] = p1 + clip(-tc, tc, val);
                        tmp++;
                    }

                    q2 = HEAPU8[$data + (imageWidth << 2)] & 255;
                    if (Math.abs(q2 - q0) < beta) {
                        val = (q2 + ((p0 + q0 + 1) >> 1) - (q1 << 1)) >> 1;
                        HEAP8[$data + imageWidth] = (q1 + clip(-tc, tc, val));
                        tmp++;
                    }

                    val = ((((q0 - p0) << 2) + (p1 - q1) + 4) >> 3);
                    delta = clip(-tmp, tmp, val);

                    p0 = HEAPU8[$clp + (p0 + delta)] & 255;
                    q0 = HEAPU8[$clp + (q0 - delta)] & 255;
                    tmp = tc;
                    HEAP8[$data - imageWidth] = p0;
                    HEAP8[$data] = q0;

                    $data ++;
                }
            }
        } else {
            origFn.OriginalFilterHorLuma($data, bS, $thresholds, imageWidth);
        }
    }

    function patchOptimizations(config, patches) {
        for (var name in patches) {
            var patch = patches[name];
            if (patch) {
                var option = config[name];
                if (!option) option = "original";
                console.info(name + ": " + option);
                assert (option in patch.options);
                var fn = patch.options[option].fn;
                if (fn) {
                    origFn[patch.original] = Module.patch(null, patch.name, fn);
                    console.info("Patching: " + patch.name + ", with: " + option);
                }
            }
        }
    }


    function constructor() {
        Module._broadwayInit();
        this.streamBuffer = toU8Array(Module._broadwayCreateStream(MAX_STREAM_BUFFER_LENGTH), MAX_STREAM_BUFFER_LENGTH);
        this.pictureBuffers = {};

        this.onPictureDecoded = function (buffer, width, height) {
            // console.info(buffer.length);
        };

        Module.patch(null, "_broadwayOnHeadersDecoded", function (x,y,z) {});


        Module.patch(null, "_broadwayOnPictureDecoded", function ($buffer, width, height) {
            var buffer = this.pictureBuffers[$buffer];
            if (!buffer) {
                buffer = this.pictureBuffers[$buffer] = toU8Array($buffer, (width * height * 3) / 2);
            }
            this.onPictureDecoded(buffer, width, height);
        }.bind(this));
    }

   /**
    * Creates a typed array from a HEAP8 pointer.
    */
    function toU8Array(ptr, length) {
        return HEAPU8.subarray(ptr, ptr + length);
    }

    constructor.prototype = {
       /**
        * Decodes a stream buffer. This may be one single (unframed) NAL unit
        * without the start code, or a sequence of NAL units with framing start
        * code prefixes. This function overwrites stream buffer allocated by
        * the codec with the supplied buffer.
        */
        decode: function decode(buffer) {
            // console.info("Decoding: " + buffer.length);
            this.streamBuffer.set(buffer);
            Module._broadwaySetStreamLength(buffer.length);
            Module._broadwayPlayStream();
        },
        configure: function (config) {
            patchOptimizations(config, patches);
            console.info("Broadway Configured: " + JSON.stringify(config));
        }
    };

    return constructor;
})();
