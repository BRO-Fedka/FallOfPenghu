from __future__ import annotations

from dataclasses import dataclass


def _rgb(c: tuple[int, int, int]) -> tuple[float, float, float]:
    return (c[0] / 255.0, c[1] / 255.0, c[2] / 255.0)


def _shift_rgb(
    color: tuple[int, int, int],
    noon: tuple[int, int, int],
    now: tuple[int, int, int],
) -> tuple[int, int, int]:
    out: list[int] = []
    for c, n, m in zip(color, noon, now, strict=True):
        if n <= 0:
            out.append(m)
        else:
            out.append(int(max(0, min(255, round(c * (m / n))))))
    return out[0], out[1], out[2]


@dataclass
class WaterParams:
    """Stylized coastal water. Tweak these; uniforms are pushed every frame.

    Distances are world meters. mesh_width_m and band_landward_m size the
    seaward band VBO and need a restart. Everything else is live on
    `renderer.water`.
    """

    water_deep_color: tuple[int, int, int] = (20, 145, 175)
    water_mid_color: tuple[int, int, int] = (30, 180, 195)
    water_shallow_color: tuple[int, int, int] = (90, 215, 215)
    ripple_cyan: tuple[int, int, int] = (120, 235, 235)
    ripple_light: tuple[int, int, int] = (180, 245, 240)
    ripple_white: tuple[int, int, int] = (225, 255, 250)

    # Geometry budget of the seaward band. Keep near foam_max so facing
    # piers (~20 m) do not overlay two bands in the channel.
    mesh_width_m: float = 10.0
    shore_width: float = 9.0
    band_shallow_width: float = 9.0

    # Coarse fullscreen SDF color ramp (meters).
    shallow_width: float = 420.0
    deep_start: float = 900.0
    deep_end: float = 10000.0

    # Master gain vs a full illustration look. Spec: ~20–35% of the reference.
    intensity: float = 0.28

    warp_scale: float = 0.07
    warp_strength: float = 0.55
    detail_scale: float = 0.18
    detail_strength: float = 0.22

    ripple_frequency: float = 0.10
    ripple_width: float = 0.11
    ripple_speed: float = 0.08
    ripple_opacity: float = 0.50
    ripple_mask_low: float = 0.30
    ripple_mask_high: float = 0.64

    ripple_b_frequency: float = 0.185
    ripple_b_width: float = 0.045
    ripple_b_speed: float = 0.05
    ripple_b_opacity: float = 0.42
    ripple_b_mask_low: float = 0.42
    ripple_b_mask_high: float = 0.72
    ripple_b_phase: float = 0.37

    highlight_frequency: float = 0.31
    highlight_width: float = 0.018
    highlight_speed: float = 0.11
    highlight_opacity: float = 0.22
    highlight_mask_low: float = 0.62
    highlight_mask_high: float = 0.88
    highlight_phase: float = 0.61

    mask_scale: float = 0.055
    # How fast the foam silhouette morphs (Hz-ish). 0 = frozen pattern.
    foam_evolve: float = 0.22
    foam_drift: float = 0.12

    # Fade ripples when a 36 m band is only a couple of pixels.
    ripple_fade_view_m: float = 14000.0
    ripple_gone_view_m: float = 32000.0

    # Hairline onto land so the join does not show a water gap. Foam 2–5 m seaward.
    band_landward_m: float = 0.35
    foam_min_m: float = 1.0
    foam_max_m: float = 7.0
    foam_pulse_hz: float = 0.28
    foam_width_noise: float = 0.45
    foam_noise_scale: float = 0.08

    def bind(self, set_uniform, prog, pal: dict[str, tuple[int, int, int]] | None = None) -> None:
        if pal is None:
            deep = self.water_deep_color
            mid = self.water_mid_color
            shallow = self.water_shallow_color
            ripple_cyan = self.ripple_cyan
            ripple_light = self.ripple_light
            ripple_white = self.ripple_white
        else:
            deep = pal["sea_deep"]
            mid = pal["sea"]
            shallow = pal["sea_shallow"]
            ripple_cyan = _shift_rgb(self.ripple_cyan, self.water_mid_color, mid)
            ripple_light = _shift_rgb(self.ripple_light, self.water_mid_color, mid)
            ripple_white = _shift_rgb(self.ripple_white, self.water_mid_color, mid)
        set_uniform(prog, "u_water_deep", _rgb(deep))
        set_uniform(prog, "u_water_mid", _rgb(mid))
        set_uniform(prog, "u_water_shallow", _rgb(shallow))
        set_uniform(prog, "u_ripple_cyan", _rgb(ripple_cyan))
        set_uniform(prog, "u_ripple_light", _rgb(ripple_light))
        set_uniform(prog, "u_ripple_white", _rgb(ripple_white))
        set_uniform(prog, "u_mesh_width", float(self.mesh_width_m))
        set_uniform(prog, "u_shore_width", float(self.shore_width))
        set_uniform(prog, "u_band_shallow_width", float(self.band_shallow_width))
        set_uniform(prog, "u_shallow_width", float(self.shallow_width))
        set_uniform(prog, "u_deep_start", float(self.deep_start))
        set_uniform(prog, "u_deep_end", float(self.deep_end))
        set_uniform(prog, "u_intensity", float(self.intensity))
        set_uniform(prog, "u_warp_scale", float(self.warp_scale))
        set_uniform(prog, "u_warp_strength", float(self.warp_strength))
        set_uniform(prog, "u_detail_scale", float(self.detail_scale))
        set_uniform(prog, "u_detail_strength", float(self.detail_strength))
        set_uniform(prog, "u_ripple_frequency", float(self.ripple_frequency))
        set_uniform(prog, "u_ripple_width", float(self.ripple_width))
        set_uniform(prog, "u_ripple_speed", float(self.ripple_speed))
        set_uniform(prog, "u_ripple_opacity", float(self.ripple_opacity))
        set_uniform(prog, "u_ripple_mask_low", float(self.ripple_mask_low))
        set_uniform(prog, "u_ripple_mask_high", float(self.ripple_mask_high))
        set_uniform(prog, "u_ripple_b_frequency", float(self.ripple_b_frequency))
        set_uniform(prog, "u_ripple_b_width", float(self.ripple_b_width))
        set_uniform(prog, "u_ripple_b_speed", float(self.ripple_b_speed))
        set_uniform(prog, "u_ripple_b_opacity", float(self.ripple_b_opacity))
        set_uniform(prog, "u_ripple_b_mask_low", float(self.ripple_b_mask_low))
        set_uniform(prog, "u_ripple_b_mask_high", float(self.ripple_b_mask_high))
        set_uniform(prog, "u_ripple_b_phase", float(self.ripple_b_phase))
        set_uniform(prog, "u_highlight_frequency", float(self.highlight_frequency))
        set_uniform(prog, "u_highlight_width", float(self.highlight_width))
        set_uniform(prog, "u_highlight_speed", float(self.highlight_speed))
        set_uniform(prog, "u_highlight_opacity", float(self.highlight_opacity))
        set_uniform(prog, "u_highlight_mask_low", float(self.highlight_mask_low))
        set_uniform(prog, "u_highlight_mask_high", float(self.highlight_mask_high))
        set_uniform(prog, "u_highlight_phase", float(self.highlight_phase))
        set_uniform(prog, "u_mask_scale", float(self.mask_scale))
        set_uniform(prog, "u_foam_evolve", float(self.foam_evolve))
        set_uniform(prog, "u_foam_drift", float(self.foam_drift))
        set_uniform(prog, "u_ripple_fade_view", float(self.ripple_fade_view_m))
        set_uniform(prog, "u_ripple_gone_view", float(self.ripple_gone_view_m))
        set_uniform(prog, "u_landward", float(self.band_landward_m))
        set_uniform(prog, "u_foam_min", float(self.foam_min_m))
        set_uniform(prog, "u_foam_max", float(self.foam_max_m))
        set_uniform(prog, "u_foam_hz", float(self.foam_pulse_hz))
        set_uniform(prog, "u_foam_width_noise", float(self.foam_width_noise))
        set_uniform(prog, "u_foam_noise_scale", float(self.foam_noise_scale))
