from __future__ import annotations

import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/validate-trickystore-keybox.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("otast_keybox_validator", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load keybox validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class KeyboxValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.openssl = shutil.which("openssl")
        if cls.openssl is None:
            raise unittest.SkipTest("openssl unavailable")
        cls.module = load_validator()

    def test_empty_and_symlink_candidates_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-keybox-read-") as raw:
            work = Path(raw)
            empty = work / "empty.xml"
            empty.write_bytes(b"")
            with self.assertRaises(self.module.KeyboxError):
                self.module.read_candidate(empty, root_prefix=None)

            real = work / "real.xml"
            real.write_text("not-a-keybox\n", encoding="utf-8")
            link = work / "link.xml"
            link.symlink_to(real)
            with self.assertRaises(self.module.KeyboxError):
                self.module.read_candidate(link, root_prefix=None)

    def test_malformed_xml_fails_before_crypto_processing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-keybox-malformed-") as raw:
            with self.assertRaises(self.module.KeyboxError):
                self.module.validate_keybox(
                    self.openssl,
                    b"<AndroidAttestation>",
                    work=Path(raw),
                )

    def test_generated_two_certificate_chain_passes_without_exposing_material(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-keybox-crypto-") as raw:
            work = Path(raw)
            root_key = work / "root.key"
            root_cert = work / "root.pem"
            leaf_key = work / "leaf.key"
            leaf_csr = work / "leaf.csr"
            leaf_cert = work / "leaf.pem"

            commands = (
                [
                    self.openssl,
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-subj",
                    "/CN=OTAST Test Root",
                    "-days",
                    "2",
                    "-keyout",
                    str(root_key),
                    "-out",
                    str(root_cert),
                ],
                [
                    self.openssl,
                    "req",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-subj",
                    "/CN=OTAST Test Leaf",
                    "-keyout",
                    str(leaf_key),
                    "-out",
                    str(leaf_csr),
                ],
                [
                    self.openssl,
                    "x509",
                    "-req",
                    "-in",
                    str(leaf_csr),
                    "-CA",
                    str(root_cert),
                    "-CAkey",
                    str(root_key),
                    "-CAcreateserial",
                    "-days",
                    "2",
                    "-out",
                    str(leaf_cert),
                ],
            )
            for command in commands:
                subprocess.run(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                    timeout=15,
                )

            private_text = leaf_key.read_text(encoding="utf-8")
            leaf_text = leaf_cert.read_text(encoding="utf-8")
            root_text = root_cert.read_text(encoding="utf-8")
            xml = (
                "<AndroidAttestation><Keybox><Key algorithm=\"rsa\">"
                f"<PrivateKey>{private_text}</PrivateKey>"
                "<CertificateChain>"
                f"<Certificate>{leaf_text}</Certificate>"
                f"<Certificate>{root_text}</Certificate>"
                "</CertificateChain></Key></Keybox></AndroidAttestation>"
            ).encode("utf-8")

            public_work = work / "public"
            public_work.mkdir()
            results = self.module.validate_keybox(self.openssl, xml, work=public_work)
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0]["result"])

            # The validator may materialize certificates for openssl verify, but
            # private-key bytes must never be written into its validation workspace.
            for path in public_work.iterdir():
                self.assertNotIn(private_text.strip(), path.read_text(encoding="utf-8"))

    def test_source_has_no_private_material_logging_path(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("print(private_pem", text)
        self.assertNotIn("print(raw.decode", text)
        self.assertNotIn("stderr.decode", text)
        self.assertIn('TemporaryDirectory(prefix="otast-keybox-public-")', text)


if __name__ == "__main__":
    unittest.main()
