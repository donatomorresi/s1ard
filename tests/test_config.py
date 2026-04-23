import os
import pytest
from s1ard.config import get_config, init, write
from s1ard.snap import get_config_keys as snap_get_keys


def test_config(tmpdir):
    with pytest.raises(ValueError):
        config = get_config()
    with pytest.raises(ValueError):
        config = get_config(work_dir=str(tmpdir), aoi_tiles='xyz')
    config = get_config(work_dir=str(tmpdir), db_file='scenes.db', aoi_tiles='32TNT')
    assert config['processing']['aoi_tiles'] == ['32TNT']
    assert config['processing']['db_file'] == os.path.join(str(tmpdir), 'scenes.db')


def test_config_snap(tmpdir):
    config = get_config(work_dir=str(tmpdir), db_file='scenes.db', aoi_tiles='32TNT')
    assert 'snap' in config.keys()
    snap_keys = list(config['snap'].keys())
    del snap_keys[snap_keys.index('dem_prepare_mode')]
    assert sorted(snap_keys) == snap_get_keys()
    expected = {
        'allow_res_osv': True,
        'cleanup': True,
        'clean_edges': True,
        'clean_edges_pixels': 4,
        'reset_locks_on_start': False,
        'dem_resampling_method': 'BILINEAR_INTERPOLATION',
        'gpt_args': None,
        'img_resampling_method': 'BILINEAR_INTERPOLATION'
    }
    
    for key, value in expected.items():
        assert config['snap'][key] == value
    
    out = str(tmpdir / 'config.ini')
    write(config, out)
    config = get_config(config_file=out)
    assert 'snap' in config.keys()
    snap_keys = list(config['snap'].keys())
    del snap_keys[snap_keys.index('dem_prepare_mode')]
    assert sorted(snap_keys) == snap_get_keys()
    for key, value in expected.items():
        assert config['snap'][key] == value


def test_init(tmpdir):
    target = str(tmpdir / 'config.ini')
    # work_dir undefined
    with pytest.raises(ValueError):
        init(target=target)
    # no search option defined
    with pytest.raises(RuntimeError):
        init(target=target, work_dir=str(tmpdir))
    gpt_args = ['-J-Xmx100G', '-c', '75G', '-q', '30']
    init(target=target, work_dir=str(tmpdir), db_file='scenes.db',
         gpt_args=gpt_args)
    config = get_config(target)
    assert config['snap']['gpt_args'] == gpt_args
    # file already exists
    with pytest.raises(RuntimeError):
        init(target=target, work_dir=str(tmpdir), db_file='scenes.db')


def test_init_default_polarizations_none(tmpdir):
    target = str(tmpdir / 'config_default_pols.ini')
    init(target=target, work_dir=str(tmpdir), db_file='scenes.db')
    config = get_config(target)
    assert config['processing']['polarizations'] is None


def test_config_custom_tiles_and_dem(tmpdir):
    dem_file = tmpdir / 'custom_dem.tif'
    dem_file.write('dummy')
    grid_file = tmpdir / 'custom_tiles.geojson'
    grid_file.write(
        """{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {"tile_id": "tile-a"},
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[11.0, 45.0], [11.1, 45.0], [11.1, 45.1], [11.0, 45.1], [11.0, 45.0]]]
      }
    }
  ]
}"""
    )
    config = get_config(work_dir=str(tmpdir),
                        db_file='scenes.db',
                        dem_type='custom_dem',
                        custom_dem_file='custom_dem.tif',
                        custom_dem_apply_geoid='True',
                        custom_dem_geoid_isg='https://www.isgeoid.polimi.it/Geoid/Europe/Sweden/SWEN17_RH2000.isg',
                        custom_tile_grid='custom_tiles.geojson',
                        custom_tile_id_field='tile_id',
                        polarizations='VV,VH')
    assert config['processing']['custom_tile_id_field'] == 'tile_id'
    assert config['processing']['custom_dem_file'] == os.path.join(str(tmpdir), 'custom_dem.tif')
    assert config['processing']['custom_dem_apply_geoid'] is True
    assert config['processing']['custom_dem_geoid_isg'] == 'https://www.isgeoid.polimi.it/Geoid/Europe/Sweden/SWEN17_RH2000.isg'
    assert config['processing']['custom_tile_grid'] == os.path.join(str(tmpdir), 'custom_tiles.geojson')
    assert config['processing']['polarizations'] == ['VV', 'VH']


