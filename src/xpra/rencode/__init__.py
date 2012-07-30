try:
    from xpra.rencode._rencode import *
except ImportError:
    import xpra.rencode.rencode_orig
    prev_all = xpra.rencode.rencode_orig.__all__[:]
    del xpra.rencode.rencode_orig.__all__
    from xpra.rencode.rencode_orig import *
    xpra.rencode.rencode_orig.__all__ = prev_all

__all__ = ['dumps', 'loads']
