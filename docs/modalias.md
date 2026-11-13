# Module aliases: what the built tree holds

`kbuild.module_aliases(tree)` reads `modules.alias` and `modules.builtin.alias` from a built tree. This note records
what those files are, what the router kernel's built tree actually contains, and what that means for the reader.

## Evidence base

Built tree: `/work/o-6.18.62` in the `rooter-build` Docker volume, mounted read-only into `rooter-builder:latest`.
Kernel source: `/work/src/linux-6.18.62`, same volume. The kernel is `6.18.62`, built with `# CONFIG_MODULES is not set`
(`/work/o-6.18.62/.config`, line 765).

## What the built tree does not contain

- `modules.alias`: absent.
- `modules.builtin.alias`: absent.
- `modules.order`, `modules.dep`: absent.
- `*.ko`: none (0 files).

These files come from `depmod`, which the install step runs only for a modules build
(`scripts/Makefile.modinst:128-135`, `scripts/depmod.sh`). With `CONFIG_MODULES` off there is nothing to install and
nothing to index, so the files are never written. The reader therefore refuses this tree. That is the correct answer:
the tree has no module aliases to read.

The reader was not fed a generated file. No alias file was derived from the sources, and none was created in the volume.

## What the built tree does contain instead

| File | Size | Content |
|---|---|---|
| `modules.builtin` | 2795 bytes, 89 lines | One path per line, `kernel/.../*.ko`. The built-in module list. |
| `modules.builtin.modinfo` | 94885 bytes, 0 newlines, 2057 NUL bytes | `module.key=value` records, each NUL-terminated. 1388 are `module.alias=` records. |
| `.config` | 88995 bytes | Holds `# CONFIG_MODULES is not set`. |

`modules.builtin.modinfo` is written by the vmlinux build (`scripts/Makefile.vmlinux:114-139`) from the kernel's
`.modinfo` section. The `module.alias=` records are emitted by `modpost` as `MODULE_INFO(<mod>.alias, "...")`
(`scripts/mod/modpost.c:2096`). They are the same alias information that `depmod` would turn into
`modules.builtin.alias`, but in the kernel's own format rather than the depmod file format.

`module_aliases` does not read this file. Reading it would be a new reader and needs its own design decision.

## Counts per bus (from `modules.builtin.modinfo`)

Each `module.alias=` record was split at its first colon. The bus is the text before that colon, with `acpi*` kept as
written in the record. Patterns without a colon are grouped under "(no colon)".

| Bus or class | Records |
|---|---:|
| pci | 587 |
| usb | 409 |
| acpi* | 159 |
| pnp | 156 |
| (no colon) | 68 |
| scsi | 4 |
| platform | 3 |
| hid | 1 |
| devname | 1 |
| **total** | **1388** |

The 68 no-colon records are filesystem, block, crypto, netfilter and similar aliases, for example `fs-ext4`,
`block-major-135-*`, `crypto-sha256`, `nft-expr-ct`. The distinct modules carrying aliases are 32; the built-in module
list has 89 entries.

Command used (read-only; output went to the container's `/tmp`):

```sh
tr "\0" "\n" < modules.builtin.modinfo | grep "\.alias=" | sed "s/^[^=]*=//" \
  | awk -F: '{ if (NF>1) k=$1; else k="(no colon)"; print k }' | sort | uniq -c | sort -rn
```

## Format of the reader's input

The reader accepts `alias <pattern> <module>`: three whitespace-separated fields, first field `alias`. Module names are
normalised so `-` and `_` are the same character.

What is verified here:
- `file2alias.c` produces the `usb:v...` (line 201), `pci:...` (line 438) and `acpi*:%s:*` (lines 546-597) pattern
  forms. The `*`-wildcard convention matches the `fnmatch` used by `trace.candidates`. The no-colon forms in the table
  above (`fs-ext4`, `block-major-...`, `crypto-...`, `nft-...`) appear in the built records; their producers were not
  traced in this pass.
- `modules.builtin.modinfo` uses the `module.alias=pattern` form, with NUL terminators. Its patterns contain no spaces.

What is not verified here:
- The exact text `depmod` writes into `modules.alias` and `modules.builtin.alias`. `depmod` is kmod, not part of the
  kernel tree, and no `depmod`-written file exists in this volume. The reader's three-field form is taken from the
  depmod output format as the code expects it. Once a modules build exists, check one real `modules.alias` against
  `module_aliases` before relying on it.

## Silent skips

`module_aliases` drops any line that is not exactly three fields starting with `alias`. A malformed line is skipped
without a message. The router tree exposes this: fed the raw `module.alias=pattern` records, the reader returns no
answers rather than refusing. The test `test_modinfo_alias_records_are_not_modules_alias_lines` pins that behaviour.
Whether a malformed line should be an error is an open question.

## Tests

- `tests/test_kbuild_modalias.py`: reader behaviour on synthetic files and refusal when files are missing.
- `tests/test_kbuild_real_tree.py`: the same reader on verbatim excerpts from the router tree. It checks refusal on
  this tree, the CONFIG_MODULES state, and that the modinfo records give no answers.
- `tests/test_kbuild_builtin.py`: the CONFIG_MODULES-off mapping and its statement.
