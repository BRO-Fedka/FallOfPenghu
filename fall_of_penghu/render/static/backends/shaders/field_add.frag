#version 330 core

uniform sampler2D u_src;
in vec2 v_uv;
out vec4 f_color;

void main() {
    float v = texture(u_src, v_uv).r;
    f_color = vec4(v, v, v, 1.0);
}
