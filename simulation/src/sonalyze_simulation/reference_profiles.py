from __future__ import annotations

from sonalyze_simulation.schemas import MetricReference, RoomReferenceProfile


def _reference_metrics(
    *,
    rt60: float,
    edt: float,
    d50: float,
    c50: float,
    c80: float,
    drr: float,
) -> list[MetricReference]:
    return [
        MetricReference(
            key="rt60_s",
            label="RT60",
            unit="s",
            value=rt60,
            min_value=0.0,
            max_value=3.0,
        ),
        MetricReference(
            key="edt_s",
            label="EDT",
            unit="s",
            value=edt,
            min_value=0.0,
            max_value=3.0,
        ),
        MetricReference(
            key="d50",
            label="D50",
            value=d50,
            min_value=0.0,
            max_value=1.0,
        ),
        MetricReference(
            key="c50_db",
            label="C50",
            unit="dB",
            value=c50,
            min_value=-10.0,
            max_value=20.0,
        ),
        MetricReference(
            key="c80_db",
            label="C80",
            unit="dB",
            value=c80,
            min_value=-10.0,
            max_value=20.0,
        ),
        MetricReference(
            key="drr_db",
            label="DRR",
            unit="dB",
            value=drr,
            min_value=-20.0,
            max_value=20.0,
        ),
    ]

_REFERENCE_PROFILES: tuple[RoomReferenceProfile, ...] = (
    RoomReferenceProfile(
        id="classroom",
        display_name="Classroom",
        metrics=_reference_metrics(
            rt60=0.6,
            edt=0.6,
            d50=0.6,
            c50=2.0,
            c80=4.0,
            drr=0.0,
        ),
        notes="Balanced clarity suited for lecture intelligibility.",
    ),
    RoomReferenceProfile(
        id="concert_hall",
        display_name="Concert Hall",
        metrics=_reference_metrics(
            rt60=2.0,
            edt=2.0,
            d50=0.3,
            c50=-2.0,
            c80=-1.0,
            drr=-5.0,
        ),
        notes="Long decay that preserves envelopment for orchestral work.",
    ),
    RoomReferenceProfile(
        id="home_theater",
        display_name="Home Theater",
        metrics=_reference_metrics(
            rt60=0.4,
            edt=0.4,
            d50=0.7,
            c50=5.0,
            c80=8.0,
            drr=5.0,
        ),
        notes="Short decay with pronounced clarity for cinematic playback.",
    ),
    RoomReferenceProfile(
        id="recording_studio",
        display_name="Recording Studio",
        metrics=_reference_metrics(
            rt60=0.3,
            edt=0.3,
            d50=0.8,
            c50=10.0,
            c80=15.0,
            drr=10.0,
        ),
        notes="Highly controlled decay to support critical listening.",
    ),
    RoomReferenceProfile(
        id="office",
        display_name="Open Office",
        metrics=_reference_metrics(
            rt60=0.5,
            edt=0.5,
            d50=0.6,
            c50=3.0,
            c80=6.0,
            drr=2.0,
        ),
        notes="Moderate decay to balance privacy and intelligibility.",
    ),
)


def get_reference_profiles() -> list[RoomReferenceProfile]:
    """Return deep copies so callers cannot mutate the canonical data."""
    return [profile.model_copy(deep=True) for profile in _REFERENCE_PROFILES]
