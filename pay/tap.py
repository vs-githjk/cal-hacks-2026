"""TAP-style request signing: RFC 9421 HTTP Message Signatures with Ed25519.

TAP-style signing per RFC 9421; conformance checked by our merchant simulator. This follows the shape of
Visa's Trusted Agent Protocol (signature covers method, authority, path, body digest and the mandate hash;
created, expires, keyid, nonce and tag params) but it is not a certified Visa integration, and nothing here
settles money.

Signed headers: Content-Digest (sha-256), Mandate-Hash, Signature-Input, Signature.
The private key comes from the path in VISA_TAP_PRIVATE_KEY_PATH. Never commit a key (*.pem is ignored).
"""
from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
from datetime import datetime
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from pay.mandate import Verdict, mandate_hash
from pay.mandate import verify as verify_mandate
from pay.replay import NS_MANDATE, NS_TAP, NonceStore

KEY_ENV = "VISA_TAP_PRIVATE_KEY_PATH"
TAG = "agent-browser-auth"
ALG = "ed25519"
LABEL = "sig1"
COMPONENTS = ("@method", "@authority", "@path", "@query", "content-digest", "mandate-hash")
MAX_SIGNATURE_TTL_SECONDS = 300
DEFAULT_TTL_SECONDS = 60
CLOCK_SKEW_SECONDS = 30
ADMISSION_TAG = "techbazaar-seller-admission-v1"
ADMISSION_COMPONENTS = ("@method", "@authority", "@path", "@query", "content-digest",
                        "agent-address", "admission-audience")
ADMISSION_NONCE_NAMESPACE = "seller-admission"
MAX_ADMISSION_BODY_BYTES = 64 * 1024


class TapKeyError(Exception):
    """The signing key is missing, unreadable or the wrong type. The message never contains key bytes."""


def _ok() -> Verdict:
    return Verdict(True, "ok")


def _no(reason: str, detail: str = "") -> Verdict:
    return Verdict(False, reason, detail)


# ---------- keys ----------

def key_id(public_key: Ed25519PublicKey) -> str:
    """base64url sha-256 of the raw public key (no padding)."""
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode()


def keyring(*public_keys: Ed25519PublicKey) -> dict[str, Ed25519PublicKey]:
    return {key_id(k): k for k in public_keys}


def load_private_key(path: Optional[str] = None) -> Ed25519PrivateKey:
    """Read the PEM at `path`, default the VISA_TAP_PRIVATE_KEY_PATH env var."""
    path = path or os.environ.get(KEY_ENV)
    if not path:
        raise TapKeyError(f"{KEY_ENV} is not set")
    try:
        with open(path, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), password=None)
    except OSError as e:
        raise TapKeyError(f"cannot read the key file at {path}") from e
    except (ValueError, TypeError) as e:
        raise TapKeyError(f"the file at {path} is not a usable PEM private key") from e
    if not isinstance(key, Ed25519PrivateKey):
        raise TapKeyError("the TAP key must be an Ed25519 private key")
    return key


def generate_keypair(path: str) -> Ed25519PublicKey:
    """Dev and test helper: write a new Ed25519 PEM to `path` (mode 0600, never overwrites) and return
    the public key. Put real keys outside the repo."""
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        if os.name == "nt":
            identity = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True,
                                      text=True, check=True, timeout=5).stdout.strip()
            rows = list(csv.reader(identity.splitlines()))
            sid = rows[0][-1] if rows and rows[0] else ""
            if not sid.startswith("S-1-"):
                raise OSError("could not identify current Windows user for private key ACL")
            for args in (["/reset"], ["/inheritance:r"], ["/grant:r", f"*{sid}:(F)"]):
                result = subprocess.run(["icacls", path, *args], capture_output=True, text=True, timeout=10)
                if result.returncode:
                    raise OSError("could not restrict TAP private key permissions")
        with os.fdopen(fd, "wb") as f:
            f.write(pem)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return key.public_key()


# ---------- signature base ----------

def _authority(split) -> str:
    host = (split.hostname or "").lower()
    port = split.port
    if port and not ((split.scheme == "https" and port == 443) or (split.scheme == "http" and port == 80)):
        return f"{host}:{port}"
    return host


def _content_digest(body: bytes) -> str:
    return "sha-256=:" + base64.b64encode(hashlib.sha256(body).digest()).decode() + ":"


