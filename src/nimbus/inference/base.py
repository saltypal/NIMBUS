from typing import Protocol


class Adapter(Protocol):
    model_id: str
    model_revision: str

    def run(self, payload: dict, media_path=None) -> dict: ...
    def smoke(self) -> dict: ...


def pinned_revision(model_id, capability, revision=None):
    from huggingface_hub import HfApi

    from ..models import resolve_model

    spec = resolve_model(model_id, capability)
    # Registry defaults are immutable SHAs. An explicitly selected branch/tag
    # is resolved once and the resulting SHA is recorded for every download.
    return HfApi().model_info(model_id, revision=revision or spec.revision).sha
