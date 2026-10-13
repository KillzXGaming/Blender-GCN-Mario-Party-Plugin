import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector, Matrix
import math
import ctypes


def set_matrix(matrix : Matrix, c_float_array ):
   for i in range(4):
        c_float_array[i] =  matrix[i][:]
        
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

class BoneUBO_struct(ctypes.Structure):
    _pack_ = 16
    _fields_ = [
        ("ViewProj",       (16 * ctypes.c_float)),
        ("Model",          (16 * ctypes.c_float)),
        ("Bone",           (16 * ctypes.c_float)),
        ("Parent",         (16 * ctypes.c_float)),
        ("Rotation",       (16 * ctypes.c_float)),
        ("HasParent", ctypes.c_int), 
        ("Scale",     ctypes.c_float),
        ("IsSelected", ctypes.c_int), 
        ("Padding",   ctypes.c_int),
        ("Color",       (4 * ctypes.c_float)),
    ]

    def __init__(self): #Creates the UBO with the struct size
        self.ubo = gpu.types.GPUUniformBuf(
            gpu.types.Buffer("UBYTE", ctypes.sizeof(self), self))

    def set(self, viewproj, model, bone, parent, rotation,
             has_parent: bool, scale: float, is_selected: bool, color):
        def copy_mat(mat, dest):
            for col in range(4):
                column = mat.col[col]
                for row in range(4):
                    dest[col * 4 + row] = column[row]

        copy_mat(viewproj, self.ViewProj)
        copy_mat(model,    self.Model)
        copy_mat(bone,     self.Bone)
        copy_mat(parent,   self.Parent)
        copy_mat(rotation, self.Rotation)

        for i in range(4):
            self.Color[i] = color[i]

        self.HasParent = 1 if has_parent else 0
        self.Scale     = scale
        self.IsSelected = 1 if is_selected else 0
        self.Padding   = 0
        self.ubo.update(gpu.types.Buffer("UBYTE", ctypes.sizeof(self), self))

    def bind(self, name, shader): #Binds the UBO to the given shader with the UBO name
        shader.uniform_block(name, self.ubo)
           
    def __del__(self):
        del self.ubo

