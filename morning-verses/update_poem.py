"""
晨间诗笺 · 每日诗歌自动生成脚本
=====================================
由 GitHub Actions 每日定时调用（北京时间 9:00）。

流程：
  1. 读取 poems.json
  2. 检查今日是否已有诗歌，若有则跳过
  3. 调用 DeepSeek API 生成一首现代诗 + 解析
  4. 将新诗插入 poems.json 数组最前端

依赖：openai, requests
运行：python update_poem.py
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

# -----------------------------------------------------------
# 配置
# -----------------------------------------------------------

# 北京时间时区 (UTC+8)
BJT = timezone(timedelta(hours=8))

# poems.json 相对于本脚本的路径（同目录）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
POEMS_FILE = os.path.join(SCRIPT_DIR, "poems.json")

# DeepSeek API 配置（兼容 OpenAI SDK）
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = "deepseek-chat"  # DeepSeek 的对话模型


# -----------------------------------------------------------
# 工具函数
# -----------------------------------------------------------

def get_today_bjt() -> str:
    """返回今日北京时间日期，格式 YYYY-MM-DD"""
    return datetime.now(BJT).strftime("%Y-%m-%d")


def load_poems() -> dict:
    """读取 poems.json，返回完整字典。文件不存在则返回初始结构。"""
    if not os.path.exists(POEMS_FILE):
        return {"poems": []}
    with open(POEMS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_poems(data: dict) -> None:
    """将数据写回 poems.json，保持 indent=2 的整洁格式。"""
    with open(POEMS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")  # 末尾换行，符合 Git 惯例


def poem_exists_for_date(data: dict, date_str: str) -> bool:
    """检查指定日期是否已有诗歌。"""
    return any(p.get("date") == date_str for p in data.get("poems", []))


# -----------------------------------------------------------
# DeepSeek API 调用
# -----------------------------------------------------------

def generate_poem(date_str: str) -> dict:
    """
    调用 DeepSeek API 生成一首现代诗及其解析。

    参数:
        date_str: 日期字符串，如 "2026-07-17"

    返回:
        dict: {"date": str, "title": str, "content": [str, ...], "analysis": str}

    异常:
        RuntimeError: API 调用失败或返回无法解析的内容
    """
    if not DEEPSEEK_API_KEY:
        raise RuntimeError(
            "环境变量 DEEPSEEK_API_KEY 未设置。"
            "请在 GitHub Secrets 或本地环境中配置该密钥。"
        )

    # 延迟导入，避免非必需依赖阻断脚本启动时的错误提示
    from openai import OpenAI

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
    )

    # 构建 system prompt：约束诗人风格与输出格式
    system_prompt = (
        "你是一位冷静克制的现代诗人，风格介于张枣与雷蒙德·卡佛之间。"
        "你擅长在日常物象中捕捉时间的纹理，用简洁准确的汉语写出安静而有力的诗。"
        "你的诗拒绝华丽修饰，拒绝滥情，追求精准的意象与克制的留白。"
        "你以严格的 JSON 格式回复，除此之外不输出任何文字。"
    )

    user_prompt = (
        f"今天是 {date_str}。请为这个清晨创作一首原创现代诗。\n\n"
        "要求：\n"
        "1. 诗题 (title)：4-10 个汉字。\n"
        "2. 正文 (content)：6-14 行，以字符串数组表示，每行不超过 20 个汉字。\n"
        "3. 解析 (analysis)：80-180 字的简短赏析，点出诗中核心意象与情感走向。\n\n"
        "请严格输出如下格式的 JSON（不要包含 Markdown 代码块标记）：\n"
        "{\n"
        '  "title": "诗题",\n'
        '  "content": ["第一行", "第二行", ...],\n'
        '  "analysis": "简短解析……"\n'
        "}"
    )

    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.85,   # 稍高温度，增加诗意的多样性
            max_tokens=1024,
        )
    except Exception as e:
        raise RuntimeError(f"DeepSeek API 调用失败: {e}")

    raw_text = response.choices[0].message.content.strip()

    # 清理可能的 Markdown 代码块标记（```json ... ```）
    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        # 去掉首行 ``` 和末行 ```
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw_text = "\n".join(lines).strip()

    # 解析 JSON
    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"API 返回内容无法解析为 JSON: {e}\n"
            f"原始返回（前 500 字符）:\n{raw_text[:500]}"
        )

    # 校验必要字段
    required = ["title", "content", "analysis"]
    missing = [f for f in required if f not in result]
    if missing:
        raise RuntimeError(f"API 返回的 JSON 缺少字段: {missing}")

    if not isinstance(result["content"], list):
        raise RuntimeError("content 字段应为字符串数组")

    # 组装最终数据
    return {
        "date": date_str,
        "title": result["title"],
        "content": result["content"],
        "analysis": result["analysis"],
    }


# -----------------------------------------------------------
# 主流程
# -----------------------------------------------------------

def main():
    print("晨间诗笺 · 每日更新脚本")
    print("=" * 40)

    today = get_today_bjt()
    print(f"今日日期 (北京时间): {today}")

    # 1. 加载现有数据
    data = load_poems()
    existing_count = len(data.get("poems", []))
    print(f"已加载 poems.json，现有 {existing_count} 首诗")

    # 2. 检查今日是否已有诗歌
    if poem_exists_for_date(data, today):
        print(f"✓ 今日 ({today}) 已有诗歌，无需更新，退出。")
        return 0

    # 3. 调用 API 生成
    print(f"正在调用 DeepSeek API 生成 {today} 的诗笺...")
    try:
        new_poem = generate_poem(today)
    except RuntimeError as e:
        print(f"✗ 生成失败: {e}", file=sys.stderr)
        return 1

    print(f"✓ 生成成功: 《{new_poem['title']}》")
    print(f"  行数: {len(new_poem['content'])}")
    print(f"  解析字数: {len(new_poem['analysis'])}")

    # 4. 插入数组最前端（最新的在前）
    data.setdefault("poems", []).insert(0, new_poem)

    # 5. 写回文件
    save_poems(data)
    print(f"✓ 已写入 poems.json（共 {len(data['poems'])} 首诗）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
