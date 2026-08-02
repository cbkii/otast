# Contributing

Changes must preserve OTAST's fail-closed transaction and authority boundaries.

1. Work in a branch.
2. Change one causal variable at a time.
3. Update compatibility hashes only from reviewed upstream evidence.
4. Never add live device captures, keyboxes, credentials, private keys or local reports.
5. Run `bash scripts/test.sh --full`.
6. Include the fake-root evidence and explain any physical-device validation still required.

Runtime shell is Magisk BusyBox `ash`. Host scripts are Bash. Do not introduce a persistent polling loop, implicit Apply at boot, fuzzy target discovery, or traversal of unrelated module trees.
