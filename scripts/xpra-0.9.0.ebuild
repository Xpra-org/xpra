# Copyright 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright 1999-2012 Gentoo Foundation
# Distributed under the terms of the GNU General Public License v2

EAPI=5

PYTHON_DEPEND="*"
RESTRICT_PYTHON_ABIS="2.4 2.5 3.*"
SUPPORT_PYTHON_ABIS="1"
inherit distutils eutils

DESCRIPTION="X Persistent Remote Apps (xpra)"
HOMEPAGE="http://xpra.org/"
SRC_URI="http://xpra.org/src/${P}.tar.bz2"

LICENSE="GPL-2"
SLOT="0"
KEYWORDS="amd64 x86 amd64-linux x86-linux"
IUSE="+clipboard ffmpeg jpeg libnotify png sound +rencode server ssh x264 vpx webp opengl"

S="${WORKDIR}/${PF}"

COMMON_DEPEND="dev-python/pygtk:2
	x11-libs/libX11
	x11-libs/libXcomposite
	x11-libs/libXdamage
	ffmpeg? (
		virtual/ffmpeg
		x264? ( media-libs/x264 )
		vpx? ( media-libs/libvpx )
	)
	server? ( x11-libs/libXtst )
	sound? (
		media-sound/pulseaudio
		media-libs/gstreamer
		media-libs/gst-plugins-base
		dev-python/gst-python
	)"

RDEPEND="${COMMON_DEPEND}
	x11-apps/xmodmap
	libnotify? ( dev-python/dbus-python )
	opengl? ( dev-python/pygtkglext )
	jpeg? ( dev-python/imaging )
	png? ( dev-python/imaging )
	webp? ( media-libs/libwebp )
	ssh? ( virtual/ssh )
	server? ( x11-base/xorg-server[xvfb,-minimal] )"
DEPEND="${COMMON_DEPEND}
	virtual/pkgconfig
	>=dev-python/cython-0.16"

src_compile() {
	#we may specify --without-vpx/--without-x264 more than once, which is ok
	distutils_src_compile \
		$(use x264 || echo '--without-x264') \
		$(use vpx || echo '--without-vpx') \
		$(use webp || echo '--without-webp') \
		$(use ffmpeg || echo '--without-vpx --without-x264') \
		$(use clipboard || echo '--without-clipboard') \
		$(use rencode || echo '--without-rencode') \
		$(use server || echo '--without-server') \
		$(use sound || echo '--without-sound') \
		$(use opengl || echo '--without-opengl')
}

src_install() {
	distutils_src_install
	rm -vf "${ED}"usr/share/{xpra}/{README*,COPYING} || die
}
