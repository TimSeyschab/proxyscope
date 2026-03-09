from dataclasses import dataclass
import ipaddress
from pathlib import Path
import re
import subprocess


class MitmCertificateError(Exception):
    """Raised when CA or leaf certificate generation fails."""


_SAFE_HOST_RE = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class MitmCertificateAuthority:
    ca_cert_path: Path
    ca_key_path: Path
    hosts_dir: Path

    def is_ready(self) -> bool:
        return self.ca_cert_path.exists() and self.ca_key_path.exists()

    def issue_host_certificate(self, host: str) -> tuple[Path, Path]:
        if not self.is_ready():
            raise MitmCertificateError(
                f"Missing CA files: cert={self.ca_cert_path} key={self.ca_key_path}"
            )

        self.hosts_dir.mkdir(parents=True, exist_ok=True)
        safe_host = _SAFE_HOST_RE.sub("_", host)
        cert_path = self.hosts_dir / f"{safe_host}.cert.pem"
        key_path = self.hosts_dir / f"{safe_host}.key.pem"
        csr_path = self.hosts_dir / f"{safe_host}.csr.pem"
        ext_path = self.hosts_dir / f"{safe_host}.ext.cnf"
        serial_path = self.hosts_dir / "mitm-ca.srl"

        if cert_path.exists() and key_path.exists():
            if self._cert_matches_private_key(cert_path=cert_path, key_path=key_path):
                return cert_path, key_path
            cert_path.unlink(missing_ok=True)
            key_path.unlink(missing_ok=True)

        san_prefix = "IP" if _is_ip_address(host) else "DNS"
        ext_path.write_text(
            "\n".join(
                [
                    "basicConstraints=CA:FALSE",
                    "keyUsage=critical,digitalSignature,keyEncipherment",
                    "extendedKeyUsage=serverAuth",
                    "subjectKeyIdentifier=hash",
                    "authorityKeyIdentifier=keyid,issuer",
                    f"subjectAltName={san_prefix}:{host}",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        self._run_openssl(
            [
                "req",
                "-new",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key_path),
                "-out",
                str(csr_path),
                "-subj",
                f"/CN={host}",
            ]
        )
        self._run_openssl(
            [
                "x509",
                "-req",
                "-in",
                str(csr_path),
                "-CA",
                str(self.ca_cert_path),
                "-CAkey",
                str(self.ca_key_path),
                "-CAserial",
                str(serial_path),
                "-CAcreateserial",
                "-out",
                str(cert_path),
                "-days",
                "825",
                "-sha256",
                "-extfile",
                str(ext_path),
            ]
        )

        # Keep generated cert/key; cleanup intermediate files.
        if csr_path.exists():
            csr_path.unlink()
        if ext_path.exists():
            ext_path.unlink()

        return cert_path, key_path

    def _cert_matches_private_key(self, *, cert_path: Path, key_path: Path) -> bool:
        """
        Return True only if certificate and private key expose the same public key.
        """
        cert_pub = self._read_openssl_output(["x509", "-in", str(cert_path), "-pubkey", "-noout"])
        key_pub = self._read_openssl_output(["pkey", "-in", str(key_path), "-pubout"])
        if cert_pub is None or key_pub is None:
            return False
        return cert_pub.strip() == key_pub.strip()

    def _read_openssl_output(self, args: list[str]) -> str | None:
        command = ["openssl", *args]
        try:
            completed = subprocess.run(command, check=True, capture_output=True, text=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            return None
        return completed.stdout

    def _run_openssl(self, args: list[str]) -> None:
        command = ["openssl", *args]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise MitmCertificateError("openssl is required but was not found in PATH.") from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip()
            raise MitmCertificateError(f"openssl failed: {' '.join(command)} | {stderr}") from exc


def default_ca() -> MitmCertificateAuthority:
    certs_root = Path("certs")
    return MitmCertificateAuthority(
        ca_cert_path=certs_root / "ca" / "mitm-ca.cert.pem",
        ca_key_path=certs_root / "ca" / "mitm-ca.key.pem",
        hosts_dir=certs_root / "hosts",
    )


def _is_ip_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False
