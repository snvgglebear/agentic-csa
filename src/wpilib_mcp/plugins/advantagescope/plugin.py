"""AdvantageScope documentation plugin."""

from ...utils.static_docs import StaticDocsPlugin


class Plugin(StaticDocsPlugin):
    NAME = "advantagescope"
    DISPLAY_NAME = "AdvantageScope"
    DESCRIPTION = "AdvantageScope documentation: viewing live and logged robot data, and each tab's features"
    BASE_URLS = ['https://docs.advantagescope.org']
