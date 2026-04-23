import cesard.tile_extraction as tile_ex


def expected_sar_epsgs(scene, use_custom_sar_geocode, custom_grid_epsg, log=None):
    """
    Determine expected SAR geocoding EPSG targets for one scene.
    """
    if use_custom_sar_geocode:
        return [custom_grid_epsg]
    try:
        aois = tile_ex.aoi_from_scene(scene=scene, multi=True)
    except Exception as e:
        if log is not None:
            log.debug(f"could not derive expected UTM EPSGs for scene {scene.scene}: {e}")
        return []
    epsgs = sorted(set([x['epsg'] for x in aois if isinstance(x, dict) and 'epsg' in x]))
    return epsgs


def sar_outputs_complete(processor, scene_path, sar_dir, epsgs, log=None):
    """
    Check whether processor outputs already exist for all expected geocoding EPSGs.
    """
    if epsgs is None or len(epsgs) == 0:
        return False
    for epsg in epsgs:
        try:
            files = processor.find_datasets(scene=scene_path, outdir=sar_dir, epsg=epsg)
        except Exception as e:
            if log is not None:
                log.debug(f"find_datasets failed for scene {scene_path} EPSG:{epsg}: {e}")
            return False
        if files is None:
            return False
    return True
