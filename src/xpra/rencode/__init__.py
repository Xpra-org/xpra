try:
    from rencode._rencode import *
except ImportError:
    import rencode.rencode_orig
    prev_all = rencode.rencode_orig.__all__[:]
    del rencode.rencode_orig.__all__
    from rencode.rencode_orig import *
    rencode.rencode_orig.__all__ = prev_all

__all__ = ['dumps', 'loads']
