# Copyright 2010-2011 Antoine Martin <antoine@nagafix.co.uk>
# Distributed under the terms of the GNU General Public License v2

SUPPORT_PYTHON_ABIS="1"

inherit eutils
inherit distutils


DESCRIPTION="screen for X - this is the modified version designed to work with
Window-Switch"
HOMEPAGE="http://code.google.com/p/partiwm/wiki/xpra"
SRC_URI="https://winswitch.org/src/${P}.tar.bz2"
LICENSE="GPL-3"
SLOT="0"
KEYWORDS="amd64 ppc x86"
IUSE="+server +ssh"
EAPI="2"
PYTHON_DEPEND="2"
RESTRICT_PYTHON_ABIS="3.*"


# You will need Xvfb!


DEPEND="dev-python/pycrypto
dev-python/pygtk
dev-python/imaging
ssh? ( net-misc/openssh )
server? ( x11-base/xorg-server[-minimal] )
server? ( dev-python/cython )
server? ( x11-libs/libXtst )
"

src_unpack() {
	unpack ${A}
	cd "${S}"
	if ! use server; then
		epatch "${FILESDIR}"/disable-posix-server.patch
	fi
}
src_compile() {
	python make_constants_pxi.py wimpiggy/lowlevel/constants.txt wimpiggy/lowlevel/constants.pxi
}
