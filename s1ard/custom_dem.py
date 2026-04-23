import os
import json
import hashlib
import shutil
import urllib.parse
import urllib.request
import urllib.error
import re
import numpy as np
from scipy.interpolate import RegularGridInterpolator
from osgeo import osr
from osgeo import gdal
from spatialist.auxil import gdalwarp
from cesard.ancillary import pixel_size_degrees

gdal.UseExceptions()


def _epsg_from_wkt(wkt):
    if wkt in [None, '']:
        return None
    srs = osr.SpatialReference()
    srs.ImportFromWkt(wkt)
    srs = srs.Clone()
    srs.AutoIdentifyEPSG()
    epsg = srs.GetAuthorityCode(None)
    if epsg is None:
        epsg = srs.GetAuthorityCode('PROJCS')
    if epsg is None:
        epsg = srs.GetAuthorityCode('GEOGCS')
    if epsg is None:
        return None
    return int(epsg)


def _download_file(url, dst, log=None):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if log is not None:
        log.info(f"downloading custom geoid model: {dst} <<-- {url}")
    tmp = f'{dst}.part.{os.getpid()}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 's1ard/ISG-geoid-fetch'})
        with urllib.request.urlopen(req) as response, open(tmp, 'wb') as out:
            shutil.copyfileobj(response, out)
        if os.path.getsize(tmp) == 0:
            raise RuntimeError(f"downloaded custom geoid model is empty: {url}")
        os.replace(tmp, dst)
    except (urllib.error.URLError, RuntimeError, OSError) as e:
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise RuntimeError(f"failed to download custom geoid model: {url} ({e})")


def _scene_extent(scene, buffer=0.002):
    with scene.bbox(buffer=buffer) as geom:
        return geom.extent


def _target_resolution(ext, spacing):
    lon_center = (ext['xmin'] + ext['xmax']) / 2.0
    lat_center = (ext['ymin'] + ext['ymax']) / 2.0
    target_res = pixel_size_degrees(lon_center, lat_center, float(spacing), float(spacing))
    if isinstance(target_res, (tuple, list)):
        return float(target_res[0]), float(target_res[1])
    return float(target_res), float(target_res)


def _warp_dem(src, dst, bounds_4326, src_nodata=None, dst_srs='EPSG:4326',
              xres=None, yres=None, target_aligned=False, resample='bilinear'):
    warp_kwargs = dict(
        src=src,
        dst=dst,
        outputBounds=bounds_4326,
        format='GTiff',
        multithread=True,
        creationOptions=['TILED=YES', 'COMPRESS=LZW', 'BIGTIFF=IF_SAFER']
    )
    if dst_srs is not None:
        warp_kwargs['dstSRS'] = dst_srs
    if src_nodata is not None:
        warp_kwargs['srcNodata'] = src_nodata
        warp_kwargs['dstNodata'] = src_nodata
        warp_kwargs['warpOptions'] = ['UNIFIED_SRC_NODATA=YES']
    if xres is not None and yres is not None:
        warp_kwargs['xRes'] = xres
        warp_kwargs['yRes'] = yres
        warp_kwargs['targetAlignedPixels'] = target_aligned
        warp_kwargs['resampleAlg'] = resample
    gdalwarp(**warp_kwargs)