def _params_string(components, created: int, expires: int, keyid: str, nonce: str) -> str:
    inner = " ".join(f'"{c}"' for c in components)
    return f'({inner});created={created};expires={expires};keyid="{keyid}";alg="{ALG}";nonce="{nonce}";tag="{TAG}"'


def _signature_base(components, values: Mapping[str, str], params: str) -> bytes:
    lines = [f'"{c}": {values[c]}' for c in components]
    lines.append(f'"@signature-params": {params}')
    return "\n".join(lines).encode("utf-8")


def _component_values(method: str, url: str, content_digest: str, mand_hash: str) -> dict[str, str]:
    split = urlsplit(url)
    return {
        "@method": method.upper(),
        "@authority": _authority(split),
        "@path": split.path or "/",
        "@query": "?" + split.query,  # RFC 9421 section 2.2.7: always a leading "?", even when empty
        "content-digest": content_digest,
        "mandate-hash": mand_hash,
    }


# ---------- sign ----------

def sign_request(
    *,
    method: str,
    url: str,
    body: bytes,
    mandate: Mapping[str, Any],
    private_key: Ed25519PrivateKey,
    now: Optional[datetime] = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    nonce: Optional[str] = None,
) -> dict[str, str]:
    """Headers to add to a buyer-agent request. Refuses a mandate whose hash is stale."""
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 0 < ttl_seconds <= MAX_SIGNATURE_TTL_SECONDS:
        raise ValueError(f"ttl_seconds must be 1..{MAX_SIGNATURE_TTL_SECONDS}")
    mand_hash = mandate_hash(mandate)
    if mandate.get("hash") != mand_hash:
        raise ValueError("mandate hash does not match its fields; refusing to sign")
    created = int((now or datetime.now().astimezone()).timestamp())
    expires = created + ttl_seconds
    nonce = nonce or secrets.token_urlsafe(16)
    keyid = key_id(private_key.public_key())
    digest = _content_digest(body)
    params = _params_string(COMPONENTS, created, expires, keyid, nonce)
    base = _signature_base(COMPONENTS, _component_values(method, url, digest, mand_hash), params)
    sig = base64.b64encode(private_key.sign(base)).decode()
    return {
        "Content-Digest": digest,
        "Mandate-Hash": mand_hash,
        "Signature-Input": f"{LABEL}={params}",
        "Signature": f"{LABEL}=:{sig}:",
    }


def attach_signature(mandate: dict, headers: Mapping[str, str]) -> dict:
    """Record the Signature header on the mandate (tap_signature is not part of the mandate hash)."""
    mandate["tap_signature"] = headers["Signature"]
    return mandate


# ---------- verify ----------

_INPUT_RE = re.compile(r'(?P<label>[a-z0-9]+)=\((?P<inner>[^)]*)\)(?P<params>(?:;[a-z]+=(?:\d+|"[A-Za-z0-9_\-=.:+/]*"))*)')
_PARAM_RE = re.compile(r';([a-z]+)=(\d+|"[A-Za-z0-9_\-=.:+/]*")')
_SIG_RE = re.compile(r'(?P<label>[a-z0-9]+)=:(?P<b64>[A-Za-z0-9+/]*={0,2}):')
_DIGEST_RE = re.compile(r'sha-256=:(?P<b64>[A-Za-z0-9+/]*={0,2}):')
_HEADER_NAME_RE = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}\Z")


def _parse_input(value: str):
    m = _INPUT_RE.fullmatch(value.strip())
    if not m:
        return None
    components = re.findall(r'"([^"]*)"', m["inner"])
    if m["inner"].strip() != " ".join(f'"{c}"' for c in components):
        return None
    params: dict[str, Any] = {}
    for k, v in _PARAM_RE.findall(m["params"]):
        if k in params:
            return None
        params[k] = int(v) if v.isdigit() else v.strip('"')
    return m["label"], components, params, value.strip()[len(m["label"]) + 1:]


