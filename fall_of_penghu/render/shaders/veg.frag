#version 330 core
#include "common.glsl"

uniform vec4 u_view;
uniform vec4 u_sea_frame;
uniform sampler2D u_sea;
uniform float u_sea_max;
uniform float u_sea_tex;
uniform vec4 u_veg_frame;
uniform sampler2D u_vegf;
uniform vec2 u_veg_tex;
uniform float u_veg_max;
uniform float u_view_width;
uniform int u_kind;
uniform int u_radar;
uniform int u_debug;
uniform vec3 u_fill;
uniform vec3 u_soil;
uniform vec3 u_canopy;
uniform vec3 u_land;
uniform float u_lod_near;
uniform float u_lod_far;
uniform float u_mix_min;
uniform float u_mix_max;
uniform float u_tree_spacing;
uniform float u_tree_freq;
uniform float u_r_core_min;
uniform float u_r_core_max;
uniform float u_r_edge_min;
uniform float u_r_edge_max;
uniform float u_tree_margin;
uniform float u_sea_clip;
uniform float u_band_width;
in vec2 v_world;
in float v_t;
in vec2 v_n;
in float v_band;
out vec4 f_color;

vec2 texel_uv(vec2 world, vec4 frame, vec2 ntex) {
    vec2 span = max(frame.zw - frame.xy, vec2(1.0));
    vec2 n = max(ntex, vec2(2.0));
    vec2 uv = (world - frame.xy) / span;
    return uv * ((n - 1.0) / n) + (0.5 / n);
}

vec4 sample_veg(vec2 world) {
    vec2 span = max(u_veg_frame.zw - u_veg_frame.xy, vec2(1.0));
    vec2 uv = (world - u_veg_frame.xy) / span;
    return texture(u_vegf, clamp(uv, 0.0, 1.0));
}

float own_field(vec2 pos) {
    vec4 vf = sample_veg(pos);
    float nrm = (u_kind == 1) ? vf.r : vf.g;
    return nrm * u_band_width;
}

float density_grad_at(float field) {
    float margin = max(u_tree_margin, 0.5);
    float span = max(u_mix_max - margin, 1.0);
    return clamp((field - margin) / span, 0.0, 1.0);
}

bool keep_tree(vec2 pos, inout float edge_t) {
    float field = own_field(pos);
    float margin = max(u_tree_margin, 0.5);
    if (field < margin) {
        edge_t = 0.0;
        return false;
    }
    edge_t = density_grad_at(field);
    return true;
}

vec3 tree_tint(ivec3 id, vec3 base) {
    float lum = mix(0.86, 1.14, hash_i3(ivec3(id.xy, id.z + 110)));
    float red = hash_i3(ivec3(id.xy, id.z + 111));
    float yel = hash_i3(ivec3(id.xy, id.z + 112));
    vec3 col = base * lum;
    col += vec3(0.055, -0.02, -0.03) * (red * 2.0 - 1.0);
    col += vec3(0.04, 0.045, -0.035) * (yel * 2.0 - 1.0);
    return clamp(col, 0.0, 1.0);
}

int cell_candidates(ivec2 c, float spacing) {
    vec2 wp = (vec2(c) + 0.5) * spacing;
    float n = valfbm(wp * 0.008);
    if (u_kind == 1) {
        return int(min(floor(n * 5.999), 5.0));
    }
    return int(min(floor(n * 2.0), 1.0));
}

vec3 tree_blobs(vec2 p, out float coverage) {
    float spacing = max(u_tree_spacing, 2.0);
    float r_search = 0.5 * u_r_core_max;
    ivec2 c0 = ivec2(floor((p - vec2(r_search)) / spacing));
    ivec2 c1 = ivec2(floor((p + vec2(r_search)) / spacing));
    coverage = 0.0;
    vec3 col = u_canopy;

    for (int j = 0; j < 3; j++) {
        for (int i = 0; i < 3; i++) {
            ivec2 c = c0 + ivec2(i, j);
            if (c.x > c1.x || c.y > c1.y) {
                continue;
            }
            int nk = cell_candidates(c, spacing);
            if (nk <= 0) {
                continue;
            }
            for (int t = 0; t < 5; t++) {
                if (t >= nk) {
                    continue;
                }
                float hx = hash_i3(ivec3(c, t * 2 + 3));
                float hy = hash_i3(ivec3(c, t * 2 + 4));
                vec2 pos = (vec2(c) + 0.12 + vec2(hx, hy) * 0.76) * spacing;
                float d = length(p - pos);
                if (d >= r_search) {
                    continue;
                }
                float edge_t = 1.0;
                if (!keep_tree(pos, edge_t)) {
                    continue;
                }
                float hr = hash_i3(ivec3(c, t + 40));
                float w_edge = mix(u_r_edge_min, u_r_edge_max, hr);
                float w_core = mix(u_r_core_min, u_r_core_max, hr);
                float radius = 0.5 * mix(w_edge, w_core, edge_t);
                float chance = clamp(u_tree_freq * edge_t, 0.0, 1.0);
                if (hash_i3(ivec3(c, t + 70)) >= chance) {
                    continue;
                }
                if (d >= radius) {
                    continue;
                }
                float cov = 1.0 - smoothstep(radius * 0.52, radius, d);
                if (cov > coverage) {
                    coverage = cov;
                    col = tree_tint(ivec3(c, t + 80), u_canopy);
                }
            }
        }
    }
    return col;
}

void main() {
    vec2 sea_uv = texel_uv(v_world, u_sea_frame, vec2(u_sea_tex));
    float sea_d = texture(u_sea, clamp(sea_uv, 0.0, 1.0)).r * u_sea_max;
    if (sea_d > u_sea_clip) {
        discard;
    }

    vec3 soil = u_soil;
    float fill_a = 1.0;
    if (u_radar == 0) {
        float span = max(u_lod_far - u_lod_near, 1.0);
        float t = clamp((u_view_width - u_lod_near) / span, 0.0, 1.0);
        fill_a = t * t * (3.0 - 2.0 * t);
    }
    if (u_debug == 0 && fill_a > 0.997) {
        f_color = vec4(u_fill, 1.0);
        return;
    }

    float trees = 0.0;
    vec3 canopy = u_canopy;
    if (u_debug == 1 || fill_a < 0.997) {
        canopy = tree_blobs(v_world, trees);
    }

    if (u_debug == 1) {
        float field = own_field(v_world);
        float margin = max(u_tree_margin, 0.5);
        vec3 col;
        if (field < margin) {
            col = mix(soil, vec3(1.0, 0.92, 0.15), 0.88);
        } else {
            float g = density_grad_at(field);
            col = mix(soil, vec3(0.92, 0.12, 0.08), g);
        }
        col = mix(col, canopy, clamp(trees, 0.0, 1.0));
        f_color = vec4(col, 1.0);
        return;
    }

    vec3 close = mix(soil, canopy, clamp(trees, 0.0, 1.0));
    f_color = vec4(mix(close, u_fill, fill_a), 1.0);
}
