"""암호화 유틸리티"""
from cryptography.fernet import Fernet
import os
from app.config import settings


class EncryptionManager:
    """계정 정보 암호화 관리자"""

    def __init__(self):
        key = settings.encryption_key.encode()
        self.cipher = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        """
        평문 암호화

        Args:
            plaintext: 암호화할 평문

        Returns:
            암호화된 문자열
        """
        if not plaintext:
            return ""
        return self.cipher.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        """
        암호문 복호화

        Args:
            ciphertext: 복호화할 암호문

        Returns:
            복호화된 평문
        """
        if not ciphertext:
            return ""
        return self.cipher.decrypt(ciphertext.encode()).decode()

    def encrypt_dict(self, data: dict) -> dict:
        """딕셔너리의 값들을 암호화"""
        return {k: self.encrypt(v) for k, v in data.items()}

    def decrypt_dict(self, data: dict) -> dict:
        """딕셔너리의 값들을 복호화"""
        return {k: self.decrypt(v) for k, v in data.items()}


# 전역 인스턴스
encryptor = EncryptionManager()
