"""
AI 助手 — 多提供商自然语言交互

支持 DeepSeek、小米 MiMo、智谱 GLM，用于自然语言生成图表配置和数据分析。
"""

import json
import copy
import logging
from typing import Optional

from .models import LLMProvider, LLM_PROVIDERS

logger = logging.getLogger(__name__)


class AIAssistant:
    """多提供商 AI 助手"""

    def __init__(self, providers_config: dict = None):
        """
        Args:
            providers_config: 从配置加载的提供商设置，兼容新旧两种格式：

                旧格式（扁平 dict）:
                {
                    "deepseek": {api_key, enabled, default_model, api_url},
                    "xiaomi_mimo": {...},
                    "zhipu_glm": {...},
                    "active": "deepseek",
                }

                新格式（providers 列表）:
                {
                    "providers": [{id, type, name, api_key, api_url, model, enabled}, ...],
                    "active": "deepseek",
                }
        """
        providers_config = providers_config or {}
        self._providers: dict[str, LLMProvider] = {}
        self._current_id = providers_config.get('active', '')

        # 兼容新格式：{"providers": [...], "active": "..."}
        if 'providers' in providers_config:
            for pdata in providers_config.get('providers', []):
                if not isinstance(pdata, dict):
                    continue
                pid = pdata.get('id', '')
                if not pid:
                    continue
                if not pdata.get('enabled') or not pdata.get('api_key', '').strip():
                    continue
                # 查找预设信息以获取默认值和 models 列表
                preset = LLM_PROVIDERS.get(pid)
                if preset:
                    name = pdata.get('name', preset.name)
                    api_url = pdata.get('api_url', '') or preset.api_url
                    default_model = pdata.get('model', '') or pdata.get('default_model', '') or preset.default_model
                    models = preset.models
                    if default_model and default_model not in models:
                        models = list(models) + [default_model]
                else:
                    # 自定义提供商（不在预设列表中）
                    name = pdata.get('name', pid)
                    api_url = pdata.get('api_url', '')
                    default_model = pdata.get('model', '') or pdata.get('default_model', '')
                    models = [default_model] if default_model else []
                provider = LLMProvider(
                    id=pid,
                    name=name,
                    api_url=api_url,
                    default_model=default_model,
                    models=models,
                    api_key=pdata['api_key'].strip(),
                    enabled=True,
                )
                self._providers[pid] = provider
        else:
            # 旧格式：{"deepseek": {api_key, enabled, ...}, "active": "..."}
            for pid, preset in LLM_PROVIDERS.items():
                cfg = providers_config.get(pid, {})
                if isinstance(cfg, dict) and cfg.get('enabled') and cfg.get('api_key'):
                    provider = LLMProvider(
                        id=pid,
                        name=preset.name,
                        api_url=cfg.get('api_url', preset.api_url),
                        default_model=cfg.get('default_model', preset.default_model),
                        models=preset.models,
                        api_key=cfg['api_key'],
                        enabled=True,
                    )
                    self._providers[pid] = provider

        if self._current_id not in self._providers and self._providers:
            self._current_id = next(iter(self._providers.keys()))

    @property
    def available_providers(self) -> list[LLMProvider]:
        return list(self._providers.values())

    @property
    def current_provider(self) -> Optional[LLMProvider]:
        return self._providers.get(self._current_id)

    @property
    def current_model_name(self) -> str:
        """当前使用的模型显示名称"""
        p = self.current_provider
        return f"{p.name} / {p.default_model}" if p else "未配置"

    @property
    def is_available(self) -> bool:
        return bool(self._providers)

    def set_current_provider(self, provider_id: str):
        if provider_id in self._providers:
            self._current_id = provider_id

    def chat(self, user_message: str, available_sources: list[dict],
             provider_id: str = None) -> str:
        """
        发送消息到 AI，返回响应文本。

        Args:
            user_message: 用户输入的自然语言
            available_sources: 可用数据源列表
                [{id, name, row_count, fields: [{key, label, data_type}]}]
            provider_id: 指定提供商 ID，不传则用当前

        Returns:
            AI 响应文本（可能是 JSON 或纯文本）
        """
        provider = self._providers.get(provider_id or self._current_id)
        if not provider:
            return "❌ 未配置 AI 模型，请先在 设置 → API 配置 中启用至少一个提供商。"

        system_prompt = self._build_system_prompt(available_sources, provider)

        # 调用 API（使用全局 perform_requests_request）
        try:
            # 从 __main__ 获取 perform_requests_request
            import sys
            main_mod = sys.modules.get('__main__')
            perform_req = getattr(main_mod, 'perform_requests_request', None)
            if not perform_req:
                import requests
                response = requests.post(
                    provider.api_url,
                    headers={
                        'Authorization': f'Bearer {provider.api_key}',
                        'Content-Type': 'application/json',
                    },
                    json={
                        'model': provider.default_model,
                        'messages': [
                            {'role': 'system', 'content': system_prompt},
                            {'role': 'user', 'content': user_message},
                        ],
                        'temperature': 0.3,
                    },
                    timeout=60,
                )
            else:
                response = perform_req(
                    'post', provider.api_url,
                    headers={
                        'Authorization': f'Bearer {provider.api_key}',
                        'Content-Type': 'application/json',
                    },
                    json={
                        'model': provider.default_model,
                        'messages': [
                            {'role': 'system', 'content': system_prompt},
                            {'role': 'user', 'content': user_message},
                        ],
                        'temperature': 0.3,
                    },
                    timeout=60,
                )

            if hasattr(response, 'status_code') and response.status_code != 200:
                return f"❌ API 请求失败 (HTTP {response.status_code}): {response.text[:200]}"

            data = response.json() if hasattr(response, 'json') else json.loads(response.text)
            content = data['choices'][0]['message']['content']

            logger.info(f"[AI] {provider.name} 响应: {content[:200]}...")
            return content

        except Exception as e:
            logger.error(f"[AI] {provider.name} 调用失败: {e}")
            return f"❌ AI 调用失败: {e}"

    def _build_system_prompt(self, available_sources: list[dict], provider=None) -> str:
        """构建 system prompt，注入数据源 schema 和模型信息"""
        provider_name = getattr(provider, 'name', 'AI')
        provider_model = getattr(provider, 'default_model', 'unknown')
        sources_desc = []
        for src in (available_sources or []):
            fields_desc = []
            for f in src.get('fields', []) or src.get('columns', []):
                if isinstance(f, dict):
                    fields_desc.append(f"    - {f.get('key','')}: {f.get('data_type','text')} ({f.get('label','')})")
                elif isinstance(f, (tuple, list)) and len(f) >= 2:
                    fields_desc.append(f"    - {f[0]}: text ({f[1]})")
                else:
                    fields_desc.append(f"    - {f}")
            row_count = src.get('row_count', 0)
            sources_desc.append(
                f"### {src.get('name', '')} (ID: {src.get('id', '')}), {row_count}行\n"
                + "\n".join(fields_desc)
            )

        sources_text = "\n\n".join(sources_desc) if sources_desc else '(暂无可用数据源)'

        return f"""你是 BI 数据分析助手，由 **{provider_name}** 的 **{provider_model}** 模型驱动。

当用户询问你的模型或技术细节时，请明确回答：你使用的是 {provider_name} 的 {provider_model} 模型。

## 当前数据源
{sources_text}

## 你的能力
1. **普通问答**: 回答关于数据的问题（哪个最多/最少、排名、占比、对比等）
2. **数据分析**: 发现趋势、异常值、关联关系，用数据支撑结论
3. **数据总结**: 对数据集进行概括性描述，提炼关键指标和洞察
4. **图表创建**: 根据用户需求生成可视化图表配置

## 回复规范
- 使用简体中文，简洁清晰，用数据说话
- 分析时引用具体数值和百分比
- 总结时列出 3-5 个关键要点
- 当用户要求创建图表时，在回复末尾附上 JSON 图表定义，用 ```json 代码块包裹:

```json
{{"chart_type": "bar", "title": "图表标题", "x_field": "维度字段", "y_fields": ["度量字段"], "aggregate_funcs": {{"度量字段": "SUM"}}, "color_field": "", "data_source_type": "report", "data_source_id": "数据源ID", "data_source_name": "数据源名称"}}
```

## 图表类型参考
bar(柱状图), line(折线图), pie(饼图), scatter(散点图), area(面积图),
table(表格), card(指标卡), gauge(仪表盘), funnel(漏斗图), treemap(树图),
sunburst(旭日图), heatmap(热力图), stacked_bar(堆叠柱状), stacked_area(堆叠面积),
radar(雷达图), sankey(桑基图), word_cloud(词云)

## 注意
- 仅使用可用数据源中存在的字段名
- 不需要图表时不要返回 JSON
- 数据源 ID 请使用上面列出的真实 ID"""

    @staticmethod
    def parse_chart_from_response(response: str) -> Optional[dict]:
        """
        从 AI 响应中解析 create_chart JSON，返回 dict 或 None。
        """
        try:
            # 尝试直接解析
            data = json.loads(response)
            if data.get('action') == 'create_chart' and 'chart' in data:
                return data
        except json.JSONDecodeError:
            pass

        # 尝试提取 {...} JSON 块
        import re
        match = re.search(r'\{[^{}]*"action"\s*:\s*"create_chart"[^{}]*\}', response, re.DOTALL)
        if not match:
            match = re.search(r'\{[^{}]*"chart"\s*:\s*\{[^{}]*\}\s*\}', response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return None
