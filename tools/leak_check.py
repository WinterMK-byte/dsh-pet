# -*- coding: utf-8 -*-
"""leak_check.py — 发布前泄漏门禁（仓内自检）

检查三类会把「本机私有信息」带进公开仓库的东西：
  1. 绝对路径（本机用户名、盘符路径、桌面目录）
  2. 凭据字面量（GitHub token / 长随机串 / 私钥头）
  3. 私人信息（邮箱、超长数字串、AI 生成水印元数据）

用法：
    python tools/leak_check.py .            # 扫当前仓
    python tools/leak_check.py --selftest   # 只跑检查器自身的用例

退出码：0 = 干净；1 = 有命中；2 = 自测失败
"""

from __future__ import annotations

import os
import re
import sys

# ---------------------------------------------------------------- 扫描范围

SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "build", "dist", "temp",
    "__pycache__", ".pytest_cache", ".idea", ".vscode", "node_modules",
}

# 这些后缀必然是二进制，不按文本扫（体积也大）
SKIP_EXT = (
    ".exe", ".dll", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svgz",
    ".zip", ".7z", ".rar", ".gz", ".whl", ".pdf", ".pyz", ".pyd",
    ".pkl", ".npy", ".onnx", ".gguf", ".safetensors",
)

# 本文件自身含各种正则字面量，扫自己必然假红
SELF_NAME = "leak_check.py"

# ---------------------------------------------------------------- 判据

# 允许的占位写法：<you> / %USERPROFILE% / * / $HOME
_ALLOW_AFTER_USERS = r"(?![<%*$])"

PATTERNS = [
    (
        "本机绝对路径（含用户名）",
        re.compile(
            r"(?<![A-Za-z])[A-Za-z]:\\+Users\\+" + _ALLOW_AFTER_USERS + r"[A-Za-z0-9_.\-]+"
        ),
    ),
    (
        "桌面路径",
        re.compile(r"(?<![A-Za-z])[A-Za-z]:\\+[^\r\n]{0,40}?Desktop\\"),
    ),
    (
        "GitHub / 云厂商 token 字面量",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,})"),
    ),
    (
        "私钥块",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ),
    (
        "引号包裹的长随机串（疑似密钥）",
        re.compile(r"""['"][A-Za-z0-9+/=_\-]{40,}['"]"""),
    ),
    (
        "私人邮箱",
        re.compile(r"(?<![\w.\-])[\w.\-]{2,}@(?!users\.noreply|example\.|test\.)[\w\-]+\.[A-Za-z]{2,}"),
    ),
    (
        "超长数字串（≥18 位，疑似账号 / 卡号）",
        re.compile(r"(?<!\d)\d{18,}(?!\d)"),
    ),
    (
        "AI 生成水印元数据",
        re.compile(r"(?i)\b(?:AIGC\s*:|ContentProducer|ContentPropagator|ProduceID|PropagateID|ReservedCode[12])"),
    ),
    (
        "内容由 AI 生成 声明残留",
        re.compile(r"（内容由\s*AI\s*生成"),
    ),
]

# 逐行豁免：这些是正常的文档/代码写法，不该报
LINE_ALLOW = [
    re.compile(r"<you>|<项目所在目录>|<your-|<path>"),
    re.compile(r"(?i)@(?:users\.noreply\.github\.com|github\.com)"),
]


def is_text(data: bytes) -> bool:
    """按 NUL 字节判二进制（比按后缀判可靠）。"""
    return b"\x00" not in data[:8000]


def walk(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS]
        for fn in filenames:
            if fn.lower().endswith(SKIP_EXT):
                continue
            if fn == SELF_NAME:
                continue
            yield os.path.join(dirpath, fn)


def scan(root: str) -> list[tuple[str, int, str, str]]:
    hits: list[tuple[str, int, str, str]] = []
    for path in walk(root):
        try:
            raw = open(path, "rb").read()
        except OSError:
            continue
        if not is_text(raw):
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw.decode("gbk")
            except UnicodeDecodeError:
                continue
        rel = os.path.relpath(path, root)
        for lineno, line in enumerate(text.splitlines(), 1):
            if any(p.search(line) for p in LINE_ALLOW):
                continue
            for label, pat in PATTERNS:
                m = pat.search(line)
                if m:
                    hits.append((rel, lineno, label, m.group(0)[:80]))
    return hits


# ---------------------------------------------------------------- 自测

SELFTEST_CASES = [
    # (样本, 是否应当命中)
    (r'cd /d C:\Users\alice\Desktop\marvis-pet', True),
    (r'path = "C:\Users\<you>\Desktop\"', False),
    (r"// %USERPROFILE%\Desktop", False),
    ("token = ghp_" + "a" * 30, True),
    ("contact me at someone@qq.com", True),
    ("noreply: WinterMK@users.noreply.github.com", False),
    ("id 12345678901234567890123", True),
    ("port 11434 / 127.0.0.1", False),
    ("AIGC:\n  ContentProducer: 0011914", True),
    ("*（内容由AI生成，仅供参考）*", True),
    ("-----BEGIN RSA PRIVATE KEY-----", True),
    ("# 正常的中文说明，无敏感内容", False),
]


def selftest() -> int:
    bad = 0
    for sample, should in SELFTEST_CASES:
        found = any(p.search(sample) for _, p in PATTERNS) and not any(
            p.search(sample) for p in LINE_ALLOW
        )
        if found != should:
            bad += 1
            print(f"  [FAIL] 期望{'命中' if should else '放行'}，实际相反：{sample[:60]!r}")
        else:
            print(f"  [ok] {'命中' if should else '放行'}：{sample[:60]!r}")
    print(f"自测：{len(SELFTEST_CASES) - bad}/{len(SELFTEST_CASES)} 通过")
    return 0 if bad == 0 else 2


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if "--selftest" in argv:
        return selftest()

    root = next((a for a in argv[1:] if not a.startswith("-")), ".")
    if not os.path.isdir(root):
        print(f"[错误] 目录不存在：{root}")
        return 2

    hits = scan(root)
    if not hits:
        print(f"[通过] 未发现泄漏：{os.path.abspath(root)}")
        return 0

    print(f"[失败] 命中 {len(hits)} 处：")
    for rel, lineno, label, val in hits:
        print(f"  {rel}:{lineno}  [{label}]  {val}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
