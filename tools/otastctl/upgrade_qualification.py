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
    _assert_originals,
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
    """Snapshot durable original backups independently of active ownership records.

    Candidate migrations may intentionally retire an old state record while retaining
    its original backup as historical evidence. Scanning the bounded OTAST backup
    directory directly proves those bytes still exist instead of treating retirement
    of the referencing state record as backup deletion.
    """

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


def _assert_predecessor_backups_preserved(
    predecessor: dict[str, str],
    current: dict[str, str],
) -> None:
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


def qualify_published_predecessor(
    repo_root: Path,
    output_dir: Path,
    ref: str = PUBLISHED_PREDECESSOR_REF,
) -> dict[str, object]:
    """Qualify the actual published predecessor runtime into the candidate.

    The predecessor module tree is reconstructed from the pinned Git tag. No
    network request or vendored release binary is used. This qualification is
    intentionally available only when the repository history contains the tag.
    """

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
            state_id
            for state_id in LEGACY_PIF_PROFILE_STATE_IDS
            if (records / f"{state_id}.state").is_file()
        )
        if not legacy_profile_state_ids:
            raise OtastError("published predecessor created no legacy PIF profile ownership state")
        pre_candidate_profiles = _pif_profile_snapshot(adb_root)
        predecessor_backups = _backup_snapshot(adb_root)
        if not predecessor_backups:
            raise OtastError("published predecessor created no original backup evidence")

        candidate_entry = _install_candidate(candidate_zip, adb_root)
        _run(candidate_entry, adb_root, "preflight")
        _run(candidate_entry, adb_root, "apply")
        _simulate_managed_boot(adb_root)
        _run(candidate_entry, adb_root, "verify")

        post_candidate_profiles = _pif_profile_snapshot(adb_root)
        if post_candidate_profiles != pre_candidate_profiles:
            raise OtastError("candidate rewrote PIF-owned profile bytes while retiring predecessor ownership")

        retired_root = adb_root / "otast/retired/pif-profile-ownership-v1"
        if retired_root.is_symlink() or not retired_root.is_dir():
            raise OtastError("candidate did not create safe retired PIF ownership evidence")
        for state_id in legacy_profile_state_ids:
            if (records / f"{state_id}.state").exists():
                raise OtastError(f"candidate left legacy PIF ownership active: {state_id}")
            retired = retired_root / f"{state_id}.state"
            if retired.is_symlink() or not retired.is_file():
                raise OtastError(f"candidate did not retain retired PIF ownership evidence: {state_id}")

        candidate_backups = _backup_snapshot(adb_root)
        _assert_predecessor_backups_preserved(predecessor_backups, candidate_backups)

        # After ownership retirement, simulate legitimate PIF/WebUI/module update
        # writes to every currently-present profile layer. Candidate Apply and
        # Restore must leave these bytes untouched.
        for relative in tuple(post_candidate_profiles):
            path = adb_root / relative
            with path.open("ab") as handle:
                handle.write(b"# simulated PIF-owned refresh after ownership retirement\n")
        refreshed_profiles = _pif_profile_snapshot(adb_root)
        if refreshed_profiles == post_candidate_profiles:
            raise OtastError("PIF-owned refresh fixture did not change profile bytes")

        before_noop = _transaction_count(adb_root)
        second_apply = _run(candidate_entry, adb_root, "apply")
        after_noop = _transaction_count(adb_root)
        if after_noop != before_noop:
            raise OtastError("published-predecessor upgrade did not settle to a no-op second Apply")
        if _pif_profile_snapshot(adb_root) != refreshed_profiles:
            raise OtastError("candidate Apply rolled back PIF-owned profile refresh bytes")

        _run(candidate_entry, adb_root, "restore")
        if _pif_profile_snapshot(adb_root) != refreshed_profiles:
            raise OtastError("candidate Restore rolled back PIF-owned profile refresh bytes")
        _simulate_managed_boot(adb_root)
        _assert_originals_except_pif_profiles(adb_root, originals)
        if records.exists() and any(records.iterdir()):
            raise OtastError("Restore after published-predecessor upgrade left managed state records")

    return {
        "schema_version": 2,
        "result": "PASS",
        "predecessor_ref": ref,
        "predecessor_commit": predecessor_commit,
        "scenarios": {
            "published_predecessor_preflight_apply_verify": True,
            "candidate_preflight_apply_verify": True,
            "legacy_pif_profile_state_retired": bool(legacy_profile_state_ids),
            "pif_profile_bytes_preserved_during_ownership_retirement": post_candidate_profiles == pre_candidate_profiles,
            "predecessor_original_backups_preserved": True,
            "candidate_may_add_new_first_time_backups": len(candidate_backups) >= len(predecessor_backups),
            "second_apply_noop": second_apply.returncode == 0 and after_noop == before_noop,
            "pif_profile_refresh_survives_noop_apply_and_restore": True,
            "candidate_restore_recovers_non_pif_pre_otast_bytes": True,
            "managed_state_removed_after_restore": True,
        },
    }


