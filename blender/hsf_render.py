import bpy
import array
import gpu
import ctypes
import os
from mathutils import Matrix
import numpy as np
from gpu_extras.batch import batch_for_shader
from . import hsf_properties
from . import dds
from . import bone_render

def set_matrix(matrix : Matrix, c_float_array ):
   for i in range(4):
        c_float_array[i] =  matrix[i][:]
        
def set_matrix3x4(matrix : Matrix, c_float_array ):
   for i in range(3):
        c_float_array[i] =  matrix[i][:]

def get_vec2(array):
    return ((ctypes.c_float * 2))(*array)
                
def get_vec3(array):
    return ((ctypes.c_float * 3))(*array)
        
def get_vec4(array):
    return ((ctypes.c_float * 4))(*array)

class SamplerObject():
    def __init__(self, img):
        self.image = img

class MaterialObject():
    def __init__(self, blender_mat):
        self.cull_state = 'NONE'
        self.blend_mode = 'ALPHA'
        self.z_write = True
        self.z_test = 'LESS_EQUAL'
        self.hsf_flags = 0 
        self.blender_mat = blender_mat
        self.samplers: List[SamplerObject] = []
        self.shader = None;
        self.macros: dict[str, str] = {}

    def get_shader(self, sceneEngine):
        # get cached shader
        if self.shader is None:
            self.shader = sceneEngine.get_shader(self.macros)
        return self.shader

    def updateMaterial(self, sceneEngine, mat):
        # update shader incase macros changed
        self.shader = sceneEngine.get_shader(self.macros)
        if not self.blender_mat:
            return

        properties = self.blender_mat.hsf_properties
        self.samplers = []
        for i, sampler in enumerate(properties.texture_maps):
            if sampler.image:
                obj = SamplerObject(sampler.image)
                self.samplers.append(obj)

    def updateMaterialAnimation(self, mat):
        pass

    def updateTransform(self, obj):
        pass

    def updateSampler(self, image):
        pass

    def is_transparent_pass(self):
        if self.blender_mat:
            properties = self.blender_mat.hsf_properties
            if properties.pass_flag != 0 or properties.inverted_transparency != 0.0:
                return True
        return False

    def render(self, sceneEngine, obj: bpy.types.Object, shader):
        if self.blender_mat:
            properties = self.blender_mat.hsf_properties

            if properties.show_both_faces:
                gpu.state.face_culling_set('NONE')
            else:
                gpu.state.face_culling_set('BACK')

            if properties.pass_flag != 0 or properties.inverted_transparency != 0.0:
                gpu.state.depth_mask_set(False)
            else:
                gpu.state.depth_mask_set(properties.enable_depthwrite)

            if properties.blend_type == 'SRC_ALPHA_ONE':
                gpu.state.blend_set('ADDITIVE_PREMULT')
            elif self.blend_mode == 'ZERO_INV_SRC_COLOR':
                gpu.state.blend_set('ALPHA') # Todo no blender set that matches this
            else: # SRC_ALPHA_INV_SRC_ALPHA
                gpu.state.blend_set('ALPHA')

        shader.bind()
        sceneEngine.contextData.updateTransform(obj)
        sceneEngine.bindGlobalTextures()

        if self.blender_mat:
            sceneEngine.contextData.updateMaterial(self.blender_mat)

        for i, sampler in enumerate(self.samplers):
            shader.uniform_sampler(f"cTexture{i}", sceneEngine.getTexture(sampler.image))

        sceneEngine.contextData.bind("context",shader)

