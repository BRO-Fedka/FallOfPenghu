from __future__ import annotations

from dataclasses import dataclass

# 0 gaussian  1 inv_sq  2 linear cone
KERNEL_GAUSS = 0
KERNEL_INV_SQ = 1
KERNEL_LINEAR = 2
KERNEL_NAMES = ("gauss", "inv_sq", "linear")


@dataclass
class UrbanParams:
    """Building density — locked. Edit here and restart.

    Field at a point is the SUM of every house kernel. Clustered houses
    add up, so the same blue level sits farther from a town than from
    scattered farms.

    kernel: 0 gauss exp(-0.5 (d/sigma)^2)
            1 inv_sq  peak / (1 + (d/sigma)^2)   — long tails
            2 linear  peak * max(0, 1 - d/sigma) — hard cutoff
    sigma_m: meters to the 'body' of one house (gauss: ~60% of peak)
    peak:    value a house of size_ref_m adds at its center
    size_ref_m: house contribution = peak * 0.5 * (bw² + bh²) / size_ref_m
    splat_sigmas: outward miter-buffer of the footprint, in units of sigma
                 (iso-lines follow buffer(house, sigma * splat_sigmas, miter))
    gain:    display multiplier; blue = clamp(field * gain)
    gamma:   display curve; >1 compresses the core, <1 lifts the halo
    overlay_alpha: max opacity of the debug blue
    threshold: land becomes concrete where the raw urban field is above this

    Concrete/land edge (same idea as grass mix). Signed fBm is added to
    (urban - threshold); noise is symmetric about 0. Tune:
      edge_octave_m     — world-meters of octave 1; octave i is half as wide
      edge_octaves      — how many octaves (1..8)
      edge_noise_weight — max displacement of the isosurface, in field units
    Octave amplitude is urban_octave_weight(i) in common.glsl (now 1/i²).
    """

    kernel: int = KERNEL_GAUSS
    sigma_m: float = 120.0
    peak: float = 1.0
    size_ref_m: float = 10.0
    splat_sigmas: float = 10.0
    gain: float = 0.0005
    gamma: float = 3.0
    overlay_alpha: float = 0.82
    threshold: float = 750.0
    edge_octave_m: float = 40.0
    edge_octaves: int = 3
    edge_noise_weight: float = 80.0

    def bind(self, set_uniform, prog) -> None:
        set_uniform(prog, "u_urban_gain", float(self.gain))
        set_uniform(prog, "u_urban_sigma", float(self.sigma_m))
        set_uniform(prog, "u_urban_kernel", int(self.kernel))
        set_uniform(prog, "u_urban_gamma", float(self.gamma))
        set_uniform(prog, "u_urban_alpha", float(self.overlay_alpha))
        set_uniform(prog, "u_urban_threshold", float(self.threshold))
        set_uniform(prog, "u_urban_noise_scale", 1.0 / max(self.edge_octave_m, 1e-6))
        set_uniform(prog, "u_urban_octaves", int(self.edge_octaves))
        set_uniform(prog, "u_urban_noise_weight", float(self.edge_noise_weight))

    def label(self) -> str:
        return f"th {self.threshold:.0f}"


@dataclass
class RoadParams:
    """Road density — locked. Does not paint concrete.

    Effective density = raw_field * gain (same value the green overlay shows
    before gamma). Each house:
        house_peak *= (1 + influence * density)
    """

    kernel: int = KERNEL_GAUSS
    sigma_m: float = 21.0
    peak: float = 1.0
    width_ref_m: float = 6.0
    splat_sigmas: float = 3.0
    step_m: float = 18.0
    gain: float = 0.581
    gamma: float = 0.15
    overlay_alpha: float = 0.75
    influence: float = 1.0

    def bind(self, set_uniform, prog) -> None:
        set_uniform(prog, "u_urban_gain", float(self.gain))
        set_uniform(prog, "u_urban_sigma", float(self.sigma_m))
        set_uniform(prog, "u_urban_kernel", int(self.kernel))
        set_uniform(prog, "u_urban_gamma", float(self.gamma))
        set_uniform(prog, "u_urban_alpha", float(self.overlay_alpha))

    def label(self) -> str:
        name = KERNEL_NAMES[self.kernel] if 0 <= self.kernel < 3 else str(self.kernel)
        return (
            f"road {name} s{self.sigma_m:.0f} g{self.gain:.3f} "
            f"γ{self.gamma:.2f} inf{self.influence:.4f}"
        )
