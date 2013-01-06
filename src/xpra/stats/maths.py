# coding=utf8
# This file is part of Parti.
# Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Math functions used for inspecting/averaging lists of statistics
# see ServerSource, WindowSource and batch_delay_calculator
# We load them from cymaths and fallback to pymaths

from xpra.stats.base import (dec1, dec2, dec3,                      #@UnusedImport
    to_std_unit, std_unit,                                          #@UnusedImport
    std_unit_dec, absolute_to_diff_values,                          #@UnusedImport
    values_to_scaled_values, values_to_diff_scaled_values,          #@UnusedImport
    add_weighted_list_stats, find_invpow, add_list_stats)           #@UnusedImport

has_cymaths = False
try:
    import os
    if os.environ.get("XPRA_CYTHON_MATH", "1")=="1":
        from xpra.stats.cymaths import (logp,                       #@UnusedImport
                              calculate_time_weighted_average,      #@UnusedImport
                              time_weighted_average,                #@UnusedImport
                              calculate_timesize_weighted_average,  #@UnusedImport
                              calculate_for_target,                 #@UnusedImport
                              calculate_for_average, queue_inspect) #@UnusedImport
        has_cymaths = True
except Exception, e:
    print("failed to load cython math: %s" % e)

if not has_cymaths:
    from xpra.stats.pymaths import (logp,                           #@UnusedImport @Reimport
                              calculate_time_weighted_average,      #@UnusedImport @Reimport
                              time_weighted_average,                #@UnusedImport @Reimport
                              calculate_timesize_weighted_average,  #@UnusedImport @Reimport
                              calculate_for_target,                 #@UnusedImport @Reimport
                              calculate_for_average, queue_inspect) #@UnusedImport @Reimport
