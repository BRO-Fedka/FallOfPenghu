// Shared noise. World coords are meters; hash is stable at ±100 km.
// Do not name functions noise/noise1/noise2/noise3/noise4 — those are GLSL builtins.

float hash11(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

// Integer lattice hash. Float fract hashes smear along X at large world coords.
float hash_i3(ivec3 p) {
    uvec3 n = uvec3(p) * uvec3(1597334677u, 3812015801u, 2798796413u);
    uint m = (n.x ^ n.y ^ n.z) * 747796405u;
    return float(m >> 8u) * (1.0 / 16777215.0);
}

float valnoise(vec2 p) {
    ivec2 cell = ivec2(floor(p));
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash_i3(ivec3(cell, 17));
    float b = hash_i3(ivec3(cell + ivec2(1, 0), 17));
    float c = hash_i3(ivec3(cell + ivec2(0, 1), 17));
    float d = hash_i3(ivec3(cell + ivec2(1, 1), 17));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

float valfbm(vec2 p) {
    float v = 0.5 * valnoise(p);
    v += 0.25 * valnoise(p * 2.17 + vec2(13.1, 4.7));
    v += 0.125 * valnoise(p * 4.31 + vec2(7.2, 19.4));
    return v;
}

float signed_noise(vec2 p) {
    return valnoise(p) * 2.0 - 1.0;
}

float ripple_band(float pos, float width) {
    float d = abs(fract(pos) - 0.5);
    return 1.0 - smoothstep(0.0, max(width, 1e-4), d);
}

float noise_mask(vec2 p, float lo, float hi) {
    return smoothstep(lo, hi, valnoise(p));
}

vec3 land_soil_mix(
    vec2 world,
    float field,
    vec3 soil,
    vec3 land,
    float mix_max,
    float noise_scale,
    float noise_amp
) {
    if (field >= mix_max) {
        return soil;
    }
    vec2 p = world * noise_scale;
    float n = valnoise(p);
    n += valnoise(p * 2.0 + vec2(13.1, 4.7));
    n += valnoise(p * 4.0 + vec2(7.2, 19.4));
    n = clamp((n / 3.0 - 0.5) * noise_amp + 0.5, 0.0, 1.0);
    return n < (field / mix_max) ? soil : land;
}
