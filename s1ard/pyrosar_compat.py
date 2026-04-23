def enable_pyrosar_cogsafe_compat(log=None):
    """
    Extend pyroSAR SAFE pattern to accept CDSE COG_SAFE naming variants.

    This keeps classic SAFE support unchanged while adding optional `_COG`
    and optional `.zip` suffix handling, e.g.:
      - ..._XXXX.SAFE
      - ..._XXXX_COG.SAFE
      - ..._XXXX.SAFE.zip
      - ..._XXXX_COG.SAFE.zip
    """
    try:
        import pyroSAR.patterns as pyropatterns
        import pyroSAR.drivers as pydrivers
    except Exception as e:
        if log is not None:
            log.debug(f"could not import pyroSAR modules for COG_SAFE compatibility: {e}")
        return

    if getattr(pydrivers, '_s1ard_cogsafe_compat_enabled', False):
        return

    safe_pattern = getattr(pyropatterns, 'safe', None)
    if isinstance(safe_pattern, str):
        if '(?:_COG)?\\.SAFE' not in safe_pattern and '(?:_COG)?\\.SAFE(?:\\.zip)?' not in safe_pattern:
            pyropatterns.safe = safe_pattern.replace(r'\.SAFE$', r'(?:_COG)?\.SAFE(?:\.zip)?$')

    orig_scanmetadata = pydrivers.SAFE.scanMetadata

    def patched_scanmetadata(self):
        try:
            return orig_scanmetadata(self)
        except IndexError:
            self.pattern_ds = (
                r'(?i)(?:^|.*/)s1[abcd]-'
                r'(?P<swath>s[1-6]|iw[1-3]?|ew[1-5]?|wv[1-2]|n[1-6])-'
                r'(?P<product>slc|grd|ocn)-'
                r'(?P<pol>hh|hv|vv|vh)-'
                r'(?P<start>[0-9]{8}t[0-9]{6})-'
                r'(?P<stop>[0-9]{8}t[0-9]{6})-'
                r'(?:[0-9]{6})-(?:[0-9a-f]{6})-'
                r'(?P<id>[0-9]{3})(?:-cog)?\.xml$'
            )
            return orig_scanmetadata(self)

    pydrivers.SAFE.scanMetadata = patched_scanmetadata
    pydrivers._s1ard_cogsafe_compat_enabled = True
    if log is not None:
        log.info("enabled pyroSAR COG_SAFE compatibility (_COG.SAFE[.zip], -cog.xml)")
