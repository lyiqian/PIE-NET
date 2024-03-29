"""Training data preparations."""
import pathlib
import re

import numpy as np
import pandas as pd
import pymeshlab as pml
import yaml

DATA_DIR = pathlib.Path("./data/")
FEAT_DIR = DATA_DIR / "feat"

N_SAMPLING_POINTS = 8096


def generate_one_pcloud(feat_path):
    obj_path = _get_corresponding_obj_path(feat_path)
    cad_model = read_obj(obj_path)
    feat = read_feat(feat_path)

    pcloud = sample_point_cloud(cad_model)

    curv = mark_edges_and_corners(cad_model.mesh(0), feat)

    pcloud_ = transfer_labels(curv, pcloud)

    write_pcloud(pcloud_, orig_feat_path=feat_path)


def read_obj(path) -> pml.MeshSet:
    ms = pml.MeshSet()
    ms.load_new_mesh(str(path))
    return ms


def read_feat(path) -> dict:
    with open(path, "r") as fi:
        feat = yaml.load(fi, yaml.CLoader)
    return feat


def sample_point_cloud(ms: pml.MeshSet) -> pd.DataFrame:
    ms.set_current_mesh(0)
    ms.generate_sampling_montecarlo(samplenum=N_SAMPLING_POINTS)

    pcloud = pd.DataFrame(
        ms.current_mesh().vertex_matrix(),
        columns=["x", "y", "z"]
    )
    return pcloud


def mark_edges_and_corners(mesh: pml.Mesh, feat: dict) -> pd.DataFrame:
    orig_points = mesh.vertex_matrix()

    curv_info = pd.DataFrame(feat["curves"])
    edge_point_idxs = curv_info.vert_indices.explode().astype(int)

    curv = (
        edge_point_idxs
            .rename("idx").to_frame()
            .rename_axis("curv_id").reset_index()
            .pipe(_mark_corner)
            .pipe(_merge_coords, orig_points=orig_points)
    )

    return curv


def transfer_labels(curv: pd.DataFrame, pcloud: pd.DataFrame) -> pd.DataFrame:
    curv_ = curv.drop_duplicates(subset=["idx"])

    pcloud_df_idxs = curv_.apply(_transfer_gt_labels, pcloud=pcloud, axis=1)

    pcloud_ = (
        curv_
            .assign(pcloud_df_idx=pcloud_df_idxs)
            .merge(pcloud,
                   how="right",
                   left_on="pcloud_df_idx", right_index=True,
                   suffixes=("_orig", None))
            .drop(columns=["idx", "pcloud_df_idx"])
            .reset_index(drop=True)
            .assign(is_edge=lambda df: df.is_corner.notna(),
                    is_corner=lambda df: df.is_corner == True)
    )
    return pcloud_


def write_pcloud(pcloud_: pd.DataFrame, orig_feat_path):
    filename = _format_pcloud_filename(orig_feat_path)
    filepath = DATA_DIR / "pcloud" / filename
    pcloud_.to_parquet(filepath)


def _get_corresponding_obj_path(feat_path: pathlib.Path):
    path_id = feat_path.parent.name
    obj_paths = list((DATA_DIR / "obj" / path_id).glob("*.obj"))
    assert len(obj_paths) == 1, f"not 1-to-1 mapping for {path_id}"
    return obj_paths[0]


def _mark_corner(edge: pd.DataFrame):
    val_counts = edge.idx.value_counts()
    return edge.assign(is_corner=edge.idx.map(lambda i: val_counts[i] > 1))


def _merge_coords(edge, orig_points):
    return edge.assign(
        x=edge.idx.map(lambda i: orig_points[i][0]),
        y=edge.idx.map(lambda i: orig_points[i][1]),
        z=edge.idx.map(lambda i: orig_points[i][2]),
    )


def _transfer_gt_labels(row: pd.Series, pcloud: pd.DataFrame):
    dist_vects = pcloud[["x", "y", "z"]].values - row[["x", "y", "z"]].values
    dist = np.square(dist_vects).sum(axis=1)
    return dist.argmin()


def _format_pcloud_filename(feat_path):
    feat_path = pathlib.Path(feat_path)
    prefix = re.match(r"([^_]+)_", feat_path.name).group(1)
    return f"{prefix}_pcloud_points.parq"
