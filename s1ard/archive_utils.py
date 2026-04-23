import os


def is_archive_duplicate_error(err):
    """
    Check whether an exception represents the known pyroSAR Archive uniqueness
    collision on (product, outname_base).
    """
    msg = str(err)
    return ('UNIQUE constraint failed' in msg
            and 'data.product' in msg
            and 'data.outname_base' in msg)


def archive_insert_safely(archive, scenes, log=None, chunk_size=500):
    """
    Insert scene paths into a pyroSAR Archive while tolerating duplicate
    `(product, outname_base)` conflicts.

    First, exact duplicate file paths are removed. Then scenes are inserted in
    chunks; if a chunk hits the known unique-key collision, it is retried
    scene-by-scene and only conflicting scenes are skipped.
    """
    if len(scenes) == 0:
        return

    unique = []
    seen = set()
    for scene in scenes:
        key = os.path.normcase(os.path.normpath(scene))
        if key in seen:
            continue
        seen.add(key)
        unique.append(scene)
    if log is not None and len(unique) != len(scenes):
        log.info(f"removed {len(scenes) - len(unique)} duplicate scene path(s) before DB insert")
    scenes = unique

    skipped = 0
    for i in range(0, len(scenes), chunk_size):
        chunk = scenes[i:i + chunk_size]
        try:
            archive.insert(chunk)
        except Exception as e:
            if not is_archive_duplicate_error(e):
                raise
            if log is not None:
                log.warning("duplicate scene key(s) in DB insert batch; retrying chunk scene-by-scene")
            for scene in chunk:
                try:
                    archive.insert([scene])
                except Exception as e2:
                    if is_archive_duplicate_error(e2):
                        skipped += 1
                        if log is not None:
                            log.debug(f"skipping duplicate outname_base scene: {scene}")
                        continue
                    raise
    if skipped > 0 and log is not None:
        log.warning(f"skipped {skipped} duplicate scene(s) with identical product/outname_base")
