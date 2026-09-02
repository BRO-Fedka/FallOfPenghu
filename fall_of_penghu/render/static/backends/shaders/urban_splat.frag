#version 330 core

uniform float u_urban_sigma;
uniform float u_urban_extent;
uniform int u_urban_kernel;
in float v_t;
in float v_peak;
out vec4 f_color;

void main() {
    float sigma = max(u_urban_sigma, 1.0);
    float peak = v_peak;
    float d = max(v_t, 0.0) * max(u_urban_extent, 1.0);
    float d2 = d * d;
    float g = 0.0;
    if (u_urban_kernel == 1) {
        float t2 = d2 / (sigma * sigma);
        g = peak / (1.0 + t2);
    } else if (u_urban_kernel == 2) {
        g = peak * max(1.0 - d / sigma, 0.0);
    } else {
        g = peak * exp(-0.5 * d2 / (sigma * sigma));
    }
    f_color = vec4(g, g, g, 1.0);
}