class PolygonObject():

    def __init__(self):
        self.material = MaterialObject(None) #default material
        self.attrs = None
        self.indices = None
        self.batch = None  # created on first draw

    def __del__(self):
        if self.batch:
            del self.batch

    def update(self, attrs, indices):
        #set the data for batching later
        self.attrs = attrs;
        self.indices = indices;
        self.batch = None #Update in draw as we need to bind the shader of the material

    def draw(self, obj: bpy.types.Object, sceneEngine):
        shader = self.material.get_shader(sceneEngine)
        if shader is None:
            return
        # not created yet, make batch instance
        if self.batch is None:
            self.batch = self.batch_shader(shader, 'TRIS', self.attrs, self.indices)
        # apply material render state, sampler, and uniform data then draw the mesh
        self.material.render(sceneEngine, obj, shader)
        self.batch.draw(shader)
        # reset blend/cull states
        sceneEngine.reset_gpu_state()

    def batch_shader(self, shader, batchType: str, content: dict[str, np.ndarray], indices: np.ndarray):
        vboFormat = shader.format_calc()
        for name, data in content.items():
            cnt = 3
            if name.startswith("vTexCoords"):
                cnt = 2
            if name.startswith("vColor"):
                cnt = 4

            vboFormat.attr_add(
                id=name,
                comp_type='F32',
                len=cnt,
                fetch_mode='FLOAT')

        vboLen = len(next(iter(content.values())))
        vbo = gpu.types.GPUVertBuf(vboFormat, vboLen)

        for name, data in content.items():
            try:
                vbo.attr_fill(name, data)
            except: #Attribute not used, skip. 
                pass #Some attributes will show unused due to compile optimization
        ibo = gpu.types.GPUIndexBuf(type=batchType, seq=indices)
        return gpu.types.GPUBatch(type=batchType, buf=vbo, elem=ibo)

