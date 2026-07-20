# F-157: 多模型并行调度 — 聚合器设计

## 1. 聚合器协议

```python
# extensions/capabilities/multimodel_protocol.py

@dataclass
class AggregatedOutput:
    """聚合后的最终输出。"""
    chosen: ChatResponse                    # 选中的最终响应
    runners_up: list[MultiModelResult]      # 备选结果
    vote_summary: dict | None = None        # 投票摘要
    provenance: list[MultiModelResult]      # 所有原始结果（审计用）
    summary_text: str | None = None         # 自动生成的差异摘要

class AggregatorProtocol(Protocol):
    """聚合器协议。"""
    async def aggregate(
        self, results: list[MultiModelResult], context: dict
    ) -> AggregatedOutput: ...
```

## 2. 聚合器实现

### 2.1 PassThroughAggregator — 透传（默认）

```python
class PassThroughAggregator:
    """透传聚合器：不做选择，全部返回。

    适用场景：ParallelStrategy — 用户自己对比选择。
    """

    async def aggregate(self, results, context) -> AggregatedOutput:
        # 取第一个成功的作为 chosen（展示层会展示所有结果）
        chosen = next((r for r in results if r.error is None), results[0])
        return AggregatedOutput(
            chosen=chosen.response,
            runners_up=[r for r in results if r is not chosen],
            provenance=results,
        )
```

### 2.2 MajorityVoteAggregator — 多数投票

```python
class MajorityVoteAggregator:
    """多数投票聚合器：对工具调用投票，取多数一致的结果。

    适用场景：代码审查、事实性判断 — 多数模型输出一致时可信度高。
    """

    min_votes: int = 2       # 最少需要几票
    tolerance: float = 0.3   # 文本相似度容差（0-1）

    async def aggregate(self, results, context) -> AggregatedOutput:
        # 1. 过滤掉失败的调用
        valid = [r for r in results if r.error is None]
        if len(valid) < self.min_votes:
            return self._fallback(valid, results)

        # 2. 对文本内容做相似度聚类
        texts = [(r.slot_name, r.response.content) for r in valid]
        clusters = self._cluster_by_similarity(texts)

        # 3. 取最大簇作为"多数意见"
        majority = max(clusters, key=len)
        chosen_slot = majority[0][0]

        # 4. 统计投票结果
        vote_summary = {
            "total_votes": len(valid),
            "majority": len(majority),
            "clusters": {name: len(c) for name, c in enumerate(clusters)},
            "winning_slot": chosen_slot,
        }

        chosen = next(r for r in results if r.slot_name == chosen_slot)
        return AggregatedOutput(
            chosen=chosen.response,
            runners_up=[r for r in results if r.slot_name != chosen_slot],
            vote_summary=vote_summary,
            provenance=results,
        )

    def _cluster_by_similarity(self, texts):
        """基于文本相似度聚类。（简化实现：LCS/Jaccard）"""
        # 实现细节：先用 difflib.SequenceMatcher 做两两相似度，
        # 相似度 > tolerance 的归为一簇
        ...
```

### 2.3 ScoringAggregator — 评分聚合

```python
class ScoringAggregator:
    """评分聚合器：用评分模型给每个输出打分。

    适用场景：创造性写作、推理 — 需要客观评价标准时。
    """

    scorer_model: str = "gpt-4o"  # 用于评分的模型
    criteria: list[str] = field(default_factory=lambda: [
        "correctness", "clarity", "completeness",
    ])

    async def aggregate(self, results, context) -> AggregatedOutput:
        valid = [r for r in results if r.error is None]
        if len(valid) <= 1:
            return self._single_result(valid, results)

        # 对每个结果进行评分
        scores = await asyncio.gather(*[
            self._score_one(r) for r in valid
        ])

        # 取最高分
        best_idx = max(range(len(scores)), key=lambda i: scores[i]["total"])
        best = valid[best_idx]

        return AggregatedOutput(
            chosen=best.response,
            runners_up=[r for i, r in enumerate(valid) if i != best_idx],
            vote_summary={
                "scores": {
                    r.slot_name: s for r, s in zip(valid, scores)
                },
                "criteria": self.criteria,
            },
            provenance=results,
        )

    async def _score_one(self, result: MultiModelResult) -> dict:
        """调用评分模型对结果打分。"""
        prompt = f"""Rate the following response on a scale of 1-10
for each criterion: {', '.join(self.criteria)}.

Response to evaluate:
{result.response.content}

Return JSON: {{"<criterion>": <score>, "total": <average>}}"""
        ...
```

### 2.4 RankAggregator — 排序聚合

```python
class RankAggregator:
    """排序聚合器：模型互评排序。

    适用场景：通用文本生成 — 让模型互相评价。
    """

    async def aggregate(self, results, context) -> AggregatedOutput:
        """每个模型对其他模型的输出打分，聚合排序。"""
        # 实现略：复杂度 O(n²)，适用于 3-5 个模型
        ...
```

## 3. 聚合器选择策略

| 场景 | 推荐聚合器 | 说明 |
|------|-----------|------|
| 用户对比选择 | `PassThroughAggregator` | 无聚合，全部展示 |
| 代码审查 | `MajorityVoteAggregator` | 多数一致即为正确 |
| 事实性问答 | `MajorityVoteAggregator` | 降低幻觉风险 |
| 创造性写作 | `ScoringAggregator` | 用评分模型客观评价 |
| 通用回答 | `RankAggregator` | 模型互评排序 |
| 高可靠性 | `ScoringAggregator` + `MajorityVoteAggregator` 组合 | 先投票再评分 |