#version 330 core

uniform sampler2D u_image;
uniform float u_alpha;
in vec2 v_uv;
out vec4 f_color;

void main() {
    f_color = texture(u_image, v_uv);
    f_color.a *= u_alpha;
}