class MeshObject():
    def __init__(self):
        self.polygons : set[PolygonObject] = set()

    def __del__(self):
        del self.polygons

    def is_transparent_pass(self):
        for poly in self.polygons:
            if poly.material.is_transparent_pass():
                return True
        return False

    def getVertexColors(self, mesh, idc, vertex_color_layer_name):
        if vertex_color_layer_name not in mesh.color_attributes:
            return None

        layer = mesh.color_attributes[vertex_color_layer_name]
        colors = np.empty(len(layer.data) * 4, dtype=np.float32)
        layer.data.foreach_get("color", colors)
        colors = colors.reshape((-1, 4))

        c = colors[idc]

        return c
    
    def getTexCoords(self, mesh, uv_layer_name):
        if uv_layer_name not in mesh.uv_layers:
            return None

        layer = mesh.uv_layers[uv_layer_name]
        uvs = np.empty(len(layer.data) * 2, dtype=np.float32)
        layer.data.foreach_get("uv", uvs)
        uvs = uvs.reshape((-1, 2))
        return uvs

    def getLoopIdcs(self, mesh):
        indices = np.empty(len(mesh.loops), 'i')
        mesh.loops.foreach_get("vertex_index", np.reshape(indices, len(mesh.loops)))
        return indices

    def getPositions(self, mesh, idc):
        positions = np.empty((len(mesh.vertices), 3), 'f')
        mesh.vertices.foreach_get("co", np.reshape(positions, len(mesh.vertices) * 3))
        return positions[idc]

    def getNormals(self, mesh):
        normals = np.empty((len(mesh.loops), 3), 'f')
        mesh.loops.foreach_get("normal", np.reshape(normals, len(mesh.loops) * 3))
        return normals

    def getTangents(self, mesh):
        mesh.calc_tangents()

        tangents = np.empty(len(mesh.loops) * 3, dtype=np.float32)
        mesh.loops.foreach_get("tangent", tangents)
        tangents = tangents.reshape((-1, 3))

        bitangent_signs = np.empty(len(mesh.loops), dtype=np.float32)
        mesh.loops.foreach_get("bitangent_sign", bitangent_signs)

        return np.column_stack((tangents, bitangent_signs))

    def getIndices(self, mesh):
        indices = np.empty((len(mesh.loop_triangles), 3), 'i')
        mesh.loop_triangles.foreach_get("loops", np.reshape(indices, len(mesh.loop_triangles) * 3))
        return indices

    def getLoopFaceIdcs(self, mesh: bpy.types.Mesh):
        loop_face_counts  = np.empty(len(mesh.polygons), 'i')
        mesh.polygons.foreach_get("loop_total", loop_face_counts)
        return np.arange(len(mesh.polygons)).repeat(loop_face_counts )

    def getFaceMatIdcs(self, mesh: bpy.types.Mesh):
        mat_indices = np.empty(len(mesh.polygons), 'i')
        mesh.polygons.foreach_get("material_index", mat_indices)
        return mat_indices

    def updateTransform(self, obj: bpy.types.Object):
        for poly in self.polygons:
            poly.material.updateTransform(obj)

    def updateMesh(self, sceneRender, obj: bpy.types.Object):
        self.polygons.clear()

        loopFaceIdcs = None

        # Get the mesh data
        mesh: bpy.types.Mesh = obj.to_mesh()
        mesh.calc_loop_triangles()
        # Blender 4.0 removes this as it is no longer needed, keep for 3.0 versions
        if hasattr(mesh, "calc_normals_split") and not mesh.has_custom_normals:
            mesh.calc_normals_split()

        # Load the vertices
        attrs: dict[str, np.ndarray] = {}

        idc = self.getLoopIdcs(mesh)
        attrs["vPosition"] = self.getPositions(mesh, idc)
        attrs["vNormal"] = self.getNormals(mesh)

        if len(mesh.uv_layers) > 0 and len(mesh.uv_layers[-1].data) > 0:
            attrs["vTangent"] = self.getTangents(mesh)

        for col in mesh.color_attributes:
            attrs["vColor"] = self.getVertexColors(mesh, idc, col.name)     
            break

        slot = 0
        for uv in mesh.uv_layers:
            uv_loop  = self.getTexCoords(mesh, uv.name)
            attrs["vTexCoords" + str(slot)] = uv_loop

            slot += 1

        indices = self.getIndices(mesh)
        matLoopIdcs = np.zeros(indices.shape)
        if len(mesh.materials) > 1: # lookup is wasteful if there's only one material
            matLoopIdcs = self.getFaceMatIdcs(mesh)[self.getLoopFaceIdcs(mesh)][indices]

        material_slots: dict[bpy.types.Material, list[int]] = {}
        for i, mat in enumerate(mesh.materials):
           if mat is None:
                continue

           if mat in material_slots:
                material_slots[mat].append(i)
           else:
                material_slots[mat] = [i]

        if None in material_slots or len(mesh.materials) == 0: # No materials
            poly = PolygonObject()
            poly.update(attrs, indices)
            poly.material = sceneRender.getMaterial(0) 
            self.polygons.clear()
            self.polygons.add(poly)
        elif (len(mesh.materials) == 1): # One material
            poly = PolygonObject()
            poly.update(attrs, indices)
            poly.material = sceneRender.getMaterial(mesh.materials[0].name)
            self.polygons.clear()
            self.polygons.add(poly)
        else: # Multiple material maps in one mesh, split per polygon object
            self.polygons.clear()
            for mat, idcs in material_slots.items():
                idcs = indices[np.isin(matLoopIdcs, idcs)]

                poly = PolygonObject()
                poly.update(attrs, idcs)
                poly.material = sceneRender.getMaterial(mat.name)
                self.polygons.add(poly)

        obj.to_mesh_clear()

    def draw(self, sceneEngine, obj: bpy.types.Object):
        if not obj.visible_get():
            return

        #Update mesh if not init yet
        if len(self.polygons) == 0:
            self.updateMesh(sceneEngine, obj)

        for poly in self.polygons:
            poly.draw(obj, sceneEngine)

class Camera():
    def __init__(self):
        self.viewMatrix: Matrix = None
        self.projectionMatrix: Matrix = None
        self.viewProjectionMatrix: Matrix = None
        self.width = 1
        self.height = 1
        self.znear = 0.01
        self.zfar = 1000
        self.fov = 0.872665
        self.isOrtho = False
        self.ortho_scale = 1.0

    def get_aspect(self):
        return self.width / self.height

