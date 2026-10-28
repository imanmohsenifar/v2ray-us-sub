#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
🤖 V2Ray US Subscription Collector & Auto-Updater
=============================================================================
این اسکریپت کانفیگ‌های رایگان V2Ray را از منابع معتبر گیت‌هاب دریافت کرده،
فقط کانفیگ‌های لوکیشن آمریکا (US) را تفکیک و بهینه‌سازی نموده و به صورت یک
لینک استاندارد Base64 برای استفاده در برنامه v2rayNG خروجی می‌دهد.
=============================================================================
"""

import os
import re
import sys
import json
import base64
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import requests

# ---------------------------------------------------------------------------
# 1. تنظیمات و منابع معتبر (Reputable GitHub Sources)
# ---------------------------------------------------------------------------
SOURCES = [
    "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/base64/mix",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub1.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub2.txt",
    "https://raw.githubusercontent.com/freefq/free/master/v2",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge.txt",
    "https://raw.githubusercontent.com/peasoft/NoMoreForbiddenSites/master/user_sub.txt",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/reality",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/vless",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/vmess",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/trojan",
]

# نام فایل‌های خروجی
OUTPUT_SUB_TXT = "sub_us.txt"          # متن خام کانفیگ‌ها (خط به خط)
OUTPUT_SUB_BASE64 = "sub_us_base64.txt" # سابسکریپشن کدگذاری شده Base64 (مخصوص v2rayNG)
OUTPUT_INFO_JSON = "sub_info.json"     # اطلاعات آماری و آخرین بروزرسانی

# الگوهای تشخیص کشور آمریکا بر اساس پرچم، نام شهرها و کلمات کلیدی در Remark
US_KEYWORDS_PATTERN = re.compile(
    r"(?:🇺🇸|\b(?:US|USA|United[\s_-]?States|America|California|Los[\s_-]?Angeles|Silicon[\s_-]?Valley|"
    r"San[\s_-]?Francisco|San[\s_-]?Jose|New[\s_-]?York|Chicago|Miami|Dallas|Texas|Seattle|"
    r"Washington|Ashburn|Virginia|Atlanta|New[\s_-]?Jersey|Phoenix|Oregon|Las[\s_-]?Vegas|Denver)\b)",
    re.IGNORECASE,
)

# الگوهای رد کردن سایر کشورها (جلوگیری از تشخیص اشتباه)
NON_US_PATTERN = re.compile(
    r"(?:🇩🇪|🇬🇧|🇫🇷|🇮🇷|🇹🇷|🇷🇺|🇯🇵|🇸🇬|🇭🇰|🇳🇱|🇨🇦|🇦🇺|🇫🇮|🇸🇪|\b(?:Germany|UK|United[\s_-]?Kingdom|"
    r"France|Iran|Turkey|Russia|Japan|Singapore|Hong[\s_-]?Kong|Netherlands|Canada|Australia)\b)",
    re.IGNORECASE,
)

# پروتکل‌های مجاز
SUPPORTED_PROTOCOLS = ("vmess://", "vless://", "trojan://", "ss://", "ssr://", "hy2://", "hysteria2://", "tuic://")

HEADERS = {
    "User-Agent": "v2rayNG/1.8.5 (Linux; Android 13; Mobile) AppleWebKit/537.36",
    "Accept": "text/plain,application/json,*/*",
}


# ---------------------------------------------------------------------------
# 2. توابع کمکی رمزگشایی و پردازش (Helper Functions)
# ---------------------------------------------------------------------------
def safe_b64decode(s: str) -> str:
    """رمزگشایی ایمن Base64 همراه با اضافه کردن Padding در صورت نیاز"""
    try:
        clean = s.strip().replace(" ", "").replace("\n", "").replace("\r", "")
        # اصلاح پدینگ در صورتی که طول مضرب ۴ نباشد
        missing_padding = len(clean) % 4
        if missing_padding:
            clean += "=" * (4 - missing_padding)
        return base64.b64decode(clean).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def safe_b64encode(s: str) -> str:
    """کدگذاری متن به رشته Base64 استاندارد برای سابسکریپشن"""
    return base64.b64encode(s.encode("utf-8")).decode("utf-8")


def fetch_source(url: str, timeout: int = 15) -> list[str]:
    """دریافت محتوای یک لینک سابسکریپشن با مدیریت خطا"""
    print(f"📥 در حال دریافت: {url}")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code != 200:
            print(f"⚠️ خطای کد وضعیت {resp.status_code} برای {url}")
            return []

        text = resp.text.strip()
        if not text:
            return []

        # اگر خروجی base64 باشد، آن را بازگشایی می‌کنیم
        if not any(proto in text for proto in ("vless://", "vmess://", "trojan://", "ss://")):
            decoded = safe_b64decode(text)
            if any(proto in decoded for proto in ("vless://", "vmess://", "trojan://", "ss://")):
                text = decoded

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        valid_configs = [line for line in lines if line.startswith(SUPPORTED_PROTOCOLS)]
        print(f"✅ دریافت {len(valid_configs)} کانفیگ از {url[:50]}...")
        return valid_configs
    except Exception as e:
        print(f"❌ خطا در دریافت {url}: {e}")
        return []


# ---------------------------------------------------------------------------
# 3. توابع تحلیل کانفیگ و تشخیص لوکیشن آمریکا (US Detection)
# ---------------------------------------------------------------------------
def extract_remark_and_server(config_line: str) -> tuple[str, str, str]:
    """استخراج Remark (توضیحات)، سرور و پورت از انواع فرمت‌های V2Ray"""
    remark = ""
    server = ""
    port = ""

    try:
        # پروتکل VMess (معمولاً JSON Base64 است)
        if config_line.startswith("vmess://"):
            raw_b64 = config_line[8:]
            decoded_json = safe_b64decode(raw_b64)
            data = json.loads(decoded_json)
            remark = str(data.get("ps", ""))
            server = str(data.get("add", ""))
            port = str(data.get("port", ""))
            return remark, server, port

        # پروتکل‌های مبتنی بر ساختار URL (vless, trojan, hysteria2, tuic)
        if config_line.startswith(("vless://", "trojan://", "hysteria2://", "hy2://", "tuic://")):
            parsed = urllib.parse.urlparse(config_line)
            remark = urllib.parse.unquote(parsed.fragment) if parsed.fragment else ""
            server = parsed.hostname or ""
            port = str(parsed.port or "443")
            return remark, server, port

        # پروتکل Shadowsocks
        if config_line.startswith("ss://"):
            fragment = ""
            if "#" in config_line:
                main_part, fragment = config_line.split("#", 1)
                remark = urllib.parse.unquote(fragment)
            else:
                main_part = config_line

            clean = main_part[5:]
            if "@" in clean:
                host_port = clean.split("@")[1].split("/")[0]
                server = host_port.split(":")[0]
                port = host_port.split(":")[1] if ":" in host_port else "443"
            return remark, server, port

    except Exception:
        pass

    return remark, server, port


def is_us_location(remark: str, server: str) -> bool:
    """بررسی اینکه آیا کانفیگ متعلق به آمریکا است یا خیر"""
    # ۱. اگر پرچم آمریکا داشت قطعی است
    if "🇺🇸" in remark:
        return True

    # ۲. اگر نام کشور دیگری صریحاً آمده و آمریکا نیامده، رد شود
    if NON_US_PATTERN.search(remark) and not US_KEYWORDS_PATTERN.search(remark):
        return False

    # ۳. بررسی کلمات کلیدی آمریکا در نام یا توضیحات کانفیگ
    if US_KEYWORDS_PATTERN.search(remark):
        return True

    # ۴. بررسی ساب‌دامین سرور (مثلاً us-server.node.net یا la.speed.org)
    server_lower = server.lower()
    if re.search(r"(?:^|.)(?:us|usa|la|nyc|chi|sjc|iad|dal|sea)(?:d+)?.", server_lower):
        return True

    return False


# ---------------------------------------------------------------------------
# 4. اجرای اصلی فرآیند دریافت، فیلتر و ذخیره (Main Routine)
# ---------------------------------------------------------------------------
def main():
    start_time = datetime.now(timezone.utc)
    print("=" * 60)
    print("🚀 شروع فرآیند دریافت و فیلتر خودکار کانفیگ‌های آمریکا (US)...")
    print(f"⏰ زمان اجرا (UTC): {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # دریافت موازی از تمام منابع برای افزایش سرعت
    all_raw_configs = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_url = {executor.submit(fetch_source, url): url for url in SOURCES}
        for future in as_completed(future_to_url):
            configs = future.result()
            all_raw_configs.extend(configs)

    print(f"\n📊 مجموع کانفیگ‌های خام دریافت شده: {len(all_raw_configs)}")

    # فیلتر کردن کانفیگ‌های آمریکا و حذف موارد تکراری
    us_configs = []
    seen_unique_keys = set()
    protocol_stats = {"vless": 0, "vmess": 0, "trojan": 0, "ss": 0, "other": 0}

    for config in all_raw_configs:
        remark, server, port = extract_remark_and_server(config)
        
        # کلید یکتا بر اساس پروتکل، سرور و پورت جهت جلوگیری از کانفیگ‌های تکراری
        proto = config.split("://")[0].lower() if "://" in config else "other"
        unique_key = f"{proto}://{server}:{port}"
        
        if unique_key in seen_unique_keys:
            continue

        if is_us_location(remark, server):
            seen_unique_keys.add(unique_key)
            us_configs.append(config)
            
            if proto in protocol_stats:
                protocol_stats[proto] += 1
            else:
                protocol_stats["other"] += 1

    print(f"✨ تعداد کانفیگ‌های یکتای لوکیشن آمریکا (US): {len(us_configs)}")
    print(f"📈 تفکیک پروتکل‌ها: {protocol_stats}")

    if not us_configs:
        print("⚠️ هیچ کانفیگ آمریکایی پیدا نشد! فایل‌های موجود دست‌نخورده باقی می‌مانند.")
        sys.exit(0)

    # ذخیره فایل sub_us.txt به صورت متن ساده
    sub_plain_text = "\n".join(us_configs) + "\n"
    with open(OUTPUT_SUB_TXT, "w", encoding="utf-8") as f:
        f.write(sub_plain_text)
    print(f"💾 فایل متنی در '{OUTPUT_SUB_TXT}' ذخیره شد.")

    # ذخیره فایل sub_us_base64.txt (سابسکریپشن مستقیم مخصوص v2rayNG)
    sub_b64 = safe_b64encode(sub_plain_text)
    with open(OUTPUT_SUB_BASE64, "w", encoding="utf-8") as f:
        f.write(sub_b64)
    print(f"💾 فایل سابسکریپشن Base64 در '{OUTPUT_SUB_BASE64}' ذخیره شد.")

    # ذخیره متادیتا و آمار در قالب JSON
    info = {
        "updated_at_utc": start_time.isoformat(),
        "total_us_configs": len(us_configs),
        "total_raw_fetched": len(all_raw_configs),
        "protocol_breakdown": protocol_stats,
        "format": "v2rayNG / Clash / Sing-box compatible Base64",
    }
    with open(OUTPUT_INFO_JSON, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2, ensure_ascii=False)
    print(f"💾 اطلاعات آماری در '{OUTPUT_INFO_JSON}' ذخیره شد.")

    print("=" * 60)
    print("🎉 عملیات با موفقیت به پایان رسید!")
    print("=" * 60)


if __name__ == "__main__":
    main()
