"""Season versions for docs sites that keep one index per season."""

import logging
from typing import Optional


logger = logging.getLogger(__name__)


class SeasonVersions:
    """
    Mixin for plugins that load one index_<version>.json per season.

    Only "latest" (the 2027 season's docs) ships. Callers may also pass the
    year. To add a season, build its index, list it in config.json, and add
    its year below.
    """

    VERSION_ALIASES = {"2027": "latest"}

    _index_data: dict

    def _resolve_version(self, version: Optional[str]) -> Optional[str]:
        """
        Map a version or year to a loaded index name.

        No version, or one that isn't loaded, means the first loaded season.
        Searching every season would return the same page once per season.
        """
        loaded = list(self._index_data)
        if not loaded:
            return None
        default = loaded[0]
        if version is None:
            return default
        resolved = self.VERSION_ALIASES.get(version, version)
        if resolved not in self._index_data:
            logger.info(
                f"{type(self).__module__}: version {version!r} not loaded; "
                f"using {default!r}"
            )
            return default
        return resolved