def test_config_custom_tiles_accept_non_mgrs_aoi_tiles(tmpdir):
    grid_file = tmpdir / 'custom_tiles.geojson'
    grid_file.write(
        """{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {"tile_id": "X0015_Y0093"},
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[11.0, 45.0], [11.1, 45.0], [11.1, 45.1], [11.0, 45.1], [11.0, 45.0]]]
      }
    }
  ]
}"""
    )
    config = get_config(work_dir=str(tmpdir),
                        db_file='scenes.db',
                        custom_tile_grid='custom_tiles.geojson',
                        custom_tile_id_field='tile_id',
                        aoi_tiles='X0015_Y0093')
    assert config['processing']['aoi_tiles'] == ['X0015_Y0093']


def test_config_custom_dem_requires_all_params(tmpdir):
    dem_file = tmpdir / 'custom_dem.tif'
    dem_file.write('dummy')
    with pytest.raises(RuntimeError):
        get_config(work_dir=str(tmpdir),
                   db_file='scenes.db',
                   dem_type='custom_dem',
                   custom_dem_file='custom_dem.tif')


def test_config_custom_dem_without_geoid_if_disabled(tmpdir):
    dem_file = tmpdir / 'custom_dem.tif'
    dem_file.write('dummy')
    config = get_config(work_dir=str(tmpdir),
                        db_file='scenes.db',
                        dem_type='custom_dem',
                        custom_dem_file='custom_dem.tif',
                        custom_dem_apply_geoid='False')
    assert config['processing']['custom_dem_apply_geoid'] is False
    assert config['processing']['custom_dem_geoid_isg'] is None


def test_config_custom_dem_params_ignored_without_custom_dem_type(tmpdir):
    config = get_config(work_dir=str(tmpdir),
                        db_file='scenes.db',
                        dem_type='Copernicus 30m Global DEM',
                        custom_dem_file='custom_dem.tif',
                        custom_dem_geoid_isg='missing_model.isg')
    assert config['processing']['dem_type'] == 'Copernicus 30m Global DEM'
    assert config['processing']['custom_dem_file'] == os.path.join(str(tmpdir), 'custom_dem.tif')
    assert config['processing']['custom_dem_geoid_isg'] == 'missing_model.isg'


def test_config_geoid_block_size_default_and_override(tmpdir):
    config = get_config(work_dir=str(tmpdir), db_file='scenes.db')
    assert config['processing']['geoid_block_size'] == 1024

    config = get_config(work_dir=str(tmpdir), db_file='scenes.db', geoid_block_size='2048')
    assert config['processing']['geoid_block_size'] == 2048


def test_config_geoid_block_size_min_value(tmpdir):
    with pytest.raises(RuntimeError, match="geoid_block_size"):
        get_config(work_dir=str(tmpdir), db_file='scenes.db', geoid_block_size='64')


def test_config_custom_dem_geoid_params_ignored_if_disabled(tmpdir):
    dem_file = tmpdir / 'custom_dem.tif'
    dem_file.write('dummy')
    config = get_config(work_dir=str(tmpdir),
                        db_file='scenes.db',
                        dem_type='custom_dem',
                        custom_dem_file='custom_dem.tif',
                        custom_dem_apply_geoid='False',
                        custom_dem_geoid_isg='https://www.isgeoid.polimi.it/Geoid/Europe/Sweden/SWEN17_RH2000.isg')
    assert config['processing']['custom_dem_apply_geoid'] is False
    assert config['processing']['custom_dem_geoid_isg'] == 'https://www.isgeoid.polimi.it/Geoid/Europe/Sweden/SWEN17_RH2000.isg'


def test_config_custom_dem_geoid_isg_local_path(tmpdir):
    dem_file = tmpdir / 'custom_dem.tif'
    dem_file.write('dummy')
    geoid_file = tmpdir / 'local_model.isg'
    geoid_file.write('dummy')
    config = get_config(work_dir=str(tmpdir),
                        db_file='scenes.db',
                        dem_type='custom_dem',
                        custom_dem_file='custom_dem.tif',
                        custom_dem_apply_geoid='True',
                        custom_dem_geoid_isg='local_model.isg')
    assert config['processing']['custom_dem_geoid_isg'] == os.path.join(str(tmpdir), 'local_model.isg')


def test_config_custom_dem_geoid_isg_warn_on_non_isg_suffix(tmpdir):
    dem_file = tmpdir / 'custom_dem.tif'
    dem_file.write('dummy')
    geoid_file = tmpdir / 'local_model.grd'
    geoid_file.write('dummy')
    with pytest.warns(UserWarning, match="does not end with '.isg'"):
        config = get_config(work_dir=str(tmpdir),
                            db_file='scenes.db',
                            dem_type='custom_dem',
                            custom_dem_file='custom_dem.tif',
                            custom_dem_apply_geoid='True',
                            custom_dem_geoid_isg='local_model.grd')
    assert config['processing']['custom_dem_geoid_isg'] == os.path.join(str(tmpdir), 'local_model.grd')
