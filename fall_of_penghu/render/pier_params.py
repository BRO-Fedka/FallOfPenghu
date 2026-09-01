from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PierParams:
    """Pier detector. Edit here and restart.

    Cheap pass: convex noses — right angles, acute tips, blunt ends —
    plus a left/right pair of parallel edges (parallel_deg). The two
    edges may sit a different number of hops from the vertex.
    Heavy pass: walk both coasts inland, allowing the pier to bend,
    while local width stays <= max_width_m.
    Then grow each seed by buffering into land. A growth front stops
    when its land contact is grow_widths times the seed width, capped
    at max_width_m so a wide seed cannot flood the island. Forks are
    followed as separate paths.
    stamp_pad_m fattens the shape on the urban texture so a pier
    thinner than a texel still paints concrete.
    """

    min_island_m2: float = 400 * 400
    parallel_deg: float = 5.0
    right_angle_min_deg: float = 84.0
    right_angle_max_deg: float = 96.0
    acute_edge_m: float = 16.0
    min_width_m: float = 1.0
    max_width_m: float = 70.0
    min_length_m: float = 5.0
    max_length_m: float = 400.0
    merge_gap_m: float = 16.0
    grow_widths: float = 10.0
    stamp_pad_m: float = 8.0
    stamp_value: float = 1100.0
