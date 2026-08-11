# Releases

The authoritative OTAST release procedure is documented in [RELEASE.md](RELEASE.md).

For the real Pixel validation path, see [PHYSICAL-DEVICE-PROOF.md](PHYSICAL-DEVICE-PROOF.md).

Use those documents for:

- automatic or explicit release versioning;
- optional full validation and mandatory release-integrity gates;
- production draft preparation;
- optional physical Pixel qualification with `otast release --no-publish`;
- publishing with physical proof required or explicitly bypassed by the repository owner;
- publication-time tag verification and stable Magisk `update.json` synchronization;
- the separate branch-build workflow.

This file intentionally contains no duplicate workflow instructions so the release contract has one maintained source of truth.
