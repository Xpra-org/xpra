try:
    from xpra.net.rencode._rencode import *
    from xpra.net.rencode._rencode import __version__
except ImportError:
    import xpra.net.rencode.rencode_orig
    prev_all = xpra.net.rencode.rencode_orig.__all__[:]
    del xpra.net.rencode.rencode_orig.__all__
    from xpra.net.rencode.rencode_orig import *
    from xpra.net.rencode.rencode_orig import __version__
    xpra.net.rencode.rencode_orig.__all__ = prev_all

__all__ = ['dumps', 'loads']
