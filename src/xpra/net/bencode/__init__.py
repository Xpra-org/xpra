try:
    from xpra.net.bencode.cython_bencode import bencode, bdecode, __version__
except ImportError:
    from xpra.net.bencode.bencode import bencode, bdecode, __version__

__all__ = ['bencode', 'bdecode', "__version__"]
