from pathlib import Path
import os

from cryptography.fernet import Fernet, InvalidToken


GEMINI_SECRET_DIR = Path.home() / ".01_suivi_av_per"
GEMINI_MASTER_KEY_PATH = GEMINI_SECRET_DIR / "gemini_master.key"
GEMINI_VAULT_PATH = GEMINI_SECRET_DIR / "gemini_api.enc"


def ensure_secret_dir():
    GEMINI_SECRET_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(GEMINI_SECRET_DIR, 0o700)
    except OSError:
        pass


def _load_or_create_master_key():
    ensure_secret_dir()
    if GEMINI_MASTER_KEY_PATH.exists():
        return GEMINI_MASTER_KEY_PATH.read_bytes().strip()

    master_key = Fernet.generate_key()
    GEMINI_MASTER_KEY_PATH.write_bytes(master_key)
    try:
        os.chmod(GEMINI_MASTER_KEY_PATH, 0o600)
    except OSError:
        pass
    return master_key


def get_fernet():
    return Fernet(_load_or_create_master_key())


def load_gemini_api_key():
    if not GEMINI_VAULT_PATH.exists():
        return ""
    try:
        token = GEMINI_VAULT_PATH.read_bytes()
        return get_fernet().decrypt(token).decode("utf-8").strip()
    except (OSError, InvalidToken, ValueError):
        return ""


def save_gemini_api_key(api_key: str):
    api_key = (api_key or "").strip()
    if not api_key:
        raise ValueError("La cle API est vide.")
    ensure_secret_dir()
    token = get_fernet().encrypt(api_key.encode("utf-8"))
    GEMINI_VAULT_PATH.write_bytes(token)
    try:
        os.chmod(GEMINI_VAULT_PATH, 0o600)
    except OSError:
        pass


def delete_gemini_api_key():
    if GEMINI_VAULT_PATH.exists():
        GEMINI_VAULT_PATH.unlink()


def gemini_api_key_exists():
    return GEMINI_VAULT_PATH.exists()