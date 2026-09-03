#version 330 core

in vec2 in_pos;
in vec2 in_side;
uniform vec4 u_view;
uniform float u_half_width_m;

void main() {
    vec2 p = in_pos + in_side * u_half_width_m;
    float w = max(u_view.z - u_view.x, 1e-6);
    float h = max(u_view.w - u_view.y, 1e-6);
    float x = (p.x - u_view.x) / w * 2.0 - 1.0;
    float y = (p.y - u_view.y) / h * 2.0 - 1.0;
    gl_Position = vec4(x, y, 0.0, 1.0);
}
