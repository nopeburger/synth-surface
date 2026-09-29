from .addon import register as _reg
from .addon import unregister as _unreg

bl_info = {
    "name": "Synth Surface - Procedural Greeble Textures",
    "author": "Nopeburger",
    "version": (1, 1, 0),
    "blender": (3, 0, 0),
    "location": "3D Viewport > Sidebar > Synth Surface",
    "description": "Generates greeble color/height/normal textures with scattered emission lights and displacement",
    "category": "Material",
}

def register():
    _reg()

def unregister():
    _unreg()
