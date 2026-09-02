from __future__ import annotations

from dataclasses import dataclass

from fall_of_penghu.render.static.scene import BUILDINGS_FADE_FULL_M, BUILDINGS_FADE_GONE_M

# True: fill far away, crowns/grass up close (current look). LOD distances unchanged.
# False: forest and grass are always the palette fill; no tree_blobs / tree_disk.
VEG_DETAIL_CROWNS = True


@dataclass
class VegParams:
    """Stylized vegetation. Uniforms are pushed every frame.

    r_* are canopy *widths* (diameters) in meters. The shader tests
    distance < width/2. Frequency is the keep-threshold scale after the
    density gradient at the tree center. Crown LOD matches buildings.
    """

    lod_near_m: float = BUILDINGS_FADE_FULL_M
    lod_far_m: float = BUILDINGS_FADE_GONE_M
    mix_max_m: float = 25.0
    mix_noise_m: float = 10.0
    mix_noise_amp: float = 1.0
    forest_spacing_m: float = 9.0
    grass_spacing_m: float = 24.0
    forest_freq: float = 0.84
    grass_freq: float = 0.09
    r_core_min: float = 5.5
    r_core_max: float = 10.0
    r_edge_min: float = 3.0
    r_edge_max: float = 7.5
    tree_margin_m: float = 5.0
    band_width_m: float = 40.0

    def bind(self, set_uniform, prog) -> None:
        set_uniform(prog, "u_lod_near", float(self.lod_near_m))
        set_uniform(prog, "u_lod_far", float(self.lod_far_m))
        set_uniform(prog, "u_mix_max", float(self.mix_max_m))
        set_uniform(prog, "u_mix_noise_scale", 1.0 / max(self.mix_noise_m, 1e-6))
        set_uniform(prog, "u_mix_noise_amp", float(self.mix_noise_amp))
        set_uniform(prog, "u_r_core_min", float(self.r_core_min))
        set_uniform(prog, "u_r_core_max", float(self.r_core_max))
        set_uniform(prog, "u_r_edge_min", float(self.r_edge_min))
        set_uniform(prog, "u_r_edge_max", float(self.r_edge_max))
        set_uniform(prog, "u_tree_margin", float(self.tree_margin_m))
        set_uniform(prog, "u_band_width", float(self.band_width_m))
