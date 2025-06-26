"""
豆包图片生成插件

基于火山引擎豆包模型的AI图片生成插件。

功能特性：
- 智能LLM判定：根据聊天内容智能判断是否需要生成图片
- 高质量图片生成：使用豆包Seed Dream模型生成图片
- 结果缓存：避免重复生成相同内容的图片
- 配置验证：自动验证和修复配置文件
- 参数验证：完整的输入参数验证和错误处理
- 多尺寸支持：支持多种图片尺寸生成

包含组件：
- 图片生成Action - 根据描述使用火山引擎API生成图片
"""

import asyncio
import json
import urllib.request
import urllib.error
import base64
import traceback
from typing import List, Tuple, Type, Optional
from .generator_tools import generate_rewrite_reply
from src.plugin_system.apis import send_api  # 新增导入

# 导入新插件系统
from src.plugin_system.base.base_plugin import BasePlugin
from src.plugin_system.base.base_plugin import register_plugin
from src.plugin_system.base.base_action import BaseAction
from src.plugin_system.base.component_types import ComponentInfo, ActionActivationType, ChatMode
from src.plugin_system.base.config_types import ConfigField
from src.common.logger import get_logger

logger = get_logger("doubao_pic_plugin")


# ===== Action组件 =====


class DoubaoImageGenerationAction(BaseAction):
    """豆包图片生成Action - 根据描述使用火山引擎API生成图片"""

    # 激活设置
    focus_activation_type = ActionActivationType.LLM_JUDGE  # 保持枚举类型
    normal_activation_type = ActionActivationType.KEYWORD  # 保持枚举类型
    mode_enable = ChatMode.ALL  # 保持枚举类型
    parallel_action = True

    # 动作基本信息
    action_name = "doubao_image_generation"
    action_description = (
        "可以根据特定的描述，生成并发送一张图片，如果没提供描述，就根据聊天内容生成,你可以立刻画好，不用等待"
    )

    # 关键词设置（用于Normal模式）
    activation_keywords = ["画", "绘制", "生成图片", "画图", "draw", "paint", "图片生成"]
    keyword_case_sensitive = False

    # LLM判定提示词（用于Focus模式）
    llm_judge_prompt = """
判定是否需要使用图片生成动作的条件：
1. 用户明确要求画图、生成图片或创作图像
2. 用户描述了想要看到的画面或场景
3. 对话中提到需要视觉化展示某些概念
4. 用户想要创意图片或艺术作品

适合使用的情况：
- "画一张..."、"画个..."、"生成图片"
- "我想看看...的样子"
- "能画出...吗"
- "创作一幅..."

绝对不要使用的情况：
1. 纯文字聊天和问答
2. 只是提到"图片"、"画"等词但不是要求生成
3. 谈论已存在的图片或照片
4. 技术讨论中提到绘图概念但无生成需求
5. 用户明确表示不需要图片时
"""

    # 动作参数定义
    action_parameters = {
        "description": "图片描述，输入你想要生成并发送的图片的描述，必填",
        "size": "图片尺寸，例如 '1024x1024' (可选, 默认从配置或 '1024x1024')",
    }

    # 动作使用场景
    action_require = [
        "当有人让你画东西时使用，你可以立刻画好，不用等待",
        "当有人要求你生成并发送一张图片时使用",
        "当有人让你画一张图时使用",
    ]

    # 关联类型
    associated_types = ["image", "text"]

    # 简单的请求缓存，避免短时间内重复请求
    _request_cache = {}
    _cache_max_size = 10

    async def execute(self) -> Tuple[bool, Optional[str]]:
        """执行图片生成动作"""
        logger.info(f"{self.log_prefix} 执行豆包图片生成动作")

        # 配置验证
        http_base_url = self.get_config("api.base_url")
        http_api_key = self.get_config("api.volcano_generate_api_key")

        if not (http_base_url and http_api_key):
            error_msg = "抱歉，图片生成功能所需的HTTP配置（如API地址或密钥）不完整，无法提供服务。"
            await self.send_text(error_msg)
            logger.error(f"{self.log_prefix} HTTP调用配置缺失: base_url 或 volcano_generate_api_key.")
            return False, "HTTP配置不完整"

        # API密钥验证
        if http_api_key == "YOUR_DOUBAO_API_KEY_HERE":
            error_msg = "图片生成功能尚未配置，请设置正确的API密钥。"
            await self.send_text(error_msg)
            logger.error(f"{self.log_prefix} API密钥未配置")
            return False, "API密钥未配置"

        # 参数验证
        description = self.action_data.get("description")
        if not description or not description.strip():
            logger.warning(f"{self.log_prefix} 图片描述为空，无法生成图片。")
            await self.send_text("你需要告诉我想要画什么样的图片哦~ 比如说'画一只可爱的小猫'")
            return False, "图片描述为空"

        # 清理和验证描述
        description = description.strip()
        if len(description) > 1000:  # 限制描述长度
            description = description[:1000]
            logger.info(f"{self.log_prefix} 图片描述过长，已截断")

        # 获取配置
        default_model = self.get_config("generation.default_model", "doubao-seedream-3-0-t2i-250415")
        image_size = self.action_data.get("size", self.get_config("generation.default_size", "1024x1024"))

        # 验证图片尺寸格式
        if not self._validate_image_size(image_size):
            logger.warning(f"{self.log_prefix} 无效的图片尺寸: {image_size}，使用默认值")
            image_size = "1024x1024"

        # 检查缓存
        cache_key = self._get_cache_key(description, default_model, image_size)
        if cache_key in self._request_cache:
            cached_result = self._request_cache[cache_key]
            logger.info(f"{self.log_prefix} 使用缓存的图片结果")
            # 用 generator_tools 生成回复
            result_status, result_message = await generate_rewrite_reply(
                chat_stream=self.chat_stream,
                raw_reply="我之前画过类似的图片，用之前的结果~",
                reason="图片生成缓存命中，优化表达后发送给用户"
            )
            if result_status:
                for reply_seg in result_message:
                    data = reply_seg[1]
                    await self.send_text(data)
                    await asyncio.sleep(1.0)
            else:
                await self.send_text("我之前画过类似的图片，用之前的结果~")
            send_success = await self._send_image(cached_result)
            if send_success:
                result_status, result_message = await generate_rewrite_reply(
                    chat_stream=self.chat_stream,
                    raw_reply="图片已发送！",
                    reason="图片已发送，优化表达后发送给用户"
                )
                if result_status:
                    for reply_seg in result_message:
                        data = reply_seg[1]
                        await self.send_text(data)
                        await asyncio.sleep(1.0)
                else:
                    await self.send_text("图片已发送！")
                return True, "图片已发送(缓存)"
            else:
                # 缓存失败，清除这个缓存项并继续正常流程
                del self._request_cache[cache_key]

        # 获取其他配置参数
        guidance_scale_val = self._get_guidance_scale()
        seed_val = self._get_seed()
        watermark_val = self._get_watermark()

        result_status, result_message = await generate_rewrite_reply(
            chat_stream=self.chat_stream,
            raw_reply=f"收到！正在为您生成关于 '{description}' 的图片，请稍候...（模型: {default_model}, 尺寸: {image_size}）",
            reason="图片生成请求已收到，优化表达后发送给用户"
        )
        if result_status:
            for reply_seg in result_message:
                data = reply_seg[1]
                await self.send_text(data)
                await asyncio.sleep(1.0)
        else:
            await self.send_text(
                f"收到！正在为您生成关于 '{description}' 的图片，请稍候...（模型: {default_model}, 尺寸: {image_size}）"
            )

        # 异步请求生成图片
        try:
            success, result = await asyncio.to_thread(
                self._make_http_image_request,
                prompt=description,
                model=default_model,
                size=image_size,
                seed=seed_val,
                guidance_scale=guidance_scale_val,
                watermark=watermark_val,
            )
        except Exception as e:
            logger.error(f"{self.log_prefix} (HTTP) 异步请求执行失败: {e!r}", exc_info=True)
            traceback.print_exc()
            success = False
            result = f"图片生成服务遇到意外问题: {str(e)[:100]}"

        if success:
            image_url = result
            # print(f"image_url: {image_url}")
            # print(f"result: {result}")
            logger.info(f"{self.log_prefix} 图片URL获取成功: {image_url[:70]}... 下载并编码.")

            try:
                encode_success, encode_result = await asyncio.to_thread(self._download_and_encode_base64, image_url)
            except Exception as e:
                logger.error(f"{self.log_prefix} (B64) 异步下载/编码失败: {e!r}", exc_info=True)
                traceback.print_exc()
                encode_success = False
                encode_result = f"图片下载或编码时发生内部错误: {str(e)[:100]}"

            if encode_success:
                base64_image_string = encode_result
                send_success = await self._send_image(base64_image_string)
                if send_success:
                    self._request_cache[cache_key] = base64_image_string
                    self._cleanup_cache()
                    result_status, result_message = await generate_rewrite_reply(
                        chat_stream=self.chat_stream,
                        raw_reply="图片已成功生成并发送！",
                        reason="图片生成成功，优化表达后发送给用户"
                    )
                    if result_status:
                        for reply_seg in result_message:
                            data = reply_seg[1]
                            await self.send_text(data)
                            await asyncio.sleep(1.0)
                    else:
                        await self.send_text("图片已成功生成并发送！")
                    return True, "图片已成功生成并发送"
                else:
                    await self.send_text("图片已处理为Base64，但发送失败了。")
                    return False, "图片发送失败 (Base64)"
            else:
                await self.send_text(f"获取到图片URL，但在处理图片时失败了：{encode_result}")
                return False, f"图片处理失败(Base64): {encode_result}"
        else:
            error_message = result
            result_status, result_message = await generate_rewrite_reply(
                chat_stream=self.chat_stream,
                raw_reply=f"哎呀，生成图片时遇到问题：{error_message}",
                reason="图片生成失败，优化表达后发送给用户"
            )
            if result_status:
                for reply_seg in result_message:
                    data = reply_seg[1]
                    await self.send_text(data)
                    await asyncio.sleep(1.0)
            else:
                await self.send_text(f"哎呀，生成图片时遇到问题：{error_message}")
            return False, f"图片生成失败: {error_message}"

    def _get_guidance_scale(self) -> float:
        """获取guidance_scale配置值"""
        guidance_scale_input = self.get_config("generation.default_guidance_scale", 2.5)
        try:
            return float(guidance_scale_input)
        except (ValueError, TypeError):
            logger.warning(f"{self.log_prefix} default_guidance_scale 值无效，使用默认值 2.5")
            return 2.5

    def _get_seed(self) -> int:
        """获取seed配置值"""
        seed_config_value = self.get_config("generation.default_seed")
        if seed_config_value is not None:
            try:
                return int(seed_config_value)
            except (ValueError, TypeError):
                logger.warning(f"{self.log_prefix} default_seed 值无效，使用默认值 42")
        return 42

    def _get_watermark(self) -> bool:
        """获取watermark配置值"""
        watermark_source = self.get_config("generation.default_watermark", True)
        if isinstance(watermark_source, bool):
            return watermark_source
        elif isinstance(watermark_source, str):
            return watermark_source.lower() == "true"
        else:
            logger.warning(f"{self.log_prefix} default_watermark 值无效，使用默认值 True")
            return True

    async def _send_image(self, base64_image: str) -> bool:
        """发送图片（根据 send_api 规范）"""
        try:
            chat_stream = self.chat_stream
            if not chat_stream:
                logger.error(f"{self.log_prefix} 没有可用的聊天流发送图片")
                return False
            if chat_stream.group_info:
                # 群聊
                return await send_api.image_to_group(
                    image_base64=base64_image,
                    group_id=chat_stream.group_info.group_id,
                    platform=chat_stream.platform
                )
            else:
                # 私聊
                return await send_api.image_to_user(
                    image_base64=base64_image,
                    user_id=chat_stream.user_info.user_id,
                    platform=chat_stream.platform
                )
        except Exception as e:
            logger.error(f"{self.log_prefix} 发送图片时出错: {e}")
            return False

    @classmethod
    def _get_cache_key(cls, description: str, model: str, size: str) -> str:
        """生成缓存键"""
        return f"{description[:100]}|{model}|{size}"

    @classmethod
    def _cleanup_cache(cls):
        """清理缓存，保持大小在限制内"""
        if len(cls._request_cache) > cls._cache_max_size:
            keys_to_remove = list(cls._request_cache.keys())[: -cls._cache_max_size // 2]
            for key in keys_to_remove:
                del cls._request_cache[key]

    def _validate_image_size(self, image_size: str) -> bool:
        """验证图片尺寸格式"""
        try:
            width, height = map(int, image_size.split("x"))
            return 100 <= width <= 10000 and 100 <= height <= 10000
        except (ValueError, TypeError):
            return False

    def _download_and_encode_base64(self, image_url: str) -> Tuple[bool, str]:
        """下载图片并将其编码为Base64字符串"""
        logger.info(f"{self.log_prefix} (B64) 下载并编码图片: {image_url[:70]}...")
        try:
            with urllib.request.urlopen(image_url, timeout=30) as response:
                if response.status == 200:
                    image_bytes = response.read()
                    base64_encoded_image = base64.b64encode(image_bytes).decode("utf-8")
                    logger.info(f"{self.log_prefix} (B64) 图片下载编码完成. Base64长度: {len(base64_encoded_image)}")
                    return True, base64_encoded_image
                else:
                    error_msg = f"下载图片失败 (状态: {response.status})"
                    logger.error(f"{self.log_prefix} (B64) {error_msg} URL: {image_url}")
                    return False, error_msg
        except Exception as e:
            logger.error(f"{self.log_prefix} (B64) 下载或编码时错误: {e!r}", exc_info=True)
            traceback.print_exc()
            return False, f"下载或编码图片时发生错误: {str(e)[:100]}"

    def _make_http_image_request(
        self, prompt: str, model: str, size: str, seed: int, guidance_scale: float, watermark: bool
    ) -> Tuple[bool, str]:
        """发送HTTP请求生成图片"""
        base_url = self.get_config("api.base_url")
        generate_api_key = self.get_config("api.volcano_generate_api_key")

        endpoint = f"{base_url.rstrip('/')}/images/generations"

        payload_dict = {
            "model": model,
            "prompt": prompt,
            "response_format": "url",
            "size": size,
            "guidance_scale": guidance_scale,
            "watermark": watermark,
            "seed": seed,
            "api-key": generate_api_key,
        }

        data = json.dumps(payload_dict).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {generate_api_key}",
        }

        logger.info(f"{self.log_prefix} (HTTP) 发起图片请求: {model}, Prompt: {prompt[:30]}... To: {endpoint}")

        req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                response_status = response.status
                response_body_bytes = response.read()
                response_body_str = response_body_bytes.decode("utf-8")

                logger.info(f"{self.log_prefix} (HTTP) 响应: {response_status}. Preview: {response_body_str[:150]}...")

                if 200 <= response_status < 300:
                    response_data = json.loads(response_body_str)
                    image_url = None
                    if (
                        isinstance(response_data.get("data"), list)
                        and response_data["data"]
                        and isinstance(response_data["data"][0], dict)
                    ):
                        image_url = response_data["data"][0].get("url")
                    elif response_data.get("url"):
                        image_url = response_data.get("url")

                    if image_url:
                        logger.info(f"{self.log_prefix} (HTTP) 图片生成成功，URL: {image_url[:70]}...")
                        return True, image_url
                    else:
                        logger.error(f"{self.log_prefix} (HTTP) API成功但无图片URL")
                        return False, "图片生成API响应成功但未找到图片URL"
                else:
                    logger.error(f"{self.log_prefix} (HTTP) API请求失败. 状态: {response.status}")
                    return False, f"图片API请求失败(状态码 {response.status})"
        except Exception as e:
            logger.error(f"{self.log_prefix} (HTTP) 图片生成时意外错误: {e!r}", exc_info=True)
            traceback.print_exc()
            return False, f"图片生成HTTP请求时发生意外错误: {str(e)[:100]}"


