To compile this policy,
just symlink the SELinux make file here, ie:
ln -sf /usr/share/selinux/devel/Makefile ./
Then run make:
make

To load the policy:
semodule -i xpra_cups.pp

To relabel the cups backend:
restorecon /usr/lib/cups/backend/xpraforwarder
