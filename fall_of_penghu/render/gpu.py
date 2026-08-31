from __future__ import annotations

from dataclasses import dataclass

SOFTWARE_MARKERS = (
    "gdi generic",
    "microsoft basic render",
    "swiftshader",
    "llvmpipe",
    "softpipe",
    "software rasterizer",
    "mesa software",
    "d3d12warp",
)

MIN_GL_MAJOR = 3
MIN_GL_MINOR = 3
MIN_TEXTURE_SIZE = 2048


@dataclass(frozen=True)
class GpuInfo:
    backend: str
    usable: bool
    version: str = ""
    renderer: str = ""
    vendor: str = ""
    max_texture: int = 0
    reason: str = ""

    @property
    def label(self) -> str:
        if self.backend == "gl" and self.usable:
            short = self.renderer.strip() or "GPU"
            return f"GL {self.version} / {short}"
        return f"CPU / {self.reason or 'software'}"


def software_info(reason: str) -> GpuInfo:
    return GpuInfo(backend="software", usable=False, reason=reason)


def assess_gl(
    *,
    version: str,
    renderer: str,
    vendor: str,
    max_texture: int,
) -> GpuInfo:
    blob = f"{renderer} {vendor} {version}".lower()
    for marker in SOFTWARE_MARKERS:
        if marker in blob:
            return GpuInfo(
                backend="gl",
                usable=False,
                version=version,
                renderer=renderer,
                vendor=vendor,
                max_texture=max_texture,
                reason=f"software adapter ({renderer or vendor})",
            )
    if max_texture and max_texture < MIN_TEXTURE_SIZE:
        return GpuInfo(
            backend="gl",
            usable=False,
            version=version,
            renderer=renderer,
            vendor=vendor,
            max_texture=max_texture,
            reason=f"max texture {max_texture} < {MIN_TEXTURE_SIZE}",
        )
    return GpuInfo(
        backend="gl",
        usable=True,
        version=version,
        renderer=renderer,
        vendor=vendor,
        max_texture=max_texture,
        reason="ok",
    )
