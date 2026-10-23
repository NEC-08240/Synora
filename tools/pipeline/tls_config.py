# TLS configuration and ephemeral certificate generation for Synora Agent Bridge
import datetime
import ipaddress
import os
import ssl
from pathlib import Path
from typing import List, Optional, Tuple

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa


class TLSConfigError(ValueError):
    pass


def create_server_ssl_context(
    certfile: str,
    keyfile: str,
    ca_certfile: Optional[str] = None,
    require_client_cert: bool = False,
) -> ssl.SSLContext:
    if not os.path.exists(certfile):
        raise TLSConfigError(f'Server certificate file does not exist: {certfile}')
    if not os.path.exists(keyfile):
        raise TLSConfigError(f'Server private key file does not exist: {keyfile}')

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        ctx.maximum_version = ssl.TLSVersion.TLSv1_3
    except AttributeError:
        pass

    ctx.set_ciphers(
        'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:'
        'ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:'
        'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256'
    )
    ctx.options |= ssl.OP_SINGLE_ECDH_USE | ssl.OP_CIPHER_SERVER_PREFERENCE

    ctx.load_cert_chain(certfile=certfile, keyfile=keyfile)

    if require_client_cert:
        if not ca_certfile or not os.path.exists(ca_certfile):
            raise TLSConfigError('ca_certfile is required when require_client_cert is True.')
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_verify_locations(cafile=ca_certfile)

    return ctx


def create_client_ssl_context(
    ca_certfile: Optional[str] = None,
    client_certfile: Optional[str] = None,
    client_keyfile: Optional[str] = None,
    check_hostname: bool = True,
) -> ssl.SSLContext:
    ctx = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH, cafile=ca_certfile)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.check_hostname = check_hostname

    if client_certfile and client_keyfile:
        if not os.path.exists(client_certfile) or not os.path.exists(client_keyfile):
            raise TLSConfigError('Client certificate or key file does not exist.')
        ctx.load_cert_chain(certfile=client_certfile, keyfile=client_keyfile)

    return ctx


def generate_ephemeral_test_cert(
    output_dir: str,
    common_name: str = 'localhost',
    ip_addresses: Optional[List[str]] = None,
    valid_days: int = 1,
) -> Tuple[str, str]:
    """Generates an ephemeral self-signed TLS cert and private key for tests.

    Never committed to Git; created dynamically in temp directories.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([
        x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, common_name),
        x509.NameAttribute(x509.oid.NameOID.ORGANIZATION_NAME, 'Synora Testing Authority'),
    ])

    alt_names: List[x509.GeneralName] = [x509.DNSName(common_name)]
    if ip_addresses:
        for ip_str in ip_addresses:
            alt_names.append(x509.IPAddress(ipaddress.ip_address(ip_str)))
    elif common_name == 'localhost':
        alt_names.append(x509.IPAddress(ipaddress.IPv4Address('127.0.0.1')))

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=valid_days))
        .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
        .sign(key, hashes.SHA256())
    )

    cert_path = os.path.join(output_dir, 'test_server.crt')
    key_path = os.path.join(output_dir, 'test_server.key')

    with open(cert_path, 'wb') as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    with open(key_path, 'wb') as f:
        f.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    return cert_path, key_path
