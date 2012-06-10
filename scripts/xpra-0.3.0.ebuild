# Copyright 2010-2012 Antoine Martin <antoine@nagafix.co.uk>
# Copyright 1999-2011 Gentoo Foundation
# Distributed under the terms of the GNU General Public License v2

EAPI=3

PYTHON_DEPEND="2"
RESTRICT_PYTHON_ABIS="2.4 2.5 3.*"
SUPPORT_PYTHON_ABIS="1"
inherit distutils eutils

DESCRIPTION="X Persistent Remote Apps (xpra)"
HOMEPAGE="http://xpra.org/"
SRC_URI="http://xpra.org/src/${P}.tar.bz2"

LICENSE="GPL-2"
SLOT="0"
KEYWORDS="amd64 x86"
IUSE="jpeg libnotify parti png server x264 vpx ssh"

EPATCH_OPTS="-p1"

COMMON_DEPEND="dev-python/pygtk:2
	x11-libs/libX11
	x11-libs/libXcomposite
	x11-libs/libXdamage
	x11-apps/setxkbmap
	server? ( x11-libs/libXtst )
	server? ( x11-base/xorg-server[-minimal] )
	!server? ( x11-apps/xmodmap )
	!x11-wm/parti"

RDEPEND="${COMMON_DEPEND}
	parti? ( dev-python/ipython
		 dev-python/dbus-python )
	libnotify? ( dev-python/dbus-python )
	jpeg? ( dev-python/imaging )
	png? ( dev-python/imaging )
	x264? ( media-libs/x264 )
	vpx? ( media-libs/libvpx )
	ssh? ( net-misc/openssh )
	server? ( x11-base/xorg-server[xvfb] )"
DEPEND="${COMMON_DEPEND}
	dev-util/pkgconfig
	server? ( dev-python/cython )"

src_prepare() {
	if ! use server; then
		epatch disable-posix-server.patch
	fi
	if ! use x264; then
		epatch disable-x264.patch
	fi
	if ! use vpx; then
		epatch disable-vpx.patch
	fi

	$(PYTHON -2) make_constants_pxi.py wimpiggy/lowlevel/constants.txt wimpiggy/lowlevel/constants.pxi || die
}
