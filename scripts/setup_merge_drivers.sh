#!/bin/sh
# WO-1184: register the "lineset" merge driver used by .gitattributes.
#
# Run once per clone. Git worktrees share the main clone's config, so one
# run covers every worktree of that clone. A fresh clone needs it again.
#
# Without it nothing breaks: git ignores an unknown merge driver name and
# uses its normal text merge (the `union` lines in .gitattributes need no
# setup at all). You only lose the automatic clean merges.
set -e
cd "$(git rev-parse --show-toplevel)"
git config merge.lineset.name "line-set merge for keyed record files"
git config merge.lineset.driver "python3 scripts/merge_line_set.py %O %A %B %P"
echo "lineset merge driver registered in $(git rev-parse --git-common-dir)/config"
