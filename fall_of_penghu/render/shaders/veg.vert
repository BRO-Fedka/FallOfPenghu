#version 330 core

in vec2 in_pos;
uniform vec4 u_view;
out vec2 v_world;
out float v_t;
out vec2 v_n;
out float v_band;

void main() {
    float w = max(u_view.z - u_view.x, 1e-6);
    float h = max(u_view.w - u_view.y, 1e-6);
    float x = (in_pos.x - u_view.x) / w * 2.0 - 1.0;
    float y = (in_pos.y - u_view.y) / h * 2.0 - 1.0;
    gl_Position = vec4(x, y, 0.0, 1.0);
    v_world = in_pos;
    v_t = 0.0;
    v_n = vec2(0.0, 1.0);
    v_band = 0.0;
}
