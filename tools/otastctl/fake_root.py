from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from .build import build_module, validate_module_zip
from .util import OtastError, atomic_write, ensure_within, sha256_file, stable_json


def _write(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)


def _extract_exact_zip(module_zip: Path, module_dir: Path) -> Path:
    validate_module_zip(module_zip)
    if module_dir.exists():
        raise OtastError(f"module extraction destination already exists: {module_dir}")
    module_dir.mkdir(parents=True)
    with zipfile.ZipFile(module_zip) as archive:
        for info in archive.infolist():
            pure = PurePosixPath(info.filename)
            if pure.is_absolute() or ".." in pure.parts or "\\" in info.filename:
                raise OtastError(f"unsafe module ZIP path: {info.filename}")
            target = ensure_within(module_dir.joinpath(*pure.parts), module_dir)
            mode = (info.external_attr >> 16) & 0o777
            kind = stat.S_IFMT((info.external_attr >> 16) & 0o177777)
            if kind not in (0, stat.S_IFREG):
                raise OtastError(f"non-regular module ZIP member: {info.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
            target.chmod(mode or 0o644)
    return module_dir


def _synthetic_module_prop(module_id: str, name: str, version: str) -> str:
    numeric = "".join(character for character in version if character.isdigit()) or "1"
    return (
        f"id={module_id}\n"
        f"name={name}\n"
        f"version={version}\n"
        f"versionCode={numeric}\n"
        "author=fixture\n"
        "description=synthetic compatibility fixture\n"
    )


def _synthetic_target(adb_root: Path, *, staged_pif: bool = True) -> dict[str, bytes]:
    originals: dict[str, bytes] = {}
    fixture_root = Path(__file__).resolve().parents[2] / "tests/fixtures/upstream"

    def target(path: Path, text: str, mode: int = 0o755) -> None:
        _write(path, text, mode)
        originals[path.relative_to(adb_root).as_posix()] = path.read_bytes()

    def target_bytes(path: Path, source: Path, mode: int = 0o755) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(source.read_bytes())
        path.chmod(mode)
        originals[path.relative_to(adb_root).as_posix()] = path.read_bytes()

    pif_trees = [adb_root / "modules/playintegrityfix"]
    if staged_pif:
        pif_trees.append(adb_root / "modules_update/playintegrityfix")
    for index, pif in enumerate(pif_trees):
        # These lifecycle entrypoints are observed-only and must remain unchanged.
        for name in ("action.sh", "post-fs-data.sh", "service.sh"):
            target(pif / name, f"#!/system/bin/sh\n# preserved upstream lifecycle {index} {name}\nexit 0\n")
        target_bytes(pif / "autopif.sh", fixture_root / "pif-autopif-ea93222c.sh")
        target_bytes(pif / "autopif_ota.sh", fixture_root / "pif-autopif-ota-ea93222c.sh")
        target_bytes(pif / "security_patch.sh", fixture_root / "pif-security-patch-ea93222c.sh")
        target(pif / "module.prop", _synthetic_module_prop("playintegrityfix", "PIF synthetic", "v4.7.1"), 0o644)
        target(
            pif / "pif.prop",
            "# preserve this comment\nFINGERPRINT=old\nCUSTOM_OPTION=keep-me\nspoofBuild=false\n",
            0o644,
        )

    tricky = adb_root / "modules/tricky_store"
    target(tricky / "module.prop", _synthetic_module_prop("tricky_store", "TrickyStore", "1.4.1"), 0o644)
    target(tricky / "service.sh", "#!/system/bin/sh\nexit 0\n")
    target(adb_root / "tricky_store/security_patch.txt", "system=prop\nboot=2000-01-01\nvendor=2000-01-01\n", 0o644)

    ta = adb_root / "modules/TA_utl"
    target(ta / "module.prop", _synthetic_module_prop("TA_utl", "TA UTL", "v4.4"), 0o644)
    target_bytes(ta / "prop.sh", fixture_root / "ta-utl-prop-v4.4.sh")

    yuri = adb_root / "modules/Yurikey"
    for name in (
        "action.sh",
        "service.sh",
        "Yuri/target_txt.sh",
        "Yuri/boot_hash.sh",
        "Yuri/security_patch.sh",
        "Yuri/pif.sh",
        "Yuri/clear_all_detection_traces.sh",
        "webroot/common/boot_hash.sh",
        "webroot/common/pif2.sh",
    ):
        target(yuri / name, f"#!/system/bin/sh\n# synthetic Yurikey {name}\nexit 0\n")
    target(yuri / "module.prop", _synthetic_module_prop("Yurikey", "Yurikey", "3.0.6"), 0o644)

    vbmeta = adb_root / "modules/vbmeta-fixer"
    target(vbmeta / "service.sh", "#!/system/bin/sh\n# synthetic vbmeta writer\nexit 0\n")
    target(vbmeta / "module.prop", _synthetic_module_prop("vbmeta-fixer", "VBMeta Fixer", "1.2.0"), 0o644)

    # This contract is intentionally the vbmeta digest, not boot.img.sha256.
    target(adb_root / "boot_hash", "2" * 64 + "\n", 0o644)

    # Synthetic sentinels prove that strict exclusions are not read or changed.
    target(adb_root / "modules/AshLooper/sentinel.bin", "ASHLOOPER-UNCHANGED\n", 0o600)
    target(adb_root / "modules/BetterKnownInstalled/sentinel.bin", "BKI-UNCHANGED\n", 0o600)
    return originals


def _authority_text(system_patch: str = "2026-03-05", vendor_patch: str = "2026-03-05") -> str:
    return "\n".join(
        (
            "boot.img.sha256=" + "1" * 64,
            "ro.boot.vbmeta.digest=" + "2" * 64,
            "ro.boot.vbmeta.size=20480",
            "ro.boot.vbmeta.avb_version=1.3",
            "ro.boot.avb_version=1.3",
            "ro.build.fingerprint=google/tegu/tegu:16/TEST/1:user/release-keys",
            "ro.build.id=TEST",
            "ro.build.version.sdk=36",
            f"ro.build.version.security_patch={system_patch}",
            f"ro.vendor.build.security_patch={vendor_patch}",
            "ro.product.device=tegu",
            "ro.product.manufacturer=Google",
            "ro.product.model=Pixel 9a",
            "otast.pif.identity=ota",
            "otast.trickystore.securityPatch=ota",
            "otast.pif.spoofBuild=true",
            "otast.pif.spoofProps=true",
            "otast.pif.spoofProvider=true",
            "otast.pif.spoofSignature=true",
            "otast.pif.spoofVendingBuild=true",
            "otast.pif.spoofVendingSdk=true",
            "otast.pif.DEBUG=false",
            "",
        )
    )


def _live_text(
    system_patch: str = "2026-03-05",
    vendor_patch: str = "2026-03-05",
    *,
    build_id: str = "TEST",
    managed_vbmeta_current: bool = True,
) -> str:
    return "\n".join(
        (
            "ro.build.fingerprint=google/tegu/tegu:16/TEST/1:user/release-keys",
            f"ro.build.id={build_id}",
            "ro.build.version.sdk=36",
            f"ro.build.version.security_patch={system_patch}",
            f"ro.vendor.build.security_patch={vendor_patch}",
            "ro.product.device=tegu",
            "ro.boot.vbmeta.digest=" + ("2" * 64 if managed_vbmeta_current else "3" * 64),
            "ro.boot.vbmeta.size=" + ("20480" if managed_vbmeta_current else "4096"),
            "ro.boot.vbmeta.avb_version=" + ("1.3" if managed_vbmeta_current else "1.0"),
            "ro.boot.avb_version=" + ("1.3" if managed_vbmeta_current else "1.0"),
            "",
        )
    )


def _shell_command() -> list[str]:
    busybox = shutil.which("busybox")
    return [busybox, "sh"] if busybox else ["sh"]


def _run(
    entry: Path,
    adb_root: Path,
    action: str,
    *,
    expect: int = 0,
    test_mode: bool = True,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "ADB_ROOT": str(adb_root),
            "OTAST_AUTHORITY": str(adb_root / "ota.prop"),
            "OTAST_LIVE_PROP_FILE": str(adb_root / "live.prop"),
            "OTAST_TEST_MODE": "1" if test_mode else "0",
        }
    )
    result = subprocess.run(
        [*_shell_command(), str(entry), action],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        timeout=timeout,
        check=False,
    )
    if result.returncode != expect:
        raise OtastError(
            f"fake-root action {action!r} returned {result.returncode}, expected {expect}:\n{result.stdout}"
        )
    return result


