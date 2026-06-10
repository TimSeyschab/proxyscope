from dataclasses import dataclass

from proxyscope.processing.pipeline import ExchangePipeline
from proxyscope.processing.ports import (
    CachePolicy,
    ExchangeRecorder,
    PolicyEvaluator,
    ResponseTransformer,
    RuntimeEventSink,
)


@dataclass(frozen=True)
class ProxyRuntimeContext:
    policy_evaluator: PolicyEvaluator
    exchange_recorder: ExchangeRecorder
    response_transformer: ResponseTransformer
    runtime_events: RuntimeEventSink
    cache_policy: CachePolicy
    exchange_pipeline: ExchangePipeline