def verify_request(
    *,
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes,
    keys: Mapping[str, Ed25519PublicKey],
    store: NonceStore,
    now: Optional[datetime] = None,
    expected_mandate_hash: Optional[str] = None,
    mandate: Optional[Mapping[str, Any]] = None,
) -> Verdict:
    """Verify a signed buyer-agent request (what the merchant simulator runs).

    `expected_mandate_hash`: the hash the merchant holds for this deal; a signed request for another deal
    fails. `mandate`: the mandate to bind; default is body["mandate"] when the body is a JSON object that
    has one. With neither `expected_mandate_hash` nor a mandate the request is bound to nothing and fails
    with `unbound_mandate`. A mandate that is present must also pass `mandate.verify` (schema, hash, ttl,
    expiry, status) and its nonce must not be spent in `store`. The nonce is recorded only after every other
    check passes, so a forged request cannot burn it."""
    h = {k.lower(): v for k, v in headers.items()}
    for name in ("signature", "signature-input", "content-digest", "mandate-hash"):
        if not isinstance(h.get(name), str) or not h[name].strip():
            return _no("missing_header", name)

    parsed = _parse_input(h["signature-input"])
    if parsed is None:
        return _no("bad_signature_input", "cannot parse Signature-Input")
    label, components, params, params_str = parsed
    sig_m = _SIG_RE.fullmatch(h["signature"].strip())
    if not sig_m or sig_m["label"] != label or label != LABEL:
        return _no("bad_signature_input", "Signature label does not match Signature-Input")
    if not set(COMPONENTS) <= set(components):
        return _no("bad_component_set", "signature must cover " + ", ".join(COMPONENTS))
    if params.get("alg") != ALG:
        return _no("bad_alg", "alg must be ed25519")
    if params.get("tag") != TAG:
        return _no("bad_tag", f"tag must be {TAG}")
    for p in ("created", "expires"):
        if not isinstance(params.get(p), int):
            return _no("bad_signature_input", f"{p} is required")
    for p in ("keyid", "nonce"):
        if not isinstance(params.get(p), str) or not params[p]:
            return _no("bad_signature_input", f"{p} is required")
    if set(components) - set(COMPONENTS):
        return _no("bad_component_set", "unsupported covered component")

    public_key = keys.get(params["keyid"])
    if public_key is None:
        return _no("unknown_key", "keyid is not in the keyring")

    now_ts = int((now or datetime.now().astimezone()).timestamp())
    created, expires = params["created"], params["expires"]
    if expires - created > MAX_SIGNATURE_TTL_SECONDS or expires <= created:
        return _no("ttl_too_long", "signature lifetime is out of range")
    if created > now_ts + CLOCK_SKEW_SECONDS:
        return _no("signature_not_yet_valid", "created is in the future")
    if now_ts >= expires:
        return _no("signature_expired", "signature is past expires")

    dm = _DIGEST_RE.fullmatch(h["content-digest"].strip())
    if not dm or not hmac.compare_digest(h["content-digest"].strip(), _content_digest(body)):
        return _no("digest_mismatch", "body does not match Content-Digest")

    values = _component_values(method, url, h["content-digest"].strip(), h["mandate-hash"].strip())
    base = _signature_base(components, values, params_str)
    try:
        public_key.verify(base64.b64decode(sig_m["b64"], validate=True), base)
    except (InvalidSignature, binascii.Error, ValueError):
        return _no("bad_signature", "signature does not verify")

    mand_hash = h["mandate-hash"].strip()
    if expected_mandate_hash is not None and not hmac.compare_digest(mand_hash, expected_mandate_hash):
        return _no("mandate_mismatch", "signed mandate hash is not the one for this deal")
    if mandate is None:
        try:
            parsed_body = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            parsed_body = None
        if isinstance(parsed_body, dict) and "mandate" in parsed_body:
            mandate = parsed_body["mandate"]
    if mandate is None and expected_mandate_hash is None:
        return _no("unbound_mandate", "request carries no mandate and no expected mandate hash")
    current = now or datetime.now().astimezone()
    if mandate is not None:
        try:
            recomputed = mandate_hash(mandate)
        except (ValueError, TypeError, AttributeError):
            return _no("mandate_hash_mismatch", "mandate in the request is malformed")
        if recomputed != mand_hash or mandate.get("hash") != mand_hash:
            return _no("mandate_hash_mismatch", "mandate fields do not match the signed hash")
        live = verify_mandate(mandate, current)
        if not live:
            return live
        if store.seen(NS_MANDATE, mandate["nonce"]):
            return _no("replayed_mandate", "this mandate was already charged")

    if not store.consume(NS_TAP, f"{params['keyid']}:{params['nonce']}"):
        return _no("replayed_nonce", "this signed request was already used")
    return _ok()


