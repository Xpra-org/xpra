#
# setup.py
#
# Copyright (C) 2010 Andrew Resch <andrewresch@gmail.com>
# Copyright (C) 2011 Pedro Algarvio <pedro@algarvio.me>
#
# Rencode is free software.
#
# You may redistribute it and/or modify it under the terms of the
# GNU General Public License, as published by the Free Software
# Foundation; either version 3 of the License, or (at your option)
# any later version.
#
# deluge is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with deluge.    If not, write to:
#     The Free Software Foundation, Inc.,
#     51 Franklin Street, Fifth Floor
#     Boston, MA  02110-1301, USA.
#

import sys
from distutils.core import setup
from distutils.extension import Extension
from Cython.Distutils import build_ext
from distutils.errors import CCompilerError, DistutilsPlatformError

ext_modules = [
    Extension("rencode._rencode",
              extra_compile_args=["-O3"],
              sources=["rencode/rencode.pyx"]
    )
]

class optional_build_ext(build_ext):
    # This class allows C extension building to fail.
    def run(self):
        try:
            build_ext.run(self)
        except DistutilsPlatformError:
            _etype, e, _tb = sys.exc_info()
            self._unavailable(e)

    def build_extension(self, ext):
        try:
            build_ext.build_extension(self, ext)
            global _speedup_available
            _speedup_available = True
        except CCompilerError:
            _etype, e, _tb = sys.exc_info()
            self._unavailable(e)

    def _unavailable(self, exc):
        print('*' * 70)
        print("""WARNING:
The C extension could not be compiled, speedups will not be
available.""")
        print('*' * 70)
        print(exc)

description = """\
The rencode module is similar to bencode from the BitTorrent project. For
complex, heterogeneous data structures with many small elements, r-encodings
take up significantly less space than b-encodings. This version of rencode is
a complete rewrite in Cython to attempt to increase the performance over the
pure Python module written by Petru Paler, Connelly Barnes et al.
"""

setup(
  name="rencode",
  version="1.0.3",
  packages=["rencode"],
  description=description,
  author="Andrew Resch",
  author_email="andrewresch@gmail.com",
  cmdclass={'build_ext': optional_build_ext},
  ext_modules=ext_modules
)
