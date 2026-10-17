"""Manim's authoring API, backed by ManimGX's scene, object and animation models."""

import numpy as np

from manimgx import audio as voices
from manimgx import constants
from manimgx.animation import easing, matching, motion, timeline, updaters
from manimgx.animation.easing import *
from manimgx.animation.matching import *
from manimgx.animation.motion import *
from manimgx.animation.timeline import *
from manimgx.animation.transform import Animate
from manimgx.animation.updaters import *
from manimgx.audio import Speech
from manimgx.audio.sound import Sound
from manimgx.config import Degrees, Munits, Percent, Pixels, config
from manimgx.constants import *
from manimgx.drawing import paint
from manimgx.drawing.geometry import (
    STRAIGHT_PATH_THRESHOLD,
    Coefficients,
    Floats,
    Path,
    QuickHull,
    R3_to_complex,
    Step,
    angle_axis_from_quaternion,
    angle_between_vectors,
    angle_of_vector,
    bezier,
    carried,
    cartesian_to_spherical,
    center_of_mass,
    clockwise_path,
    compass_directions,
    complex_func_to_R3_func,
    complex_to_R3,
    counterclockwise_path,
    cross2d,
    earclip_triangulation,
    find_intersection,
    get_unit_normal,
    get_winding_number,
    interpolate,
    inverse_interpolate,
    line_intersection,
    midpoint,
    norm_squared,
    normalize,
    normalize_along_axis,
    path_along_arc,
    path_along_circles,
    perpendicular_bisector,
    polylabel,
    quaternion_conjugate,
    quaternion_from_angle_axis,
    quaternion_mult,
    regular_vertices,
    rotate_vector,
    rotation_about_z,
    rotation_matrix,
    rotation_matrix_from_quaternion,
    rotation_matrix_transpose,
    rotation_matrix_transpose_from_quaternion,
    shoelace,
    shoelace_direction,
    sigmoid,
    spherical_to_cartesian,
    spiral_path,
    straight_path,
    thick_diagonal,
    z_to_vector,
)
from manimgx.drawing.paint import *
from manimgx.drawing.paint import stretch_array_to_length
from manimgx.mobject import (
    ComplexValueTracker,
    Group,
    MeshMobject,
    Mobject,
    Mobject1D,
    PGroup,
    PMobject,
    Point,
    ValueTracker,
    VDict,
    VectorizedPoint,
    VGroup,
    VMobject,
    override_animate,
    override_animation,
    remove_list_redundancies,
)
from manimgx.mobjects import (
    annotations,
    code,
    graph,
    grid,
    lights,
    logo,
    plotting,
    shapes,
    three_d,
    vector_field,
)
from manimgx.mobjects.annotations import *
from manimgx.mobjects.code import *
from manimgx.mobjects.graph import *
from manimgx.mobjects.grid import *
from manimgx.mobjects.images import ImageMobject, ImageMobjectFromCamera
from manimgx.mobjects.lights import *
from manimgx.mobjects.logo import *
from manimgx.mobjects.numbers import DecimalNumber, Integer, Variable, index_labels
from manimgx.mobjects.plotting import *
from manimgx.mobjects.shapes import *
from manimgx.mobjects.shapes import PointCloudDot
from manimgx.mobjects.svg import SVGMobject, VMobjectFromSVGPath
from manimgx.mobjects.text import (
    BulletedList,
    MathTex,
    MathTexPart,
    MathTypst,
    Paragraph,
    SingleStringMathTex,
    Tex,
    Text,
    Title,
    Typst,
)
from manimgx.mobjects.three_d import *
from manimgx.mobjects.vector_field import *
from manimgx.rendering.film import Film
from manimgx.rendering.window import Window
from manimgx.scene import (
    Camera,
    LinearTransformationScene,
    MovingCameraScene,
    Scene,
    ThreeDScene,
    VectorScene,
    ZoomedScene,
)

# the authoring API: what `from manimgx import *` brings, and what a type checker takes as
# exported (a typed package's imports are private to it unless `__all__` names them)
__all__ = [
    "STRAIGHT_PATH_THRESHOLD",
    "Animate",
    "BulletedList",
    "Camera",
    "Coefficients",
    "ComplexValueTracker",
    "DecimalNumber",
    "Degrees",
    "Film",
    "Group",
    "ImageMobject",
    "ImageMobjectFromCamera",
    "Integer",
    "LinearTransformationScene",
    "MathTex",
    "MathTexPart",
    "MathTypst",
    "MeshMobject",
    "Mobject",
    "Mobject1D",
    "MovingCameraScene",
    "Munits",
    "PGroup",
    "PMobject",
    "Paragraph",
    "Path",
    "Percent",
    "Pixels",
    "Point",
    "QuickHull",
    "R3_to_complex",
    "SVGMobject",
    "Scene",
    "SingleStringMathTex",
    "Sound",
    "Speech",
    "Step",
    "Tex",
    "Text",
    "ThreeDScene",
    "Title",
    "Typst",
    "VDict",
    "VGroup",
    "VMobject",
    "VMobjectFromSVGPath",
    "ValueTracker",
    "Variable",
    "VectorScene",
    "VectorizedPoint",
    "Window",
    "ZoomedScene",
    "angle_axis_from_quaternion",
    "angle_between_vectors",
    "angle_of_vector",
    "bezier",
    "carried",
    "cartesian_to_spherical",
    "center_of_mass",
    "clockwise_path",
    "compass_directions",
    "complex_func_to_R3_func",
    "complex_to_R3",
    "config",
    "counterclockwise_path",
    "cross2d",
    "earclip_triangulation",
    "find_intersection",
    "get_unit_normal",
    "get_winding_number",
    "index_labels",
    "interpolate",
    "inverse_interpolate",
    "line_intersection",
    "midpoint",
    "norm_squared",
    "normalize",
    "normalize_along_axis",
    "override_animate",
    "override_animation",
    "path_along_arc",
    "path_along_circles",
    "perpendicular_bisector",
    "polylabel",
    "quaternion_conjugate",
    "quaternion_from_angle_axis",
    "quaternion_mult",
    "regular_vertices",
    "remove_list_redundancies",
    "rotate_vector",
    "rotation_about_z",
    "rotation_matrix",
    "rotation_matrix_from_quaternion",
    "rotation_matrix_transpose",
    "rotation_matrix_transpose_from_quaternion",
    "shoelace",
    "shoelace_direction",
    "sigmoid",
    "spherical_to_cartesian",
    "spiral_path",
    "straight_path",
    "stretch_array_to_length",
    "thick_diagonal",
    "voices",
    "z_to_vector",
]
__all__ += easing.__all__
__all__ += matching.__all__
__all__ += motion.__all__
__all__ += timeline.__all__
__all__ += updaters.__all__
__all__ += constants.__all__
__all__ += paint.__all__
__all__ += annotations.__all__
__all__ += code.__all__
__all__ += graph.__all__
__all__ += grid.__all__
__all__ += lights.__all__
__all__ += logo.__all__
__all__ += plotting.__all__
__all__ += shapes.__all__
__all__ += three_d.__all__
__all__ += vector_field.__all__
