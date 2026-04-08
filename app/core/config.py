"""应用配置加载模块。"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-4o-2024-08-06"
DEFAULT_WORKSPACE_DIR = PROJECT_ROOT / "workspace"

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:  # pragma: no cover - 兼容未安装 pydantic-settings 的环境
    BaseSettings = None
    SettingsConfigDict = None

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - 兼容未安装 python-dotenv 的环境
    load_dotenv = None


class Settings(BaseModel):
    """统一的应用配置对象。"""

    openai_api_key: str = Field(..., description="OpenAI API Key。")
    openai_base_url: str = Field(
        default=DEFAULT_OPENAI_BASE_URL,
        description="OpenAI API 基础地址。",
    )
    openai_model: str = Field(
        default=DEFAULT_OPENAI_MODEL,
        description="默认使用的大模型名称。",
    )
    workspace_dir: Path = Field(
        default=DEFAULT_WORKSPACE_DIR,
        description="AI 可操作代码库所在的工作区目录。",
    )

    @field_validator("workspace_dir", mode="before")
    @classmethod
    def normalize_workspace_dir(cls, value: str | Path | None) -> Path:
        """将工作区目录解析为项目根目录下的绝对路径。"""

        if value in (None, ""):
            path = DEFAULT_WORKSPACE_DIR
        else:
            path = Path(value)
            if not path.is_absolute():
                path = PROJECT_ROOT / path

        return path.resolve()


if BaseSettings is not None:

    class _SettingsFromEnv(BaseSettings):
        """基于 pydantic-settings 的环境变量读取实现。"""

        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore",
        )

        openai_api_key: str = Field(
            ...,
            validation_alias="OPENAI_API_KEY",
            description="OpenAI API Key。",
        )
        openai_base_url: str = Field(
            default=DEFAULT_OPENAI_BASE_URL,
            validation_alias="OPENAI_BASE_URL",
            description="OpenAI API 基础地址。",
        )
        openai_model: str = Field(
            default=DEFAULT_OPENAI_MODEL,
            validation_alias="OPENAI_MODEL",
            description="默认使用的大模型名称。",
        )
        workspace_dir: str | Path = Field(
            default=DEFAULT_WORKSPACE_DIR,
            validation_alias="WORKSPACE_DIR",
            description="AI 可操作代码库所在的工作区目录。",
        )


def _load_settings_from_os() -> Settings:
    """使用 os 环境变量和可选 dotenv 文件加载配置。"""

    env_path = Path(".env")
    if load_dotenv is not None and env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)
    elif env_path.exists():
        logger.warning("python-dotenv is not installed; .env file will not be loaded automatically.")

    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY is required.")

    return Settings(
        openai_api_key=openai_api_key,
        openai_base_url=os.getenv("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
        openai_model=os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
        workspace_dir=os.getenv("WORKSPACE_DIR", str(DEFAULT_WORKSPACE_DIR)),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回缓存后的应用配置实例。"""

    if BaseSettings is not None:
        loaded_settings = _SettingsFromEnv()
        return Settings(
            openai_api_key=loaded_settings.openai_api_key,
            openai_base_url=loaded_settings.openai_base_url,
            openai_model=loaded_settings.openai_model,
            workspace_dir=loaded_settings.workspace_dir,
        )

    return _load_settings_from_os()
