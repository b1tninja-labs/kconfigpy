# Security

Report a vulnerability privately through GitHub's "Report a vulnerability" button on this repository,
not in a public issue. Include the kernel version and the snapshot or tree that reproduces it, with any
hardware identifiers removed.

kconfigpy only reads `/sys` and `/proc/modules` on the machine it runs on, and it writes only the output
directory you name. Over SSH it pipes its snapshot module to the remote `python3` and reads the result; it
installs nothing on the remote host.
