import numpy as np

from manimgx.primitives.vector import Vec3, Vec3DArray, Vec4

IDENTITY_QUAT: Vec4 = np.array([0.0, 0.0, 0.0, 1.0])
IDENTITY_QUAT.flags.writeable = False


def quat_from_angle_axis(angle: float, axis: Vec3) -> Vec4:

    norm = float(np.linalg.norm(axis))
    if norm == 0.0:
        return IDENTITY_QUAT.copy()
    normalized = axis / norm
    half = angle / 2.0
    sin_half = np.sin(half)
    return np.array([*(sin_half * normalized), np.cos(half)])


def quat_multiply(q1: Vec4, q2: Vec4) -> Vec4:

    x1, y1, z1, w1 = q1
    x2, y2, z2, w2 = q2
    return np.array(
        [
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        ]
    )


def quat_conjugate(q: Vec4) -> Vec4:
    """Return the conjugate (inverse for unit quaternions)."""
    return np.array([-q[0], -q[1], -q[2], q[3]])


def quat_rotate_vectors(q: Vec4, vs: Vec3DArray) -> Vec3DArray:

    qv = q[:3]
    qw = q[3]
    t = 2.0 * np.cross(qv, vs)
    return vs + qw * t + np.cross(qv, t)