# ===== 插件主类 =====


@register_plugin
class DoubaoImagePlugin(BasePlugin):
    """豆包图片生成插件

    基于火山引擎豆包模型的AI图片生成插件：
    - 图片生成Action：根据描述使用火山引擎API生成图片
    """

    # 插件基本信息
    plugin_name = "doubao_pic_plugin"  # 内部标识符
    enable_plugin = True
    config_file_name = "config.toml"

    # 配置节描述
    config_section_descriptions = {
        "plugin": "插件基本信息配置",
        "api": "API相关配置，包含火山引擎API的访问信息",
        "generation": "图片生成参数配置，控制生成图片的各种参数",
        "cache": "结果缓存配置",
        "components": "组件启用配置",
    }

    # 配置Schema定义
    config_schema = {
        "plugin": {
            "name": ConfigField(type=str, default="doubao_pic_plugin", description="插件名称", required=True),
            "version": ConfigField(type=str, default="2.0.0", description="插件版本号"),
            "enabled": ConfigField(type=bool, default=False, description="是否启用插件"),
            "description": ConfigField(
                type=str, default="基于火山引擎豆包模型的AI图片生成插件", description="插件描述", required=True
            ),
        },
        "api": {
            "base_url": ConfigField(
                type=str,
                default="https://ark.cn-beijing.volces.com/api/v3",
                description="API基础URL",
                example="https://api.example.com/v1",
            ),
            "volcano_generate_api_key": ConfigField(
                type=str, default="YOUR_DOUBAO_API_KEY_HERE", description="火山引擎豆包API密钥", required=True
            ),
        },
        "generation": {
            "default_model": ConfigField(
                type=str,
                default="doubao-seedream-3-0-t2i-250415",
                description="默认使用的文生图模型",
                choices=["doubao-seedream-3-0-t2i-250415", "doubao-seedream-2-0-t2i"],
            ),
            "default_size": ConfigField(
                type=str,
                default="1024x1024",
                description="默认图片尺寸",
                example="1024x1024",
                choices=["1024x1024", "1024x1280", "1280x1024", "1024x1536", "1536x1024"],
            ),
            "default_watermark": ConfigField(type=bool, default=True, description="是否默认添加水印"),
            "default_guidance_scale": ConfigField(
                type=float, default=2.5, description="模型指导强度，影响图片与提示的关联性", example="2.0"
            ),
            "default_seed": ConfigField(type=int, default=42, description="随机种子，用于复现图片"),
        },
        "cache": {
            "enabled": ConfigField(type=bool, default=True, description="是否启用请求缓存"),
            "max_size": ConfigField(type=int, default=10, description="最大缓存数量"),
        },
        "components": {
            "enable_image_generation": ConfigField(type=bool, default=True, description="是否启用图片生成Action")
        },
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        """返回插件包含的组件列表"""

        # 从配置获取组件启用状态
        enable_image_generation = self.get_config("components.enable_image_generation", True)

        components = []

        # 添加图片生成Action
        if enable_image_generation:
            components.append((DoubaoImageGenerationAction.get_action_info(), DoubaoImageGenerationAction))

        return components
