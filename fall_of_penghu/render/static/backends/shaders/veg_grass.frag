#version 330 core
#include "common.glsl"

uniform vec4 u_veg_frame;
uniform sampler2D u_vegf;
uniform sampler2D u_veg_mix;
uniform float u_view_width;
uniform int u_debug;
uniform vec3 u_fill;
uniform vec3 u_soil;
uniform vec3 u_canopy;
uniform float u_lod_near;
uniform float u_lod_far;
uniform float u_mix_max;
uniform float u_mix_noise_scale;
uniform float u_mix_noise_amp;
uniform float u_tree_spacing;
uniform float u_tree_freq;
uniform float u_r_core_min;
uniform float u_r_core_max;
uniform float u_r_edge_min;
uniform float u_r_edge_max;
uniform float u_tree_margin;
uniform float u_band_width;
in vec2 v_world;
out vec4 f_color;

float veg_uv_sample(sampler2D tex, vec2 pos) {
    vec2 span = max(u_veg_frame.zw - u_veg_frame.xy, vec2(1.0));
    vec2 uv = clamp((pos - u_veg_frame.xy) / span, 0.0, 1.0);
    return texture(tex, uv).r;
}

float own_field(vec2 pos) {
    vec2 span = max(u_veg_frame.zw - u_veg_frame.xy, vec2(1.0));
    vec2 uv = clamp((pos - u_veg_frame.xy) / span, 0.0, 1.0);
    return texture(u_vegf, uv).g * u_band_width;
}

float mix_field(vec2 pos) {
    return veg_uv_sample(u_veg_mix, pos) * u_band_width;
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

vec3 tree_disk(vec2 p, out float coverage) {
    float spacing = max(u_tree_spacing, 8.0);
    float r_search = 0.5 * u_r_core_max;
    ivec2 c0 = ivec2(floor((p - vec2(r_search)) / spacing));
    coverage = 0.0;
    vec3 col = u_canopy;
    float margin = max(u_tree_margin, 0.5);
    float mix_span = max(u_mix_max - margin, 1.0);

    for (int j = 0; j < 2; j++) {
        for (int i = 0; i < 2; i++) {
            ivec2 c = c0 + ivec2(i, j);
            if (hash_i3(ivec3(c, 19)) >= 0.5) {
                continue;
            }
            float hx = hash_i3(ivec3(c, 3));
            float hy = hash_i3(ivec3(c, 4));
            vec2 pos = (vec2(c) + 0.18 + vec2(hx, hy) * 0.64) * spacing;
            float d = length(p - pos);
            if (d >= r_search) {
                continue;
            }
            float field = own_field(pos);
            if (field < margin) {
                continue;
            }
            float edge_t = clamp((field - margin) / mix_span, 0.0, 1.0);
            if (hash_i3(ivec3(c, 70)) >= clamp(u_tree_freq * edge_t, 0.0, 1.0)) {
                continue;
            }
            float hr = hash_i3(ivec3(c, 40));
            float radius = 0.5 * mix(
                mix(u_r_edge_min, u_r_edge_max, hr),
                mix(u_r_core_min, u_r_core_max, hr),
                edge_t
            );
            if (d >= radius) {
                continue;
            }
            float aa = max(u_view_width * 0.0007, 0.04);
            float cov = clamp((radius - d) / aa, 0.0, 1.0);
            if (cov > coverage) {
                coverage = cov;
                col = tree_tint(ivec3(c, 80), u_canopy);
            }
        }
    }
    return col;
}

void main() {
    float span = max(u_lod_far - u_lod_near, 1.0);
    float t = clamp((u_view_width - u_lod_near) / span, 0.0, 1.0);
    float fill_a = t * t * (3.0 - 2.0 * t);
    if (u_debug == 0 && fill_a > 0.997) {
        f_color = vec4(u_fill, 1.0);
        return;
    }

    float trees = 0.0;
    vec3 canopy = u_canopy;
    if (u_debug == 1 || fill_a < 0.997) {
        canopy = tree_disk(v_world, trees);
    }

    float field = mix_field(v_world);
    bool keep_soil = veg_mix_is_soil(
        v_world, field, u_mix_max, u_mix_noise_scale, u_mix_noise_amp, fill_a
    );
    vec3 soil = u_soil;

    if (!keep_soil) {
        if (trees < 0.02) {
            discard;
        }
        f_color = vec4(canopy, 1.0);
        return;
    }

    if (u_debug == 1) {
        vec3 col;
        if (field < max(u_tree_margin, 0.5)) {
            col = mix(soil, vec3(1.0, 0.92, 0.15), 0.88);
        } else {
            float g = clamp((field - u_tree_margin) / max(u_mix_max - u_tree_margin, 1.0), 0.0, 1.0);
            col = mix(soil, vec3(0.92, 0.12, 0.08), g);
        }
        col = mix(col, canopy, clamp(trees, 0.0, 1.0));
        f_color = vec4(col, 1.0);
        return;
    }

    vec3 close = mix(soil, canopy, clamp(trees, 0.0, 1.0));
    f_color = vec4(mix(close, u_fill, fill_a), 1.0);
}
