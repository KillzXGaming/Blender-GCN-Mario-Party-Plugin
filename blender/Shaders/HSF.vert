
const int GX_DF_NONE = 0;
const int GX_DF_CLAMP = 1;

const int GX_AF_NONE = 2;
const int GX_AF_SPOT = 1;
const int GX_AF_SPEC = 2;

float ApplyAttenuation(vec3 t_Coeff, float t_Value) {
    return dot(t_Coeff, vec3(1.0, t_Value, t_Value*t_Value));
}

vec3 CalculateChannel(bool enable_lights, vec3 t_Normal, vec3 t_Position, vec3 ambient_src, vec3 mat_src, int atten_func, int diffuse_func)
{
    if (!enable_lights)
        return ambient_src.rgb + mat_src.rgb;

    vec3 l_cos_att = context.uLightCosAtten.xyz;
    vec3 l_dist_att = context.uLightDistAtten.xyz;

    vec3 lighting = ambient_src;
    vec3 N = normalize(t_Normal);

    vec3 ldir = context.uLightPosition.xyz - t_Position.xyz;
    float dist2 = dot(ldir, ldir);
    float dist = sqrt(dist2);
    ldir = ldir / dist;

    float diff = 1.0;
    float attn = 1.0;

    if (diffuse_func == GX_DF_CLAMP) // CLAMP
         diff = max(dot(N, ldir), 0.0);

    if (atten_func == GX_AF_SPOT) // SPOT
    {
        float attnv = max(0.0, dot(ldir, context.uLightDir.xyz));
        float cos_attnv = ApplyAttenuation(l_cos_att, attnv);
        float dist_attnv = dot(l_dist_att, vec3(1.0, dist, dist2));
       // attn = max(0.0, cos_attnv / dist_attnv);
    }
    if (atten_func == GX_AF_SPEC) // SPEC
    {
        float attnv = (dot(t_Normal, ldir) >= 0.0) ? max(0.0, dot(t_Normal, context.uLightDir.xyz)) : 0.0;
        float cos_attnv = max(0.0, ApplyAttenuation(l_cos_att, attnv));
        float dist_attnv = max(0.0, ApplyAttenuation(l_dist_att, attnv));
        attn = max(0.0, cos_attnv / dist_attnv);
    }
    return lighting + (diff * mat_src.rgb * attn * context.uLightColor.rgb);
}

void CalculateRasterChannels(vec3 t_Normal, vec3 t_Position)
{
    int vtxMode = int(context.uVertexMode);
    int enableSpecular = (vtxMode == 2 || vtxMode == 3) ? 1 : 0;
    enableSpecular = 0;

    vec3 color0, color1;
    vec3 alpha0, alpha1;

    bool use_lighting = vtxMode != 0;
    bool use_alpha_lighting = vtxMode == 5; // with obj.flags & 0x4000

    if (enableSpecular != 0) {
        if (vtxMode == 5) {
            //Vertex colors
            color0.rgb = CalculateChannel(true, t_Normal, t_Position, context.cAmbientColor.rgb, vColor.rgb, GX_DF_CLAMP, GX_AF_NONE);
            color1.rgb = CalculateChannel(true,t_Normal, t_Position, context.cAmbientColor.rgb, vColor.rgb, GX_DF_NONE, GX_AF_SPEC);
            alpha0.rgb = vColor.aaa;
            alpha0.rgb = vColor.aaa;
        } else {
            // Material color for diffuse and specular
            color0.rgb = CalculateChannel(true, t_Normal, t_Position, context.cAmbientColor.rgb, context.cMaterialColor.rgb, GX_DF_CLAMP, GX_AF_NONE);
            color1.rgb = CalculateChannel(true, t_Normal, t_Position, context.cAmbientColor.rgb, context.cMaterialColor.rgb, GX_DF_NONE, GX_AF_SPEC);
            alpha0.rgb = vColor.aaa;
            alpha0.rgb = vColor.aaa;
        }
    } else { // single channel
        if (vtxMode == 5) {
            color0.rgb = CalculateChannel(true, t_Normal, t_Position, context.cAmbientColor.rgb, vColor.rgb, GX_DF_CLAMP, GX_AF_SPOT);
            alpha0.rgb = vColor.aaa;
        } else {
            color0.rgb = CalculateChannel(use_lighting, t_Normal, t_Position, context.cAmbientColor.rgb, context.cMaterialColor.rgb, GX_DF_CLAMP, GX_AF_SPOT);
            alpha0 = vec3(1.0);
        }
        color1 = vec3(0.0);
        alpha1 = vec3(1.0);
    }

    fColor0 = vec4(color0.rgb, alpha0.r);
    fColor1 = vec4(color1.rgb, alpha1.r);
}

vec2 CalculateMatrix(vec2 uv, vec4 scale_pos)
{
    return uv * (1.0 / scale_pos.xy) + scale_pos.zw;
}

vec2 HiliteCoords(vec3 n_view, vec3 light_dir_view, float hilite_scale)
{
    vec3 H = -normalize(light_dir_view) + vec3(0.0, 0.0, 1.0);
    if (dot(H, H) < 1e-8) return vec2(0.0);
    H = normalize(H);
    vec3 k = cross(H, vec3(0.0, 0.0, 1.0));
    vec3 r = n_view + cross(k, n_view) + cross(k, cross(k, n_view)) / (1.0 + H.z);
    float s = max(0.1, hilite_scale / 50.0);
    return r.xy * s + 0.5;
}

void main()
{
    fNormal = normalize(vNormal * mat3(context.cTransform));
    vec4 t_Position = vec4(vPosition.xyz, 1.0f) * mat4(context.cTransform);

    if (context.uVertexMode == 0)
    {
        fColor0 = vec4(context.cMaterialColor.rgb, 1.0);
    }
    else
        CalculateRasterChannels(fNormal, t_Position.xyz);

    // Texture transforms
    vec2 t0 = CalculateMatrix(vTexCoords0, context.samplers[0].cTransform);
    vec2 t1 = CalculateMatrix(vTexCoords0, context.samplers[1].cTransform);
    vec2 t2 = CalculateMatrix(vTexCoords0, context.samplers[2].cTransform);

    fTexCoord0 = t0;
    fTexCoord1 = t1;
    fTexCoord2 = t2;

    // Sphere map coords for light map and reflection map
    vec3 view_n = (normalize(fNormal.xyz) * mat3(context.cView)).xyz;
    fSphereCoords = vec2(view_n.x, view_n.y) * 0.5 + 0.5;

	vec3 light_view = normalize(context.uLightDir.xyz * mat3(context.cView));
	fHiliteCoords = HiliteCoords(view_n, light_view, context.uLightmapScale);

    gl_Position = t_Position * context.cViewProj;
}