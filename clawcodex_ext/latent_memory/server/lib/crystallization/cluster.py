"""Similarity graph clustering for semantic crystallization."""

from __future__ import annotations

from typing import Any


def cluster_similarity_graph(
    raw_embeddings: list[list[float]],
    crystal_embeddings: list[list[float]],
    *,
    min_cluster_size: int,
    cluster_create_similarity: float,
    cluster_absorb_similarity: float,
    cluster_min_avg_similarity: float,
    cluster_max_size: int,
    raw_subjects: list[str] | None = None,
    raw_asset_types: list[str] | None = None,
) -> tuple[list[dict[str, list[int]]], dict[str, Any]]:
    """Cluster new facts via direct similarity only, and attach crystals to their cluster.

    Existing crystals are deliberately excluded from the union-find set. If crystals and raw facts
    entered the same transitive graph, a chain like crystal-A ~ raw-1 ~ raw-2 could incorrectly
    absorb raw-2 into crystal-A, and two unrelated crystals could also be merged through a raw
    bridge. Raw facts still use union-find for local grouping, but crystal attachment is direct
    and per-raw.
    """
    if not raw_embeddings:
        return [], {}

    import numpy as np

    n_raw = len(raw_embeddings)

    if len(raw_embeddings) < min_cluster_size and not crystal_embeddings:
        return [], {}

    all_emb = raw_embeddings + crystal_embeddings
    X = np.array(all_emb, dtype=np.float64)
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    safe_norms = np.where(norms == 0, 1.0, norms)
    normalized = X / safe_norms
    similarity = normalized @ normalized.T
    parent = list(range(n_raw))

    def find(item: int) -> int:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left: int, right: int) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for i in range(n_raw):
        for j in range(i + 1, n_raw):
            if similarity[i, j] >= cluster_create_similarity:
                union(i, j)

    components: dict[int, list[int]] = {}
    for idx in range(n_raw):
        components.setdefault(find(idx), []).append(idx)

    clusters: list[dict[str, list[int]]] = []
    skipped_small = 0
    skipped_low_avg = 0
    split_count = 0
    low_avg_batch_count = 0
    low_avg_batch_raw_count = 0
    low_avg_refined_cluster_count = 0
    low_avg_refined_raw_count = 0
    low_avg_split_events: list[dict[str, Any]] = []
    subject_pre_split_count = 0
    asset_pre_split_count = 0
    asset_pre_split_small_raw_count = 0
    direct_crystal_edges = 0
    raw_batches_with_crystal = 0

    def ordered_by_center(raw_indices: list[int]) -> list[int]:
        center = normalized[raw_indices].mean(axis=0)
        center_norm = np.linalg.norm(center)
        if center_norm > 0:
            center = center / center_norm
        return sorted(
            raw_indices,
            key=lambda idx: float(normalized[idx] @ center),
            reverse=True,
        )

    def farthest_partition(raw_indices: list[int]) -> tuple[list[int], list[int]] | None:
        if len(raw_indices) < min_cluster_size * 2:
            return None

        seed_left = raw_indices[0]
        seed_right = raw_indices[1]
        lowest = float("inf")
        for left_pos, left in enumerate(raw_indices):
            for right in raw_indices[left_pos + 1 :]:
                score = float(similarity[left, right])
                if score < lowest:
                    lowest = score
                    seed_left = left
                    seed_right = right

        left_group: list[int] = []
        right_group: list[int] = []
        for idx in raw_indices:
            if idx == seed_left:
                left_group.append(idx)
            elif idx == seed_right:
                right_group.append(idx)
            elif similarity[idx, seed_left] >= similarity[idx, seed_right]:
                left_group.append(idx)
            else:
                right_group.append(idx)

        if len(left_group) < min_cluster_size or len(right_group) < min_cluster_size:
            return None
        return left_group, right_group

    def peel_dense_core(raw_indices: list[int]) -> tuple[list[int], list[int]]:
        core = list(raw_indices)
        peeled: list[int] = []
        while (
            len(core) >= min_cluster_size
            and avg_similarity(similarity, core) < cluster_min_avg_similarity
        ):
            worst = min(
                core,
                key=lambda idx: (
                    sum(float(similarity[idx, other]) for other in core if other != idx)
                    / max(len(core) - 1, 1)
                ),
            )
            core.remove(worst)
            peeled.append(worst)
        if (
            len(core) >= min_cluster_size
            and avg_similarity(similarity, core) >= cluster_min_avg_similarity
        ):
            return core, peeled
        return [], list(raw_indices)

    def refine_low_avg(raw_indices: list[int]) -> tuple[list[list[int]], list[int]]:
        if len(raw_indices) < min_cluster_size:
            return [], list(raw_indices)

        if avg_similarity(similarity, raw_indices) >= cluster_min_avg_similarity:
            return [raw_indices], []

        partition = farthest_partition(raw_indices)
        if partition:
            accepted: list[list[int]] = []
            residual: list[int] = []
            for part in partition:
                part_accepted, part_residual = refine_low_avg(part)
                accepted.extend(part_accepted)
                residual.extend(part_residual)
            if accepted:
                return accepted, residual

        core, peeled = peel_dense_core(raw_indices)
        if core:
            accepted = [core]
            residual = peeled
            if len(residual) >= min_cluster_size:
                residual_accepted, residual_unaccepted = refine_low_avg(residual)
                accepted.extend(residual_accepted)
                residual = residual_unaccepted
            return accepted, residual

        return [], list(raw_indices)

    def split_by_subject(raw_indices: list[int]) -> list[list[int]]:
        nonlocal subject_pre_split_count
        if raw_subjects is None or len(raw_indices) < min_cluster_size * 2:
            return [raw_indices]

        groups: dict[str, list[int]] = {}
        for idx in raw_indices:
            subject = raw_subjects[idx] if idx < len(raw_subjects) else ""
            if not subject:
                return [raw_indices]
            groups.setdefault(subject, []).append(idx)

        if len(groups) <= 1 or any(len(group) < min_cluster_size for group in groups.values()):
            return [raw_indices]

        subject_pre_split_count += len(groups) - 1
        return list(groups.values())

    def split_by_asset_type(raw_indices: list[int]) -> list[list[int]]:
        nonlocal asset_pre_split_count, asset_pre_split_small_raw_count
        if raw_asset_types is None or len(raw_indices) < min_cluster_size:
            return [raw_indices]

        if any(
            not (raw_asset_types[idx] if idx < len(raw_asset_types) else "")
            or (raw_asset_types[idx] if idx < len(raw_asset_types) else "") == "unknown"
            for idx in raw_indices
        ):
            return [raw_indices]

        groups: dict[str, list[int]] = {}
        for idx in raw_indices:
            asset_type = raw_asset_types[idx] if idx < len(raw_asset_types) else ""
            if not asset_type:
                return [raw_indices]
            groups.setdefault(asset_type, []).append(idx)

        if len(groups) <= 1:
            return [raw_indices]

        asset_pre_split_count += len(groups) - 1
        asset_pre_split_small_raw_count += sum(
            len(group) for group in groups.values() if len(group) < min_cluster_size
        )
        return list(groups.values())

    def append_batches(raw_indices: list[int], crystal_indices: list[int]) -> None:
        nonlocal skipped_small, skipped_low_avg, split_count, raw_batches_with_crystal
        nonlocal low_avg_batch_count, low_avg_batch_raw_count
        nonlocal low_avg_refined_cluster_count, low_avg_refined_raw_count
        ordered_raw = ordered_by_center(raw_indices)
        for start in range(0, len(ordered_raw), cluster_max_size):
            batch = ordered_raw[start : start + cluster_max_size]
            if crystal_indices:
                raw_batches_with_crystal += 1
                clusters.append(
                    {
                        "raw_indices": batch,
                        "crystal_indices": crystal_indices,
                    }
                )
            elif len(batch) < min_cluster_size:
                skipped_small += len(batch)
            else:
                batch_avg = avg_similarity(similarity, batch)
                if batch_avg < cluster_min_avg_similarity:
                    refined, residual = refine_low_avg(batch)
                    accepted_raw_count = sum(len(group) for group in refined)
                    low_avg_batch_count += 1
                    low_avg_batch_raw_count += len(batch)
                    low_avg_refined_cluster_count += len(refined)
                    low_avg_refined_raw_count += accepted_raw_count
                    low_avg_split_events.append(
                        {
                            "component_size": len(batch),
                            "avg_similarity": round(batch_avg, 6),
                            "split_before": 1,
                            "split_after": len(refined) + (1 if residual else 0),
                            "accepted_after_split": len(refined),
                            "accepted_raw_count": accepted_raw_count,
                            "skipped_raw_count": len(residual),
                        }
                    )
                    for group in refined:
                        clusters.append({"raw_indices": group, "crystal_indices": []})
                    skipped_low_avg += len(residual)
                else:
                    clusters.append({"raw_indices": batch, "crystal_indices": []})
            if start > 0:
                split_count += 1

    for component_raw_indices in components.values():
        subject_groups = split_by_subject(component_raw_indices)
        for subject_indices in subject_groups:
            for raw_indices in split_by_asset_type(subject_indices):
                crystal_groups: dict[int, list[int]] = {}
                raw_without_direct_crystal: list[int] = []
                if crystal_embeddings:
                    for raw_idx in raw_indices:
                        raw_to_crystals = similarity[raw_idx, n_raw:]
                        best_local = int(np.argmax(raw_to_crystals))
                        best_score = float(raw_to_crystals[best_local])
                        if best_score >= cluster_absorb_similarity:
                            direct_crystal_edges += 1
                            crystal_groups.setdefault(best_local, []).append(raw_idx)
                        else:
                            raw_without_direct_crystal.append(raw_idx)
                else:
                    raw_without_direct_crystal = list(raw_indices)

                for crystal_idx, grouped_raw in crystal_groups.items():
                    attached = [crystal_idx]
                    best_global = n_raw + crystal_idx
                    for other_idx in range(len(crystal_embeddings)):
                        if other_idx == crystal_idx:
                            continue
                        other_global = n_raw + other_idx
                        if similarity[
                            best_global, other_global
                        ] >= cluster_absorb_similarity and any(
                            similarity[raw_idx, other_global] >= cluster_absorb_similarity
                            for raw_idx in grouped_raw
                        ):
                            attached.append(other_idx)
                    append_batches(grouped_raw, attached)

                if raw_without_direct_crystal:
                    append_batches(raw_without_direct_crystal, [])

    covered_raw = sum(len(cluster["raw_indices"]) for cluster in clusters)
    diagnostics = {
        "method": "raw_graph_direct_crystal_attach",
        "clusters": len(clusters),
        "covered_raw": covered_raw,
        "create_similarity": cluster_create_similarity,
        "absorb_similarity": cluster_absorb_similarity,
        "min_avg_similarity": cluster_min_avg_similarity,
        "max_cluster_size": cluster_max_size,
        "split_count": split_count,
        "skipped_small": skipped_small,
        "skipped_low_avg": skipped_low_avg,
        "low_avg_batch_count": low_avg_batch_count,
        "low_avg_batch_raw_count": low_avg_batch_raw_count,
        "low_avg_refined_cluster_count": low_avg_refined_cluster_count,
        "low_avg_refined_raw_count": low_avg_refined_raw_count,
        "low_avg_split_events": low_avg_split_events,
        "subject_pre_split_count": subject_pre_split_count,
        "asset_pre_split_count": asset_pre_split_count,
        "asset_pre_split_small_raw_count": asset_pre_split_small_raw_count,
        "raw_components": len(components),
        "direct_crystal_edges": direct_crystal_edges,
        "raw_batches_with_crystal": raw_batches_with_crystal,
    }
    return clusters, diagnostics


def avg_similarity(similarity: Any, indices: list[int]) -> float:
    """Compute the average pairwise similarity within a raw-only cluster."""
    if len(indices) < 2:
        return 1.0
    total = 0.0
    count = 0
    for left_pos, left in enumerate(indices):
        for right in indices[left_pos + 1 :]:
            total += float(similarity[left, right])
            count += 1
    return total / max(count, 1)
