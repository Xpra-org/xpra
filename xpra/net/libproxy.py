# encoding: utf-8
###############################################################################
# libproxy - A library for proxy configuration
# Copyright (C) 2006 Nathaniel McCallum <nathaniel@natemccallum.com>
# 
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
# 
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
# 
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301 USA
###############################################################################

"A library for proxy configuration and autodetection."

import ctypes
import ctypes.util
import platform

import sys

def _load(name, *versions):
    for ver in versions:
        try: return ctypes.cdll.LoadLibrary('lib%s.so.%s' % (name, ver))
        except: pass
    name_ver = ctypes.util.find_library(name)
    if name_ver:
        return ctypes.cdll.LoadLibrary(name_ver)
    raise ImportError("Unable to find %s library" % name)

# Load libproxy
_libproxy = _load("proxy", 1)
_libproxy.px_proxy_factory_new.restype = ctypes.POINTER(ctypes.c_void_p)
_libproxy.px_proxy_factory_free.argtypes = [ctypes.c_void_p]
_libproxy.px_proxy_factory_get_proxies.restype = ctypes.POINTER(ctypes.c_void_p)
_libproxy.px_proxy_factory_free_proxies.argtypes = [ctypes.POINTER(ctypes.c_void_p)]

class ProxyFactory(object):
    """A ProxyFactory object is used to provide potential proxies to use
    in order to reach a given URL (via 'getProxies(url)').
 
    This instance should be kept around as long as possible as it contains
    cached data to increase performance.  Memory usage should be minimal (cache
    is small) and the cache lifespan is handled automatically.

    Usage is pretty simple:
        pf = libproxy.ProxyFactory()
        for url in urls:
            proxies = pf.getProxies(url)
            for proxy in proxies:
                if proxy == "direct://":
                    # Fetch URL without using a proxy
                elif proxy.startswith("http://"):
                    # Fetch URL using an HTTP proxy
                elif proxy.startswith("socks://"):
                    # Fetch URL using a SOCKS proxy
                
                if fetchSucceeded:
                    break    
    """

    class ProxyResolutionError(RuntimeError):
        """Exception raised when proxy cannot be resolved generally
           due to invalid URL"""
        pass

    def __init__(self):
        self._pf = _libproxy.px_proxy_factory_new()
        
    def getProxies(self, url):
        """Given a URL, returns a list of proxies in priority order to be used
        to reach that URL.

        A list of proxy strings is returned.  If the first proxy fails, the 
        second should be tried, etc... In all cases, at least one entry in the
        list will be returned. There are no error conditions.

        Regarding performance: this method always blocks and may be called
        in a separate thread (is thread-safe).  In most cases, the time
        required to complete this function call is simply the time required
        to read the configuration (e.g  from GConf, Kconfig, etc).  

        In the case of PAC, if no valid PAC is found in the cache (i.e.
        configuration has changed, cache is invalid, etc), the PAC file is 
        downloaded and inserted into the cache. This is the most expensive
        operation as the PAC is retrieved over the network. Once a PAC exists
        in the cache, it is merely a JavaScript invocation to evaluate the PAC.
        One should note that DNS can be called from within a PAC during 
        JavaScript invocation.

        In the case of WPAD, WPAD is used to automatically locate a PAC on the
        network.  Currently, we only use DNS for this, but other methods may
        be implemented in the future.  Once the PAC is located, normal PAC 
        performance (described above) applies.

        """
        if type(url) != str:
            raise TypeError("url must be a string!")

        if type(url) is bytes:
            # Python 2: str is bytes
            url_bytes = url
        else:
            # Python 3: str is unicode
            # TODO: Does this need to be encoded from IRI to ASCII (ACE) URI,
            # for example http://кц.рф/пример ->
            # http://xn--j1ay.xn--p1ai/%D0%BF%D1%80%D0%B8%D0%BC%D0%B5%D1%80?
            # Or is libproxy designed to accept IRIs like
            # http://кц.рф/пример? Passing in an IRI does seem to work
            # acceptably in practice, so do that for now.
            url_bytes = url.encode('utf-8')

        proxies = []
        array = _libproxy.px_proxy_factory_get_proxies(self._pf, url_bytes)
    
        if not bool(array):
            raise ProxyFactory.ProxyResolutionError(
                    "Can't resolve proxy for '%s'" % url)

        i=0
        while array[i]:
            proxy_bytes = ctypes.cast(array[i], ctypes.c_char_p).value
            if type(proxy_bytes) is str:
                # Python 2
                proxies.append(proxy_bytes)
            else:
                # Python 3
                proxies.append(proxy_bytes.decode('utf-8', errors='replace'))
            i += 1

        _libproxy.px_proxy_factory_free_proxies(array)
        
        return proxies
        
    def __del__(self):
        if _libproxy:
            _libproxy.px_proxy_factory_free(self._pf)
    
