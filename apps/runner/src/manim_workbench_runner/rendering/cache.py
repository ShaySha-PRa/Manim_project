from __future__ import annotations

import hashlib
import json

from .models import (
    MANIM_IMAGE_DIGEST,
    MANIM_VERSION,
    PROFILE_CONFIGS,
    RENDER_CONTRACT_VERSION,
    RenderRequest,
)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def build_cache_key(request: RenderRequest, *, source_bytes: bytes) -> str:
    profile = PROFILE_CONFIGS[request.profile]
    payload = {
        "contract_version": RENDER_CONTRACT_VERSION,
        "engine": "manimce",
        "engine_version": MANIM_VERSION,
        "image_digest": MANIM_IMAGE_DIGEST,
        "profile": {
            "name": profile.name.value,
            "quality": profile.quality,
            "width": profile.width,
            "height": profile.height,
            "frame_rate": profile.frame_rate,
            "timeout_seconds": profile.timeout_seconds,
            "renderer": profile.renderer,
            "seed": profile.seed,
        },
        "scene_class": request.scene_class,
        "scene_id": request.scene_id,
        "source_sha256": sha256_bytes(source_bytes),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(canonical)
