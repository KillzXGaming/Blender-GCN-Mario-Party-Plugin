
struct Sampler
{
    vec4 cTransform; // scale xy, trans xy
    float cCombinerMode;
    float cCombinerBlend;
    float cBumpIntensity;
    float cTextureEnable;
};

struct Context
{
    mat3x4 cView;
    mat3x4 cViewInv;
    mat4 cViewProj;
    vec4 ZNearFar; //[22] //Near, Far, Far - Near, 1 / (Far - Near)
    mat3x4 cTransform;

    vec4 cMaterialColor;
    vec4 cAmbientColor;
    vec4 cShadowColor;

    float uSetLightmap;
    float uSetToonmap;
    float uVertexMode;
    float uBillboard;

    float uReflection;
    float uTransparency;
    float uLightmapScale;
    float cTextureCount;

    vec4 uLightPosition;
    vec4 uLightColor;
    vec4 uLightDir;
    vec4 uLightCosAtten;
    vec4 uLightDistAtten;

    // Sampler settings
    Sampler samplers[4];
};