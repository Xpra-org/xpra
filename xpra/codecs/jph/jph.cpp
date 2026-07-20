/*
 * This file is part of Xpra.
 * Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

#include "jph.h"

#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <exception>

#ifndef __has_include
#define __has_include(x) 0
#endif

#if __has_include(<openjph/ojph_codestream.h>)
#include <openjph/ojph_codestream.h>
#include <openjph/ojph_file.h>
#include <openjph/ojph_mem.h>
#include <openjph/ojph_params.h>
#include <openjph/ojph_version.h>
#else
#include <ojph_codestream.h>
#include <ojph_file.h>
#include <ojph_mem.h>
#include <ojph_params.h>
#include <ojph_version.h>
#endif

/* upper bound for the image dimensions parsed from an untrusted codestream,
 * so that a tiny input cannot make us allocate an arbitrarily large buffer.
 * Keep this in sync with MAX_IMAGE_DIMENSION in xpra/codecs/constants.py */
#define JPH_MAX_DIMENSION 16384

static void set_error(char *error, size_t error_size, const char *msg)
{
    if (error == nullptr || error_size == 0)
        return;
    if (msg == nullptr)
        msg = "unknown OpenJPH error";
    std::strncpy(error, msg, error_size - 1);
    error[error_size - 1] = 0;
}

static ojph::ui32 choose_decompositions(ojph::ui32 width, ojph::ui32 height)
{
    ojph::ui32 dim = std::min(width, height);
    ojph::ui32 decomps = 0;
    while (decomps < 5 && dim >= (1u << (decomps + 2)))
        ++decomps;
    return decomps;
}

static ojph::ui8 clamp8(ojph::si32 v)
{
    if (v < 0)
        return 0;
    if (v > 255)
        return 255;
    return static_cast<ojph::ui8>(v);
}

int jph_version_major(void)
{
    return OPENJPH_VERSION_MAJOR;
}

int jph_version_minor(void)
{
    return OPENJPH_VERSION_MINOR;
}

int jph_version_patch(void)
{
    return OPENJPH_VERSION_PATCH;
}

int jph_encode(const uint8_t *pixels,
               uint32_t width, uint32_t height, uint32_t stride,
               int bytes_per_pixel, int r_offset, int g_offset, int b_offset,
               int quality,
               uint8_t **out, size_t *out_size,
               char *error, size_t error_size)
{
    if (out == nullptr || out_size == nullptr) {
        set_error(error, error_size, "missing output pointer");
        return -1;
    }
    *out = nullptr;
    *out_size = 0;
    if (pixels == nullptr || width == 0 || height == 0) {
        set_error(error, error_size, "invalid image dimensions");
        return -1;
    }
    if (bytes_per_pixel < 3 || r_offset < 0 || g_offset < 0 || b_offset < 0 ||
        r_offset >= bytes_per_pixel || g_offset >= bytes_per_pixel || b_offset >= bytes_per_pixel) {
        set_error(error, error_size, "invalid pixel format");
        return -1;
    }
    if (stride < width * static_cast<uint32_t>(bytes_per_pixel)) {
        set_error(error, error_size, "invalid rowstride");
        return -1;
    }

    try {
        ojph::codestream codestream;
        ojph::param_siz siz = codestream.access_siz();
        siz.set_image_extent(ojph::point(width, height));
        siz.set_num_components(3);
        for (ojph::ui32 c = 0; c < 3; ++c)
            siz.set_component(c, ojph::point(1, 1), 8, false);

        ojph::param_cod cod = codestream.access_cod();
        cod.set_num_decomposition(choose_decompositions(width, height));
        cod.set_block_dims(64, 64);
        cod.set_progression_order("RPCL");
        cod.set_color_transform(true);
        bool reversible = quality >= 100;
        cod.set_reversible(reversible);
        if (!reversible) {
            quality = std::max(1, std::min(100, quality));
            codestream.access_qcd().set_irrev_quant(0.5f / static_cast<float>(quality));
        }
        codestream.set_planar(false);

        ojph::mem_outfile mem;
        mem.open(std::max<size_t>(65536, static_cast<size_t>(width) * height));
        codestream.write_headers(&mem);

        ojph::ui32 next_comp = 0;
        ojph::line_buf *line = codestream.exchange(nullptr, next_comp);
        const int offsets[3] = {r_offset, g_offset, b_offset};
        for (ojph::ui32 y = 0; y < height; ++y) {
            const uint8_t *row = pixels + static_cast<size_t>(y) * stride;
            for (ojph::ui32 c = 0; c < 3; ++c) {
                if (next_comp != c) {
                    set_error(error, error_size, "unexpected OpenJPH component order");
                    codestream.close();
                    return -1;
                }
                ojph::si32 *dst = line->i32;
                const uint8_t *src = row + offsets[c];
                for (ojph::ui32 x = 0; x < width; ++x)
                    dst[x] = src[static_cast<size_t>(x) * bytes_per_pixel];
                line = codestream.exchange(line, next_comp);
            }
        }
        codestream.flush();

        size_t size = static_cast<size_t>(mem.tell());
        uint8_t *buf = static_cast<uint8_t *>(std::malloc(size));
        if (buf == nullptr) {
            set_error(error, error_size, "failed to allocate output buffer");
            codestream.close();
            return -1;
        }
        std::memcpy(buf, mem.get_data(), size);
        codestream.close();

        *out = buf;
        *out_size = size;
        return 0;
    } catch (const std::exception &e) {
        set_error(error, error_size, e.what());
        return -1;
    } catch (...) {
        set_error(error, error_size, "unknown OpenJPH encode error");
        return -1;
    }
}