def _admission_url_values(method: str, url: str, content_digest: str,
                          agent_address: str, audience: str) -> dict[str, str]:
    if not isinstance(method, str) or method.upper() != "POST":
        raise ValueError("admission method must be POST")
    if not isinstance(url, str):
        raise ValueError("admission URL must be a string")
    if (not url or len(url) > 8192 or any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7f
                                           for char in url)):
        raise ValueError("invalid admission URL")
    split = urlsplit(url)
    if (split.scheme not in ("http", "https") or not split.hostname or split.username is not None
            or split.password is not None or split.fragment or split.netloc.endswith(":")
            or any(char.isspace() for char in url)):
        raise ValueError("invalid admission URL")
    _ = split.port
    values = _component_values(method, url, content_digest, "")
    values.pop("mandate-hash")
    values["agent-address"] = agent_address
    values["admission-audience"] = audience
    return values


def _admission_header_value(value: str, limit: int) -> bool:
    return len(value) <= limit and value.isascii() and all(ord(char) >= 0x20 and ord(char) != 0x7f
                                                           for char in value)


def _admission_params_string(created: int, expires: int, keyid: str, nonce: str) -> str:
    inner = " ".join(f'"{component}"' for component in ADMISSION_COMPONENTS)
    return (f'({inner});created={created};expires={expires};keyid="{keyid}";alg="{ALG}";'
            f'nonce="{nonce}";tag="{ADMISSION_TAG}"')


def sign_agent_request(
    *,
    method: str,
    url: str,
    body: bytes,
    agent_address: str,
    audience: str,
    private_key: Ed25519PrivateKey,
    now: Optional[datetime] = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    nonce: Optional[str] = None,
) -> dict[str, str]:
    """Sign an agent-admission request; this fixed profile carries no payment fields or mandate."""
    if (isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int)
            or not 0 < ttl_seconds <= MAX_SIGNATURE_TTL_SECONDS):
        raise ValueError(f"ttl_seconds must be 1..{MAX_SIGNATURE_TTL_SECONDS}")
    if not isinstance(body, bytes) or not body or len(body) > MAX_ADMISSION_BODY_BYTES:
        raise ValueError("admission body must be non-empty bytes within the size limit")
    if (not isinstance(agent_address, str) or not agent_address or len(agent_address) > 256
            or not _admission_header_value(agent_address, 256) or any(char.isspace() for char in agent_address)
            or not isinstance(audience, str) or not audience or len(audience) > 2048
            or not _admission_header_value(audience, 2048) or any(char.isspace() for char in audience)):
        raise ValueError("agent address and audience are required")
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("admission signing key must be Ed25519")
    nonce = nonce or secrets.token_urlsafe(16)
    if not isinstance(nonce, str) or not re.fullmatch(r"[A-Za-z0-9_\-=.:+/]{1,256}", nonce):
        raise ValueError("invalid admission nonce")
    created = int((now or datetime.now().astimezone()).timestamp())
    expires = created + ttl_seconds
    digest = _content_digest(body)
    params = _admission_params_string(created, expires, key_id(private_key.public_key()), nonce)
    values = _admission_url_values(method, url, digest, agent_address, audience)
    signature = base64.b64encode(private_key.sign(_signature_base(ADMISSION_COMPONENTS, values, params))).decode()
    return {
        "Content-Digest": digest,
        "Agent-Address": agent_address,
        "Admission-Audience": audience,
        "Signature-Input": f"{LABEL}={params}",
        "Signature": f"{LABEL}=:{signature}:",
    }


