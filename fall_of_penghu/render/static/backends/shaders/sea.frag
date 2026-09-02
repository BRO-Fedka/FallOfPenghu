#version 330 core

uniform sampler2D u_dist;
uniform vec4 u_view;
uniform vec4 u_frame;
uniform float u_max_dist;
uniform float u_tex_size;
uniform vec3 u_water_deep;
uniform vec3 u_water_mid;
uniform vec3 u_water_shallow;
uniform float u_shallow_width;
uniform float u_deep_start;
uniform float u_deep_end;
in vec2 v_uv;
out vec4 f_color;

void main() {
    vec2 world = mix(u_view.xy, u_view.zw, v_uv);
    vec2 span = max(u_frame.zw - u_frame.xy, vec2(1.0));
    float n = max(u_tex_size, 2.0);
    vec2 uv = (world - u_frame.xy) / span;
    uv = uv * ((n - 1.0) / n) + (0.5 / n);
    float dist_m = texture(u_dist, clamp(uv, 0.0, 1.0)).r * u_max_dist;
    float shallow_t = 1.0 - smoothstep(0.0, max(u_shallow_width, 1.0), dist_m);
    float deep_t = smoothstep(u_deep_start, max(u_deep_end, u_deep_start + 1.0), dist_m);
    vec3 col = mix(u_water_mid, u_water_shallow, shallow_t);
    col = mix(col, u_water_deep, deep_t);
    f_color = vec4(col, 1.0);
}
