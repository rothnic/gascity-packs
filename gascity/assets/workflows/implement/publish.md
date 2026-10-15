Execute `gc gc workspace flow publish` through
[the native publication recipe](../workspace-publication.md). It requires the
current approved canonical commit, retained artifacts and explicit authority
for the selected target. Persist the publish intent before effects. An uncertain
response reconciles that same intent and marker before any further action.

The direct workflow requires the exact qualified terminal result and canonical
approval before publication. Missing independent review blocks publication.
A summary path or caller opt-in alone cannot approve source. Retain the caller's
publication options:

- push {{push}}
- open_pr {{open_pr}}
- summary_path {{summary_path}}

When `summary_path` is set, require its absolute path and bytes to match the
accepted canonical summary. Otherwise read the accepted summary's exact path
from the native canonical record. An absent or changed summary blocks publication.
If neither `push` nor `open_pr` is enabled, record a no-op without mutating
remotes. Preserve any earlier failure.
