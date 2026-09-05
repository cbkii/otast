# Releases

The authoritative OTAST release procedure is documented in [RELEASE.md](RELEASE.md).

For the real Pixel validation path, see [PHYSICAL-DEVICE-PROOF.md](PHYSICAL-DEVICE-PROOF.md).

Use those documents for:

- automatic or explicit release versioning;
- fresh release-time compatibility target/dependency monitoring;
- mandatory full deterministic qualification for stable candidates;
- production draft preparation and exact hosted-bundle verification;
- mandatory stable physical Pixel proof, with proof reuse only under runtime-equivalence provenance;
- independent 4 KiB/16 KiB page-size qualification status;
- publication-time tag verification and stable Magisk `update.json` synchronisation;
- the separate read-only branch-build workflow;
- immutable GitHub Actions pins maintained through Dependabot review.

This file intentionally contains no duplicate workflow procedure so the release contract has one maintained source of truth.
