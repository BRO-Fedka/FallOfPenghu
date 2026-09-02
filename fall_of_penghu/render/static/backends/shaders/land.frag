#version 330 core
#include "common.glsl"

uniform vec4 u_land_frame;
uniform sampler2D u_landf;
uniform sampler2D u_urban;
uniform vec3 u_land;
uniform vec3 u_rock;
uniform vec3 u_concrete;
uniform float u_mix_max;
uniform float u_mix_noise_scale;
uniform float u_mix_noise_amp;
uniform float u_band_width;
uniform float u_urban_threshold;
uniform float u_urban_noise_scale;
uniform int u_urban_octaves;
uniform float u_urban_noise_weight;
uniform int u_radar;
in vec2 v_world;
out vec4 f_color;

void main() {
    if (u_radar == 1) {
        f_color = vec4(u_land, 1.0);
        return;
    }
    vec2 span = max(u_land_frame.zw - u_land_frame.xy, vec2(1.0));
    vec2 uv = clamp((v_world - u_land_frame.xy) / span, 0.0, 1.0);
    float field = texture(u_landf, uv).r * u_band_width;
    vec3 col = land_soil_mix(
        v_world, field, u_land, u_rock, u_mix_max, u_mix_noise_scale, u_mix_noise_amp
    );
    float urban = texture(u_urban, uv).r;
    float n = urban_edge_noise(v_world, u_urban_noise_scale, u_urban_octaves);
    if (urban + n * u_urban_noise_weight > u_urban_threshold) {
        col = u_concrete;
    }
    f_color = vec4(col, 1.0);
}
