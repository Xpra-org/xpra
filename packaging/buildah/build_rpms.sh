#!/bin/bash

DNF="${DNF:-dnf}"

if [ `id -u` != "0" ]; then
	if [ "${DNF}" == "dnf" ]; then
		echo "Warning: this script usually requires root to be able to run dnf"
	fi
fi

ARCH=`arch`
for dir in "./repo/SRPMS" "./repo/$ARCH"; do
	if [ ! -d "$dir/repodata" ]; then
		echo "* creating repodata in $dir"
		mkdir $dir
		createrepo $dir > /dev/null
	fi
done

#if we are going to build xpra,
#make sure we expose the revision number
#so the spec file can generate the expected file names
#(ie: xpra-4.2-0.r29000)
XPRA_REVISION=""
XPRA_TAR_XZ=`ls pkgs/xpra-* | grep -v html5 | sort -n | tail -n 1`
if [ -z "${XPRA_TAR_XZ}" ]; then
	echo "Warning: xpra source not found"
else
	rm -fr xpra-*
	tar -Jxf ${XPRA_TAR_XZ} "xpra-*/xpra/src_info.py"
	if [ "$?" != "0" ]; then
		echo "failed to extract src_info"
		exit 1
	fi
	XPRA_REVISION=`grep "REVISION=" xpra-*/xpra/src_info.py | awk -F= '{print $2}'`
	if [ -z "${XPRA_REVISION}" ]; then
		echo "revision not found in src_info.py"
		exit 1
	fi
fi
export XPRA_REVISION


#read the name of the spec files we may want to build:
while read p; do
	if [ -z "${p}" ]; then
		#skip empty lines
		continue
	fi
	if [[ "$p" == "#"* ]]; then
		#skip comments
		continue
	fi
	echo "****************************************************************"
	echo " $p"
	SPECFILE="./rpm/$p.spec"
	MISSING=""
	while read -r dep; do
		MATCHES=`$DNF repoquery "$dep" --repo xpra-local-build 2> /dev/null | wc -l`
		if [ "${MATCHES}" == "0" ]; then
			echo " * missing ${dep}"
			MISSING="${MISSING} ${dep}"
		else
			echo " * found   ${dep}"
		fi
	done < <(rpmspec -q --rpms ${SPECFILE} 2> /dev/null)
	if [ ! -z "${MISSING}" ]; then
		echo " need to rebuild $p to get:${MISSING}"
		echo " - installing build dependencies"
		$DNF builddep -y ${SPECFILE} > builddep.log
		if [ "$?" != "0" ]; then
			echo "-------------------------------------------"
			echo "builddep failed:"
			cat builddep.log
			exit 1
		fi
		rm -fr "rpmbuild/RPMS" "rpmbuild/SRPMS"
		mkdir -p "rpmbuild/SOURCES" "rpmbuild/RPMS" 2> /dev/null
		#specfiles and patches
		cp ./rpm/* "rpmbuild/SOURCES/"
		#source packages
		cp ./pkgs/* "rpmbuild/SOURCES/"
		echo " - building RPM package(s)"
		rpmbuild --define "_topdir `pwd`/rpmbuild/" -ba $SPECFILE >& rpmbuild.log
		if [ "$?" != "0" ]; then
			echo "-------------------------------------------"
			echo "rpmbuild failed:"
			cat rpmbuild.log
			exit 1
		fi
		rsync -rplogt rpmbuild/RPMS/*/*rpm "./repo/$ARCH/"
		rsync -rplogt rpmbuild/SRPMS/*rpm "./repo/SRPMS/"
		#update the local repo:
		echo " - re-creating repository metadata"
		for dir in "./repo/SRPMS" "./repo/$ARCH"; do
			createrepo $dir >& createrepo.log
			if [ "$?" != "0" ]; then
				echo "-------------------------------------------"
				echo "'createrepo $dir' failed"
				cat createrepo.log
				exit 1
			fi
		done
		echo " - updating local packages"
		$DNF update -y
	fi
done <./rpms.txt
