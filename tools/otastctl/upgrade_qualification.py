from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from .build import build_module
from .fake_root import (
    _extract_exact_zip,
    _new_root,
    _run,
    _simulate_managed_boot,
)
from .util import OtastError

PUBLISHED_PREDECESSOR_REF = "v1.0.2"
PIF_PROFILE_RELATIVE_PATHS = (
    "pif.prop",
    "modules/playintegrityfix/pif.prop",
    "modules_update/playintegrityfix/pif.prop",
)
LEGACY_PIF_PROFILE_STATE_IDS = (
    "pif-global-prop",
    "pif-prop-active",
    "pif-prop-staged",
)
LEGACY_PIF_WRITER_STATE_IDS = (
    "pif-autopif-active",
    "pif-autopif-staged",
    "pif-autopif-ota-active",
    "pif-autopif-ota-staged",
    "pif-runtime-system-prop-active",
    "pif-runtime-system-prop-staged",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _state_snapshot(adb_root: Path) -> dict[str, str]:
    records = adb_root / "otast/records"
    if not records.is_dir() or records.is_symlink():
        raise OtastError("upgrade qualification has no safe managed-state directory")
    snapshot: dict[str, str] = {}
    for state in sorted(records.glob("*.state")):
        if state.is_symlink() or not state.is_file():
            raise OtastError(f"unsafe managed-state record: {state}")
        snapshot[state.relative_to(adb_root).as_posix()] = _sha256(state)
        backup = ""
        for line in state.read_text(encoding="utf-8").splitlines():
            if line.startswith("backup="):
                backup = line.split("=", 1)[1]
                break
        if backup:
            backup_path = Path(backup)
            try:
                relative = backup_path.resolve(strict=True).relative_to(adb_root.resolve(strict=True))
            except (OSError, ValueError) as exc:
                raise OtastError(f"managed-state backup escapes fake ADB root: {backup}") from exc
            if backup_path.is_symlink() or not backup_path.is_file():
                raise OtastError(f"managed-state backup is missing or unsafe: {backup}")
            snapshot[f"backup:{relative.as_posix()}"] = _sha256(backup_path)
    if not snapshot:
        raise OtastError("upgrade qualification captured no managed state")
    return snapshot


def _backup_snapshot(adb_root: Path) -> dict[str, str]:
    backups = adb_root / "otast/backups"
    if not backups.exists():
        return {}
    if backups.is_symlink() or not backups.is_dir():
        raise OtastError("upgrade qualification has an unsafe backup directory")
    snapshot: dict[str, str] = {}
    for backup in sorted(backups.glob("*.original")):
        if backup.is_symlink() or not backup.is_file():
            raise OtastError(f"unsafe original backup: {backup}")
        relative = backup.relative_to(adb_root).as_posix()
        snapshot[f"backup:{relative}"] = _sha256(backup)
    return snapshot


def _pif_profile_snapshot(adb_root: Path) -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    for relative in PIF_PROFILE_RELATIVE_PATHS:
        path = adb_root / relative
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file():
            raise OtastError(f"unsafe PIF profile during upgrade qualification: {path}")
        snapshot[relative] = path.read_bytes()
    if "modules/playintegrityfix/pif.prop" not in snapshot:
        raise OtastError("upgrade qualification is missing the active PIF fallback profile")
    return snapshot


def _assert_originals_except_pif_profiles(adb_root: Path, originals: dict[str, bytes]) -> None:
    for relative, expected in originals.items():
        if relative in PIF_PROFILE_RELATIVE_PATHS:
            continue
        path = adb_root / relative
        if not path.is_file() or path.is_symlink() or path.read_bytes() != expected:
            raise OtastError(f"Restore did not recover original fixture bytes: {relative}")


def _assert_predecessor_backups_preserved(predecessor: dict[str, str], current: dict[str, str]) -> None:
    for key, digest in predecessor.items():
        observed = current.get(key)
        if observed is None:
            raise OtastError(f"candidate removed predecessor original backup: {key}")
        if observed != digest:
            raise OtastError(f"candidate changed predecessor original backup bytes: {key}")


def _transaction_count(adb_root: Path) -> int:
    root = adb_root / "otast/transactions"
    return len([path for path in root.glob("*") if path.is_dir() and not path.is_symlink()])


def _install_candidate(module_zip: Path, adb_root: Path) -> Path:
    destination = adb_root / "modules/otast"
    if destination.is_symlink():
        raise OtastError("candidate module destination is a symlink")
    if destination.exists():
        shutil.rmtree(destination)
    module_dir = _extract_exact_zip(module_zip, destination)
    return module_dir / "runtime/entry.sh"


def _stamp_synthetic_predecessor(module_prop: Path) -> None:
    lines: list[str] = []
    saw_version = False
    saw_code = False
    for line in module_prop.read_text(encoding="utf-8").splitlines():
        if line.startswith("version="):
            lines.append("version=v0.0.0-upgrade-fixture")
            saw_version = True
        elif line.startswith("versionCode="):
            raw = line.split("=", 1)[1]
            if not raw.isdigit() or int(raw) <= 1:
                raise OtastError("candidate versionCode cannot produce a predecessor fixture")
            lines.append(f"versionCode={int(raw) - 1}")
            saw_code = True
        else:
            lines.append(line)
    if not saw_version or not saw_code:
        raise OtastError("candidate module.prop lacks version identity")
    module_prop.write_text("\n".join(lines) + "\n", encoding="utf-8")
    module_prop.chmod(0o644)


def git_ref_available(repo_root: Path, ref: str = PUBLISHED_PREDECESSOR_REF) -> bool:
    try:
        result = subprocess.run(
            ["git", "cat-file", "-e", f"{ref}^{{commit}}"],
            cwd=repo_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def _git_output(repo_root: Path, *args: str, timeout: int = 30) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise OtastError("git is required for published-predecessor qualification") from exc
    except subprocess.TimeoutExpired as exc:
        raise OtastError("git operation timed out during published-predecessor qualification") from exc
    except OSError as exc:
        raise OtastError(f"cannot execute git for published-predecessor qualification: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise OtastError(f"git {' '.join(args)} failed with status {result.returncode}: {detail}")
    return result.stdout


def _materialize_git_module(repo_root: Path, ref: str, destination_root: Path) -> str:
    commit = _git_output(repo_root, "rev-parse", f"{ref}^{{commit}}").decode("ascii").strip()
    if len(commit) != 40 or any(ch not in "0123456789abcdef" for ch in commit):
        raise OtastError(f"published predecessor did not resolve to a full commit SHA: {ref}")

    archive_bytes = _git_output(repo_root, "archive", "--format=tar", ref, "module", timeout=45)
    module_root = destination_root / "module"
    module_root.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as archive:
            for member in archive.getmembers():
                posix = PurePosixPath(member.name)
                if posix.is_absolute() or ".." in posix.parts or not posix.parts or posix.parts[0] != "module":
                    raise OtastError(f"unsafe predecessor archive path: {member.name}")
                relative = Path(*posix.parts[1:])
                if not relative.parts:
                    continue
                output = module_root / relative
                if member.isdir():
                    output.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    raise OtastError(f"unsupported predecessor archive member: {member.name}")
                source = archive.extractfile(member)
                if source is None:
                    raise OtastError(f"cannot read predecessor archive member: {member.name}")
                data = source.read()
                if len(data) > 8 * 1024 * 1024:
                    raise OtastError(f"oversized predecessor archive member: {member.name}")
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(data)
                output.chmod(member.mode & 0o777)
    except (tarfile.TarError, OSError) as exc:
        raise OtastError(f"cannot materialize published predecessor {ref}: {exc}") from exc

    source_compatibility = repo_root / "compatibility"
    if source_compatibility.is_symlink() or not source_compatibility.is_dir():
        raise OtastError("current compatibility registry directory is missing or unsafe")
    shutil.copytree(source_compatibility, destination_root / "compatibility")
    return commit


def _build_published_predecessor(
    repo_root: Path,
    output_dir: Path,
    ref: str = PUBLISHED_PREDECESSOR_REF,
) -> tuple[Path, str]:
    with tempfile.TemporaryDirectory(prefix="otast-predecessor-source-") as raw:
        source_root = Path(raw)
        commit = _materialize_git_module(repo_root, ref, source_root)
        predecessor = build_module(source_root, output_dir, commit_sha=commit)
    return predecessor, commit


def _assert_profile_mirrors_equal(adb_root: Path, canonical: bytes) -> None:
    for relative in (
        "modules/playintegrityfix/pif.prop",
        "modules_update/playintegrityfix/pif.prop",
    ):
        path = adb_root / relative
        if path.exists() and path.read_bytes() != canonical:
            raise OtastError(f"PIF fallback was not reconciled to canonical source: {relative}")


def qualify_published_predecessor(
    repo_root: Path,
    output_dir: Path,
    ref: str = PUBLISHED_PREDECESSOR_REF,
) -> dict[str, object]:
    """Qualify the published v1 ownership model into canonical-mirror v2."""

    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_zip = build_module(repo_root, output_dir / "candidate")
    predecessor_zip, predecessor_commit = _build_published_predecessor(
        repo_root, output_dir / "predecessor", ref
    )

    with tempfile.TemporaryDirectory(prefix="otast-published-upgrade-") as raw:
        base = Path(raw)
        adb_root, predecessor_entry, originals = _new_root(base / "managed", predecessor_zip)
        _run(predecessor_entry, adb_root, "preflight")
        _run(predecessor_entry, adb_root, "apply")
        _simulate_managed_boot(adb_root)
        _run(predecessor_entry, adb_root, "verify")

        records = adb_root / "otast/records"
        legacy_profile_state_ids = tuple(
            state_id for state_id in LEGACY_PIF_PROFILE_STATE_IDS
            if (records / f"{state_id}.state").is_file()
        )
        legacy_writer_state_ids = tuple(
            state_id for state_id in LEGACY_PIF_WRITER_STATE_IDS
            if (records / f"{state_id}.state").is_file()
        )
        if not legacy_profile_state_ids:
            raise OtastError("published predecessor created no legacy PIF profile ownership state")
        pre_candidate_profiles = _pif_profile_snapshot(adb_root)
        canonical_before = pre_candidate_profiles.get("pif.prop")
        if canonical_before is None:
            raise OtastError("published predecessor fixture has no global canonical PIF profile")
        predecessor_backups = _backup_snapshot(adb_root)
        if not predecessor_backups:
            raise OtastError("published predecessor created no original backup evidence")

        candidate_entry = _install_candidate(candidate_zip, adb_root)
        _run(candidate_entry, adb_root, "preflight")
        _run(candidate_entry, adb_root, "apply")
        _simulate_managed_boot(adb_root)
        _run(candidate_entry, adb_root, "verify")

        if (adb_root / "pif.prop").read_bytes() != canonical_before:
            raise OtastError("candidate rewrote canonical PIF profile during ownership migration")
        _assert_profile_mirrors_equal(adb_root, canonical_before)

        retired_profile_root = adb_root / "otast/retired/pif-profile-ownership-v1"
        if retired_profile_root.is_symlink() or not retired_profile_root.is_dir():
            raise OtastError("candidate did not create safe retired PIF profile ownership evidence")
        for state_id in legacy_profile_state_ids:
            if (records / f"{state_id}.state").exists():
                raise OtastError(f"candidate left legacy PIF profile ownership active: {state_id}")
            retired = retired_profile_root / f"{state_id}.state"
            if retired.is_symlink() or not retired.is_file():
                raise OtastError(f"candidate did not retain retired PIF profile evidence: {state_id}")

        if legacy_writer_state_ids:
            retired_writer_root = adb_root / "otast/retired/pif-writer-ownership-v2"
            if retired_writer_root.is_symlink() or not retired_writer_root.is_dir():
                raise OtastError("candidate did not create safe retired PIF writer ownership evidence")
            for state_id in legacy_writer_state_ids:
                if (records / f"{state_id}.state").exists():
                    raise OtastError(f"candidate left deprecated PIF writer ownership active: {state_id}")
                retired = retired_writer_root / f"{state_id}.state"
                if retired.is_symlink() or not retired.is_file():
                    raise OtastError(f"candidate did not retain retired PIF writer evidence: {state_id}")

        for role in ("modules", "modules_update"):
            for name in ("autopif.sh", "autopif_ota.sh"):
                relative = f"{role}/playintegrityfix/{name}"
                path = adb_root / relative
                if path.exists() and path.read_bytes() != originals[relative]:
                    raise OtastError(f"candidate did not restore upstream-owned PIF executable: {relative}")

        candidate_backups = _backup_snapshot(adb_root)
        _assert_predecessor_backups_preserved(predecessor_backups, candidate_backups)

        # A legitimate PIF refresh changes only the canonical source. Verify must
        # expose stale mirrors; explicit Apply reconciles them transactionally.
        global_profile = adb_root / "pif.prop"
        refreshed = canonical_before + b"# simulated PIF-owned refresh after v2 migration\n"
        global_profile.write_bytes(refreshed)
        global_profile.chmod(0o600)
        stale_verify = _run(candidate_entry, adb_root, "verify", expect=1)
        if "PIF fallback profile is not synchronized" not in stale_verify.stdout:
            raise OtastError("published-upgrade refresh did not expose stale PIF mirror state")
        before_reconcile = _transaction_count(adb_root)
        reconcile_apply = _run(candidate_entry, adb_root, "apply")
        after_reconcile = _transaction_count(adb_root)
        if after_reconcile != before_reconcile + 1:
            raise OtastError("PIF refresh reconciliation did not use exactly one transaction")
        _assert_profile_mirrors_equal(adb_root, refreshed)
        _simulate_managed_boot(adb_root)
        _run(candidate_entry, adb_root, "verify")

        before_noop = _transaction_count(adb_root)
        second_apply = _run(candidate_entry, adb_root, "apply")
        after_noop = _transaction_count(adb_root)
        if after_noop != before_noop:
            raise OtastError("published-predecessor upgrade did not settle to a no-op second Apply")

        _run(candidate_entry, adb_root, "restore")
        if global_profile.read_bytes() != refreshed:
            raise OtastError("Restore rolled back the current canonical PIF source")
        for relative in (
            "modules/playintegrityfix/pif.prop",
            "modules_update/playintegrityfix/pif.prop",
        ):
            if relative in originals:
                path = adb_root / relative
                if not path.is_file() or path.read_bytes() != originals[relative]:
                    raise OtastError(f"Restore did not recover true pre-OTAST fallback bytes: {relative}")
        _simulate_managed_boot(adb_root)
        _assert_originals_except_pif_profiles(adb_root, originals)
        if records.exists() and any(records.iterdir()):
            raise OtastError("Restore after published-predecessor upgrade left managed state records")

    return {
        "schema_version": 3,
        "result": "PASS",
        "predecessor_ref": ref,
        "predecessor_commit": predecessor_commit,
        "scenarios": {
            "published_predecessor_preflight_apply_verify": True,
            "candidate_preflight_apply_verify": True,
            "legacy_pif_profile_state_retired": bool(legacy_profile_state_ids),
            "legacy_pif_writer_state_retired": bool(legacy_writer_state_ids),
            "canonical_pif_source_preserved_during_migration": True,
            "fallbacks_reconciled_to_canonical": True,
            "predecessor_original_backups_preserved": True,
            "candidate_may_add_v2_mirror_backups": len(candidate_backups) >= len(predecessor_backups),
            "pif_refresh_requires_explicit_reconcile": stale_verify.returncode == 1,
            "pif_refresh_reconciled_transactionally": reconcile_apply.returncode == 0,
            "second_apply_noop": second_apply.returncode == 0 and after_noop == before_noop,
            "canonical_refresh_survives_restore": True,
            "candidate_restore_recovers_true_fallback_originals": True,
            "candidate_restore_recovers_non_pif_pre_otast_bytes": True,
            "managed_state_removed_after_restore": True,
        },
    }


def qualify_upgrade_path(repo_root: Path, output_dir: Path) -> dict[str, object]:
    """Exercise v2 managed-state upgrade/reinstall boundaries on a fake root."""

    output_dir.mkdir(parents=True, exist_ok=True)
    module_zip = build_module(repo_root, output_dir)

    with tempfile.TemporaryDirectory(prefix="otast-upgrade-") as raw:
        base = Path(raw)
        adb_root, predecessor_entry, _ = _new_root(base / "managed", module_zip)
        _stamp_synthetic_predecessor(adb_root / "modules/otast/module.prop")

        _run(predecessor_entry, adb_root, "preflight")
        _run(predecessor_entry, adb_root, "apply")
        _simulate_managed_boot(adb_root)
        _run(predecessor_entry, adb_root, "verify")

        staged_record = adb_root / "otast/records/pif-mirror-staged.state"
        if not staged_record.is_file():
            raise OtastError("v2 predecessor did not create managed mirror state for modules_update")
        before_upgrade = _state_snapshot(adb_root)

        candidate_entry = _install_candidate(module_zip, adb_root)
        _run(candidate_entry, adb_root, "preflight")
        transactions_before = _transaction_count(adb_root)
        upgrade_apply = _run(candidate_entry, adb_root, "apply")
        transactions_after = _transaction_count(adb_root)
        if transactions_after != transactions_before + 1:
            raise OtastError("candidate upgrade did not use exactly one self-rehydration transaction")
        if _state_snapshot(adb_root) != before_upgrade:
            raise OtastError("candidate upgrade rewrote existing managed-state/original contracts")

        before_noop = _transaction_count(adb_root)
        no_op_apply = _run(candidate_entry, adb_root, "apply")
        after_noop = _transaction_count(adb_root)
        if after_noop != before_noop:
            raise OtastError("second candidate Apply created a transaction despite no changes")

        reinstalled_entry = _install_candidate(module_zip, adb_root)
        _run(reinstalled_entry, adb_root, "preflight")
        before_reinstall = _transaction_count(adb_root)
        reinstall_apply = _run(reinstalled_entry, adb_root, "apply")
        after_reinstall = _transaction_count(adb_root)
        if after_reinstall != before_reinstall + 1:
            raise OtastError("candidate reinstall did not use exactly one self-rehydration transaction")
        if _state_snapshot(adb_root) != before_upgrade:
            raise OtastError("candidate reinstall rewrote managed-state/original contracts")

        staged_path = adb_root / "modules_update/playintegrityfix/pif.prop"
        staged_bytes = staged_path.read_bytes()
        staged_path.write_text("FINGERPRINT=drift\nSECURITY_PATCH=2026-08-05\n", encoding="utf-8")
        staged_path.chmod(0o644)
        before_reject = _state_snapshot(adb_root)
        disagreement = _run(reinstalled_entry, adb_root, "apply", expect=1)
        if _state_snapshot(adb_root) != before_reject:
            raise OtastError("fallback mirror drift changed managed state before failing")
        staged_path.write_bytes(staged_bytes)
        staged_path.chmod(0o644)

        state = adb_root / "otast/records/pif-mirror-active.state"
        original_state = state.read_bytes()
        state.write_bytes(original_state.replace(b"version=1\n", b"version=999\n", 1))
        corrupt = _run(reinstalled_entry, adb_root, "apply", expect=1)
        if state.read_bytes() == original_state:
            raise OtastError("corrupt-state scenario unexpectedly rewrote the invalid record")

        return {
            "schema_version": 2,
            "result": "PASS",
            "scenarios": {
                "synthetic_stable_to_candidate": upgrade_apply.returncode == 0,
                "self_managed_system_prop_rehydrated_transactionally": transactions_after == transactions_before + 1,
                "existing_v2_managed_state_adopted": True,
                "modules_update_mirror_state_preserved": True,
                "original_backups_preserved": True,
                "second_apply_noop": no_op_apply.returncode == 0 and after_noop == before_noop,
                "candidate_reinstall_safe": reinstall_apply.returncode == 0 and after_reinstall == before_reinstall + 1,
                "fallback_mirror_drift_rejected": disagreement.returncode == 1,
                "contradictory_state_rejected": corrupt.returncode == 1,
            },
        }
