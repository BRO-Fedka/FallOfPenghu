#version 330 core

uniform sampler2D u_map;
uniform vec2 u_resolution;
uniform float u_time;
uniform int u_radar;
in vec2 v_uv;
out vec4 f_color;

// Compact FXAA. MSAA already smoothed the FBO; this knocks down leftover jaggies
// on 1-pixel building edges. u_time / u_radar stay wired for later effects.
void main() {
    vec2 texel = 1.0 / max(u_resolution, vec2(1.0));
    vec3 rgbM = texture(u_map, v_uv).rgb;
    vec3 rgbN = texture(u_map, v_uv + vec2(0.0, -texel.y)).rgb;
    vec3 rgbS = texture(u_map, v_uv + vec2(0.0, texel.y)).rgb;
    vec3 rgbW = texture(u_map, v_uv + vec2(-texel.x, 0.0)).rgb;
    vec3 rgbE = texture(u_map, v_uv + vec2(texel.x, 0.0)).rgb;

    vec3 luma_w = vec3(0.299, 0.587, 0.114);
    float lumaM = dot(rgbM, luma_w);
    float lumaMin = min(lumaM, min(min(dot(rgbN, luma_w), dot(rgbS, luma_w)), min(dot(rgbW, luma_w), dot(rgbE, luma_w))));
    float lumaMax = max(lumaM, max(max(dot(rgbN, luma_w), dot(rgbS, luma_w)), max(dot(rgbW, luma_w), dot(rgbE, luma_w))));
    float contrast = lumaMax - lumaMin;

    vec3 blend = (rgbN + rgbS + rgbW + rgbE) * 0.25;
    float edge = smoothstep(0.08, 0.22, contrast);
    vec3 color = mix(rgbM, mix(rgbM, blend, 0.22), edge);

    float hook = u_time * 0.0 + float(u_radar) * 0.0;
    f_color = vec4(color + vec3(hook), 1.0);
}
