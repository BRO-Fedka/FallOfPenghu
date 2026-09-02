#version 330 core
#include "common.glsl"

uniform float u_time;
uniform float u_mesh_width;
uniform float u_shore_width;
uniform float u_band_shallow_width;
uniform float u_view_width;
uniform float u_intensity;
uniform vec3 u_water_mid;
uniform vec3 u_water_shallow;
uniform vec3 u_ripple_cyan;
uniform vec3 u_ripple_light;
uniform vec3 u_ripple_white;
uniform float u_warp_scale;
uniform float u_warp_strength;
uniform float u_detail_scale;
uniform float u_detail_strength;
uniform float u_ripple_frequency;
uniform float u_ripple_width;
uniform float u_ripple_speed;
uniform float u_ripple_opacity;
uniform float u_ripple_mask_low;
uniform float u_ripple_mask_high;
uniform float u_ripple_b_frequency;
uniform float u_ripple_b_width;
uniform float u_ripple_b_speed;
uniform float u_ripple_b_opacity;
uniform float u_ripple_b_mask_low;
uniform float u_ripple_b_mask_high;
uniform float u_ripple_b_phase;
uniform float u_highlight_frequency;
uniform float u_highlight_width;
uniform float u_highlight_speed;
uniform float u_highlight_opacity;
uniform float u_highlight_mask_low;
uniform float u_highlight_mask_high;
uniform float u_highlight_phase;
uniform float u_mask_scale;
uniform float u_foam_evolve;
uniform float u_foam_drift;
uniform float u_ripple_fade_view;
uniform float u_ripple_gone_view;
uniform float u_landward;
uniform float u_foam_min;
uniform float u_foam_max;
uniform float u_foam_hz;
uniform float u_foam_width_noise;
uniform float u_foam_noise_scale;

in float v_t;
in vec2 v_world;
out vec4 f_color;

void main() {
    float span_m = max(u_landward + u_mesh_width, 1e-4);
    float dist_signed = v_t * span_m - u_landward;
    float dist_m = max(dist_signed, 0.0);
    float zone = max(u_shore_width, 1.0);

    vec2 drift = vec2(u_time * u_foam_drift, u_time * u_foam_drift * 0.73);
    vec2 drift_b = vec2(u_time * u_foam_drift * -0.55, u_time * u_foam_drift * 0.41);
    vec2 gp = v_world * u_foam_noise_scale + drift;
    vec2 gp2 = v_world * u_foam_noise_scale * 2.15 + drift_b + 19.0;

    float evolve = 0.5 + 0.5 * sin(u_time * 6.28318 * u_foam_evolve);
    float n_a = signed_noise(gp);
    float n_b = signed_noise(gp + vec2(37.1, 14.6));
    float n_c = signed_noise(gp2);
    float n_d = signed_noise(gp2 + vec2(9.3, 28.4));
    float n_thick = 0.5 + 0.5 * mix(n_a, n_b, evolve);
    float n_thick2 = 0.5 + 0.5 * mix(n_c, n_d, 1.0 - evolve);
    float pulse = 0.5 + 0.5 * sin(u_time * 6.28318 * u_foam_hz);
    float thick = mix(u_foam_min, u_foam_max, mix(n_thick, pulse, 0.25));
    thick = mix(thick, mix(u_foam_min, u_foam_max, n_thick2), u_foam_width_noise);

    float foam = 1.0 - smoothstep(thick - 0.7, thick, dist_signed);
    foam *= smoothstep(-0.2, 0.0, dist_signed);

    float warp =
        signed_noise(v_world * u_warp_scale + drift) * u_warp_strength
        + signed_noise(v_world * u_detail_scale + 31.0 + drift_b) * u_detail_strength;
    float warped = dist_m + warp;

    float lod = 1.0 - smoothstep(u_ripple_fade_view, u_ripple_gone_view, u_view_width);
    float shore_factor = 1.0 - smoothstep(thick, zone, dist_m);
    float gain = u_intensity * lod * shore_factor;

    vec2 mask_uv = v_world * u_mask_scale + drift * 0.4;
    float mask_a = noise_mask(mask_uv, u_ripple_mask_low, u_ripple_mask_high);
    float mask_b = noise_mask(mask_uv * 1.7 + 9.1 + drift_b, u_ripple_b_mask_low, u_ripple_b_mask_high);
    float mask_c = noise_mask(mask_uv * 2.4 + 18.4 + drift, u_highlight_mask_low, u_highlight_mask_high);

    float wave_a = warped * u_ripple_frequency + u_time * u_ripple_speed;
    float wave_b = warped * u_ripple_b_frequency + u_time * u_ripple_b_speed + u_ripple_b_phase;
    float wave_c = warped * u_highlight_frequency + u_time * u_highlight_speed + u_highlight_phase;

    float beyond = smoothstep(thick, thick + 0.6, dist_m);
    float layer_a = ripple_band(wave_a, u_ripple_width) * mask_a * u_ripple_opacity * beyond;
    float layer_b = ripple_band(wave_b, u_ripple_b_width) * mask_b * u_ripple_b_opacity * beyond;
    float layer_c = ripple_band(wave_c, u_highlight_width) * mask_c * u_highlight_opacity * beyond;

    float shallow_t = 1.0 - smoothstep(0.0, max(u_band_shallow_width, 1.0), dist_m);
    vec3 col = mix(u_water_mid, u_water_shallow, shallow_t);
    col = mix(col, u_ripple_cyan, clamp(layer_a * gain, 0.0, 1.0));
    col = mix(col, u_ripple_light, clamp(layer_b * gain, 0.0, 1.0));
    col = mix(col, u_ripple_white, clamp(layer_c * gain, 0.0, 1.0));
    col = mix(col, vec3(1.0), clamp(foam, 0.0, 1.0));

    float alpha = shore_factor * mix(0.4, 1.0, clamp((layer_a + layer_b + layer_c) * gain, 0.0, 1.0));
    alpha = max(alpha * lod, foam);
    if (alpha < 0.02) {
        discard;
    }
    f_color = vec4(col, alpha);
}
