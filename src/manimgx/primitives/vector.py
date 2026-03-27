from typing import Any, Final, Literal

import numpy as np

type Vec3 = np.ndarray[tuple[Literal[3]], np.dtype[np.floating]]
type Vec4 = np.ndarray[tuple[Literal[4]], np.dtype[np.floating]]

type Vec3DArray = np.ndarray[tuple[int, int], np.dtype[np.floating[Any]]]


def freeze_numpy_array(arr: Vec3) -> Vec3:
    arr.flags.writeable = False
    return arr


LEFT: Final[Vec3] = freeze_numpy_array(np.array([-1.0, 0.0, 0.0]))
RIGHT: Final[Vec3] = freeze_numpy_array(np.array([1.0, 0.0, 0.0]))
UP: Final[Vec3] = freeze_numpy_array(np.array([0.0, 1.0, 0.0]))
DOWN: Final[Vec3] = freeze_numpy_array(np.array([0.0, -1.0, 0.0]))
OUT: Final[Vec3] = freeze_numpy_array(np.array([0.0, 0.0, 1.0]))
IN: Final[Vec3] = freeze_numpy_array(np.array([0.0, 0.0, -1.0]))
ORIGIN: Final[Vec3] = freeze_numpy_array(np.array([0.0, 0.0, 0.0]))
