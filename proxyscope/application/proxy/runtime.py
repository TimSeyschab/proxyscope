from dataclasses import dataclass

from proxyscope.application.processing.pipeline import ExchangePipeline
from proxyscope.application.processing.ports import (
    CachePolicy,
    ExchangeRecorder,
    ResponseTransformer,
)


@dataclass(frozen=True)
class ProxyRuntimeContext:
    exchange_recorder: ExchangeRecorder
    response_transformer: ResponseTransformer
    cache_policy: CachePolicy
    exchange_pipeline: ExchangePipeline
