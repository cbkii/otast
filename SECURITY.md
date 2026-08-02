# Security policy

## Supported release

Security fixes are applied to the latest release candidate or stable release on the default branch.

## Reporting

Use GitHub private vulnerability reporting after the public repository is initialized. Do not open a public issue containing a keybox, private key, device identifier, raw `/data/adb` capture or other secret.

## Security model

OTAST is intentionally fail closed. It rejects unknown target hashes, unsafe symlinks, authority/live identity mismatch, malformed state, managed drift and unrecoverable interrupted transactions. A passing fake-root gate does not emulate the Android kernel, Magisk daemon, SELinux, Binder, hardware-backed security or a real mount namespace; physical-device validation remains required for runtime-sensitive release changes.