class ContextUBO_struct(ctypes.Structure):
    _pack_ = 16
    _fields_ = [
        ("cView",             3 * (4 * ctypes.c_float)),
        ("cViewInv",          3 * (4 * ctypes.c_float)),
        ("cViewProj",         4 * (4 * ctypes.c_float)),
        ("cZNearFar",        (4 * ctypes.c_float)),
        ("cTransform",         3 * (4 * ctypes.c_float)),

        ("cMaterialColor",        (4 * ctypes.c_float)),
        ("cAmbientColor",        (4 * ctypes.c_float)),
        ("cShadowColor",        (4 * ctypes.c_float)),

        ("uSetLightmap",        (ctypes.c_float)),
        ("uSetToonmap",        (ctypes.c_float)),
        ("uVertexMode",        (ctypes.c_float)),
        ("uBillboard",        (ctypes.c_float)),

        ("uReflection",        (ctypes.c_float)),
        ("uTransparency",        (ctypes.c_float)),
        ("uLightmapScale",        (ctypes.c_float)),
        ("cTextureCount",        (ctypes.c_float)),

        ("uLightPosition",        (4 * ctypes.c_float)),
        ("uLightColor",        (4 * ctypes.c_float)),
        ("uLightDir",        (4 * ctypes.c_float)),
        ("uLightCosAtten",        (4 * ctypes.c_float)),
        ("uLightDistAtten",        (4 * ctypes.c_float)),

        # Sampler structs
        ("cSampler0_Transform",        (4 * ctypes.c_float)),
        ("cSampler0_CombinerMode",     (ctypes.c_float)),
        ("cSampler0_CombinerBlend",     (ctypes.c_float)),
        ("cSampler0_BumpIntensity",     (ctypes.c_float)),
        ("cSampler0_TextureEnable",     (ctypes.c_float)),

        ("cSampler1_Transform",        (4 * ctypes.c_float)),
        ("cSampler1_CombinerMode",     (ctypes.c_float)),
        ("cSampler1_CombinerBlend",     (ctypes.c_float)),
        ("cSampler1_BumpIntensity",     (ctypes.c_float)),
        ("cSampler1_TextureEnable",     (ctypes.c_float)),
    ]

    def __init__(self): #Creates the UBO with the struct size
        self.cMaterialColor = get_vec4((1.0, 1.0, 1.0, 1.0))
        self.cAmbientColor = get_vec4((0.5, 0.5, 0.5, 1.0))
        self.cShadowColor = get_vec4((0.0, 0.0, 0.0, 1.0))
        self.cSamplerUseFlags = get_vec4((1.0, 1.0, 1.0, 1.0))

        self.uLightPosition = (577350.25, -577350.25, 577350.25, 1.0)
        self.uLightColor = (0.50, 0.50, 0.50, 1.0)
        self.uLightDir = ( 0.57735, -0.57735, 0.57735, 1.0)
        self.uLightCosAtten = (1.0, 1.0, 1.0, 1.0)
        self.uLightDistAtten = (1.0, 1.0, 1.0, 1.0)

        self.ubo = gpu.types.GPUUniformBuf(
            gpu.types.Buffer("UBYTE", ctypes.sizeof(self), self))

    def updateMaterial(self, mat: bpy.types.Material):
        properties = mat.hsf_properties
        self.cMaterialColor = get_vec4((properties.mat_color))
        self.cAmbientColor = get_vec4(properties.amb_color)
        self.cShadowColor = get_vec4(properties.shad_color)
        self.cTextureCount = float(len(properties.texture_maps))
        self.uLightmapScale = properties.light_map_scale
        self.uReflection = properties.reflection_intensity
        self.uTransparency = 1.0 - properties.inverted_transparency
        self.uVertexMode = float(hsf_properties.get_enum_int(properties, "vertex_type", properties.vertex_type))
        self.uBillboard = float(properties.enable_billboard)
        self.uSetLightmap = float(properties.enable_lightmap)

        if len(properties.texture_maps) > 0:
            prop_attr = properties.texture_maps[0]
            self.cSampler0_Transform = get_vec4((prop_attr.scale[0], prop_attr.scale[1], prop_attr.translate[0], prop_attr.translate[1]))
            self.cSampler0_TextureEnable = 1.0
            self.cSampler0_CombinerBlend = prop_attr.blend_alpha[0]
            self.cSampler0_CombinerMode = float(hsf_properties.get_enum_int(prop_attr, "blend_combiner", prop_attr.blend_combiner))

        if len(properties.texture_maps) > 1:
            prop_attr = properties.texture_maps[1]
            self.cSampler1_Transform = get_vec4((prop_attr.scale[0], prop_attr.scale[1], prop_attr.translate[0], prop_attr.translate[1]))
            self.cSampler1_TextureEnable = 1.0
            self.cSampler1_CombinerBlend = prop_attr.blend_alpha[0]
            self.cSampler1_CombinerMode = float(hsf_properties.get_enum_int(prop_attr, "blend_combiner", prop_attr.blend_combiner))

        self.ubo.update(
            gpu.types.Buffer("UBYTE", ctypes.sizeof(self), self)
        )

    def updateTransform(self, obj: bpy.types.Object):
        set_matrix3x4(obj.matrix_world, self.cTransform)

        self.ubo.update(
            gpu.types.Buffer("UBYTE", ctypes.sizeof(self), self)
        )

    def update(self, camera: Camera):
        inv_view = camera.viewMatrix.inverted()
        #view proj and view matrices
        set_matrix(camera.viewProjectionMatrix, self.cViewProj)
        set_matrix3x4(camera.viewMatrix, self.cView)
        #inverted
        set_matrix3x4(inv_view, self.cViewInv)

        self.cZNearFar = get_vec4([camera.znear, camera.zfar, 0, 0])
        self.ubo.update(
            gpu.types.Buffer("UBYTE", ctypes.sizeof(self), self)
        )

    def bind(self, name, shader): #Binds the UBO to the given shader with the UBO name
        shader.uniform_block(name, self.ubo)
           
    def __del__(self):
        del self.ubo

