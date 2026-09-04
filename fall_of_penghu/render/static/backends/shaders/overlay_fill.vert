#version 330 core

in vec2 in_pos;
uniform vec2 u_screen;

void main() {
    vec2 ndc = vec2(in_pos.x / u_screen.x * 2.0 - 1.0, 1.0 - in_pos.y / u_screen.y * 2.0);
    gl_Position = vec4(ndc, 0.0, 1.0);
}
