#version 330 core

in vec2 v_delta;
in float v_radius;
uniform vec4 u_color;
uniform float u_half_width;
out vec4 f_color;

void main() {
    float d = abs(length(v_delta) - v_radius);
    float alpha = u_color.a * (1.0 - smoothstep(u_half_width, u_half_width + 0.375, d));
    if (alpha <= 0.004) {
        discard;
    }
    f_color = vec4(u_color.rgb, alpha);
}