def _new_root(parent: Path, module_zip: Path, *, staged_pif: bool = True) -> tuple[Path, Path, dict[str, bytes]]:
    adb_root = parent / "data/adb"
    adb_root.mkdir(parents=True)
    _write(adb_root / ".otast-fake-root", "1\n", 0o600)
    _write(adb_root / "ota.prop", _authority_text(), 0o600)
    _write(adb_root / "live.prop", _live_text(managed_vbmeta_current=False), 0o600)
    originals = _synthetic_target(adb_root, staged_pif=staged_pif)
    module = _extract_exact_zip(module_zip, adb_root / "modules/otast")
    return adb_root, module / "runtime/entry.sh", originals


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_originals(adb_root: Path, originals: dict[str, bytes]) -> None:
    for rel, expected in originals.items():
        path = adb_root / rel
        if not path.is_file() or path.is_symlink() or path.read_bytes() != expected:
            raise OtastError(f"Restore did not recover original fixture bytes: {rel}")


def _simulate_interrupted_transaction(adb_root: Path, managed_path: Path) -> None:
    state = adb_root / "otast/records/pif-autopif-active.state"
    if not state.is_file():
        raise OtastError("interruption scenario is missing managed state")
    tx = adb_root / "otast/transactions/simulated-interruption"
    tx.mkdir(parents=True)
    _write(tx / "status", "IN_PROGRESS\n", 0o600)
    _write(tx / "journal.tsv", f"pif-autopif-active\t{managed_path}\n", 0o600)
    (tx / "before.pif-autopif-active").write_bytes(managed_path.read_bytes())
    (tx / "before.pif-autopif-active").chmod(0o600)
    _write(tx / "before-meta.pif-autopif-active", "1\t0755\n", 0o600)
    (tx / "state.pif-autopif-active").write_bytes(state.read_bytes())
    (tx / "state.pif-autopif-active").chmod(0o600)
    managed_path.write_text("interrupted-write\n", encoding="utf-8")
    managed_path.chmod(0o755)


