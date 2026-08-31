#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

MIN_PYTHON = (3, 11)
MAX_BYTES = 256 * 1024
SUBPROCESS_TIMEOUT = 10.0
DEFAULT_PATH = Path("/data/adb/tricky_store/keybox.xml")


class KeyboxError(RuntimeError):
    pass


def run(
    command: list[str],
    *,
    data: bytes | None = None,
    timeout: float = SUBPROCESS_TIMEOUT,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            command,
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise KeyboxError(f"subprocess timed out after {timeout:.0f}s: {command[0]}") from exc
    except OSError as exc:
        raise KeyboxError(f"cannot execute {command[0]}: {exc}") from exc


def root_command() -> str | None:
    if os.geteuid() == 0:
        return None
    return shutil.which("sudo")


def rooted(prefix: str | None, *arguments: str) -> list[str]:
    return [*([prefix] if prefix else []), *arguments]


def read_candidate(path: Path, *, root_prefix: str | None) -> bytes:
    exists = run(rooted(root_prefix, "test", "-e", str(path)))
    if exists.returncode != 0:
        raise KeyboxError(f"candidate is absent: {path}")

    if run(rooted(root_prefix, "test", "-L", str(path))).returncode == 0:
        raise KeyboxError(f"STOP: refusing symlink candidate: {path}")
    if run(rooted(root_prefix, "test", "-f", str(path))).returncode != 0:
        raise KeyboxError(f"STOP: candidate is not a regular file: {path}")

    size_result = run(rooted(root_prefix, "stat", "-c", "%s", str(path)))
    if size_result.returncode != 0:
        raise KeyboxError(f"cannot stat candidate: {path}")
    try:
        size = int(size_result.stdout.decode("ascii").strip())
    except (UnicodeDecodeError, ValueError) as exc:
        raise KeyboxError(f"invalid candidate size metadata: {path}") from exc

    if size <= 0:
        raise KeyboxError(f"candidate is empty: {path}")
    if size > MAX_BYTES:
        raise KeyboxError(f"STOP: candidate exceeds {MAX_BYTES} bytes: {path}")

    content = run(rooted(root_prefix, "cat", str(path)))
    if content.returncode != 0:
        raise KeyboxError(f"cannot read candidate: {path}")
    if len(content.stdout) != size:
        raise KeyboxError(f"STOP: candidate changed while being read: {path}")
    return content.stdout


def normalized_pem(text: str) -> bytes:
    return (text.strip() + "\n").encode("utf-8")


def openssl_ok(openssl: str, arguments: list[str], data: bytes) -> bool:
    return run([openssl, *arguments], data=data).returncode == 0


def private_public_key(openssl: str, private_pem: bytes) -> bytes:
    result = run([openssl, "pkey", "-pubout", "-outform", "DER"], data=private_pem)
    if result.returncode != 0:
        raise KeyboxError("private-key public-key extraction failed")
    return result.stdout


def certificate_public_key(openssl: str, certificate_pem: bytes) -> bytes:
    extracted = run([openssl, "x509", "-pubkey", "-noout"], data=certificate_pem)
    if extracted.returncode != 0:
        raise KeyboxError("certificate public-key extraction failed")
    normalized = run(
        [openssl, "pkey", "-pubin", "-outform", "DER"],
        data=extracted.stdout,
    )
    if normalized.returncode != 0:
        raise KeyboxError("certificate public-key normalization failed")
    return normalized.stdout


def verify_chain(
    openssl: str,
    certificates: list[bytes],
    *,
    work: Path,
    prefix: str,
) -> bool:
    if len(certificates) < 2:
        return False

    paths: list[Path] = []
    for index, certificate in enumerate(certificates):
        path = work / f"{prefix}-{index}.pem"
        path.write_bytes(certificate)
        path.chmod(0o600)
        paths.append(path)

    command = [
        openssl,
        "verify",
        "-purpose",
        "any",
        "-CAfile",
        str(paths[-1]),
    ]
    if len(paths) > 2:
        intermediates = work / f"{prefix}-intermediates.pem"
        intermediates.write_bytes(b"".join(certificates[1:-1]))
        intermediates.chmod(0o600)
        command += ["-untrusted", str(intermediates)]
    command.append(str(paths[0]))
    return run(command).returncode == 0


def validate_keybox(openssl: str, raw: bytes, *, work: Path) -> list[dict[str, object]]:
    try:
        root = ET.fromstring(raw.decode("utf-8"))
    except (UnicodeDecodeError, ET.ParseError) as exc:
        raise KeyboxError(f"XML parse failed: {type(exc).__name__}") from exc

    keys = root.findall(".//Key")
    if not keys:
        raise KeyboxError("XML contains no Key entries")

    results: list[dict[str, object]] = []
    for index, key in enumerate(keys, 1):
        algorithm = key.get("algorithm", "unspecified")
        private_node = key.find("PrivateKey")
        chain = key.find("CertificateChain")
        cert_nodes = [] if chain is None else chain.findall(".//Certificate")

        if private_node is None or not (private_node.text or "").strip() or not cert_nodes:
            results.append(
                {
                    "index": index,
                    "algorithm": algorithm,
                    "certificates": len(cert_nodes),
                    "private": False,
                    "key_match": False,
                    "cert_parse": False,
                    "cert_dates": False,
                    "chain": False,
                    "result": False,
                }
            )
            continue

        private_pem = normalized_pem(private_node.text or "")
        certificates = [
            normalized_pem(node.text or "")
            for node in cert_nodes
            if (node.text or "").strip()
        ]

        private_ok = openssl_ok(openssl, ["pkey", "-check", "-noout"], private_pem)
        cert_parse = all(
            openssl_ok(openssl, ["x509", "-noout"], certificate)
            for certificate in certificates
        )
        cert_dates = all(
            openssl_ok(openssl, ["x509", "-checkend", "0", "-noout"], certificate)
            for certificate in certificates
        )

        key_match = False
        if private_ok and cert_parse and certificates:
            try:
                private_public = private_public_key(openssl, private_pem)
                certificate_public = certificate_public_key(openssl, certificates[0])
                key_match = hashlib.sha256(private_public).digest() == hashlib.sha256(certificate_public).digest()
            except KeyboxError:
                key_match = False

        chain_ok = (
            verify_chain(
                openssl,
                certificates,
                work=work,
                prefix=f"key-{index}",
            )
            if cert_parse
            else False
        )
        passed = private_ok and cert_parse and cert_dates and key_match and chain_ok
        results.append(
            {
                "index": index,
                "algorithm": algorithm,
                "certificates": len(certificates),
                "private": private_ok,
                "key_match": key_match,
                "cert_parse": cert_parse,
                "cert_dates": cert_dates,
                "chain": chain_ok,
                "result": passed,
            }
        )
    return results


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Validate a local Tricky Store OSS keybox without printing key or certificate contents."
    )
    value.add_argument("path", nargs="?", type=Path, default=DEFAULT_PATH)
    return value


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < MIN_PYTHON:
        print(
            f"ERROR: Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required; found {sys.version.split()[0]}",
            file=sys.stderr,
        )
        return 2

    arguments = parser().parse_args(argv)
    openssl = shutil.which("openssl")
    if openssl is None:
        print("ERROR: openssl is required", file=sys.stderr)
        return 2

    root_prefix = root_command()
    if os.geteuid() != 0 and root_prefix is None and not os.access(arguments.path, os.R_OK):
        print("ERROR: candidate is not readable and sudo is unavailable", file=sys.stderr)
        return 2

    try:
        raw = read_candidate(arguments.path, root_prefix=root_prefix)
        with tempfile.TemporaryDirectory(prefix="otast-keybox-public-") as raw_temp:
            work = Path(raw_temp)
            work.chmod(0o700)
            results = validate_keybox(openssl, raw, work=work)
    except KeyboxError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 1

    print(f"KEYBOX: {arguments.path}")
    print(f"SIZE:   {len(raw)}")
    print(f"SHA256: {hashlib.sha256(raw).hexdigest()}")
    print(f"KEYS:   {len(results)}")
    overall = True
    for result in results:
        passed = bool(result["result"])
        overall &= passed
        print(
            "KEY[{index}] algorithm={algorithm} certs={certificates} "
            "private={private} key_match={key_match} cert_parse={cert_parse} "
            "cert_dates={cert_dates} chain={chain} RESULT={outcome}".format(
                **result,
                private="PASS" if result["private"] else "FAIL",
                key_match="PASS" if result["key_match"] else "FAIL",
                cert_parse="PASS" if result["cert_parse"] else "FAIL",
                cert_dates="PASS" if result["cert_dates"] else "FAIL",
                chain="PASS" if result["chain"] else "FAIL",
                outcome="PASS" if passed else "FAIL",
            )
        )

    print(f"RESULT: {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
