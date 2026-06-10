import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from proxyscope.mitm.certificates import MitmCertificateAuthority


class TestMitmCertificateAuthority(unittest.TestCase):
    def test_ensure_ca_material_generates_missing_ca(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ca_dir = root / "ca"
            hosts_dir = root / "hosts"
            cert_path = ca_dir / "mitm-ca.cert.pem"
            key_path = ca_dir / "mitm-ca.key.pem"
            ca = MitmCertificateAuthority(
                ca_cert_path=cert_path,
                ca_key_path=key_path,
                hosts_dir=hosts_dir,
            )

            def fake_run(_args: list[str]) -> None:
                cert_path.write_text("generated-cert", encoding="utf-8")
                key_path.write_text("generated-key", encoding="utf-8")

            with patch.object(MitmCertificateAuthority, "_run_openssl", side_effect=fake_run) as openssl_mock:
                created = ca.ensure_ca_material()

            self.assertTrue(created)
            self.assertTrue(cert_path.exists())
            self.assertTrue(key_path.exists())
            self.assertTrue(hosts_dir.exists())
            self.assertEqual((ca_dir / "mitm-ca.crt").read_text(encoding="utf-8"), "generated-cert")
            openssl_mock.assert_called_once()

    def test_ensure_ca_material_reuses_existing_ca(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ca_dir = root / "ca"
            hosts_dir = root / "hosts"
            ca_dir.mkdir(parents=True)
            cert_path = ca_dir / "mitm-ca.cert.pem"
            key_path = ca_dir / "mitm-ca.key.pem"
            cert_path.write_text("existing-cert", encoding="utf-8")
            key_path.write_text("existing-key", encoding="utf-8")

            ca = MitmCertificateAuthority(
                ca_cert_path=cert_path,
                ca_key_path=key_path,
                hosts_dir=hosts_dir,
            )

            with patch.object(MitmCertificateAuthority, "_run_openssl") as openssl_mock:
                created = ca.ensure_ca_material()

            self.assertFalse(created)
            self.assertTrue(hosts_dir.exists())
            self.assertEqual((ca_dir / "mitm-ca.crt").read_text(encoding="utf-8"), "existing-cert")
            openssl_mock.assert_not_called()

    def test_issue_host_certificate_reuses_matching_cached_pair(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ca_dir = root / "ca"
            hosts_dir = root / "hosts"
            ca_dir.mkdir(parents=True)
            hosts_dir.mkdir(parents=True)
            (ca_dir / "mitm-ca.cert.pem").write_text("ca-cert", encoding="utf-8")
            (ca_dir / "mitm-ca.key.pem").write_text("ca-key", encoding="utf-8")
            (hosts_dir / "example.com.cert.pem").write_text("leaf-cert", encoding="utf-8")
            (hosts_dir / "example.com.key.pem").write_text("leaf-key", encoding="utf-8")

            ca = MitmCertificateAuthority(
                ca_cert_path=ca_dir / "mitm-ca.cert.pem",
                ca_key_path=ca_dir / "mitm-ca.key.pem",
                hosts_dir=hosts_dir,
            )

            with (
                patch.object(MitmCertificateAuthority, "_cert_matches_private_key", return_value=True) as match_mock,
                patch.object(MitmCertificateAuthority, "_run_openssl") as openssl_mock,
            ):
                cert_path, key_path = ca.issue_host_certificate("example.com")

            self.assertEqual(cert_path, hosts_dir / "example.com.cert.pem")
            self.assertEqual(key_path, hosts_dir / "example.com.key.pem")
            match_mock.assert_called_once()
            openssl_mock.assert_not_called()

    def test_issue_host_certificate_regenerates_mismatched_cached_pair(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ca_dir = root / "ca"
            hosts_dir = root / "hosts"
            ca_dir.mkdir(parents=True)
            hosts_dir.mkdir(parents=True)
            (ca_dir / "mitm-ca.cert.pem").write_text("ca-cert", encoding="utf-8")
            (ca_dir / "mitm-ca.key.pem").write_text("ca-key", encoding="utf-8")
            cached_cert = hosts_dir / "example.com.cert.pem"
            cached_key = hosts_dir / "example.com.key.pem"
            cached_cert.write_text("stale-cert", encoding="utf-8")
            cached_key.write_text("stale-key", encoding="utf-8")

            ca = MitmCertificateAuthority(
                ca_cert_path=ca_dir / "mitm-ca.cert.pem",
                ca_key_path=ca_dir / "mitm-ca.key.pem",
                hosts_dir=hosts_dir,
            )

            def fake_run(_args: list[str]) -> None:
                # Simulate openssl creating a fresh pair during regeneration.
                cached_cert.write_text("new-cert", encoding="utf-8")
                cached_key.write_text("new-key", encoding="utf-8")

            with (
                patch.object(MitmCertificateAuthority, "_cert_matches_private_key", return_value=False) as match_mock,
                patch.object(MitmCertificateAuthority, "_run_openssl", side_effect=fake_run) as openssl_mock,
            ):
                cert_path, key_path = ca.issue_host_certificate("example.com")

            self.assertEqual(cert_path, cached_cert)
            self.assertEqual(key_path, cached_key)
            self.assertTrue(cached_cert.exists())
            self.assertTrue(cached_key.exists())
            match_mock.assert_called_once()
            self.assertEqual(openssl_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
