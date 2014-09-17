try:
    from rencode._rencode import *
    from rencode._rencode import __version__
except ImportError:
    import rencode.rencode_orig
    prev_all = rencode.rencode_orig.__all__[:]
    del rencode.rencode_orig.__all__
    from rencode.rencode_orig import *
    from rencode.rencode_orig import __version__
    rencode.rencode_orig.__all__ = prev_all

__all__ = ['dumps', 'loads']
