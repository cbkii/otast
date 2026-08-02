# Validation limitations

A passing host and fake-root suite proves deterministic packaging, bounded extraction, shell/parser compatibility, authority validation, reviewed-hash gates, transaction behavior and the tested path-containment properties.

It does not prove behavior of:

- Android init ordering outside the simulated entrypoints;
- Magisk daemon internals or a real module upgrade;
- SELinux labels and policy enforcement;
- real bind mounts or mount namespaces;
- Binder services, package manager, HALs or proprietary Pixel components;
- bootloader, AVB, TEE or hardware-backed attestation.

Those claims require a controlled Pixel 9a validation after installing the exact candidate ZIP.
