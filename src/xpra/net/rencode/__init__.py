try:
    from xpra.net.rencode.rencode import *
    from xpra.net.rencode.rencode import __version__
except ImportError:
    import rencode_orig
    prev_all = rencode_orig.__all__[:]
    del rencode_orig.__all__
    from rencode_orig import *
    from rencode_orig import __version__
    rencode_orig.__all__ = prev_all

__all__ = ['dumps', 'loads']