class TextureObject():
    def __init__(self, img):
        self.gpuTexture = gpu.texture.from_image(img)

class SceneEngine():

    def __init__(self, previewMode):
        # Meshes with custom render attached
        self.objects: dict[str, MeshObject] = {}
        # Materials with custom render attached
        self.materials: dict[str, MaterialObject] = {}
        # Textures cached with gpu instance attached
        self.textures: dict[str, TextureObject] = {}
        # Shader instance
        self.shader: gpu.types.GPUShader = None
        self.previewMode = previewMode #for material icons
        self.camera:Camera = None
        self.contextData = None
        self.lightmapTexture = None
        self.reflectTexture = None
        self.defaultTexture = None
        self.default_material = MaterialObject(None)
        self.bone_render = None

    def get_shader(self, macros):
        shader_hash = self.computeMacroHash(macros)
        return self.shader

    def computeMacroHash(self, macros):
        hash_value = 0
        for key, value in sorted(macros.items()):
            for c in value:
                hash_value ^= ord(c)
                hash_value = (hash_value * 16777619) & 0xFFFFFFFF

        return hash_value

    def __del__(self):
        try:
            del self.objects
            del self.materials
            del self.shader
            del self.lightmapTexture
            del self.reflectTexture
            del self.defaultTexture
        except AttributeError:
            pass
        pass

    def setup_shader(self, macros = None):
        if not self.contextData:
            self.contextData = ContextUBO_struct()

        shader_info = gpu.types.GPUShaderCreateInfo()
        shader_info.vertex_in(0, 'VEC3', "vPosition")
        shader_info.vertex_in(1, 'VEC3', "vNormal")
        shader_info.vertex_in(2, 'VEC4', "vColor")
        shader_info.vertex_in(3, 'VEC2', "vTexCoords0")

        vert_out = gpu.types.GPUStageInterfaceInfo("shader_interface")
        vert_out.smooth('VEC3', "fNormal")
        vert_out.smooth('VEC4', "fColor0")
        vert_out.smooth('VEC4', "fColor1")
        vert_out.smooth('VEC2', "fSphereCoords")
        vert_out.smooth('VEC2', "fTexCoord0")
        vert_out.smooth('VEC2', "fTexCoord1")
        vert_out.smooth('VEC2', "fTexCoord2")
        vert_out.smooth('VEC2', "fHiliteCoords")

        shader_info.sampler(0, 'FLOAT_2D', "cTexture0")
        shader_info.sampler(1, 'FLOAT_2D', "cTexture1")
        shader_info.sampler(2, 'FLOAT_2D', "cTexture2")
        shader_info.sampler(3, 'FLOAT_2D', "cLightmapTexture")
        shader_info.sampler(4, 'FLOAT_2D', "cReflectionTexture")

        shader_info.uniform_buf(1, "Context", "context")

        shader_info.vertex_out(vert_out)
        shader_info.fragment_out(0, 'VEC4', "FragColor")
        shader_info.sampler(0, 'FLOAT_2D', "image")

        addOnPath = os.path.dirname(__file__)
        vertShaderPath = os.path.join(addOnPath, "Shaders", "HSF.vert")
        fragShaderPath = os.path.join(addOnPath, "Shaders", "HSF.frag")
        typedefsShaderPath = os.path.join(addOnPath, "Shaders", "TypeDefs.glsl")

        if macros:
            with open(typedefsShaderPath, "r", encoding="utf-8") as f:
                shader_info.typedef_source(self.updateShaderMacros(macros, f.read()))
        else:
            with open(typedefsShaderPath, "r", encoding="utf-8") as f:
                shader_info.typedef_source(f.read())

        with open(vertShaderPath, "r", encoding="utf-8") as f:
            shader_info.vertex_source(f.read())
        with open(fragShaderPath, "r", encoding="utf-8") as f:
            shader_info.fragment_source(f.read())

        try:
            shader = gpu.shader.create_from_info(shader_info)
        except Exception as e:
            print(e)

        print(shader)

        del vert_out
        del shader_info

        return shader

    def updateShaderMacros(self, macros, original_string):
        lines = original_string.splitlines()
        macros['BLENDER_RENDER'] = '1'
        edited_lines = []
        for line in lines:
            edited = line
            if line.startswith("#define"):
                args = line.split()
                #check if macro is edited
                if macros.get(args[1]):
                    macro_value = macros[args[1]]
                    edited = f"#define {args[1]} {macro_value}"
            edited_lines.append(edited)
        return '\n'.join(edited_lines)

    def loadGlobalTextures(self):
        if self.lightmapTexture:
            return

        addOnPath = os.path.dirname(__file__)

        self.lightmapTexture = dds.load_as_gpu_image(str(os.path.join(addOnPath, "Resources", "HsfLightMap.dds")))
        self.reflectTexture = dds.load_as_gpu_image(str(os.path.join(addOnPath, "Resources", "Reflect.dds")))

        defaultTexImg = bpy.data.images.load(str(os.path.join(addOnPath, "Resources", "Default.png")), check_existing=True)
        self.defaultTexture = gpu.texture.from_image(defaultTexImg)

    def onViewUpdate(self):
        if not self.lightmapTexture:
            self.loadGlobalTextures()

    def bindGlobalTextures(self):
        self.shader.uniform_sampler("cLightmapTexture", self.lightmapTexture)
        self.shader.uniform_sampler("cReflectionTexture", self.reflectTexture)
        self.shader.uniform_sampler("cTexture0", self.defaultTexture)
        self.shader.uniform_sampler("cTexture1", self.defaultTexture)
        self.shader.uniform_sampler("cTexture2", self.defaultTexture)

    def getTexture(self, img):
        if img is None:
            return self.defaultTexture

        if img.name not in self.textures:
            self.textures[img.name] = TextureObject(img)

        return self.textures[img.name].gpuTexture

    def getMaterial(self, slot):
        if self.materials.get(slot):
            return self.materials[slot]
        return self.default_material

    def reset_gpu_state(self):
        gpu.state.blend_set('NONE')
        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.depth_mask_set(True) 
        gpu.state.face_culling_set('NONE')

    def updateImage(self, update):
        img = update.id
        # Look for image references
        for name, mat in self.materials.items():
            self.materials[name].updateSampler(img)

    def updateMaterial(self, update):
        mat = update.id
        if self.materials.get(mat.name):
            if update.is_updated_shading and update.is_updated_geometry:
                self.materials[mat.name].updateMaterial(self, mat)
            else:
                self.materials[mat.name].updateMaterialAnimation(mat)

    def updateObject(self, update):
        obj = update.id
        if self.objects.get(obj.name):
            if update.is_updated_geometry:
                self.objects[obj.name].updateMesh(self, obj)
            if update.is_updated_transform:
                self.objects[obj.name].updateTransform(obj)

    def updateScene(self, depsgraph: bpy.types.Depsgraph, context: bpy.types.Context = None):
        pass

    def updateMeshes(self, depsgraph: bpy.types.Depsgraph, context: bpy.types.Context = None):
        for obj in depsgraph.objects:
            if obj.type != 'MESH':
                continue

            for slot in obj.material_slots:
                if slot.material:
                    mat = slot.material
                    #check if a mat instance is attached
                    if not self.materials.get(mat.name):
                        self.materials[mat.name] = MaterialObject(mat)
                        self.materials[mat.name].updateMaterial(self, mat)

            #check if a mesh instance is attached
            if not self.objects.get(obj.name):
                self.objects[obj.name] = MeshObject()
                self.objects[obj.name].updateMesh(self, obj)
                self.objects[obj.name].updateTransform(obj)

        for mat in bpy.data.materials:
            #check if a mat instance is attached
            if self.materials.get(mat.name):
                if (hasattr(mat, "hsf_properties") and mat.hsf_properties.updated):
                    mat.hsf_properties.updated = False
                    self.materials[mat.name].updateMaterial(self, mat)

        for update in depsgraph.updates:
            #check if obj is updated
            if isinstance(update.id, bpy.types.Object):
                self.updateObject(update)
            elif isinstance(update.id, bpy.types.Material):
                self.updateMaterial(update)
            elif isinstance(update.id, bpy.types.Image):
                self.updateImage(update)
            elif isinstance(update.id, bpy.types.Scene) and update.is_updated_geometry:
                pass

    def draw(self, camera): 
        if self.shader is None:
            self.shader = self.setup_shader()

        self.camera = camera 
        self.contextData.update(camera)

        if not self.bone_render:
            self.bone_render = bone_render.BoneRenderer()

        for obj in bpy.context.scene.objects:
            if not self.objects.get(obj.name):
                continue

            meshObject = self.objects[obj.name]
            # opaque only
            if meshObject.is_transparent_pass():
                continue

            meshObject.draw(self, obj)
        for obj in bpy.context.scene.objects:
            if not self.objects.get(obj.name):
                continue

            meshObject = self.objects[obj.name]
            # transparent
            if not meshObject.is_transparent_pass():
                continue

            meshObject.draw(self, obj)

        for obj in bpy.context.scene.objects:
            if obj.type != 'ARMATURE':
                continue
            self.bone_render.draw(camera, obj)

