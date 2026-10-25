"""Read a Sphinx site's objects.inv to list every page it publishes."""

import zlib
from urllib.parse import urljoin

import httpx


async def sphinx_doc_urls(client: httpx.AsyncClient, docs_root: str) -> list[str]:
    """
    Return the absolute URL of every page (std:doc entry) in a Sphinx site.

    docs_root is the folder that holds objects.inv, ending in "/",
    for example "https://docs.wpilib.org/en/stable/".
    """
    resp = await client.get(urljoin(docs_root, "objects.inv"))
    resp.raise_for_status()
    # Four plain-text header lines, then zlib-compressed entries:
    # "name domain:role priority uri display-name"
    parts = resp.content.split(b"\n", 4)
    if len(parts) < 5 or not parts[0].startswith(b"# Sphinx inventory version 2"):
        raise ValueError(f"Unsupported objects.inv at {docs_root}")
    body = zlib.decompress(parts[4]).decode("utf-8")

    urls = []
    for line in body.splitlines():
        fields = line.split(" ", 4)
        if len(fields) >= 4 and fields[1] == "std:doc":
            uri = fields[3].replace("$", fields[0])
            urls.append(urljoin(docs_root, uri))
    return urls
