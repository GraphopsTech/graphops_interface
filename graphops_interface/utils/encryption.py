import base64
import json
import os
from typing import Dict, Union

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def encrypt_payload(data: dict, encryption_key: str) -> Union[str, Dict[str, str]]:
    if _looks_like_pem(encryption_key):
        return _encrypt_hybrid(data, encryption_key)
    return _encrypt_aes_gcm(data, encryption_key)


def _looks_like_pem(key: str) -> bool:
    return "BEGIN PUBLIC KEY" in key or "BEGIN RSA PUBLIC KEY" in key


def _encrypt_hybrid(data: dict, public_key_pem: str) -> Dict[str, str]:
    public_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    aes_key = os.urandom(32)
    nonce = os.urandom(12)
    plaintext = json.dumps(data).encode("utf-8")
    aesgcm = AESGCM(aes_key)
    ct_with_tag = aesgcm.encrypt(nonce, plaintext, None)
    tag, ciphertext = ct_with_tag[-16:], ct_with_tag[:-16]
    wrapped_key = public_key.encrypt(aes_key, padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA1()), algorithm=hashes.SHA1(), label=None))
    return {"alg": "RSA-OAEP+AES-256-GCM", "wrapped_key": base64.b64encode(wrapped_key).decode("utf-8"), "nonce": base64.b64encode(nonce).decode("utf-8"), "ciphertext": base64.b64encode(ciphertext).decode("utf-8"), "tag": base64.b64encode(tag).decode("utf-8")}


def _encrypt_aes_gcm(data: dict, enc_key: str) -> dict:
    if len(enc_key) == 64:
        key = bytes.fromhex(enc_key)
    elif len(enc_key) == 44:
        key = base64.b64decode(enc_key)
    else:
        key = base64.b64decode(enc_key)
        if len(key) != 32:
            raise ValueError(f"Invalid key length: expected 32 bytes, got {len(key)}")
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, json.dumps(data).encode("utf-8"), None)
    tag, encrypted_data = ciphertext[-16:], ciphertext[:-16]
    return {"alg": "AES-256-GCM", "nonce": base64.b64encode(nonce).decode("utf-8"), "ciphertext": base64.b64encode(encrypted_data).decode("utf-8"), "tag": base64.b64encode(tag).decode("utf-8")}
