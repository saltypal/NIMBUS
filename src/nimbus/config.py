"""Configuration has no database, network, or model-loading side effects."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NIMBUS_", env_file=ROOT / ".env", extra="ignore")

    storage_backend: str = "mongo"
    mongo_uri: str = "mongodb://127.0.0.1:27017"
    database: str = "nimbus"
    data_dir: Path = ROOT / ".data"
    knowledge_dir: Path = ROOT / "knowledge"
    demo_mode: bool = True
    inference_enabled: bool = False
    retrieval_backend: str = "lexical"
    embedding_revision: str | None = None
    bridge_speech_key: str = ""
    bridge_handwriting_key: str = ""
    bridge_llm_key: str = ""
    job_lease_seconds: int = 60
    job_max_attempts: int = 3
    job_max_runtime_seconds: int = 600
    max_upload_bytes: int = 20 * 1024 * 1024
    max_image_pixels: int = 20_000_000
    max_text_characters: int = 20_000
    ticket_size_guard_bytes: int = 8 * 1024 * 1024

    def worker_keys(self) -> dict[str, str]:
        return {
            "speech": self.bridge_speech_key,
            "handwriting": self.bridge_handwriting_key,
            "llm": self.bridge_llm_key,
        }
