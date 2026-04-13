# AGENTS.md

## Source Of Truth: Root vs `pkg/`

This repository has two relevant areas:

- Root scripts (development source of truth):
  - `dictee`
  - `dictee-setup.py`
  - `dictee-tray.py`
  - `dictee-ptt.py`
  - `dictee-postprocess.py`
- Packaging/staging tree:
  - `pkg/dictee/...`
  - especially `pkg/dictee/usr/bin/...`

## Why both exist

`pkg/dictee/` is a package layout/staging tree used to build/install artifacts
(`.deb`, `.rpm`, tarballs, system paths like `/usr/bin`, `/usr/share`, etc).

This pattern is common in packaging workflows.

## Mandatory editing rule

- Do **not** treat `pkg/dictee/usr/bin/*` as primary source for the scripts listed above.
- Edit those scripts in the repository root only.
- Consider `pkg/dictee/usr/bin/*` as generated/synced staging copies.

## Sync behavior in this repo

Build/install scripts copy from root into `pkg`:

- `build-deb.sh`
- `build-rpm.sh`
- `install.sh`
- `PKGBUILD`

So manual edits inside `pkg/dictee/usr/bin/*` can be overwritten by normal build/install steps.

## Practical workflow

1. Implement changes in root source files.
2. Sync/copy updated files into `pkg/dictee/usr/bin/` when preparing packages.
3. Avoid manual divergent changes between root and `pkg`.

## Build staging policy

- Build scripts must use a temporary staging directory (for example under `/tmp`)
  copied from `pkg/dictee` template.
- Do not mutate `pkg/dictee` directly during package build.
- `pkg/dictee` remains a template/reference tree in git.

## Volatile artifacts cleanup

- After successful build/install, run safe cleanup for volatile artifacts:
  - `__pycache__/`
  - `*.pyc`, `*.pyo`
  - root-generated `dictee.plasmoid`
- Never delete `pkg/dictee` as part of normal cleanup.

## If divergence is found

- Compare root vs `pkg` versions first.
- Keep root as canonical for the scripts listed in this file.
- Re-sync `pkg` from root unless there is an explicit, documented packaging-only exception.

## AGENTS.md maintenance rule

- Keep this file up to date on every task that changes architecture, build/install flow,
  source-of-truth policy, or developer workflow.
- If a new recurring rule/process is introduced during development, document it here
  in the same branch before finishing the task.

## Build and install

After implementing changes, always run `./build_and_install.sh` to build Rust binaries
and install the latest version to the system. This script:
1. Builds Rust release binaries (`build.sh`)
2. Syncs root scripts into `pkg/dictee/usr/bin/`
3. Installs to system (`install.sh`)
