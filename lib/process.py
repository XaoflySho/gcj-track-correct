"""Shared GCJ correction pipeline for footprint and DoL tracks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Set, Tuple

from .detect import (
    SegmentResult,
    TrackPoint,
    analyze_segment,
    correct_points,
    fmt_cst,
    path_stats,
    segment_indices,
)
from .detect import _gcj_runs
from .qa_anchors import discover_stay_anchors, near_any_anchor


@dataclass
class LabeledSegment:
    idxs: List[int]
    points: List[TrackPoint]
    result: SegmentResult
    labels: List[str]


def label_segments(points: Sequence[TrackPoint]) -> List[LabeledSegment]:
    """Analyze drive segments and drop GCJ runs that touch stay anchors."""
    times = [p.t for p in points]
    segs_idx = segment_indices(times)
    anchors = discover_stay_anchors(points)
    out: List[LabeledSegment] = []

    for idxs in segs_idx:
        seg_points = [points[i] for i in idxs]
        result = analyze_segment(seg_points)
        labels = list(result.labels)
        if anchors and result.gcj_count > 0:
            for start, end in _gcj_runs(labels):
                if any(
                    near_any_anchor(seg_points[i].lon, seg_points[i].lat, anchors)
                    for i in range(start, end)
                ):
                    for i in range(start, end):
                        labels[i] = "W"
            if not any(lab == "G" for lab in labels):
                labels = ["U"] * len(labels)
        out.append(
            LabeledSegment(
                idxs=list(idxs),
                points=seg_points,
                result=result,
                labels=labels,
            )
        )
    return out


def apply_corrections(
    segs: Sequence[LabeledSegment],
    *,
    dedupe: bool = True,
    drop_indices: Optional[Sequence[int]] = None,
) -> Tuple[List[TrackPoint], List[dict], int, List[int]]:
    """Convert labeled G points; optionally drop indices and near-duplicates."""
    drop_set: Set[int] = set(drop_indices or ())
    corrected_all: List[TrackPoint] = []
    summaries: List[dict] = []
    removed_all: List[int] = []
    fixed_total = 0

    for seg in segs:
        before_coords = [(p.lon, p.lat) for p in seg.points]
        _, _, max_before = path_stats(before_coords)

        keep_points: List[TrackPoint] = []
        keep_labels: List[str] = []
        dropped: List[int] = []
        for p, lab in zip(seg.points, seg.labels):
            if p.index in drop_set:
                dropped.append(p.index)
                continue
            keep_points.append(p)
            keep_labels.append(lab)

        gcj_count = sum(1 for lab in keep_labels if lab == "G")
        if seg.result.is_drive and gcj_count > 0:
            corrected, fixed, removed = correct_points(
                keep_points, keep_labels, dedupe=dedupe
            )
        else:
            corrected = keep_points
            fixed = 0
            removed = []

        removed = list(dropped) + list(removed)
        after_coords = [(p.lon, p.lat) for p in corrected]
        _, _, max_after = path_stats(after_coords)

        fixed_total += fixed
        removed_all.extend(removed)
        corrected_all.extend(corrected)

        summaries.append(
            {
                "t0": fmt_cst(seg.result.t0),
                "t1": fmt_cst(seg.result.t1),
                "n_in": len(seg.points),
                "n_out": len(corrected),
                "fixed": fixed,
                "removed": len(removed),
                "switches": len(seg.result.switches),
                "max_spd": seg.result.max_speed,
                "max_before": max_before,
                "max_after": max_after,
                "is_drive": seg.result.is_drive,
            }
        )

    return corrected_all, summaries, fixed_total, removed_all


def process_track(
    points: List[TrackPoint],
    *,
    dedupe: bool = True,
    drop_indices: Optional[Sequence[int]] = None,
) -> Tuple[List[dict], List[dict], int, int]:
    segs = label_segments(points)
    corrected, summaries, fixed_total, removed = apply_corrections(
        segs, dedupe=dedupe, drop_indices=drop_indices
    )
    return [p.raw for p in corrected], summaries, fixed_total, len(removed)