class BoneRenderer:
    def __init__(self):
        self.handle = None
        self.shader = None
        self.bone_ubo = BoneUBO_struct()
        self._create_shader()
        self._create_static_mesh()

    def _create_shader(self):
        shader_info = gpu.types.GPUShaderCreateInfo()
        shader_info.vertex_in(0, 'VEC4', "vPosition")

        shader_info.uniform_buf(1, "BoneContext", "bone")

        vert_out = gpu.types.GPUStageInterfaceInfo("shader_interface")
        vert_out.smooth('VEC4', "fColor")

        shader_info.vertex_out(vert_out)
        shader_info.fragment_out(0, 'VEC4', "FragColor")

        shader_info.vertex_source(
            '''
            void main()
            {
                vec4 pos = bone.cBone * bone.cRotation * vec4(vPosition.xyz * bone.cScale, 1.0);

                if (bone.cHasParent == 1) {
                    if (vPosition.w == 0.0)
                        pos = bone.cParent * bone.cRotation * vec4(vPosition.xyz * bone.cScale, 1.0);
                    else
                        pos = bone.cBone * bone.cRotation * vec4((vPosition.xyz - vec3(0.0, 1.0, 0.0)) * bone.cScale, 1.0);
                }
                gl_Position = bone.cViewProj * (bone.cModel * vec4(pos.xyz, 1.0));
                fColor = bone.cColor;
            }
            '''
        )
        shader_info.fragment_source(
            '''
            void main()
            {
                FragColor = fColor;
            }    
            '''
        )
        shader_info.typedef_source(
            '''
            struct BoneContext
            {
                    mat4 cViewProj;
                    mat4 cModel;
                    mat4 cBone;
                    mat4 cParent;
                    mat4 cRotation;
                    int   cHasParent;
                    float cScale;
                    int   cIsSelected;
                    int   padding;
                    vec4   cColor;
            };            
            '''
        )
        self.shader = gpu.shader.create_from_info(shader_info)

        del vert_out
        del shader_info

    def _create_static_mesh(self):
        self.verts = [
            # ---------- cube ----------
            (0, 0, -1, 0), (1, 0, 0, 0),
            (1, 0, 0, 0), (0, 0, 1, 0),
            (0, 0, 1, 0), (-1, 0, 0, 0),
            (-1, 0, 0, 0), (0, 0, -1, 0),

            # ---------- point top parentless ----------
            (0, 0, -1, 0), (0, 1, 0, 0),
            (0, 0, 1, 0), (0, 1, 0, 0),
            (1, 0, 0, 0), (0, 1, 0, 0),
            (-1, 0, 0, 0), (0, 1, 0, 0),

            # ---------- point top ----------
            (0, 0, -1, 0), (0, 1, 0, 1),
            (0, 0, 1, 0), (0, 1, 0, 1),
            (1, 0, 0, 0), (0, 1, 0, 1),
            (-1, 0, 0, 0), (0, 1, 0, 1),

            # ---------- point bottom ----------
            (0, 0, -1, 0), (0, -1, 0, 0),
            (0, 0, 1, 0), (0, -1, 0, 0),
            (1, 0, 0, 0), (0, -1, 0, 0),
            (-1, 0, 0, 0), (0, -1, 0, 0),
        ]
        self.batch = batch_for_shader(
            self.shader,
            'LINES',
            {"vPosition": self.verts}
        )


    def draw(self, camera, arm_obj):
        if arm_obj.type != 'ARMATURE' or not arm_obj.pose.bones:
            return
            
        # Settings
        radius = 0.08
        color = (0.9, 0.9, 0.95, 1.0)
        selected_color = (1.0, 0.6, 0.2, 1.0)
        
        # Get view projection matrix
        view_matrix = camera.viewMatrix
        proj_matrix = camera.projectionMatrix
        vp_matrix = proj_matrix @ view_matrix
        model = Matrix.Identity(4)

        self.shader.bind()
        gpu.state.face_culling_set('NONE')
        if arm_obj.show_in_front:
            gpu.state.depth_test_set('NONE')
        else:
            gpu.state.depth_test_set('LESS_EQUAL')

        selected_index = -1
        for idx, pbone in enumerate(arm_obj.pose.bones):
            bone = pbone.bone
            if bone.hide:
                continue

            bone_mat = arm_obj.matrix_world @ pbone.matrix

            parent_mat = Matrix.Identity(4)
            has_parent = False
            parent_pbone = pbone.parent
            if parent_pbone:
                parent_mat = arm_obj.matrix_world @ parent_pbone.matrix
                has_parent = True

            scale = 1
            color = [1, 1, 0, 1]
            if pbone.select:
                color = [1, 1, 1, 1]

            self.bone_ubo.set(
                vp_matrix,
                model,
                bone_mat,
                parent_mat,
                Matrix.Identity(4),
                has_parent,
                scale, 
                idx == selected_index,
                color,
            )

            self.bone_ubo.bind("bone", self.shader)
            self.batch.draw(self.shader)

        for idx, pbone in enumerate(arm_obj.pose.bones):
            bone = pbone.bone
            if bone.hide:
                continue

            bone_mat = arm_obj.matrix_world @ pbone.matrix
            scale = 1
            color = [1, 1, 0, 1]
            if pbone.select:
                color = [1, 1, 1, 1]
                scale = 2

            self.bone_ubo.set(
                vp_matrix,
                model,
                bone_mat,
                Matrix.Identity(4),
                Matrix.Identity(4),
                False,
                scale, 
                idx == selected_index,
                color,
            )

            self.bone_ubo.bind("bone", self.shader)
            self.batch.draw(self.shader)

        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.blend_set('NONE')
        gpu.state.face_culling_set('NONE')