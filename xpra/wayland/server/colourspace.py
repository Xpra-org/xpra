# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Translation between the `wp_color_manager_v1` named enums and ITU-T H.273 code points.

The wayland colour management protocol names its primaries and transfer functions,
whereas the rest of xpra uses the H.273 numbering (see `xpra.util.colourspace`).
The values below are protocol wire values, so they are stable and can be hardcoded:
this module does not need wayland or wlroots to be present, which also makes it testable
without a compositor.

Only the entries that H.273 can express are listed:
`adobe_rgb` primaries have no code point, so we neither advertise nor accept them.
"""

from typing import Final

from xpra.util.colourspace import Colourspace, Primaries, TransferFunction, SRGB

# `enum wp_color_manager_v1_primaries` -> H.273 colour primaries
PRIMARIES: Final[dict[int, Primaries]] = {
    1: Primaries.BT709,             # srgb
    2: Primaries.BT470M,            # pal_m
    3: Primaries.BT470BG,           # pal
    4: Primaries.SMPTE170M,         # ntsc
    5: Primaries.GENERIC_FILM,      # generic_film
    6: Primaries.BT2020,            # bt2020
    7: Primaries.XYZ,               # cie1931_xyz
    8: Primaries.DCI_P3,            # dci_p3
    9: Primaries.DISPLAY_P3,        # display_p3
}

# `enum wp_color_manager_v1_transfer_function` -> H.273 transfer characteristics
TRANSFER_FUNCTIONS: Final[dict[int, TransferFunction]] = {
    1: TransferFunction.BT709,          # bt1886
    2: TransferFunction.GAMMA22,        # gamma22
    3: TransferFunction.GAMMA28,        # gamma28
    4: TransferFunction.SMPTE240M,      # st240
    5: TransferFunction.LINEAR,         # ext_linear
    6: TransferFunction.LOG,            # log_100
    7: TransferFunction.LOG_SQRT,       # log_316
    8: TransferFunction.IEC61966_2_4,   # xvycc
    9: TransferFunction.SRGB,           # srgb
    10: TransferFunction.SRGB,          # ext_srgb: sRGB curve, extended beyond [0, 1]
    11: TransferFunction.PQ,            # st2084_pq
    12: TransferFunction.ST428,         # st428
    13: TransferFunction.HLG,           # hlg
}


def get_colourspace(primaries_named: int, tf_named: int) -> Colourspace:
    """
    Convert the named parts of a `wp_image_description_info_v1` into a `Colourspace`.

    Both arguments are zero when unset, and surfaces are free to tag only one of the two:
    whatever is missing (or is something H.273 cannot express) keeps its sRGB value,
    which is also the protocol's own default.
    Wayland surfaces are always RGB and full range, so the matrix and range never vary.
    """
    return Colourspace(
        primaries=PRIMARIES.get(primaries_named, SRGB.primaries),
        transfer=TRANSFER_FUNCTIONS.get(tf_named, SRGB.transfer),
        matrix=SRGB.matrix,
        range=SRGB.range,
    )
