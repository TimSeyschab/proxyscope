#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CERTS_DIR="${ROOT_DIR}/certs"
CA_DIR="${CERTS_DIR}/ca"
HOSTS_DIR="${CERTS_DIR}/hosts"

CA_KEY="${CA_DIR}/mitm-ca.key.pem"
CA_CERT="${CA_DIR}/mitm-ca.cert.pem"
CA_CRT="${CA_DIR}/mitm-ca.crt"
CA_CONFIG="${CA_DIR}/mitm-ca.cnf"

FORCE_REGENERATE=false
if [[ "${1:-}" == "--force" ]]; then
  FORCE_REGENERATE=true
fi

mkdir -p "${CA_DIR}" "${HOSTS_DIR}"

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required but not installed or not in PATH." >&2
  exit 1
fi

if [[ "${FORCE_REGENERATE}" == "true" ]]; then
  rm -f "${CA_KEY}" "${CA_CERT}" "${CA_CRT}" "${CA_CONFIG}" "${HOSTS_DIR}"/*.pem "${HOSTS_DIR}"/*.srl
fi

cat > "${CA_CONFIG}" <<'CONF'
[ req ]
distinguished_name = dn
x509_extensions = v3_ca
prompt = no

[ dn ]
CN = proxyscope Local MITM CA

[ v3_ca ]
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints = critical, CA:true
keyUsage = critical, keyCertSign, cRLSign
CONF

if [[ -f "${CA_KEY}" && -f "${CA_CERT}" ]]; then
  echo "Existing MITM CA found:"
  echo "  Key : ${CA_KEY}"
  echo "  Cert: ${CA_CERT}"
else
  echo "Generating MITM CA key and certificate..."
  openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes \
    -config "${CA_CONFIG}" \
    -extensions v3_ca \
    -keyout "${CA_KEY}" \
    -out "${CA_CERT}"
fi

cp "${CA_CERT}" "${CA_CRT}"

cat <<MSG

MITM CA files ready:
  CA Key : ${CA_KEY}
  CA Cert: ${CA_CERT}
  Browser import (.crt): ${CA_CRT}
  Host cert cache dir: ${HOSTS_DIR}

Next steps:
1) Import ${CA_CRT} into your browser/OS trust store (for local testing only).
2) Restart your browser.
3) Run the proxy; host certificates will be generated on-demand under ${HOSTS_DIR}.
4) If browser trust changes do not apply, regenerate and reimport with:
   ./scripts/generate_mitm_ca.sh --force

MSG
