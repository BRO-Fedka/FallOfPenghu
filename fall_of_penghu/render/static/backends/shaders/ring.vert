#version 330 core

in vec2 in_pos;
in vec2 in_center;
in float in_radius;
uniform vec2 u_screen;
out vec2 v_delta;
out float v_radius;

void main() {
    v_delta = in_pos - in_center;
    v_radius = in_radius;
    vec2 ndc = vec2(
        in_pos.x / u_screen.x * 2.0 - 1.0,
        1.0 - in_pos.y / u_screen.y * 2.0
    );
    gl_Position = vec4(ndc, 0.0, 1.0);
}
