"""A rippling surface, rebuilt every frame, with the camera circling it. (Blender, run
headless: `blender -b --factory-startup -P morph_blender.py -- --engine EEVEE|WORKBENCH
--out FILE`.)

The axes, camera, light and output are orbit_blender.py's. The surface's points are
recomputed with numpy on every frame by a frame-change handler and written with
foreach_set, the fastest way to move a mesh from Python.
"""

import argparse
import math
import sys

import bpy
import numpy as np

FPS, SECONDS = 60, 10
BLUE_D, BLUE_E, AXES = "#29ABCA", "#236B8E", "#FFFFFF"
# scene units per axis unit, as ThreeDAxes(x_length=7, z_length=4) has them
X, Z = 7 / 6, 1.0
N = 48
U, V = np.meshgrid(np.linspace(-3, 3, N + 1), np.linspace(-3, 3, N + 1), indexing="ij")


def c2p(u: np.ndarray, v: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Axis coordinates to scene points."""
    return np.stack([X * u, X * v, Z * w], -1)


def material(name: str, color: str) -> bpy.types.Material:
    """A plain material of a color given in hex (sRGB)."""
    rgb = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*linear, 1)  # Workbench's color
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (
        *linear,
        1,
    )
    return mat


def points(frame: int) -> np.ndarray:
    """The ripple's points at a frame, flat: z = 0.8 sin(2r - phase), the phase from 0 to
    4 pi over the ten seconds."""
    phase = 4 * np.pi * (frame - 1) / (SECONDS * FPS)
    return c2p(U, V, 0.8 * np.sin(2 * np.hypot(U, V) - phase)).ravel()


def surface() -> None:
    """The 48 x 48 checkerboard ripple, as one mesh whose points follow the frame."""
    i, j = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    corner = (i * (N + 1) + j).ravel()
    quads = np.stack([corner, corner + N + 1, corner + N + 2, corner + 1], -1)
    mesh = bpy.data.meshes.new("surface")
    mesh.from_pydata(points(1).reshape(-1, 3).tolist(), [], quads.tolist())
    mesh.polygons.foreach_set("material_index", ((i + j) % 2).ravel().astype(np.int32))
    mesh.polygons.foreach_set("use_smooth", np.ones(N * N, bool))
    mesh.materials.append(material("blue_d", BLUE_D))
    mesh.materials.append(material("blue_e", BLUE_E))
    bpy.context.collection.objects.link(bpy.data.objects.new("surface", mesh))

    def move(scene: bpy.types.Scene, *_: object) -> None:
        mesh.vertices.foreach_set("co", points(scene.frame_current))
        mesh.update()

    bpy.app.handlers.frame_change_pre.append(move)


def axes() -> None:
    """Three thin shafts with cone tips, from -3 to 3 (x, y) and -2 to 2 (z)."""
    white = material("axes", AXES)
    for axis, (low, high) in enumerate(
        [(-3 * X, 3 * X), (-3 * X, 3 * X), (-2 * Z, 2 * Z)]
    ):
        rotation = [(0, math.pi / 2, 0), (-math.pi / 2, 0, 0), (0, 0, 0)][axis]
        center = [0.0, 0.0, 0.0]
        center[axis] = (low + high) / 2
        bpy.ops.mesh.primitive_cylinder_add(
            radius=0.01,
            depth=high - low,
            location=center,
            rotation=rotation,
            vertices=12,
        )
        bpy.context.object.data.materials.append(white)
        tip = [0.0, 0.0, 0.0]
        tip[axis] = high
        bpy.ops.mesh.primitive_cone_add(
            radius1=0.06, depth=0.18, location=tip, rotation=rotation, vertices=16
        )
        bpy.context.object.data.materials.append(white)


def camera() -> None:
    """Manim's camera: 20 units from the origin, 8 units of frame height there, at
    phi = 65 degrees, orbiting from theta = -45 degrees at 0.3 rad/s."""
    pivot = bpy.data.objects.new("pivot", None)
    bpy.context.collection.objects.link(pivot)
    data = bpy.data.cameras.new("camera")
    data.sensor_fit = "VERTICAL"
    data.angle = 2 * math.atan(4 / 20)
    data.clip_end = 100
    cam = bpy.data.objects.new("camera", data)
    bpy.context.collection.objects.link(cam)
    phi, theta = math.radians(65), math.radians(-45)
    cam.location = (
        20 * math.sin(phi) * math.cos(theta),
        20 * math.sin(phi) * math.sin(theta),
        20 * math.cos(phi),
    )
    track = cam.constraints.new("TRACK_TO")
    track.target, track.track_axis, track.up_axis = pivot, "TRACK_NEGATIVE_Z", "UP_Y"
    cam.parent = pivot
    pivot.keyframe_insert("rotation_euler", index=2, frame=1)
    pivot.rotation_euler = (0, 0, 0.3 * SECONDS)
    pivot.keyframe_insert("rotation_euler", index=2, frame=1 + SECONDS * FPS)
    bpy.context.scene.camera = cam


def light() -> None:
    """A sun from above the camera's side, for shading in EEVEE."""
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.data.energy = 3
    sun.rotation_euler = (math.radians(40), 0, math.radians(-30))
    bpy.context.collection.objects.link(sun)


def output(engine: str, path: str) -> None:
    """1920 x 1080 at 60 fps, 600 frames, straight to an H.264 MP4 with Blender's
    settings for it; black background and the Standard view (colors as sRGB)."""
    scene = bpy.context.scene
    scene.render.engine = {"EEVEE": "BLENDER_EEVEE", "WORKBENCH": "BLENDER_WORKBENCH"}[
        engine
    ]
    scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
    scene.render.resolution_percentage = 100
    scene.render.fps = FPS
    scene.frame_start, scene.frame_end = 1, SECONDS * FPS
    scene.view_settings.view_transform = "Standard"
    scene.world = scene.world or bpy.data.worlds.new("world")
    scene.world.color = (0, 0, 0)
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (
        0,
        0,
        0,
        1,
    )
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    settings = scene.render.image_settings
    settings.media_type = "VIDEO"
    settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
    scene.render.ffmpeg.ffmpeg_preset = "GOOD"
    scene.render.filepath = path
    scene.render.use_file_extension = False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=["EEVEE", "WORKBENCH"], default="EEVEE")
    parser.add_argument("--out", default="morph.mp4")
    parser.add_argument("--frames", type=int, default=SECONDS * FPS)  # fewer, to try it
    args = parser.parse_args(
        sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    )
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"
    surface()
    axes()
    camera()
    light()
    output(args.engine, args.out)
    bpy.context.scene.frame_end = args.frames
    bpy.ops.render.render(animation=True)


main()
