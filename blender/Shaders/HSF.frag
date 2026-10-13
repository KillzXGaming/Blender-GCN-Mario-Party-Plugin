// Blends between 1 gray scale texture with tint color
vec4 SetupGrayscaleTexStageFirstTex1()
{
    return vec4(1.0);
}
// Blends between 2 gray scale textures with tint color
vec4 SetupGrayscaleTexStageFirstTex2()
{
    return vec4(1.0);
}

vec4 GetTexture0()
{
    vec4 tex0 = texture(cTexture0, fTexCoord0);
    tex0.rgb = pow(tex0.rgb, vec3(1.0 / 2.2)); // Blender defaults to srgb, so correct it before use
    return tex0;
}

vec4 GetTexture1()
{
    vec4 tex0 = texture(cTexture1, fTexCoord1);
    tex0.rgb = pow(tex0.rgb, vec3(1.0 / 2.2)); // Blender defaults to srgb, so correct it before use
    return tex0;
}


void main()
{
        vec4 light_map = texture(cLightmapTexture, fHiliteCoords);
        vec4 reflect_map = texture(cReflectionTexture, fSphereCoords);
        int grayScaleFlags = 3;
        vec4 raster_color = vec4(1.0);
        float tev_alpha = raster_color.a;
        int bump_map_usage = 0;
        vec4 color_output = vec4(0.0);

        FragColor.rgba = vec4(1.0);

        if (context.cTextureCount >= 1)
        {
            vec4 tex0 = GetTexture0();
            FragColor.rgb = tex0.rgb;
            FragColor.a = tex0.a;
        }
        if (context.cTextureCount >= 2)
        {
            vec4 tex1 = GetTexture1();
            FragColor.rgb = mix(FragColor.rgb, tex1.rgb, tex1.a * context.samplers[1].cCombinerBlend);
        }
        FragColor.rgb = mix(FragColor.rgb, reflect_map.rgb, vec3(context.uReflection));
        FragColor.a *= context.uTransparency;

        if (context.uSetLightmap == 1)
            FragColor.rgb += light_map.rgb;

        FragColor.rgb *= fColor0.rgb;
}