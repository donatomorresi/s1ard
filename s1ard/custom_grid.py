from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable

from osgeo import ogr, osr
from pyproj import Transformer
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely import wkt as shapely_wkt
from shapely.ops import transform as shp_transform


def _epsg_from_srs(srs: osr.SpatialReference | None) -> int:
    if srs is None:
        raise RuntimeError("custom tile grid has no spatial reference")
    srs = srs.Clone()
    srs.AutoIdentifyEPSG()
    epsg = srs.GetAuthorityCode(None)
    if epsg is None:
        epsg = srs.GetAuthorityCode("PROJCS")
    if epsg is None:
        epsg = srs.GetAuthorityCode("GEOGCS")
    if epsg is None:
        raise RuntimeError("could not determine EPSG code of custom tile grid")
    return int(epsg)


def _reproject_geometry(
        geometry: BaseGeometry,
        src_epsg: int,
        dst_epsg: int
) -> BaseGeometry:
    if src_epsg == dst_epsg:
        return geometry
    transformer = Transformer.from_crs(
        f"EPSG:{src_epsg}", f"EPSG:{dst_epsg}", always_xy=True
    )
    return shp_transform(transformer.transform, geometry)


def reproject_geometry(
        geometry: BaseGeometry,
        src_epsg: int,
        dst_epsg: int
) -> BaseGeometry:
    """
    Reproject a Shapely geometry between two EPSG codes.
    """
    return _reproject_geometry(geometry=geometry, src_epsg=src_epsg, dst_epsg=dst_epsg)


@dataclass(frozen=True)
class CustomTile:
    mgrs: str
    extent: dict[str, float]
    epsg: int
    geometry: BaseGeometry

    def getProjection(self, type: str = "epsg") -> int:
        if type != "epsg":
            raise ValueError("CustomTile only supports getProjection(type='epsg')")
        return self.epsg


def _read_vector_union(path: str, target_epsg: int) -> BaseGeometry:
    ds = ogr.Open(path)
    if ds is None:
        raise RuntimeError(f"could not open vector file: {path}")
    layer = ds.GetLayer(0)
    if layer is None:
        ds = None
        raise RuntimeError(f"vector file has no layers: {path}")
    src_epsg = _epsg_from_srs(layer.GetSpatialRef())
    geoms = []
    for feat in layer:
        geom_ref = feat.GetGeometryRef()
        if geom_ref is None:
            continue
        geom = shape(json.loads(geom_ref.ExportToJson()))
        geom = _reproject_geometry(geom, src_epsg=src_epsg, dst_epsg=target_epsg)
        geoms.append(geom)
    ds = None
    if len(geoms) == 0:
        raise RuntimeError(f"vector file has no geometries: {path}")
    union = geoms[0]
    for g in geoms[1:]:
        union = union.union(g)
    return union


