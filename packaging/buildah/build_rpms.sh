#!/bin/bash

dnf --version >& /dev/null
if [ "$?" == "0" ]; then
	DNF="${DNF:-dnf}"
else
	DNF="${DNF:-yum}"
fi

if [ `id -u` != "0" ]; then
	if [ "${DNF}" == "dnf" ]; then
		echo "Warning: this script usually requires root to be able to run dnf"
	fi
fi

ARCH=`arch`
for dir in "./repo/SRPMS" "./repo/$ARCH"; do
	echo "* (re)creating repodata in $dir"
	mkdir $dir 2> /dev/null
	rm -fr $dir/repodata
	createrepo_c $dir > /dev/null
done

#if we are going to build xpra,
#make sure we expose the revision number
#so the spec file can generate the expected file names
#(ie: xpra-4.2-0.r29000)
XPRA_REVISION=""
XPRA_TAR_XZ=`ls -d pkgs/xpra-* | grep -v html5 | sort -V | tail -n 1`
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
	rpmspec -q --rpms ${SPECFILE}
	while read -r dep; do
		if [ "$DNF" == "yum" ]; then
			MATCHES=`repoquery "$dep" --repoid=xpra-local-build 2> /dev/null | wc -l`
		else
			MATCHES=`$DNF repoquery "$dep" --repo xpra-local-build 2> /dev/null | wc -l`
			if [ "${MATCHES}" == "0" ]; then
				#sometimes rpmspec gets confused,
				#try to find the source package instead:
				srcdep="${dep/$ARCH/src}"
				MATCHES=`$DNF repoquery "$srcdep" --repo xpra-local-source 2> /dev/null | wc -l`
			fi
		fi
		if [ "${MATCHES}" != "0" ]; then
			echo " * found   ${srcdep}"
		else
			echo " * missing ${dep}"
			if [[ $dep == *debuginfo* ]]; then
				echo " (ignored debuginfo)"
			elif [[ $dep == *debugsource* ]]; then
				echo " (ignored debugsource)"
			elif [[ $dep == *-doc-* ]]; then
				echo " (ignored doc)"
			else
				MISSING="${MISSING} ${dep}"
			fi
		fi
	done < <(rpmspec -q --rpms ${SPECFILE} 2> /dev/null)
	if [ ! -z "${MISSING}" ]; then
		echo " need to rebuild $p to get:${MISSING}"
		echo " - installing build dependencies"
		yum-builddep --version >& /dev/null
		if [ "$?" == "0" ]; then
			yum-builddep -y ${SPECFILE} > builddep.log
		else
			$DNF builddep -y ${SPECFILE} > builddep.log
		fi
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
		cp ./rpm/* "$HOME/rpmbuild/SOURCES/"
		#source packages
		cp ./pkgs/* "rpmbuild/SOURCES/"
		cp ./pkgs/* "$HOME/rpmbuild/SOURCES/"
		echo " - building RPM package(s)"
		rpmbuild --define "_topdir `pwd`/rpmbuild/" --define "xpra_revision_no ${XPRA_REVISION}" -ba $SPECFILE >& rpmbuild.log
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
			createrepo_c $dir >& createrepo.log
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
