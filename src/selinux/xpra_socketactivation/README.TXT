To compile this policy,
just symlink the SELinux make file here, ie:
ln -sf /usr/share/selinux/devel/Makefile ./
Then run make:
make

To load the policy:
semodule -i xpra_socketactivation.pp

Assign the port:
semanage port -a -t xpra_port_t -p tcp 14500


To remove the policy:
semanage port -d -p tcp 14500
semodule -r xpra_socketactivation

