// Shared noise. World coords are meters; hash is stable at ±100 km.
// Do not name functions noise/noise1/noise2/noise3/noise4 — those are GLSL builtins.

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

// Octave i is 1-based. Change this to retune urban-edge fBm weights.
float urban_octave_weight(float x) {
    return 1.0 / (x * x);
}

float urban_edge_noise(vec2 world, float noise_scale, int octaves) {
    int n = octaves;
    if (n < 1) {
        n = 1;
    }
    if (n > 8) {
        n = 8;
    }
    float sum = 0.0;
    float wsum = 0.0;
    float freq = noise_scale;
    for (int i = 1; i <= 8; i++) {
        if (i > n) {
            break;
        }
        float w = urban_octave_weight(float(i));
        vec2 p = world * freq + vec2(float(i) * 17.1, float(i) * 9.3);
        sum += w * signed_noise(p);
        wsum += w;
        freq *= 2.0;
    }
    return sum / max(wsum, 1e-6);
}

float ripple_band(float pos, float width) {
    float d = abs(fract(pos) - 0.5);
    return 1.0 - smoothstep(0.0, max(width, 1e-4), d);
}

float noise_mask(vec2 p, float lo, float hi) {
    return smoothstep(lo, hi, valnoise(p));
}

bool veg_mix_is_soil(
    vec2 world,
    float field,
    float mix_max,
    float noise_scale,
    float noise_amp,
    float lod_fill
) {
    if (lod_fill >= 0.997) {
        return true;
    }
    if (field >= mix_max) {
        return true;
    }
    vec2 p = world * noise_scale;
    float n = valnoise(p);
    n += valnoise(p * 2.0 + vec2(13.1, 4.7));
    n += valnoise(p * 4.0 + vec2(7.2, 19.4));
    n = clamp((n / 3.0 - 0.5) * noise_amp + 0.5, 0.0, 1.0);
    float gate = field / mix_max;
    gate = mix(gate, 1.01, clamp(lod_fill, 0.0, 1.0));
    return n < gate;
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
    return veg_mix_is_soil(world, field, mix_max, noise_scale, noise_amp, 0.0) ? soil : land;
}
