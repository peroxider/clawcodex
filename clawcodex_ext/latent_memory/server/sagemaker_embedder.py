"""
SageMaker 向量嵌入提供器。

该类调用部署在 AWS SageMaker 上的 HuggingFace TEI 服务，输入格式为
{"inputs": [text]}，输出会按 embedding_dims 截断，默认 768 维。

可在 mem0 配置的 embedder.config 中设置：
  sagemaker_endpoint_name:  例如 "tei-qwen-600m-staging"
  aws_region:               例如 "us-west-2"
  embedding_dims:           例如 768
  aws_access_key_id:        可选，默认读取环境变量或实例角色
  aws_secret_access_key:    可选，默认读取环境变量或实例角色
"""

import json
import logging
import os
from typing import Literal, Optional

from mem0.configs.embeddings.base import BaseEmbedderConfig
from mem0.embeddings.base import EmbeddingBase

logger = logging.getLogger(__name__)


class SageMakerEmbedding(EmbeddingBase):
    def __init__(self, config: Optional[BaseEmbedderConfig] = None):
        super().__init__(config)

        try:
            import boto3
        except ImportError as exc:
            raise ImportError("SageMaker 嵌入需要 boto3，请先安装：pip install boto3") from exc

        self.endpoint_name = getattr(self.config, "sagemaker_endpoint_name", None) or os.getenv(
            "SAGEMAKER_ENDPOINT_NAME", "tei-qwen-600m-staging"
        )
        self.dims = self.config.embedding_dims or 768

        region = (
            getattr(self.config, "aws_region", None)
            or os.getenv("AWS_REGION")
            or os.getenv("AWS_DEFAULT_REGION")
            or "us-west-2"
        )
        access_key = os.getenv("AWS_ACCESS_KEY_ID")
        secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")

        kwargs = {"region_name": region}
        if access_key and secret_key:
            kwargs["aws_access_key_id"] = access_key
            kwargs["aws_secret_access_key"] = secret_key

        self.client = boto3.client(
            "sagemaker-runtime",
            endpoint_url=f"https://runtime.sagemaker.{region}.amazonaws.com",
            **kwargs,
        )
        logger.info(
            "SageMaker embedder: endpoint=%s, region=%s, dims=%d",
            self.endpoint_name,
            region,
            self.dims,
        )

    def embed(
        self, text: str, memory_action: Optional[Literal["add", "search", "update"]] = None
    ) -> list[float]:
        text = text.replace("\n", " ")
        response = self.client.invoke_endpoint(
            EndpointName=self.endpoint_name,
            ContentType="application/json",
            Body=json.dumps({"inputs": [text]}),
        )
        result = json.loads(response["Body"].read().decode("utf-8"))
        return result[0][: self.dims]

    def embed_batch(self, texts: list[str], memory_action: str = "add") -> list[list[float]]:
        texts = [t.replace("\n", " ") for t in texts]
        response = self.client.invoke_endpoint(
            EndpointName=self.endpoint_name,
            ContentType="application/json",
            Body=json.dumps({"inputs": texts}),
        )
        result = json.loads(response["Body"].read().decode("utf-8"))
        return [vec[: self.dims] for vec in result]
