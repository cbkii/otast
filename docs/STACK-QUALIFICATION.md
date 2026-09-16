<!-- GENERATED from compatibility/stack-observers.json; do not hand-edit. -->
# Integrity stack qualification

OTAST treats the surrounding root/integrity stack as read-only qualification evidence, not as additional OTA-property authority.

## Runtime preconditions

- Known module-based Zygisk providers: `rezygisk`, `zygisksu`.
- Active and staged copies of the same module ID count as one provider transition; different effective provider IDs are a qualification conflict.
- Zero visible module-based providers are reported `EXTERNAL_OR_BUILTIN_UNRESOLVED`, because Magisk built-in Zygisk cannot be disproved from module-tree absence.
- Vector and Treat Wheel are observed only; neither becomes an OTAST writer.
- zygisk-detach is read from `/data/adb/zygisk-detach/detach.bin` without executing its CLI.
- Protected BKI/Ash non-target trees remain outside runtime discovery and are bound only by host/physical qualification evidence.

Qualification-critical detached packages:

- `com.google.android.gms`
- `com.android.vending`
- `com.google.android.apps.walletnfcrel`
- the configured Play Integrity test package, when `OTAST_PI_TEST_PACKAGE` is set.

## Physical Pixel qualification sequence

1. Bind the exact OTAST source commit, deterministic ZIP SHA-256 and runtime digest.
2. Bind the exact device/build/authority digest and runtime page size.
3. Record the selected PIF provider, version/source and effective profile digest.
4. Record TrickyStore version/source and the OTAST-owned security-patch policy digest.
5. Record the actual Zygisk provider/version/source; unresolved built-in/external state is not release proof.
6. Record Vector, BKI and concealment-module state/version evidence without mutating them.
7. Record zygisk-detach version/config digest and confirm no qualification-critical package is detached.
8. Run OTAST Preflight/Apply/Verify across the required reboot boundaries and confirm provider/ownership health.
9. Perform one fresh Play Integrity evaluation and separately check Play Store Play Protect certification.
10. Record Wallet and banking/app root-detection results separately when tested; they are not substitutes for Play Integrity or certification.
11. Exercise Restore and repeat Apply/Verify where the release lifecycle requires repeatability proof.

Fork v18 remains a supported candidate until this exact-stack physical evidence exists for Pixel 9a (`tegu`); repository support alone does not make it preferred.
