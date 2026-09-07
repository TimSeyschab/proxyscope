from dataclasses import dataclass

from proxyscope.application.processing.pipeline import ExchangePipeline
from proxyscope.application.processing.ports import (
    CachePolicy,
    ExchangeRecorder,
    ResponseTransformer,
    RuntimeEventSink,
)


@dataclass(frozen=True)
class ProxyRuntimeContext:
    exchange_recorder: ExchangeRecorder
    response_transformer: ResponseTransformer
    runtime_events: RuntimeEventSink
    cache_policy: CachePolicy
    exchange_pipeline: ExchangePipeline