def verify_agent_request(
    *,
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes,
    keys: Mapping[str, Ed25519PublicKey],
    store: NonceStore,
    actual_sender: str,
    expected_audience: str,
    now: Optional[datetime] = None,
) -> Verdict:
    """Verify the purpose-bound seller-admission profile without mandate or payment semantics."""
    if (not isinstance(headers, Mapping) or not isinstance(body, bytes) or not body
            or len(body) > MAX_ADMISSION_BODY_BYTES):
        return _no("bad_request", "headers must be a mapping and body bytes")
    if len(headers) > 64:
        return _no("bad_header", "too many request headers")
    h: dict[str, str] = {}
    for name, value in headers.items():
        if (not isinstance(name, str) or not isinstance(value, str) or not name.isascii()
                or not _HEADER_NAME_RE.fullmatch(name)
                or not _admission_header_value(value, 8192) or name.lower() in h):
            return _no("duplicate_or_bad_header", "headers must have unique case-insensitive string names")
        h[name.lower()] = value
    if "mandate-hash" in h:
        return _no("wrong_purpose", "admission requests do not carry Mandate-Hash")
    for name in ("signature", "signature-input", "content-digest", "agent-address", "admission-audience"):
        if not isinstance(h.get(name), str) or not h[name]:
            return _no("missing_header", name)
    if (not _admission_header_value(h["content-digest"], 128)
            or not _admission_header_value(h["agent-address"], 256)
            or not _admission_header_value(h["admission-audience"], 2048)
            or not _admission_header_value(h["signature-input"], 4096)
            or not _admission_header_value(h["signature"], 2048)):
        return _no("bad_signature_input", "signature headers are too large")
    if (not isinstance(actual_sender, str) or not actual_sender or len(actual_sender) > 256
            or any(char.isspace() for char in actual_sender)
            or not isinstance(expected_audience, str) or not expected_audience or len(expected_audience) > 2048
            or any(char.isspace() for char in expected_audience)):
        return _no("bad_binding", "actual sender and expected audience are required")
    if h["agent-address"] != actual_sender:
        return _no("sender_mismatch", "signed agent address does not match actual sender")
    if h["admission-audience"] != expected_audience:
        return _no("audience_mismatch", "signed audience does not match expected audience")
    try:
        values = _admission_url_values(method, url, h["content-digest"], h["agent-address"],
                                       h["admission-audience"])
    except (ValueError, TypeError, AttributeError):
        return _no("bad_url", "invalid admission request URL or method")

    try:
        parsed = _parse_input(h["signature-input"])
    except (ValueError, TypeError, OverflowError):
        return _no("bad_signature_input", "cannot parse Signature-Input")
    if parsed is None:
        return _no("bad_signature_input", "cannot parse Signature-Input")
    label, components, params, params_str = parsed
    sig_m = _SIG_RE.fullmatch(h["signature"].strip())
    if not sig_m or sig_m["label"] != label or label != LABEL:
        return _no("bad_signature_input", "Signature label does not match Signature-Input")
    if tuple(components) != ADMISSION_COMPONENTS:
        return _no("bad_component_set", "signature must cover the exact admission component set")
    if set(params) != {"created", "expires", "keyid", "alg", "nonce", "tag"}:
        return _no("bad_signature_input", "signature parameters do not match the admission profile")
    if params.get("alg") != ALG:
        return _no("bad_alg", "alg must be ed25519")
    if params.get("tag") != ADMISSION_TAG:
        return _no("bad_tag", "signature purpose is not seller admission")
    if any(not isinstance(params.get(p), int) for p in ("created", "expires")):
        return _no("bad_signature_input", "created and expires are required")
    for name in ("keyid", "nonce"):
        if not isinstance(params.get(name), str) or not params[name]:
            return _no("bad_signature_input", f"{name} is required")
    if len(params["nonce"]) > 256:
        return _no("bad_signature_input", "nonce is too long")
    if not isinstance(keys, Mapping):
        return _no("unknown_key", "admission keyring is unavailable")
    public_key = keys.get(params["keyid"])
    if not isinstance(public_key, Ed25519PublicKey):
        return _no("unknown_key", "keyid is not pinned in the admission keyring")

    try:
        now_ts = int((now or datetime.now().astimezone()).timestamp())
    except (AttributeError, TypeError, ValueError, OverflowError):
        return _no("bad_time", "invalid verifier time")
    created, expires = params["created"], params["expires"]
    if expires - created > MAX_SIGNATURE_TTL_SECONDS or expires <= created:
        return _no("ttl_too_long", "signature lifetime is out of range")
    if created > now_ts + CLOCK_SKEW_SECONDS:
        return _no("signature_not_yet_valid", "created is in the future")
    if now_ts >= expires:
        return _no("signature_expired", "signature is past expires")
    try:
        digest_matches = hmac.compare_digest(h["content-digest"], _content_digest(body))
    except TypeError:
        return _no("bad_digest", "Content-Digest is malformed")
    if not digest_matches:
        return _no("digest_mismatch", "body does not match Content-Digest")
    try:
        public_key.verify(base64.b64decode(sig_m["b64"], validate=True),
                          _signature_base(components, values, params_str))
    except (InvalidSignature, binascii.Error, ValueError, TypeError):
        return _no("bad_signature", "signature does not verify")
    try:
        if not store.consume(ADMISSION_NONCE_NAMESPACE, f"{params['keyid']}:{params['nonce']}"):
            return _no("replayed_nonce", "this admission request was already used")
    except Exception:
        return _no("replay_store_error", "admission replay protection is unavailable")
    return _ok()
