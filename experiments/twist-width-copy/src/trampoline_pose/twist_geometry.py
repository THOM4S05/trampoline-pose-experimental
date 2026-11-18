"""Explicit segment Cardan geometry for the offline twist experiment.

Matrices map body columns (right, anterior, superior) to a fixed camera frame.
This is a torso proxy, not an inertia-axis whole-body measurement. See
docs/TWIST-EXPERIMENT.md for the restricted domain and camera conventions.
"""
from __future__ import annotations

import math
import numpy as np
from scipy.spatial.transform import Rotation

TAU = 2 * math.pi
CONVENTION = "body-right-anterior-superior; active-columns; reference-RxRyRz-v1"


def rotation_matrix(value):
    """Reject reflections, scale, NaNs and malformed matrices; never repair them."""
    matrix = np.asarray(value, dtype=float)
    if (matrix.shape != (3, 3) or not np.isfinite(matrix).all()
            or not np.allclose(matrix.T @ matrix, np.eye(3), atol=1e-5)
            or not np.isclose(np.linalg.det(matrix), 1, atol=1e-5)):
        raise ValueError("Expected a finite right-handed rotation matrix")
    return matrix


def quaternion_matrix(xyzw):
    q = np.asarray(xyzw, dtype=float)
    if q.shape != (4,) or not np.isfinite(q).all() or not np.isclose(np.linalg.norm(q), 1, atol=1e-5):
        raise ValueError("Expected a unit quaternion in explicit xyzw order")
    return Rotation.from_quat(q).as_matrix()


def wrap(angle):
    return (angle + math.pi) % TAU - math.pi


def segment_frame(left, right, inferior, superior):
    """Anatomical lateral direction orthogonalized to a measured long axis."""
    left, right, inferior, superior = np.asarray([left, right, inferior, superior], dtype=float)
    if left.shape != (3,) or not np.isfinite([left, right, inferior, superior]).all():
        raise ValueError("Invalid segment landmarks")
    z = superior - inferior
    if np.linalg.norm(z) < 1e-6:
        raise ValueError("Degenerate longitudinal axis")
    z /= np.linalg.norm(z)
    lateral = right - left
    x = lateral - z * np.dot(lateral, z)
    if np.linalg.norm(x) < max(1e-6, .05 * np.linalg.norm(lateral)):
        raise ValueError("Degenerate lateral axis")
    x /= np.linalg.norm(x)
    return rotation_matrix(np.column_stack((x, np.cross(z, x), z)))


def undo_crop_camera(matrix, source_to_model_camera):
    """Undo the *3D* camera rotation, separately from any pixel affine inverse."""
    return rotation_matrix(source_to_model_camera).T @ rotation_matrix(matrix)


def image_ccw_camera(degrees):
    """OpenCV x-right/y-down/z-forward camera change for an in-plane CCW crop."""
    if not math.isfinite(degrees) or abs(degrees / 90 - round(degrees / 90)) > 1e-8:
        raise ValueError("Only explicit right-angle crop rotations are supported")
    return Rotation.from_rotvec([0, 0, -math.radians(degrees)]).as_matrix()


def cardan(matrix, reference, singular_cos=.2):
    """R_ref.T R = Rx(somersault) Ry(tilt) Rz(twist), |tilt| < pi/2.

    R02=sin(tilt), (-R12,R22)=cos(tilt)(sin(s),cos(s)),
    (-R01,R00)=cos(tilt)(sin(w),cos(w)). No angular-velocity integral.
    """
    r = rotation_matrix(reference).T @ rotation_matrix(matrix)
    tilt = math.asin(float(np.clip(r[0, 2], -1, 1)))
    if abs(math.cos(tilt)) < singular_cos:
        raise ValueError("Cardan tilt singularity or ill-conditioned decomposition")
    return dict(somersault=math.atan2(-r[1, 2], r[2, 2]), tilt=tilt,
                twist=math.atan2(-r[0, 1], r[0, 0]))


def upright_heading(matrix, reference, max_lean_degrees=25):
    """Heading is a twist proxy ONLY while the entire torso stays upright."""
    r = rotation_matrix(reference).T @ rotation_matrix(matrix)
    if r[2, 2] < math.cos(math.radians(max_lean_degrees)):
        raise ValueError("Upright heading branch used outside its upright domain")
    return math.atan2(r[1, 0], r[0, 0])
