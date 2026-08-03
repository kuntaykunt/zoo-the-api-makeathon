import os
import json
import base64
from dotenv import load_dotenv
from cryptography.fernet import Fernet

# Directory where the encrypted key file lives (gitignored).
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY_FILE = os.path.join(BASE_DIR, ".key")
ENC_ENV = os.path.join(BASE_DIR, ".env.enc")

# Plaintext .env is still supported (gitignored) for convenience.
load_dotenv()

# --- Encrypted key storage ------------------------------------------------- #
# Keys are stored in .env.enc (Fernet token) and decrypted with .key at runtime.
# Falls back to plaintext environment variables / .env if .env.enc is absent.


def _load_key() -> bytes:
    """Return the Fernet key, creating one on first run."""
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read().strip()
    key = Fernet.generate_key()
    with open(KEY_FILE, "wb") as f:
        f.write(key)
    # Tighten permissions so only the owner can read the secret key.
    try:
        os.chmod(KEY_FILE, 0o600)
    except OSError:
        pass
    return key


def _decrypt_env() -> dict:
    """Decrypt .env.enc into a dict of settings, or return {} if unavailable."""
    if not os.path.exists(ENC_ENV):
        return {}
    try:
        fernet = Fernet(_load_key())
        with open(ENC_ENV, "rb") as f:
            token = f.read()
        plain = fernet.decrypt(token)
        data = {}
        for line in plain.decode("utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
        return data
    except Exception as e:
        print(f"[Config] could not decrypt .env.enc: {e}")
        return {}


def _encrypt_env(values: dict) -> None:
    """Encrypt a dict of settings into .env.enc using the Fernet key."""
    fernet = Fernet(_load_key())
    lines = "\n".join(f"{k}={v}" for k, v in values.items())
    token = fernet.encrypt(lines.encode("utf-8"))
    with open(ENC_ENV, "wb") as f:
        f.write(token)
    try:
        os.chmod(ENC_ENV, 0o600)
    except OSError:
        pass


# Encrypted overrides take precedence over plaintext env/.env.
_enc = _decrypt_env()


class Config:
    QWEN_API_KEY = _enc.get("QWEN_API_KEY") or os.getenv("QWEN_API_KEY", "")
    QWEN_BASE_URL = _enc.get("QWEN_BASE_URL") or os.getenv("QWEN_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
    QWEN_MODEL = _enc.get("QWEN_MODEL") or os.getenv("QWEN_MODEL", "qwen-vl-max")

    ZOO_API_KEY = _enc.get("ZOO_API_KEY") or os.getenv("ZOO_API_KEY", "")
    ZOO_BASE_URL = _enc.get("ZOO_BASE_URL") or os.getenv("ZOO_BASE_URL", "https://api.zoo.dev")

    PORT = int(os.getenv("PORT", 8000))
    HOST = os.getenv("HOST", "0.0.0.0")

    @staticmethod
    def has_qwen() -> bool:
        return bool(Config.QWEN_API_KEY) and not Config.QWEN_API_KEY.startswith("your_")

    @staticmethod
    def has_zoo() -> bool:
        return bool(Config.ZOO_API_KEY) and not Config.ZOO_API_KEY.startswith("your_")

    @staticmethod
    def save_keys(qwen_api_key: str, zoo_api_key: str,
                  qwen_base_url: str = "", zoo_base_url: str = "") -> None:
        """Persist keys (encrypted) and reload the in-memory config."""
        values = {
            "QWEN_API_KEY": qwen_api_key,
            "ZOO_API_KEY": zoo_api_key,
        }
        if qwen_base_url:
            values["QWEN_BASE_URL"] = qwen_base_url
        if zoo_base_url:
            values["ZOO_BASE_URL"] = zoo_base_url
        _encrypt_env(values)
        enc = _decrypt_env()
        Config.QWEN_API_KEY = enc.get("QWEN_API_KEY", Config.QWEN_API_KEY)
        Config.ZOO_API_KEY = enc.get("ZOO_API_KEY", Config.ZOO_API_KEY)
        if qwen_base_url:
            Config.QWEN_BASE_URL = enc.get("QWEN_BASE_URL", Config.QWEN_BASE_URL)
        if zoo_base_url:
            Config.ZOO_BASE_URL = enc.get("ZOO_BASE_URL", Config.ZOO_BASE_URL)

    @staticmethod
    def masked(key: str) -> str:
        """Return a masked preview of a key for safe display."""
        if not key:
            return ""
        if len(key) <= 8:
            return "•" * len(key)
        return key[:4] + "•" * (len(key) - 8) + key[-4:]


config = Config()
