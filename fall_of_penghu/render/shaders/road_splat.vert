#version 330 core

in vec2 in_pos;
in vec2 in_center;
in float in_peak;
uniform vec4 u_view;
out vec2 v_off;
out float v_peak;

void main() {
    float w = max(u_view.z - u_view.x, 1e-6);
    float h = max(u_view.w - u_view.y, 1e-6);
    float x = (in_pos.x - u_view.x) / w * 2.0 - 1.0;
    float y = (in_pos.y - u_view.y) / h * 2.0 - 1.0;
    gl_Position = vec4(x, y, 0.0, 1.0);
    v_off = in_pos - in_center;
    v_peak = in_peak;
}
