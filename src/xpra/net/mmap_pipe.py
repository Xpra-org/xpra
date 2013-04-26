# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import ctypes
from wimpiggy.log import Logger
log = Logger()
debug = log.debug
warn = log.warn

#descr_data is a list of (offset, length)
#areas from the mmap region
def mmap_read(mmap_area, descr_data):
    """
        Reads data from the mmap_area as written by 'mmap_write'.
        The descr_data is the list of mmap chunks used.
    """
    data_start = ctypes.c_uint.from_buffer(mmap_area, 0)
    if len(descr_data)==1:
        #construct an array directly from the mmap zone:
        offset, length = descr_data[0]
        arraytype = ctypes.c_char * length
        data_start.value = offset+length
        return arraytype.from_buffer(mmap_area, offset)
    #re-construct the buffer from discontiguous chunks:
    data = ""
    for offset, length in descr_data:
        mmap_area.seek(offset)
        data += mmap_area.read(length)
        data_start.value = offset+length
    return data


def mmap_write(mmap_area, mmap_size, data):
    """
        Sends 'data' to the client via the mmap shared memory region,
        returns the chunks of the mmap area used (or None if it failed)
        and the mmap area's free memory.
    """
    #This is best explained using diagrams:
    #mmap_area=[&S&E-------------data-------------]
    #The first pair of 4 bytes are occupied by:
    #S=data_start index is only updated by the client and tells us where it has read up to
    #E=data_end index is only updated here and marks where we have written up to (matches current seek)
    # '-' denotes unused/available space
    # '+' is for data we have written
    # '*' is for data we have just written in this call
    # E and S show the location pointed to by data_start/data_end
    mmap_data_start = ctypes.c_uint.from_buffer(mmap_area, 0)
    mmap_data_end = ctypes.c_uint.from_buffer(mmap_area, 4)
    start = max(8, mmap_data_start.value)
    end = max(8, mmap_data_end.value)
    if end<start:
        #we have wrapped around but the client hasn't yet:
        #[++++++++E--------------------S+++++]
        #so there is one chunk available (from E to S):
        available = start-end
        chunk = available
    else:
        #we have not wrapped around yet, or the client has wrapped around too:
        #[------------S++++++++++++E---------]
        #so there are two chunks available (from E to the end, from the start to S):
        chunk = mmap_size-end
        available = chunk+(start-8)
    l = len(data)
    #update global mmap stats:
    mmap_free_size = available-l
    if mmap_free_size<=0:
        warn("mmap area full: we need more than %s but only %s left! ouch!", l, available)
        return None, mmap_free_size
    if l<chunk:
        """ data fits in the first chunk """
        #ie: initially:
        #[----------------------------------]
        #[*********E------------------------]
        #or if data already existed:
        #[+++++++++E------------------------]
        #[+++++++++**********E--------------]
        mmap_area.seek(end)
        mmap_area.write(data)
        data = [(end, l)]
        mmap_data_end.value = end+l
    else:
        """ data does not fit in first chunk alone """
        if available>=(mmap_size/2) and available>=(l*3) and l<(start-8):
            """ still plenty of free space, don't wrap around: just start again """
            #[------------------S+++++++++E------]
            #[*******E----------S+++++++++-------]
            mmap_area.seek(8)
            mmap_area.write(data)
            data = [(8, l)]
            mmap_data_end.value = 8+l
        else:
            """ split in 2 chunks: wrap around the end of the mmap buffer """
            #[------------------S+++++++++E------]
            #[******E-----------S+++++++++*******]
            mmap_area.seek(end)
            mmap_area.write(data[:chunk])
            mmap_area.seek(8)
            mmap_area.write(data[chunk:])
            l2 = l-chunk
            data = [(end, chunk), (8, l2)]
            mmap_data_end.value = 8+l2
    debug("sending damage with mmap: %s", data)
    return data, mmap_free_size