int jph_decode(const uint8_t *data, size_t data_size,
               uint8_t **pixels, size_t *pixels_size,
               uint32_t *width, uint32_t *height, uint32_t *stride,
               char *error, size_t error_size)
{
    if (pixels == nullptr || pixels_size == nullptr || width == nullptr ||
        height == nullptr || stride == nullptr) {
        set_error(error, error_size, "missing output pointer");
        return -1;
    }
    *pixels = nullptr;
    *pixels_size = 0;
    *width = *height = *stride = 0;
    if (data == nullptr || data_size == 0) {
        set_error(error, error_size, "empty JPH data");
        return -1;
    }

    try {
        ojph::mem_infile mem;
        mem.open(data, data_size);

        ojph::codestream codestream;
        codestream.read_headers(&mem);
        codestream.restrict_input_resolution(0, 0);
        codestream.set_planar(false);

        ojph::param_siz siz = codestream.access_siz();
        ojph::ui32 comps = siz.get_num_components();
        if (comps != 1 && comps != 3) {
            set_error(error, error_size, "only grayscale and RGB JPH images are supported");
            codestream.close();
            return -1;
        }
        for (ojph::ui32 c = 0; c < comps; ++c) {
            if (siz.get_bit_depth(c) > 8 || siz.is_signed(c)) {
                set_error(error, error_size, "only unsigned 8-bit JPH images are supported");
                codestream.close();
                return -1;
            }
            ojph::point ds = siz.get_downsampling(c);
            if (ds.x != 1 || ds.y != 1) {
                set_error(error, error_size, "subsampled JPH components are not supported");
                codestream.close();
                return -1;
            }
        }

        ojph::ui32 w = siz.get_recon_width(0);
        ojph::ui32 h = siz.get_recon_height(0);
        if (w == 0 || h == 0 || w > JPH_MAX_DIMENSION || h > JPH_MAX_DIMENSION) {
            set_error(error, error_size, "JPH image dimensions are out of range");
            codestream.close();
            return -1;
        }
        size_t rowstride = static_cast<size_t>(w) * 4;
        size_t size = rowstride * h;
        uint8_t *buf = static_cast<uint8_t *>(std::malloc(size));
        if (buf == nullptr) {
            set_error(error, error_size, "failed to allocate pixel buffer");
            codestream.close();
            return -1;
        }
        std::memset(buf, 0xff, size);

        codestream.create();
        if (comps == 1) {
            for (ojph::ui32 y = 0; y < h; ++y) {
                ojph::ui32 comp_num = 0;
                ojph::line_buf *line = codestream.pull(comp_num);
                if (comp_num != 0) {
                    std::free(buf);
                    set_error(error, error_size, "unexpected OpenJPH component order");
                    codestream.close();
                    return -1;
                }
                uint8_t *row = buf + static_cast<size_t>(y) * rowstride;
                for (ojph::ui32 x = 0; x < w; ++x) {
                    uint8_t v = clamp8(line->i32[x]);
                    row[x * 4] = v;
                    row[x * 4 + 1] = v;
                    row[x * 4 + 2] = v;
                }
            }
        } else {
            const int offsets[3] = {2, 1, 0};
            for (ojph::ui32 y = 0; y < h; ++y) {
                uint8_t *row = buf + static_cast<size_t>(y) * rowstride;
                for (ojph::ui32 c = 0; c < 3; ++c) {
                    ojph::ui32 comp_num = 0;
                    ojph::line_buf *line = codestream.pull(comp_num);
                    if (comp_num != c) {
                        std::free(buf);
                        set_error(error, error_size, "unexpected OpenJPH component order");
                        codestream.close();
                        return -1;
                    }
                    int offset = offsets[c];
                    for (ojph::ui32 x = 0; x < w; ++x)
                        row[x * 4 + offset] = clamp8(line->i32[x]);
                }
            }
        }
        codestream.close();

        *pixels = buf;
        *pixels_size = size;
        *width = w;
        *height = h;
        *stride = static_cast<uint32_t>(rowstride);
        return 0;
    } catch (const std::exception &e) {
        set_error(error, error_size, e.what());
        return -1;
    } catch (...) {
        set_error(error, error_size, "unknown OpenJPH decode error");
        return -1;
    }
}
