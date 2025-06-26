"""
doubao_pic_tools.py

豆包图片生成工具函数，供其他插件调用。
"""
import json
import urllib.request
import base64
import traceback
from typing import Tuple
import logging

def make_http_image_request(
    prompt: str,
    model: str,
    size: str,
    seed: int,
    guidance_scale: float,
    watermark: bool,
    api_key: str,
    base_url: str,
    timeout: int = 60
) -> Tuple[bool, str]:
    """
    发送HTTP请求生成图片，返回 (成功, 图片URL或错误信息)
    """
    endpoint = f"{base_url.rstrip('/')}/images/generations"
    payload_dict = {
        "model": model,
        "prompt": prompt,
        "response_format": "url",
        "size": size,
        "guidance_scale": guidance_scale,
        "watermark": watermark,
        "seed": seed,
        "api-key": api_key,
    }
    data = json.dumps(payload_dict).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    try:
        req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            response_status = response.status
            response_body_bytes = response.read()
            response_body_str = response_body_bytes.decode("utf-8")
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
                    return True, image_url
                else:
                    return False, "图片生成API响应成功但未找到图片URL"
            else:
                return False, f"图片API请求失败(状态码 {response.status})"
    except Exception as e:
        traceback.print_exc()
        return False, f"图片生成HTTP请求时发生意外错误: {str(e)[:100]}"

def download_and_encode_base64(image_url: str, timeout: int = 30) -> Tuple[bool, str]:
    """
    下载图片并将其编码为Base64字符串，返回 (成功, base64字符串或错误信息)
    """
    try:
        with urllib.request.urlopen(image_url, timeout=timeout) as response:
            if response.status == 200:
                image_bytes = response.read()
                base64_encoded_image = base64.b64encode(image_bytes).decode("utf-8")
                return True, base64_encoded_image
            else:
                return False, f"下载图片失败 (状态: {response.status})"
    except Exception as e:
        traceback.print_exc()
        return False, f"下载或编码图片时发生错误: {str(e)[:100]}"

def validate_image_size(image_size: str) -> bool:
    """
    验证图片尺寸格式，格式如 '1024x1024'，宽高100~10000
    """
    try:
        width, height = map(int, image_size.split("x"))
        return 100 <= width <= 10000 and 100 <= height <= 10000
    except (ValueError, TypeError):
        return False
