try:
    from xpra.rencode._rencode import *
    from xpra.rencode._rencode import __version__
except ImportError:
    import xpra.rencode.rencode_orig
    prev_all = xpra.rencode.rencode_orig.__all__[:]
    del xpra.rencode.rencode_orig.__all__
    from xpra.rencode.rencode_orig import *
    from xpra.rencode.rencode_orig import __version__
    xpra.rencode.rencode_orig.__all__ = prev_all

__all__ = ['dumps', 'loads']
