"""Deterministic, CPU-only building assets from edited photos and OSM polygons."""


def build_asset(*args, **kwargs):
    from .pipeline import build_asset as build
    return build(*args, **kwargs)


def restyle_existing_asset(*args, **kwargs):
    from .preserve import restyle_existing_asset as restyle
    return restyle(*args, **kwargs)
