"""Source files: bounded capture, checksums, validation, and safe resolution."""

import hashlib
import os
from pathlib import Path

from PIL import Image

from .errors import NimbusError
from .util import identifier


class MediaStore:
    def __init__(self, directory: Path, max_bytes: int, max_pixels: int):
        self.directory = Path(directory).resolve()
        self.max_bytes = max_bytes
        self.max_pixels = max_pixels

    def save(self, payload: bytes, source_type: str, content_type: str):
        content_type = content_type.split(";", 1)[0].strip().lower()
        if not payload or len(payload) > self.max_bytes:
            raise NimbusError("upload_limit_exceeded", "Empty or oversized source file.", 413)
        if source_type == "handwriting":
            from io import BytesIO

            try:
                with Image.open(BytesIO(payload)) as image:
                    if (
                        image.format not in {"PNG", "JPEG", "WEBP"}
                        or image.width * image.height > self.max_pixels
                    ):
                        raise NimbusError(
                            "unsupported_image", "Use a bounded PNG, JPEG, or WebP image.", 415
                        )
                    image.verify()
            except (OSError, Image.DecompressionBombError) as error:
                raise NimbusError(
                    "invalid_image", "The source is not a valid supported image.", 415
                ) from error
        elif source_type == "audio":
            if content_type not in {
                "audio/webm",
                "audio/ogg",
                "audio/wav",
                "audio/x-wav",
                "audio/mpeg",
                "audio/mp4",
                "video/webm",
            }:
                raise NimbusError("unsupported_audio", "Unsupported audio container.", 415)
        else:
            raise NimbusError("invalid_source", "Files must be audio or handwriting.")
        self.directory.mkdir(parents=True, exist_ok=True)
        key = identifier("media")
        temporary = self.directory / f"{key}.upload"
        target = self.directory / key
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)
        return {
            "media_key": key,
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "content_type": content_type,
        }

    def resolve(self, key):
        path = (self.directory / key).resolve()
        if path.parent != self.directory or not path.is_file():
            raise NimbusError("media_not_found", "Source file not found.", 404)
        return path