class ScreenQuad():

    def __init__(self, previewMode = False):
        self.shader: gpu.types.GPUShader = None
        self.batch = None

    def setup(self):
        shader_info = gpu.types.GPUShaderCreateInfo()
        shader_info.vertex_in(0, 'VEC3', "position")
        shader_info.vertex_in(1, 'VEC2', "texCoord")

        vert_out = gpu.types.GPUStageInterfaceInfo("shader_interface")
        vert_out.smooth('VEC2', "fTexCoords")

        shader_info.vertex_out(vert_out)
        shader_info.fragment_out(0, 'VEC4', "FragColor")
        shader_info.sampler(0, 'FLOAT_2D', "image")

        shader_info.vertex_source(
            "void main()"
            "{"
            "  fTexCoords = texCoord;"
            "  gl_Position = vec4(position.xyz, 1.0f);"
            "}"
        )

        shader_info.fragment_source(
            """
            void main()
            {
                FragColor = texture(image, fTexCoords.xy).rgba; 
                FragColor = pow(FragColor, vec4(2.2, 2.2, 2.2, 1.0));
            }
            """
        )

        self.shader = gpu.shader.create_from_info(shader_info)

        del vert_out
        del shader_info

        self.batch = batch_for_shader(
            self.shader, 'TRIS',
            {
                "position": (
                (-1, -1, 1),
                (-1, 1, 1),
                (1, 1, 1),
                
                (1, 1, 1),
                (1, -1, 1),
                (-1, -1, 1)),

                "texCoord": 
                ((0, 0),
                (0, 1),
                (1, 1), 
                
                (1, 1),
                (1, 0),
                (0, 0)),
            },
        )

    def draw(self, texture_color):
        if self.batch is None:
            self.setup()

        self.shader.bind()
        self.shader.uniform_sampler("image", texture_color)     
        self.batch.draw(self.shader)

