#version 330 core

uniform vec4 u_land_frame;
uniform sampler2D u_urban;
uniform float u_urban_gain;
uniform float u_urban_gamma;
uniform float u_urban_alpha;
uniform vec3 u_overlay_rgb;
in vec2 v_world;
out vec4 f_color;

void main() {
    vec2 span = max(u_land_frame.zw - u_land_frame.xy, vec2(1.0));
    vec2 uv = clamp((v_world - u_land_frame.xy) / span, 0.0, 1.0);
    float d = texture(u_urban, uv).r;
    float t = max(d * u_urban_gain, 0.0);
    float g = max(u_urban_gamma, 0.05);
    float a = clamp(pow(t, g), 0.0, 1.0);
    if (a < 0.02) {
        discard;
    }
    f_color = vec4(u_overlay_rgb, a * clamp(u_urban_alpha, 0.0, 1.0));
}
