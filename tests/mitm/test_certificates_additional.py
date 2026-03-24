from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from proxyscope.mitm.certificates import (
    MitmCertificateAuthority,
    MitmCertificateError,
    _browser_import_ca_path,
    _is_ip_address,
    certificate_authority_for_root,
    default_ca,
)


class TestMitmCertificateUtilities(unittest.TestCase):
    def test_is_ip_address(self) -> None:
        self.assertTrue(_is_ip_address("127.0.0.1"))
        self.assertTrue(_is_ip_address("::1"))
        self.assertFalse(_is_ip_address("example.com"))

    def test_browser_import_path_uses_crt_suffix(self) -> None:
        cert_path = Path("/tmp/mitm-ca.cert.pem")
        self.assertEqual(_browser_import_ca_path(cert_path), Path("/tmp/mitm-ca.crt"))

    def test_browser_import_path_falls_back_to_with_suffix(self) -> None:
        cert_path = Path("/tmp/mitm-ca.pem")
        self.assertEqual(_browser_import_ca_path(cert_path), Path("/tmp/mitm-ca.crt"))

    def test_certificate_authority_factories(self) -> None:
        authority = certificate_authority_for_root("custom-certs")
        self.assertEqual(authority.ca_cert_path, Path("custom-certs/ca/mitm-ca.cert.pem"))
        self.assertEqual(authority.ca_key_path, Path("custom-certs/ca/mitm-ca.key.pem"))
        self.assertEqual(authority.hosts_dir, Path("custom-certs/hosts"))

        default_authority = default_ca()
        self.assertEqual(default_authority.ca_cert_path, Path("certs/ca/mitm-ca.cert.pem"))


class TestMitmCertificateErrorPaths(unittest.TestCase):
    def test_ensure_ca_material_recreates_partial_material(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            cert_path = root / "ca" / "mitm-ca.cert.pem"
            key_path = root / "ca" / "mitm-ca.key.pem"
            hosts_dir = root / "hosts"
            cert_path.parent.mkdir(parents=True)
            cert_path.write_text("stale", encoding="utf-8")
            authority = MitmCertificateAuthority(cert_path, key_path, hosts_dir)

            def fake_run(_args: list[str]) -> None:
                cert_path.write_text("new-cert", encoding="utf-8")
                key_path.write_text("new-key", encoding="utf-8")

            with patch.object(MitmCertificateAuthority, "_run_openssl", side_effect=fake_run):
                created = authority.ensure_ca_material()

            self.assertTrue(created)
            self.assertEqual(cert_path.read_text(encoding="utf-8"), "new-cert")
            self.assertEqual(key_path.read_text(encoding="utf-8"), "new-key")

    def test_issue_host_certificate_requires_ready_ca(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            authority = MitmCertificateAuthority(
                ca_cert_path=root / "ca" / "mitm-ca.cert.pem",
                ca_key_path=root / "ca" / "mitm-ca.key.pem",
                hosts_dir=root / "hosts",
            )
            with self.assertRaises(MitmCertificateError):
                authority.issue_host_certificate("example.com")

    def test_read_openssl_output_returns_none_for_subprocess_errors(self) -> None:
        authority = MitmCertificateAuthority(Path("/tmp/ca.cert.pem"), Path("/tmp/ca.key.pem"), Path("/tmp/hosts"))

        with patch("proxyscope.mitm.certificates.subprocess.run", side_effect=FileNotFoundError):
            self.assertIsNone(authority._read_openssl_output(["x509"]))  # noqa: SLF001

        failed = subprocess.CalledProcessError(returncode=1, cmd=["openssl"], stderr="boom")
        with patch("proxyscope.mitm.certificates.subprocess.run", side_effect=failed):
            self.assertIsNone(authority._read_openssl_output(["x509"]))  # noqa: SLF001

    def test_run_openssl_raises_mitm_error_when_binary_missing(self) -> None:
        authority = MitmCertificateAuthority(Path("/tmp/ca.cert.pem"), Path("/tmp/ca.key.pem"), Path("/tmp/hosts"))
        with patch("proxyscope.mitm.certificates.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaises(MitmCertificateError):
                authority._run_openssl(["x509"])  # noqa: SLF001

    def test_run_openssl_raises_mitm_error_with_stderr(self) -> None:
        authority = MitmCertificateAuthority(Path("/tmp/ca.cert.pem"), Path("/tmp/ca.key.pem"), Path("/tmp/hosts"))
        error = subprocess.CalledProcessError(returncode=1, cmd=["openssl"], stderr="invalid config")
        with patch("proxyscope.mitm.certificates.subprocess.run", side_effect=error):
            with self.assertRaises(MitmCertificateError) as raised:
                authority._run_openssl(["req", "-x509"])  # noqa: SLF001
        self.assertIn("invalid config", str(raised.exception))