def _simulate_managed_boot(adb_root: Path) -> None:
    authority = {}
    for line in (adb_root / "ota.prop").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            authority[key] = value
    live_path = adb_root / "live.prop"
    live = {}
    order = []
    for line in live_path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key not in live:
            order.append(key)
        live[key] = value
    for key in (
        "ro.boot.vbmeta.digest",
        "ro.boot.vbmeta.avb_version",
        "ro.boot.avb_version",
    ):
        if key not in authority:
            raise OtastError(f"authority missing managed runtime key: {key}")
        if key not in live:
            order.append(key)
        live[key] = authority[key]
    _write(live_path, "\n".join(f"{key}={live[key]}" for key in order) + "\n", 0o600)


def qualify_fake_root(repo_root: Path, output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    module_zip = build_module(repo_root, output_dir)
    logs: list[str] = []

    with tempfile.TemporaryDirectory(prefix="otast-fake-root-") as raw:
        base = Path(raw)
        adb_root, entry, originals = _new_root(base / "primary", module_zip)
        strict_before = {
            "AshLooper": _file_digest(adb_root / "modules/AshLooper/sentinel.bin"),
            "BetterKnownInstalled": _file_digest(adb_root / "modules/BetterKnownInstalled/sentinel.bin"),
        }

        preflight = _run(entry, adb_root, "preflight")
        logs.append("## preflight\n" + preflight.stdout)
        stale_lock = adb_root / "otast/lock"
        stale_lock.mkdir(parents=True)
        _write(stale_lock / "pid", "999999999\n", 0o600)
        first_apply = _run(entry, adb_root, "apply")
        if "reclaimed stale OTAST lock" not in first_apply.stdout:
            raise OtastError("Apply did not identify and reclaim the synthetic stale lock")
        logs.append("## first apply\n" + first_apply.stdout)
        if (adb_root / "boot_hash").read_text(encoding="utf-8") != "2" * 64 + "\n":
            raise OtastError("boot_hash does not contain the authoritative vbmeta digest")
        for role in ("modules", "modules_update"):
            pif_dir = adb_root / role / "playintegrityfix"
            if not pif_dir.is_dir():
                continue
            for observed in ("action.sh", "post-fs-data.sh", "service.sh"):
                rel = (pif_dir / observed).relative_to(adb_root).as_posix()
                if (pif_dir / observed).read_bytes() != originals[rel]:
                    raise OtastError(f"OTAST changed observed-only PIF lifecycle entrypoint: {rel}")
            pif_text = (pif_dir / "pif.prop").read_text(encoding="utf-8")
            for expected in (
                "# preserve this comment",
                "CUSTOM_OPTION=keep-me",
                "FINGERPRINT=google/tegu/tegu:16/TEST/1:user/release-keys",
                "SECURITY_PATCH=2026-03-05",
                "spoofBuild=true",
            ):
                if expected not in pif_text:
                    raise OtastError(f"PIF configuration merge lost required content: {expected}")
        ta_text = (adb_root / "modules/TA_utl/prop.sh").read_text(encoding="utf-8")
        if "# --- otast vbmeta ownership BEGIN ---" not in ta_text:
            raise OtastError("TA UTL vbmeta writer was not narrowly neutralised")
        if 'check_reset_prop "ro.boot.verifiedbootstate" "green"' not in ta_text:
            raise OtastError("TA UTL non-vbmeta behaviour was not preserved")
        pre_reboot_verify = _run(entry, adb_root, "verify", expect=1)
        if "reboot after Apply before Verify" not in pre_reboot_verify.stdout:
            raise OtastError("pre-reboot Verify failed for the wrong reason")
        _simulate_managed_boot(adb_root)
        verify_one = _run(entry, adb_root, "verify")
        logs.append("## pre-reboot verify rejection\n" + pre_reboot_verify.stdout)
        logs.append("## post-reboot verify\n" + verify_one.stdout)
        transactions_before = len(list((adb_root / "otast/transactions").glob("*")))
        second_apply = _run(entry, adb_root, "apply")
        transactions_after = len(list((adb_root / "otast/transactions").glob("*")))
        if transactions_before != transactions_after:
            raise OtastError("idempotent Apply created an unnecessary transaction")
        logs.append("## idempotent apply\n" + second_apply.stdout)

        _write(adb_root / "ota.prop", _authority_text("2026-04-05", "2026-04-05"), 0o600)
        _write(adb_root / "live.prop", _live_text("2026-04-05", "2026-04-05"), 0o600)
        authority_update = _run(entry, adb_root, "apply")
        _simulate_managed_boot(adb_root)
        verify_two = _run(entry, adb_root, "verify")
        logs.append("## authority update\n" + authority_update.stdout)
        patch_value = (adb_root / "tricky_store/security_patch.txt").read_text(encoding="utf-8")
        if "boot=2026-04-05" not in patch_value or "vendor=2026-04-05" not in patch_value:
            raise OtastError("authority update did not reach the TrickyStore contract")
        staged_pif = adb_root / "modules_update/playintegrityfix/pif.prop"
        if "SECURITY_PATCH=2026-04-05" not in staged_pif.read_text(encoding="utf-8"):
            raise OtastError("authority update did not reach the staged PIF contract")

        managed_autopif = adb_root / "modules/playintegrityfix/autopif.sh"
        managed_bytes = managed_autopif.read_bytes()
        _simulate_interrupted_transaction(adb_root, managed_autopif)
        recovery = _run(entry, adb_root, "boot-recover")
        if managed_autopif.read_bytes() != managed_bytes:
            raise OtastError("boot recovery did not restore interrupted bytes")
        _run(entry, adb_root, "verify")
        logs.append("## interrupted recovery\n" + recovery.stdout)

        managed_autopif.write_text("drift\n", encoding="utf-8")
        managed_autopif.chmod(0o755)
        drift_verify = _run(entry, adb_root, "verify", expect=1)
        drift_apply = _run(entry, adb_root, "apply", expect=1)
        drift_restore = _run(entry, adb_root, "restore", expect=1)
        logs.append("## drift rejection\n" + drift_verify.stdout + drift_apply.stdout + drift_restore.stdout)
        managed_autopif.write_bytes(managed_bytes)
        managed_autopif.chmod(0o755)

        restore = _run(entry, adb_root, "restore")
        final_report = _run(entry, adb_root, "report")
        if "NO_MANAGED_STATE" not in final_report.stdout:
            raise OtastError("Restore did not remove managed state records")
        _assert_originals(adb_root, originals)
        strict_after = {
            "AshLooper": _file_digest(adb_root / "modules/AshLooper/sentinel.bin"),
            "BetterKnownInstalled": _file_digest(adb_root / "modules/BetterKnownInstalled/sentinel.bin"),
        }
        if strict_before != strict_after:
            raise OtastError("a strict-exclusion sentinel changed")
        logs.append("## restore\n" + restore.stdout + final_report.stdout)

        # A second root proves unknown exact hashes are rejected without the fake-only override.
        reject_root, reject_entry, _ = _new_root(base / "unknown-hash", module_zip, staged_pif=False)
        unknown = _run(reject_entry, reject_root, "preflight", expect=1, test_mode=False)
        if "unsupported exact-replacement hash" not in unknown.stdout:
            raise OtastError("unknown-hash scenario failed for the wrong reason")
        if (reject_root / "otast/records").exists():
            raise OtastError("unknown-hash rejection created managed state")
        logs.append("## unknown hash rejection\n" + unknown.stdout)

        # Live identity mismatch must stop before target planning.
        mismatch_root, mismatch_entry, _ = _new_root(base / "identity-mismatch", module_zip, staged_pif=False)
        _write(mismatch_root / "live.prop", _live_text(build_id="DIFFERENT"), 0o600)
        mismatch = _run(mismatch_entry, mismatch_root, "preflight", expect=1)
        if "live platform identity differs from authority" not in mismatch.stdout:
            raise OtastError("identity mismatch scenario failed for the wrong reason")
        logs.append("## identity mismatch rejection\n" + mismatch.stdout)

        # A symlinked external-contract parent must never be followed.
        symlink_root, symlink_entry, _ = _new_root(base / "symlink-attack", module_zip, staged_pif=False)
        outside = base / "outside"
        outside.mkdir()
        marker = outside / "security_patch.txt"
        marker.write_text("outside-unchanged\n", encoding="utf-8")
        shutil.rmtree(symlink_root / "tricky_store")
        os.symlink(outside, symlink_root / "tricky_store")
        symlink = _run(symlink_entry, symlink_root, "preflight", expect=1)
        if marker.read_text(encoding="utf-8") != "outside-unchanged\n":
            raise OtastError("symlink attack modified an outside path")
        logs.append("## symlink rejection\n" + symlink.stdout)

        # A live lock owner must not be displaced.
        locked_root, locked_entry, _ = _new_root(base / "active-lock", module_zip, staged_pif=False)
        active_lock = locked_root / "otast/lock"
        active_lock.mkdir(parents=True)
        _write(active_lock / "pid", f"{os.getpid()}\n", 0o600)
        locked = _run(locked_entry, locked_root, "apply", expect=1)
        if "another OTAST operation holds the lock" not in locked.stdout or not active_lock.is_dir():
            raise OtastError("active-lock scenario did not fail closed")
        logs.append("## active lock rejection\n" + locked.stdout)

        # A missing reviewed writer path must stop even in fake fixture mode.
        missing_root, missing_entry, _ = _new_root(base / "missing-required", module_zip, staged_pif=False)
        (missing_root / "modules/playintegrityfix/autopif.sh").unlink()
        missing = _run(missing_entry, missing_root, "preflight", expect=1)
        if "required reviewed target path is missing" not in missing.stdout:
            raise OtastError("missing-required scenario failed for the wrong reason")
        logs.append("## missing required writer rejection\n" + missing.stdout)

        # Legacy governors must block all normal operations until removed.
        legacy_root, legacy_entry, _ = _new_root(base / "legacy-governor", module_zip, staged_pif=False)
        legacy_dir = legacy_root / "modules/otasst"
        legacy_dir.mkdir(parents=True)
        _write(legacy_dir / "module.prop", _synthetic_module_prop("otasst", "legacy", "1"), 0o644)
        legacy = _run(legacy_entry, legacy_root, "preflight", expect=1)
        if "legacy OTA authority governor trace" not in legacy.stdout:
            raise OtastError("legacy-governor scenario failed for the wrong reason")
        logs.append("## legacy governor rejection\n" + legacy.stdout)

        # PIF's Auto Security Patch flag is user configuration. The flag itself is
        # preserved while OTAST neutralizes the reviewed writer it would invoke.
        auto_root, auto_entry, auto_originals = _new_root(base / "pif-auto-generator", module_zip, staged_pif=False)
        auto_flag = auto_root / "tricky_store/pif_auto_security_patch"
        _write(auto_flag, "", 0o600)
        auto_preflight = _run(auto_entry, auto_root, "preflight")
        if "will neutralize its reviewed writer on Apply" not in auto_preflight.stdout:
            raise OtastError("PIF auto-patch flag was accepted without explicit ownership evidence")
        auto_apply = _run(auto_entry, auto_root, "apply")
        auto_writer = auto_root / "modules/playintegrityfix/security_patch.sh"
        auto_writer_text = auto_writer.read_text(encoding="utf-8")
        if "# otast managed" not in auto_writer_text or "exit 0" not in auto_writer_text.splitlines()[:5]:
            raise OtastError("PIF automatic security-patch writer was not neutralized on Apply")
        if not auto_flag.is_file() or auto_flag.is_symlink():
            raise OtastError("PIF auto-patch user flag was not preserved during Apply")
        auto_restore = _run(auto_entry, auto_root, "restore")
        if auto_writer.read_bytes() != auto_originals["modules/playintegrityfix/security_patch.sh"]:
            raise OtastError("Restore did not recover the original PIF security-patch writer")
        if not auto_flag.is_file() or auto_flag.is_symlink():
            raise OtastError("PIF auto-patch user flag was not preserved through Restore")
        logs.append(
            "## PIF automatic generator ownership\n"
            + auto_preflight.stdout
            + auto_apply.stdout
            + auto_restore.stdout
        )

        # The compatibility exception applies only to a safe regular marker.
        auto_link_root, auto_link_entry, _ = _new_root(base / "pif-auto-generator-symlink", module_zip, staged_pif=False)
        outside_auto_flag = base / "outside-auto-flag"
        outside_auto_flag.write_text("unchanged\n", encoding="utf-8")
        os.symlink(outside_auto_flag, auto_link_root / "tricky_store/pif_auto_security_patch")
        auto_link = _run(auto_link_entry, auto_link_root, "preflight", expect=1)
        if "PIF automatic security-patch flag is not a safe regular file" not in auto_link.stdout:
            raise OtastError("unsafe PIF auto-patch marker scenario failed for the wrong reason")
        if outside_auto_flag.read_text(encoding="utf-8") != "unchanged\n":
            raise OtastError("unsafe PIF auto-patch marker modified its symlink target")
        logs.append("## PIF automatic generator unsafe marker rejection\n" + auto_link.stdout)

        # Tampered state may never redirect Restore outside ADB_ROOT.
        state_root, state_entry, _ = _new_root(base / "state-tamper", module_zip, staged_pif=False)
        _run(state_entry, state_root, "apply")
        state_file = state_root / "otast/records/boot-hash.state"
        state_text = state_file.read_text(encoding="utf-8")
        outside_state_target = base / "state-tamper-outside"
        outside_state_target.write_text("outside-unchanged\n", encoding="utf-8")
        state_file.write_text(
            state_text.replace(f"path={state_root}/boot_hash", f"path={outside_state_target}"),
            encoding="utf-8",
        )
        tampered = _run(state_entry, state_root, "restore", expect=1)
        if outside_state_target.read_text(encoding="utf-8") != "outside-unchanged\n":
            raise OtastError("tampered state modified an outside path")
        logs.append("## state tamper rejection\n" + tampered.stdout)

        evidence = {
            "schema_version": 2,
            "result": "PASS",
            "module_zip": module_zip.name,
            "module_sha256": sha256_file(module_zip),
            "scenarios": {
                "exact_zip_install": True,
                "active_and_staged_targets": True,
                "preflight": preflight.returncode,
                "first_apply": first_apply.returncode,
                "stale_lock_recovered": True,
                "identical_external_contract_adopted": True,
                "verify": verify_one.returncode,
                "idempotent_apply_without_transaction": True,
                "authority_update": authority_update.returncode,
                "verify_updated": verify_two.returncode,
                "interrupted_transaction_recovery": recovery.returncode,
                "unknown_hash_rejected": True,
                "identity_mismatch_rejected": True,
                "symlink_escape_rejected": True,
                "active_lock_rejected": True,
                "missing_required_writer_rejected": True,
                "legacy_governor_rejected": True,
                "pif_auto_flag_absorbed": True,
                "pif_auto_flag_unsafe_symlink_rejected": True,
                "pif_lifecycle_entrypoints_preserved": True,
                "pif_unknown_options_preserved": True,
                "ta_non_vbmeta_behaviour_preserved": True,
                "boot_hash_uses_vbmeta_digest": True,
                "vbmeta_size_is_provenance_only": True,
                "tampered_state_rejected": True,
                "drift_verify_rejected": drift_verify.returncode == 1,
                "drift_apply_rejected": drift_apply.returncode == 1,
                "drift_restore_rejected": drift_restore.returncode == 1,
                "complete_restore": restore.returncode,
                "originals_recovered": True,
                "strict_exclusions_preserved": True,
            },
        }
        atomic_write(output_dir / "fake-magisk-root.json", stable_json(evidence).encode())
        atomic_write(output_dir / "fake-magisk-root.log", ("\n".join(logs)).encode())
        return evidence


def clone_fixture_root(
    repo_root: Path,
    fixture: Path,
    destination: Path,
    allowed_root: Path,
    module_zip: Path | None = None,
) -> dict[str, object]:
    """Reset a private sanitized fixture and install one exact candidate ZIP.

    Release qualification supplies the deterministic ZIP it already built.
    Rebuilding here would change ``release.properties`` commit binding and prove
    a different artifact.
    """

    from .fixture import reset_fixture

    reset_fixture(fixture, destination, allowed_root)
    try:
        adb_root = destination / "data/adb"
        if adb_root.is_symlink() or not adb_root.is_dir():
            raise OtastError("fixture does not contain a safe data/adb directory")
        modules = adb_root / "modules"
        if modules.is_symlink():
            raise OtastError("fake modules directory is a symlink")
        modules.mkdir(parents=True, exist_ok=True)
        module_dir = modules / "otast"
        if module_dir.is_symlink():
            raise OtastError("candidate module destination is a symlink")
        if module_dir.exists():
            shutil.rmtree(module_dir)
        with tempfile.TemporaryDirectory(prefix="otast-candidate-", dir=allowed_root) as raw:
            if module_zip is None:
                candidate_zip = build_module(repo_root, Path(raw))
            else:
                if module_zip.is_symlink() or not module_zip.is_file():
                    raise OtastError(f"candidate module ZIP is missing or unsafe: {module_zip}")
                candidate_zip = module_zip.resolve()
                validate_module_zip(candidate_zip)
            _extract_exact_zip(candidate_zip, module_dir)
            marker = adb_root / ".otast-fake-root"
            _write(marker, "1\n", 0o600)
            evidence = {
                "schema_version": 1,
                "result": "PASS",
                "fixture": str(fixture),
                "destination": str(destination),
                "module_zip": candidate_zip.name,
                "module_sha256": sha256_file(candidate_zip),
                "candidate_source": "supplied" if module_zip is not None else "built",
            }
            atomic_write(destination / "candidate-module.json", stable_json(evidence).encode(), 0o600)
            return evidence
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
