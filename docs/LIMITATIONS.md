# Validation limitations

A passing host and fake-root suite proves deterministic packaging, bounded extraction, shell/parser compatibility, authority validation, reviewed-hash gates, transaction behavior and the tested path-containment properties.

It does not prove behavior of:

- Android init ordering outside the simulated entrypoints;
- Magisk daemon internals or a real module upgrade;
- SELinux labels and policy enforcement;
- real bind mounts or mount namespaces;
- Binder services, package manager, HALs or proprietary Pixel components;
- bootloader, AVB, TEE or hardware-backed attestation.

Those claims require controlled physical-device validation on the exact Pixel model/build after installing the exact candidate ZIP.

Physical-device testing to date is limited to **Pixel 9a** and **Pixel 8**. Other Pixel models remain untested and must not be treated as validated merely because the host/fake-root suite passes.
