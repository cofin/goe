# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""AES-256-CBC + PKCS7 keyfile password and PKCS8 PEM private key management."""

from __future__ import annotations

import logging
import os
from base64 import b64decode
from pathlib import Path
from typing import Any

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding, serialization
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from goe.exceptions import ConfigurationError

__all__ = [
    "PasswordTools",
    "PasswordToolsException",
]

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class PasswordToolsException(ConfigurationError):
    """Raised when password keyfile reading, encryption, decryption, or PEM loading fails."""


class PasswordTools:
    """AES-256-CBC + PKCS7 password encryption/decryption compatible with $OFFLOAD_HOME keyfiles."""

    def __init__(self) -> None:
        self._cipher: Cipher[Any] | None = None
        logger.debug("Initialized PasswordTools() object")

    def get_password_key_from_key_file(
        self,
        password_key_file: str | None = None,
        ignore_absent_keyfile: bool = False,
    ) -> str | None:
        """Read the 96-hex-character key from PASSWORD_KEY_FILE."""
        resolved_path = password_key_file or os.environ.get("PASSWORD_KEY_FILE")
        if not resolved_path:
            return None
        resolved_path = resolved_path.strip()
        try:
            goe_key: str | None = Path(resolved_path).read_text(encoding="utf-8").strip("\r\n")
        except OSError as exc:
            if "No such file or directory" in str(exc):
                if ignore_absent_keyfile:
                    goe_key = None
                else:
                    raise PasswordToolsException("Decryption string is not base64 encoded") from exc
            else:
                raise
        if not goe_key:
            raise PasswordToolsException(f"No password key retrieved from key file: {resolved_path}")
        return goe_key

    def encrypt(self, clear_text: str | bytes, goe_key: str | bytes | None = None) -> bytes:
        """Encrypt clear_text using AES-256-CBC and 128-bit PKCS7 padding."""
        assert clear_text
        logger.debug("Encrypting clear text string")
        resolved_key = self._resolve_goe_key(goe_key)
        cipher = self._get_cipher_for_goe_password(resolved_key)
        padder = padding.PKCS7(128).padder()
        clear_bytes = clear_text if isinstance(clear_text, bytes) else clear_text.encode()
        padded_text = padder.update(clear_bytes) + padder.finalize()
        encryptor = cipher.encryptor()
        return encryptor.update(padded_text) + encryptor.finalize()

    def decrypt(self, enc_text: bytes, goe_key: str | bytes | None = None) -> str:
        """Decrypt AES-256-CBC + PKCS7 ciphertext bytes into a UTF-8 string."""
        assert enc_text
        logger.debug("Decrypting encrypted string")
        resolved_key = self._resolve_goe_key(goe_key)
        cipher = self._get_cipher_for_goe_password(resolved_key)
        decryptor = cipher.decryptor()
        padded_text = decryptor.update(enc_text) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        clear_bytes = unpadder.update(padded_text) + unpadder.finalize()
        return clear_bytes.decode()

    def b64decrypt(self, enc_text: str | bytes, goe_key: str | bytes | None = None) -> str:
        """Base64-decode enc_text and decrypt with AES-256-CBC + PKCS7."""
        assert enc_text
        try:
            decode_text = b64decode(enc_text)
        except Exception as exc:
            if any(token in str(exc) for token in ("Invalid base64-encoded string", "Incorrect padding")):
                raise PasswordToolsException("Decryption string is not base64 encoded") from exc
            raise
        return self.decrypt(decode_text, goe_key=goe_key)

    def get_private_key_from_pkcs8_pem_file(self, pem_file: str, passphrase: str | None = None) -> bytes:
        """Load a PKCS8 PEM private key file and return DER-encoded unencrypted private bytes."""
        return self._get_private_key_from_pem_file(
            pem_file,
            pem_format=serialization.PrivateFormat.PKCS8,
            passphrase=passphrase,
        )

    def _resolve_goe_key(self, goe_key: str | bytes | None) -> str:
        if goe_key:
            return goe_key.decode() if isinstance(goe_key, bytes) else goe_key
        from_file = self.get_password_key_from_key_file()
        assert from_file is not None
        return from_file

    def _get_cipher_for_goe_password(self, goe_key: str) -> Cipher[Any]:
        assert goe_key
        if not self._cipher:
            logger.debug("Setting up cipher for goe key")
            if len(goe_key) != 96:
                raise PasswordToolsException("Malformed encryption key")
            key = bytes.fromhex(goe_key[:64])
            iv = bytes.fromhex(goe_key[64:])
            backend = default_backend()
            self._cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=backend)
        return self._cipher

    def _get_private_key_from_pem_file(
        self,
        pem_file: str,
        pem_format: serialization.PrivateFormat,
        passphrase: str | None = None,
    ) -> bytes:
        assert pem_file
        assert isinstance(pem_file, str)
        assert pem_format in (serialization.PrivateFormat.PKCS8,)
        encoded_passphrase = passphrase.encode() if passphrase else None
        try:
            pem_bytes = Path(pem_file).read_bytes()
            p_key = serialization.load_pem_private_key(
                pem_bytes,
                password=encoded_passphrase,
                backend=default_backend(),
            )
        except OSError as exc:
            raise PasswordToolsException(f"PEM file does not exist or is not readable: {pem_file}\n{exc}") from exc
        except Exception as exc:
            raise PasswordToolsException(f"Unable to load private key from PEM file: {pem_file}\n{exc}") from exc
        return p_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=pem_format,
            encryption_algorithm=serialization.NoEncryption(),
        )
