"""OHush Vibe starter library — playback experiment only.

scientific_authority=false. dataset_role=live_dev.
Does not modify commercial detection, Exp001–005, or LIVE_RECOVERY_001 logic.
Enable on the listener path only with OHUSH_VIBES_EXPERIMENT=1.
"""

from ohush_live.vibes.catalog import DEFAULT_VIBE, VIBES, vibe_bed_names
from ohush_live.vibes.loader import load_vibe_beds, resolve_vibe_track

__all__ = [
    "DEFAULT_VIBE",
    "VIBES",
    "load_vibe_beds",
    "resolve_vibe_track",
    "vibe_bed_names",
]