def load_custom_tiles(
        grid_file: str,
        tile_id_field: str,
        aoi_tiles: list[str] | None = None,
        aoi_geometry: str | None = None
) -> list[CustomTile]:
    ds = ogr.Open(grid_file)
    if ds is None:
        raise RuntimeError(f"could not open custom tile grid: {grid_file}")
    layer = ds.GetLayer(0)
    if layer is None:
        ds = None
        raise RuntimeError(f"custom tile grid has no layers: {grid_file}")

    grid_epsg = _epsg_from_srs(layer.GetSpatialRef())
    aoi_geom = _read_vector_union(aoi_geometry, grid_epsg) if aoi_geometry else None
    tile_filter = set(aoi_tiles) if aoi_tiles is not None else None

    out = []
    for i, feat in enumerate(layer, start=1):
        tile_id = feat.GetField(tile_id_field)
        if tile_id is None:
            ds = None
            raise RuntimeError(
                f"feature #{i} in custom tile grid is missing field '{tile_id_field}'"
            )
        tile_id = str(tile_id).strip()
        if tile_filter is not None and tile_id not in tile_filter:
            continue
        geom_ref = feat.GetGeometryRef()
        if geom_ref is None:
            continue
        geom = shape(json.loads(geom_ref.ExportToJson()))
        if aoi_geom is not None and not geom.intersects(aoi_geom):
            continue
        xmin, ymin, xmax, ymax = geom.bounds
        out.append(
            CustomTile(
                mgrs=tile_id,
                extent={"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax},
                epsg=grid_epsg,
                geometry=geom
            )
        )
    ds = None
    if len(out) == 0:
        msg = "no custom tiles selected from the provided grid"
        if tile_filter is not None:
            msg += " (check that aoi_tiles matches IDs in custom_tile_grid)"
        raise RuntimeError(msg)
    return out


def union_extent(tiles: Iterable[CustomTile]) -> dict[str, float]:
    tiles = list(tiles)
    if len(tiles) == 0:
        raise RuntimeError("cannot compute extent from empty tile list")
    xmin = min(t.extent["xmin"] for t in tiles)
    ymin = min(t.extent["ymin"] for t in tiles)
    xmax = max(t.extent["xmax"] for t in tiles)
    ymax = max(t.extent["ymax"] for t in tiles)
    return {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax}


def union_geometry(tiles: Iterable[CustomTile]) -> BaseGeometry:
    tiles = list(tiles)
    if len(tiles) == 0:
        raise RuntimeError("cannot compute geometry from empty tile list")
    geom = tiles[0].geometry
    for tile in tiles[1:]:
        geom = geom.union(tile.geometry)
    return geom


def scene_extent_in_grid(
        scene,
        grid_epsg: int,
        clip_geometry: BaseGeometry | None = None
) -> dict[str, float] | None:
    """
    Reproject a scene footprint to `grid_epsg` and return its bounding extent.
    Optionally clip with a geometry in the same CRS.
    """
    geom_obj = scene.geometry()
    if isinstance(geom_obj, list):
        if len(geom_obj) == 0:
            return None
        geom_obj = geom_obj[0]
    if hasattr(geom_obj, "__enter__"):
        with geom_obj as vec:
            scene_epsg = vec.getProjection("epsg")
            scene_wkt = vec.convert2wkt(set3D=False)[0]
    else:
        scene_epsg = geom_obj.getProjection("epsg")
        scene_wkt = geom_obj.convert2wkt(set3D=False)[0]
    geom_scene = shapely_wkt.loads(scene_wkt)
    geom_scene = _reproject_geometry(geom_scene, src_epsg=scene_epsg, dst_epsg=grid_epsg)
    if clip_geometry is not None:
        geom_scene = geom_scene.intersection(clip_geometry)
        if geom_scene.is_empty:
            return None
    xmin, ymin, xmax, ymax = geom_scene.bounds
    return {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax}


def scene_intersects_tile(scene, tile: CustomTile) -> bool:
    geom_obj = scene.geometry()
    if isinstance(geom_obj, list):
        if len(geom_obj) == 0:
            return False
        geom_obj = geom_obj[0]
    if hasattr(geom_obj, "__enter__"):
        with geom_obj as vec:
            scene_epsg = vec.getProjection("epsg")
            scene_wkt = vec.convert2wkt(set3D=False)[0]
    else:
        scene_epsg = geom_obj.getProjection("epsg")
        scene_wkt = geom_obj.convert2wkt(set3D=False)[0]
    geom_scene = shapely_wkt.loads(scene_wkt)
    geom_scene = _reproject_geometry(geom_scene, src_epsg=scene_epsg, dst_epsg=tile.epsg)
    return tile.geometry.intersects(geom_scene)


def filter_tiles_by_scenes(tiles: list[CustomTile], scenes: list) -> list[CustomTile]:
    out = []
    for tile in tiles:
        if any(scene_intersects_tile(scene=scene, tile=tile) for scene in scenes):
            out.append(tile)
    return out
