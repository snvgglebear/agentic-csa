"""PathPlanner documentation plugin."""

from ...utils.static_docs import StaticDocsPlugin


class Plugin(StaticDocsPlugin):
    NAME = "pathplanner"
    DISPLAY_NAME = "PathPlanner"
    DESCRIPTION = "PathPlanner and PathPlannerLib documentation: autos, paths, named commands, and pathfinding"
    BASE_URLS = ['https://pathplanner.dev']
