# doubao_pic_tools.py

豆包图片生成工具函数

本文件为豆包图片生成插件的工具函数集合，便于其他插件（如 search 插件等）直接调用图片生成能力，无需依赖插件主类。

## 功能简介
- 发送 HTTP 请求调用火山引擎豆包图片生成 API
- 下载图片并编码为 base64 字符串
- 校验图片尺寸格式

## 主要函数

### make_http_image_request
```python
def make_http_image_request(prompt, model, size, seed, guidance_scale, watermark, api_key, base_url, timeout=60) -> Tuple[bool, str]
```
- 功能：调用豆包 API 生成图片，返回 (成功, 图片URL或错误信息)
- 参数：
  - prompt: 图片描述
  - model: 模型名
  - size: 图片尺寸（如 '1024x1024'）
  - seed: 随机种子
  - guidance_scale: 指导强度
  - watermark: 是否加水印
  - api_key: API密钥
  - base_url: API基础URL
  - timeout: 超时时间（秒）
- 返回：
  - (True, 图片URL) 或 (False, 错误信息)

### download_and_encode_base64
```python
def download_and_encode_base64(image_url, timeout=30) -> Tuple[bool, str]
```
- 功能：下载图片并转为 base64 字符串
- 参数：
  - image_url: 图片URL
  - timeout: 超时时间（秒）
- 返回：
  - (True, base64字符串) 或 (False, 错误信息)

### validate_image_size
```python
def validate_image_size(image_size) -> bool
```
- 功能：校验图片尺寸格式（如 '1024x1024'，宽高100~10000）
- 返回：
  - True/False

## 使用示例

```python
from doubao_pic_tools import make_http_image_request, download_and_encode_base64, validate_image_size

# 生成图片URL
ok, url_or_err = make_http_image_request(
    prompt="画一只可爱的猫",
    model="doubao-seedream-3-0-t2i-250415",
    size="1024x1024",
    seed=42,
    guidance_scale=2.5,
    watermark=True,
    api_key="你的API密钥",
    base_url="https://ark.cn-beijing.volces.com/api/v3"
)
if ok:
    # 下载并转base64
    ok2, b64_or_err = download_and_encode_base64(url_or_err)
    if ok2:
        print("图片base64:", b64_or_err[:100], "...")
    else:
        print("下载失败:", b64_or_err)
else:
    print("生成失败:", url_or_err)
```

## 注意事项
- 需提前配置好 API 密钥和 base_url。
- 若图片描述过长建议截断。
- 本工具文件可被任意插件 import 使用。

---

如需更多高级用法，请参考主插件 `plugin.py` 的实现。
