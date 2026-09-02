#version 330 core

in float v_t;
uniform float u_band_width;
uniform float u_max;
out vec4 f_color;

void main() {
    float d = max((1.0 - v_t) * u_band_width, 0.0);
    float n = clamp(d / max(u_max, 1e-6), 0.0, 1.0);
    f_color = vec4(n, n, n, 1.0);
}
