#version 330 core

in vec2 in_pos;
in float in_t;
uniform vec4 u_view;
out float v_t;

void main() {
    float w = max(u_view.z - u_view.x, 1e-6);
    float h = max(u_view.w - u_view.y, 1e-6);
    float x = (in_pos.x - u_view.x) / w * 2.0 - 1.0;
    float y = (in_pos.y - u_view.y) / h * 2.0 - 1.0;
    gl_Position = vec4(x, y, 0.0, 1.0);
    v_t = in_t;
}