def qualify_upgrade_path(repo_root: Path, output_dir: Path) -> dict[str, object]:
    """Exercise managed-state upgrade/reinstall boundaries against a fake Magisk root.

    The synthetic predecessor uses candidate runtime bytes with an older module
    identity. This isolates transaction continuity from runtime migration. The
    separate published-predecessor qualification above covers the actual v1.0.2
    runtime-to-candidate transition when repository history is available.
    """

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

        staged_record = adb_root / "otast/records/pif-autopif-staged.state"
        if not staged_record.is_file():
            raise OtastError("predecessor did not create managed state for modules_update")
        before_upgrade = _state_snapshot(adb_root)

        candidate_entry = _install_candidate(module_zip, adb_root)
        _run(candidate_entry, adb_root, "preflight")
        transactions_before = _transaction_count(adb_root)
        upgrade_apply = _run(candidate_entry, adb_root, "apply")
        transactions_after = _transaction_count(adb_root)
        if transactions_after != transactions_before + 1:
            raise OtastError("candidate upgrade did not use exactly one rehydration transaction")
        if _state_snapshot(adb_root) != before_upgrade:
            raise OtastError("candidate upgrade rewrote predecessor state or original backups")

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
            raise OtastError("candidate reinstall did not use exactly one rehydration transaction")
        if _state_snapshot(adb_root) != before_upgrade:
            raise OtastError("candidate reinstall rewrote managed state or original backups")

        staged_path = adb_root / "modules_update/playintegrityfix/autopif.sh"
        staged_bytes = staged_path.read_bytes()
        staged_path.write_text("contradictory staged drift\n", encoding="utf-8")
        staged_path.chmod(0o755)
        before_reject = _state_snapshot(adb_root)
        disagreement = _run(reinstalled_entry, adb_root, "apply", expect=1)
        if _state_snapshot(adb_root) != before_reject:
            raise OtastError("active/staged disagreement changed managed state before failing")
        staged_path.write_bytes(staged_bytes)
        staged_path.chmod(0o755)

        state = adb_root / "otast/records/pif-autopif-active.state"
        original_state = state.read_bytes()
        state.write_bytes(original_state.replace(b"version=1\n", b"version=999\n", 1))
        corrupt = _run(reinstalled_entry, adb_root, "apply", expect=1)
        if state.read_bytes() == original_state:
            raise OtastError("corrupt-state scenario unexpectedly rewrote the invalid record")

        return {
            "schema_version": 1,
            "result": "PASS",
            "scenarios": {
                "synthetic_stable_to_candidate": upgrade_apply.returncode == 0,
                "self_managed_system_prop_rehydrated_transactionally": transactions_after == transactions_before + 1,
                "existing_managed_state_adopted": True,
                "modules_update_state_preserved": True,
                "original_backups_preserved": True,
                "second_apply_noop": no_op_apply.returncode == 0 and after_noop == before_noop,
                "candidate_reinstall_safe": reinstall_apply.returncode == 0 and after_reinstall == before_reinstall + 1,
                "active_staged_disagreement_rejected": disagreement.returncode == 1,
                "contradictory_state_rejected": corrupt.returncode == 1,
            },
        }
