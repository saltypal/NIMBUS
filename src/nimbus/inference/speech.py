"""Whisper transcription; no summarization or ticket decisions occur here."""

from pathlib import Path

import numpy as np

from ..errors import NimbusError
from ..models import MODELS
from .base import pinned_revision


class SpeechAdapter:
    def __init__(
        self, model_id=None, revision=None, device="cuda", device_index=0, max_seconds=180
    ):
        from faster_whisper import WhisperModel
        from huggingface_hub import snapshot_download

        self.model_id = model_id or MODELS["speech"].model_id
        self.model_revision = pinned_revision(self.model_id, "speech", revision)
        snapshot = snapshot_download(self.model_id, revision=self.model_revision)
        self.model = WhisperModel(
            snapshot,
            device=device,
            device_index=device_index,
            compute_type="float16" if device == "cuda" else "int8",
        )
        self.max_seconds = max_seconds

    def run(self, payload, media_path=None):
        if media_path is None:
            raise NimbusError("audio_path_required", "Provide a local audio source.")
        # Container duration is an early guard. The decoded sample count is the
        # final guard because some containers omit or misreport their duration.
        import av

        samples = []
        sample_count = 0
        with av.open(str(Path(media_path))) as container:
            if container.duration and container.duration / av.time_base > self.max_seconds:
                raise NimbusError(
                    "audio_duration_exceeded", "Voice notes must be at most 180 seconds."
                )
            resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)

            def add_frames(frames):
                nonlocal sample_count
                for frame in frames:
                    decoded = frame.to_ndarray().reshape(-1)
                    sample_count += len(decoded)
                    if sample_count > self.max_seconds * 16000:
                        raise NimbusError(
                            "audio_duration_exceeded", "Voice notes must be at most 180 seconds."
                        )
                    samples.append(decoded.astype(np.float32) / 32768.0)

            for frame in container.decode(audio=0):
                add_frames(resampler.resample(frame))
            add_frames(resampler.resample(None))
        audio = np.concatenate(samples) if samples else np.zeros(0, dtype=np.float32)
        if not len(audio):
            raise NimbusError("empty_audio", "The uploaded source contains no decoded audio.")
        segments, _ = self.model.transcribe(
            audio,
            beam_size=3,
            vad_filter=True,
            condition_on_previous_text=False,
            language=payload.get("language"),
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return {"text": text, "model_id": self.model_id, "model_revision": self.model_revision}

    def smoke(self):
        # This checks execution only, not speech recognition quality. An actual
        # noisy-factory recording still has to be evaluated separately.
        segments, _ = self.model.transcribe(
            np.zeros(16000, dtype=np.float32), beam_size=1, vad_filter=True
        )
        list(segments)
        return {"ok": True, "kind": "silence_execution_only"}
