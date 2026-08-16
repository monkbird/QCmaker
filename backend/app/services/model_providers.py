from dataclasses import asdict, dataclass

VERIFIED_AT = "2026-08-16"


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    region: str
    base_url: str
    api_style: str = "openai"
    key_url: str | None = None
    docs_url: str | None = None
    verified_at: str = VERIFIED_AT


PROVIDERS = (
    Provider("openai", "OpenAI", "global", "https://api.openai.com/v1", key_url="https://platform.openai.com/api-keys", docs_url="https://platform.openai.com/docs/api-reference/models/list"),
    Provider("anthropic", "Anthropic Claude", "global", "https://api.anthropic.com/v1", "anthropic", "https://console.anthropic.com/settings/keys", "https://docs.anthropic.com/en/api/models-list"),
    Provider("gemini", "Google Gemini", "global", "https://generativelanguage.googleapis.com/v1beta/openai", key_url="https://aistudio.google.com/app/apikey", docs_url="https://ai.google.dev/api/models"),
    Provider("xai", "xAI Grok", "global", "https://api.x.ai/v1", key_url="https://console.x.ai/", docs_url="https://docs.x.ai/docs/api-reference#list-models"),
    Provider("mistral", "Mistral AI", "global", "https://api.mistral.ai/v1", key_url="https://console.mistral.ai/api-keys", docs_url="https://docs.mistral.ai/api/endpoint/models"),
    Provider("groq", "Groq", "global", "https://api.groq.com/openai/v1", key_url="https://console.groq.com/keys", docs_url="https://console.groq.com/docs/api-reference/models"),
    Provider("openrouter", "OpenRouter", "global", "https://openrouter.ai/api/v1", key_url="https://openrouter.ai/settings/keys", docs_url="https://openrouter.ai/docs/api-reference/list-available-models"),
    Provider("together", "Together AI", "global", "https://api.together.xyz/v1", key_url="https://api.together.ai/settings/api-keys", docs_url="https://docs.together.ai/reference/models-1"),
    Provider("cerebras", "Cerebras", "global", "https://api.cerebras.ai/v1", key_url="https://cloud.cerebras.ai/", docs_url="https://inference-docs.cerebras.ai/api-reference/models/list"),
    Provider("perplexity", "Perplexity", "global", "https://api.perplexity.ai", key_url="https://www.perplexity.ai/settings/api", docs_url="https://docs.perplexity.ai/api-reference/models/list-models"),
    Provider("deepseek", "DeepSeek 深度求索", "cn", "https://api.deepseek.com", key_url="https://platform.deepseek.com/api_keys", docs_url="https://api-docs.deepseek.com/api/list-models"),
    Provider("qwen", "阿里云百炼 Qwen", "cn", "https://dashscope.aliyuncs.com/compatible-mode/v1", key_url="https://bailian.console.aliyun.com/", docs_url="https://help.aliyun.com/zh/model-studio/getting-started/models"),
    Provider("moonshot", "Moonshot Kimi", "cn", "https://api.moonshot.cn/v1", key_url="https://platform.moonshot.cn/console/api-keys", docs_url="https://platform.moonshot.cn/docs/api-reference"),
    Provider("zhipu", "智谱 GLM", "cn", "https://open.bigmodel.cn/api/paas/v4", key_url="https://open.bigmodel.cn/usercenter/apikeys", docs_url="https://docs.bigmodel.cn/cn/api/introduction"),
    Provider("siliconflow", "硅基流动 SiliconFlow", "cn", "https://api.siliconflow.cn/v1", key_url="https://cloud.siliconflow.cn/account/ak", docs_url="https://docs.siliconflow.cn/cn/api-reference/models/get-model-list"),
    Provider("volcengine", "火山引擎方舟", "cn", "https://ark.cn-beijing.volces.com/api/v3", key_url="https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey", docs_url="https://www.volcengine.com/docs/82379/1330310"),
    Provider("baidu", "百度智能云千帆", "cn", "https://qianfan.baidubce.com/v2", key_url="https://console.bce.baidu.com/iam/#/iam/apikey/list", docs_url="https://cloud.baidu.com/doc/qianfan-api/s/3m7of64lb"),
    Provider("hunyuan", "腾讯混元", "cn", "https://api.hunyuan.cloud.tencent.com/v1", key_url="https://console.cloud.tencent.com/hunyuan/api-key", docs_url="https://cloud.tencent.com/document/product/1729/111007"),
    Provider("minimax", "MiniMax", "cn", "https://api.minimaxi.com/v1", key_url="https://platform.minimaxi.com/user-center/basic-information/interface-key", docs_url="https://platform.minimaxi.com/docs/api-reference/text-openai-api"),
    Provider("stepfun", "阶跃星辰 StepFun", "cn", "https://api.stepfun.com/v1", key_url="https://platform.stepfun.com/", docs_url="https://platform.stepfun.com/docs/llm/modeloverview"),
    Provider("yi", "零一万物 Yi", "cn", "https://api.lingyiwanwu.com/v1", key_url="https://platform.lingyiwanwu.com/apikeys", docs_url="https://platform.lingyiwanwu.com/docs"),
    Provider("baichuan", "百川智能", "cn", "https://api.baichuan-ai.com/v1", key_url="https://platform.baichuan-ai.com/console/apikey", docs_url="https://platform.baichuan-ai.com/docs/api"),
    Provider("ollama", "Ollama 本地模型", "local", "http://localhost:11434/v1", "ollama", docs_url="https://docs.ollama.com/api/tags"),
    Provider("custom", "自定义 OpenAI 兼容服务", "custom", "", docs_url="https://platform.openai.com/docs/api-reference/models/list"),
)

_BY_ID = {provider.id: provider for provider in PROVIDERS}


def get_provider(provider_id: str) -> Provider:
    try:
        return _BY_ID[provider_id]
    except KeyError as exc:
        raise ValueError(f"unknown provider: {provider_id}") from exc


def provider_catalog() -> list[dict[str, object]]:
    return [asdict(provider) for provider in PROVIDERS]
