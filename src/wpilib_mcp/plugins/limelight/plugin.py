"""Limelight documentation plugin."""

from ...utils.static_docs import StaticDocsPlugin


class Plugin(StaticDocsPlugin):
    NAME = "limelight"
    DISPLAY_NAME = "Limelight"
    DESCRIPTION = "Limelight smart camera documentation: setup, AprilTag localization (MegaTag), pipelines, and the robot APIs"
    BASE_URLS = ['https://docs.limelightvision.io']