def prepare_custom_geoid_model(geoid_isg, cache_dir, work_dir=None, log=None):
    """
    Prepare a custom ISG geoid model from either URL or local path.
    """
    if geoid_isg in [None, '', 'None']:
        return None, None
    source = str(geoid_isg).strip()
    is_url = re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', source) is not None

    if is_url:
        parsed = urllib.parse.urlparse(source)
        if parsed.scheme not in ['http', 'https', 'ftp']:
            raise RuntimeError("custom_dem_geoid_isg URL must use http/https/ftp")
        if not (parsed.path or '').lower().endswith('.isg'):
            if log is not None:
                log.warning("custom_dem_geoid_isg URL does not end with '.isg'. Proceeding anyway.")
        src_name = os.path.basename(parsed.path) or 'custom_geoid_model.isg'
        key_raw = json.dumps({'source': source}, sort_keys=True)
        key = hashlib.sha256(key_raw.encode('utf-8')).hexdigest()[:16]
        root = os.path.join(cache_dir, 'custom_geoid_models', key)
        os.makedirs(root, exist_ok=True)
        marker = os.path.join(root, 'model.json')
        if os.path.isfile(marker):
            with open(marker, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            model_path = meta.get('model_path')
            if model_path is not None and os.path.isfile(model_path):
                try:
                    model_path = _ensure_geoid_model_gdal_readable(model_path=model_path)
                    return model_path
                except RuntimeError as e:
                    if log is not None:
                        log.warning(f"cached custom geoid model is unreadable and will be refreshed: {e}")
                    try:
                        os.remove(marker)
                    except OSError:
                        pass
                    try:
                        if os.path.abspath(model_path).startswith(os.path.abspath(root)):
                            os.remove(model_path)
                    except OSError:
                        pass

        src_local = os.path.join(root, src_name)
        refresh = False
        if os.path.isfile(src_local):
            try:
                model_path = _ensure_geoid_model_gdal_readable(model_path=src_local)
            except RuntimeError as e:
                refresh = True
                if log is not None:
                    log.warning(f"cached custom geoid model is unreadable and will be downloaded again: {e}")
        else:
            refresh = True
        if refresh:
            try:
                if os.path.isfile(src_local):
                    os.remove(src_local)
            except OSError:
                pass
            _download_file(url=source, dst=src_local, log=log)
            model_path = _ensure_geoid_model_gdal_readable(model_path=src_local)
        with open(marker, 'w', encoding='utf-8') as f:
            json.dump({'model_path': model_path, 'format': 'isg', 'source': source}, f, indent=2)
        if log is not None:
            log.info(f"prepared custom geoid ISG model: {model_path}")
        return model_path

    model_path = source
    if not os.path.isabs(model_path) and work_dir not in [None, '', 'None']:
        model_path = os.path.join(work_dir, model_path)
    if not os.path.isfile(model_path):
        raise RuntimeError(f"custom_dem_geoid_isg file does not exist: {model_path}")
    if not model_path.lower().endswith('.isg'):
        if log is not None:
            log.warning("custom_dem_geoid_isg local path does not end with '.isg'. Proceeding anyway.")
    model_path = _ensure_geoid_model_gdal_readable(model_path=model_path)
    if log is not None:
        log.info(f"using local custom geoid ISG model: {model_path}")
    return model_path


def _ensure_geoid_model_gdal_readable(model_path):
    if gdal.GetDriverByName('ISG') is None:
        raise RuntimeError(
            "GDAL ISG driver is not available in this environment; "
            f"cannot read custom geoid model: {model_path}"
        )
    try:
        ds = gdal.Open(model_path)
    except RuntimeError:
        ds = None
    if ds is not None:
        ds = None
        return model_path
    size = os.path.getsize(model_path) if os.path.isfile(model_path) else 0
    raise RuntimeError(
        f"ISG geoid model is not readable by GDAL ISG driver: {model_path} "
        f"(size={size} bytes)"
    )


def _geoid_interpolator_from_raster(path):
    try:
        ds = gdal.Open(path)
    except RuntimeError:
        return None
    if ds is None:
        return None
    gt = ds.GetGeoTransform(can_return_null=True)
    if gt is None:
        ds = None
        return None
    if abs(gt[2]) > 1e-12 or abs(gt[4]) > 1e-12:
        ds = None
        raise RuntimeError("rotated geoid rasters are not supported")
    band = ds.GetRasterBand(1)
    arr = band.ReadAsArray().astype(np.float32)
    nodata = band.GetNoDataValue()
    if nodata is not None:
        arr[arr == nodata] = np.nan
    nrows, ncols = arr.shape
    lons = gt[0] + (np.arange(ncols) + 0.5) * gt[1]
    lats = gt[3] + (np.arange(nrows) + 0.5) * gt[5]
    if lats[0] > lats[-1]:
        lats = lats[::-1]
        arr = arr[::-1, :]
    if lons[0] > lons[-1]:
        lons = lons[::-1]
        arr = arr[:, ::-1]
    ds = None
    return RegularGridInterpolator((lats, lons), arr, method='linear', bounds_error=False, fill_value=np.nan)


def _build_geoid_interpolator(path):
    interp = _geoid_interpolator_from_raster(path)
    if interp is not None:
        return interp
    raise RuntimeError(f"ISG geoid model is not readable by GDAL: {path}")


def _apply_geoid(src_dem_4326, dst_dem_4326, geoid_model_path,
                 geoid_block_size=1024, log=None):
    interp = _build_geoid_interpolator(path=geoid_model_path)
    ds = gdal.Open(src_dem_4326)
    if ds is None:
        raise RuntimeError(f"could not open temporary DEM for geoid correction: {src_dem_4326}")
    band = ds.GetRasterBand(1)
    nodata = band.GetNoDataValue()
    gt = ds.GetGeoTransform()
    proj = ds.GetProjection()
    xsize = ds.RasterXSize
    ysize = ds.RasterYSize
    out_nodata = nodata if nodata is not None else -9999.0

    driver = gdal.GetDriverByName('GTiff')
    out_ds = driver.Create(
        dst_dem_4326, xsize, ysize, 1, gdal.GDT_Float32,
        options=['TILED=YES', 'COMPRESS=LZW', 'BIGTIFF=IF_SAFER']
    )
    if out_ds is None:
        raise RuntimeError(f"could not create geoid-corrected DEM: {dst_dem_4326}")
    out_ds.SetGeoTransform(gt)
    out_ds.SetProjection(proj)
    out_band = out_ds.GetRasterBand(1)
    out_band.SetNoDataValue(out_nodata)

    # Process DEM in windows to avoid loading full arrays in memory.
    try:
        block_size = int(geoid_block_size)
    except ValueError:
        block_size = 1024
    block_size = max(128, block_size)

    nan_found = False
    for yoff in range(0, ysize, block_size):
        ywin = min(block_size, ysize - yoff)
        for xoff in range(0, xsize, block_size):
            xwin = min(block_size, xsize - xoff)

            arr = band.ReadAsArray(xoff, yoff, xwin, ywin).astype(np.float64)
            if nodata is not None:
                mask = (arr == nodata) | np.isnan(arr)
            else:
                mask = np.isnan(arr)

            # Pixel center coordinates with full geotransform support
            cols = np.arange(xoff, xoff + xwin, dtype=np.float64) + 0.5
            rows = np.arange(yoff, yoff + ywin, dtype=np.float64) + 0.5
            xv, yv = np.meshgrid(cols, rows)
            lon = gt[0] + xv * gt[1] + yv * gt[2]
            lat = gt[3] + xv * gt[4] + yv * gt[5]
            points = np.column_stack((lat.ravel(), lon.ravel()))

            n_vals = interp(points).reshape((ywin, xwin))
            n_invalid = np.isnan(n_vals)
            if np.any(n_invalid):
                nan_found = True
                mask = mask | n_invalid

            arr_out = arr + n_vals
            arr_out[mask] = out_nodata
            out_band.WriteArray(arr_out.astype(np.float32), xoff, yoff)

    if nan_found and log is not None:
        log.warning("geoid interpolation returned NaN for part of DEM extent; these pixels will be set to nodata")

    out_band.FlushCache()
    out_ds = None
    ds = None


def _finalize_dem(apply_geoid, tmp_dem_ortho, out_dem, geoid_model_path,
                  geoid_block_size, geoid_block_size_log, log=None):
    if not apply_geoid:
        return out_dem
    if log is not None:
        log.info(f"applying geoid correction to DEM heights "
                 f"(block size: {geoid_block_size_log}x{geoid_block_size_log} pixels)")
    _apply_geoid(
        src_dem_4326=tmp_dem_ortho,
        dst_dem_4326=out_dem,
        geoid_model_path=geoid_model_path,
        geoid_block_size=geoid_block_size,
        log=log
    )
    if os.path.isfile(tmp_dem_ortho):
        os.remove(tmp_dem_ortho)
    return out_dem


def prepare_custom_dem(custom_dem_file, scene, tmp_dir_scene, spacing, geoid_model_path=None,
                       geoid_block_size=1024, log=None):
    """
    Prepare a scene-specific DEM subset from a user-provided DEM.
    """
    scene_base = os.path.splitext(os.path.basename(scene.scene))[0]
    out_dem = os.path.join(tmp_dir_scene, f'{scene_base}_DEM_CUSTOM.tif')
    if os.path.isfile(out_dem):
        return out_dem

    ext = _scene_extent(scene=scene, buffer=0.002)
    target_xres_deg, target_yres_deg = _target_resolution(ext=ext, spacing=spacing)

    ds = gdal.Open(custom_dem_file)
    if ds is None:
        raise RuntimeError(f"could not open custom DEM file: {custom_dem_file}")
    dem_wkt = ds.GetProjection()
    try:
        geotransform = ds.GetGeoTransform(can_return_null=True)
    except TypeError:
        geotransform = ds.GetGeoTransform()
    band = ds.GetRasterBand(1)
    src_nodata = band.GetNoDataValue() if band is not None else None
    ds = None

    dem_epsg = _epsg_from_wkt(dem_wkt)

    tmp_dem_ortho = os.path.join(tmp_dir_scene, f'{scene_base}_DEM_CUSTOM_ORTHO_4326.tif')
    apply_custom_geoid = geoid_model_path not in [None, '', 'None']
    try:
        geoid_block_size_log = max(128, int(geoid_block_size))
    except (TypeError, ValueError):
        geoid_block_size_log = 1024
    warp_dst = tmp_dem_ortho if apply_custom_geoid else out_dem

    if dem_wkt in [None, '']:
        if log is not None:
            log.warning("custom DEM has no CRS metadata; clipping without reprojection/resampling "
                        "(assuming EPSG:4326 and matching resolution)")
        _warp_dem(
            src=custom_dem_file,
            dst=warp_dst,
            bounds_4326=[ext['xmin'], ext['ymin'], ext['xmax'], ext['ymax']],
            src_nodata=src_nodata,
            dst_srs=None
        )
        return _finalize_dem(
            apply_geoid=apply_custom_geoid,
            tmp_dem_ortho=tmp_dem_ortho,
            out_dem=out_dem,
            geoid_model_path=geoid_model_path,
            geoid_block_size=geoid_block_size,
            geoid_block_size_log=geoid_block_size_log,
            log=log
        )

    src_xres = None
    src_yres = None
    if geotransform is not None:
        src_xres = abs(float(geotransform[1]))
        src_yres = abs(float(geotransform[5]))

    needs_resample = dem_epsg != 4326
    if dem_epsg == 4326 and src_xres is not None and src_yres is not None:
        tol_x = target_xres_deg * 0.01
        tol_y = target_yres_deg * 0.01
        if abs(src_xres - target_xres_deg) > tol_x or abs(src_yres - target_yres_deg) > tol_y:
            needs_resample = True
    elif dem_epsg == 4326:
        needs_resample = True

    if needs_resample:
        if log is not None:
            if dem_epsg == 4326:
                log.info(
                    f"preparing scene-specific custom DEM (EPSG:4326, resample to "
                    f"{target_xres_deg:.10f}/{target_yres_deg:.10f} deg): {os.path.basename(out_dem)}"
                )
            else:
                log.info(
                    f"preparing scene-specific custom DEM (reproject to EPSG:4326 at "
                    f"{target_xres_deg:.10f}/{target_yres_deg:.10f} deg): {os.path.basename(out_dem)}"
                )
    else:
        if log is not None:
            log.info(
                f"preparing scene-specific custom DEM (crop only, buffer=0.002 deg): "
                f"{os.path.basename(out_dem)}"
            )

    _warp_dem(
        src=custom_dem_file,
        dst=warp_dst,
        bounds_4326=[ext['xmin'], ext['ymin'], ext['xmax'], ext['ymax']],
        src_nodata=src_nodata,
        dst_srs='EPSG:4326',
        xres=target_xres_deg if needs_resample else None,
        yres=target_yres_deg if needs_resample else None,
        target_aligned=needs_resample,
        resample='bilinear'
    )
    return _finalize_dem(
        apply_geoid=apply_custom_geoid,
        tmp_dem_ortho=tmp_dem_ortho,
        out_dem=out_dem,
        geoid_model_path=geoid_model_path,
        geoid_block_size=geoid_block_size,
        geoid_block_size_log=geoid_block_size_log,
        log=log
    )
