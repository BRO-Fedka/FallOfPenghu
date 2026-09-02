#version 330 core

uniform vec3 u_color;
uniform float u_opacity;
uniform vec3 u_tint;
out vec4 f_color;

void main() {
    f_color = vec4(u_color * u_tint, u_opacity);
}
