# Source: manim/scene/moving_camera_scene.py
import manimgx as m


def _set_frame_width(frame, width):
    frame.width = width
    return frame


def _ensure_frame_supports_set_width(frame):
    if not hasattr(type(frame), "set_width"):
        type(frame).set_width = _set_frame_width


class ChangingCameraWidthAndRestore(m.MovingCameraScene):
    def construct(self):
        text = m.Text("Hello World").set_color(m.BLUE)
        self.add(text)
        self.camera.frame.save_state()
        _ensure_frame_supports_set_width(self.camera.frame)
        self.play(self.camera.frame.animate.set_width(text.width * 1.2))
        self.wait(0.3)
        self.play(m.Restore(self.camera.frame))