class HsfRenderEngine(bpy.types.RenderEngine):

    bl_idname = "HSF_RENDER"
    bl_label = "HSF Render Engine"
    bl_use_preview = True
    bl_use_gpu_context = True
    use_color_management = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.mainRender = SceneEngine(False)
        self._backgroundColor = None
        self.isViewport = False
        self.dimensions = 1, 1
        self.screen_quad = ScreenQuad()
        self.framebuffer: gpu.types.Offscreen = None
        self.offscreen: gpu.types.GPUOffScreen = None

    # When the render engine instance is destroy, this is called. Clean up any
    # render engine data here, for example stopping running render threads.
    def __del__(self):
        try:
            del self.mainRender
            self.offscreen.free()
        except AttributeError:
            pass
        pass

    def _updateBackgroundColor(self, depsgraph: bpy.types.Depsgraph):
        if depsgraph.id_type_updated('WORLD') or self._backgroundColor is None:
            self._backgroundColor = (0, 0, 0)

            isTransparentFinal = depsgraph.scene.render.film_transparent and not self.isViewport
            if isTransparentFinal:
                self._backgroundColor = (0, 0, 0)
            else:
               # self._backgroundColor = np.array(depsgraph.scene.world.color[:3]) ** .4545
                self._backgroundColor = np.array(depsgraph.scene.world.color[:3])

    def onScreenSizeChanged(self, dims):
        if self.offscreen is not None:
            self.offscreen.free()
        self.offscreen = gpu.types.GPUOffScreen(*dims)

    def drawScene(self, camera: Camera):
        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.depth_mask_set(True) 

        if not self.offscreen: 
            self.offscreen = gpu.types.GPUOffScreen(*self.dimensions)

        with self.offscreen.bind():
            fbo: gpu.types.GPUFrameBuffer = gpu.state.active_framebuffer_get()
            fbo.clear(color=(*self._backgroundColor, 0), depth=1, stencil=0)

            if self.mainRender: 
                 self.mainRender.draw(camera)

        if not self.screen_quad: 
            self.screen_quad = ScreenQuad()
        self.screen_quad.draw(self.offscreen.texture_color)
        gpu.state.depth_test_set('NONE')

    # This is the method called by Blender for both final renders (F12) and
    # small preview for materials, world and lights.
    def render(self, depsgraph):
        if self.is_preview:
            return
        # TODO

    # For viewport renders, this method gets called once at the start and
    # whenever the scene or 3D viewport changes. This method is where data
    # should be read from Blender in the same thread. Typically a render
    # thread will be started to do the work while keeping Blender responsive.
    def view_update(self, context, depsgraph):
        region = context.region
        view3d = context.space_data
        scene = depsgraph.scene
        # Get viewport dimensions
        dims = region.width, region.height

        self._updateBackgroundColor(depsgraph)
        if not self.mainRender:
            self.mainRender = SceneRender(self.is_preview) 

            
        self.mainRender.onViewUpdate()
        self.mainRender.updateScene(depsgraph,context)
        self.mainRender.updateMeshes(depsgraph,context)
        self.tag_redraw()

    # For viewport renders, this method is called whenever Blender redraws
    # the 3D viewport. The renderer is expected to quickly draw the render
    # with OpenGL, and not perform other expensive work.
    # Blender will draw overlays for selection and editing on top of the
    # rendered image automatically.
    def view_draw(self, context, depsgraph):
        width, height = context.region.width, context.region.height

        camera = Camera()
        camera.projectionMatrix = context.region_data.window_matrix
        camera.viewMatrix = context.region_data.view_matrix
        camera.viewProjectionMatrix = context.region_data.perspective_matrix
        camera.width = width
        camera.height = height
        camera.znear = context.space_data.clip_start
        camera.zfar = context.space_data.clip_end

        dims = width, height
        if self.dimensions != dims:
            self.dimensions = dims
            self.onScreenSizeChanged(dims)

        self._updateBackgroundColor(depsgraph)
        self.drawScene(camera)