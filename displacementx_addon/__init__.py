from .addon import register as _reg
from .addon import unregister as _unreg

bl_info = {
    "name": "Synth Surface - Procedural Greeble Textures",
    "author": "Nopeburger",
    "version": (1, 2, 0),
    "blender": (3, 0, 0),
    "location": "3D Viewport > Sidebar > Synth Surface",
    "description": "Generates float32 greeble maps, scattered emission lights and displacement, with EXR export",
    "category": "Material",
}

def register():
    _reg()

def unregister():
    _unreg()
