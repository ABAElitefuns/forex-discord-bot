"""
🤖 Forex Alert Bot — USD High Impact News Tracker
ติดตามข่าว Forex High Impact และวิเคราะห์ด้วย AI อัตโนมัติ
"""

import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
from datetime import datetime, timedelta
import pytz
import os
import logging
from anthropic import Anthropic

# ─────────────────────────────────────────────
# ⚙️ CONFIGURATION — อ่านจาก Environment Variables
# ─────────────────────────────────────────────
DISCORD_TOKEN       = os.environ["DISCORD_TOKEN"]
ANTHROPIC_API_KEY   = os.environ["ANTHROPIC_API_KEY"]
DISCORD_CHANNEL_ID  = int(os.environ["DISCORD_CHANNEL_ID"])

# Timezone settings
UTC_TZ  = pytz.utc
BKK_TZ  = pytz.timezone("Asia/Bangkok")   # UTC+7

# Forex Factory calendar endpoint (ไม่ต้อง API Key)
FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# ─────────────────────────────────────────────
# 📋 LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ForexBot")

# ─────────────────────────────────────────────
# 🤖 BOT SETUP
# ─────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)

# ป้องกันการแจ้งเตือนซ้ำ
alerted_5min: set[str]   = set()
alerted_actual: set[str] = set()

# ─────────────────────────────────────────────
# 📡 FOREX CALENDAR API
# ─────────────────────────────────────────────
async def fetch_usd_high_impact() -> list[dict]:
    """ดึงข่าว USD High Impact จาก ForexFactory"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(FF_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    log.error(f"FF API error: {resp.status}")
                    return []
                data = await resp.json(content_type=None)
                filtered = [
                    e for e in data
                    if e.get("country") == "USD" and e.get("impact") == "High"
                ]
                log.info(f"พบข่าว USD High Impact {len(filtered)} รายการ")
                return filtered
    except Exception as e:
        log.error(f"Fetch error: {e}")
        return []

def parse_event_dt(event: dict) -> datetime | None:
    """แปลง ISO date string → datetime object (UTC-aware)"""
    raw = event.get("date", "")
    try:
        # format: "2025-01-15T13:30:00+00:00"
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.astimezone(UTC_TZ)
    except Exception:
        return None

def event_key(event: dict) -> str:
    return f"{event.get('title')}|{event.get('date')}"

# ─────────────────────────────────────────────
# 🧠 AI ANALYSIS
# ─────────────────────────────────────────────
SYSTEM_PROMPT = """คุณคือนักวิเคราะห์ Forex ผู้เชี่ยวชาญระดับมืออาชีพ
มีหน้าที่วิเคราะห์ตัวเลขเศรษฐกิจสหรัฐฯ และบอกผลกระทบต่อ USD กับคู่เงินหลักอย่างรวดเร็วและแม่นยำ
ตอบเป็นภาษาไทย กระชับ ตรงประเด็น ไม่ใช้ Markdown แบบซับซ้อน"""

def build_analysis_prompt(event: dict) -> str:
    actual   = event.get("actual", "N/A")
    forecast = event.get("forecast", "N/A")
    previous = event.get("previous", "N/A")
    title    = event.get("title", "N/A")

    # เปรียบเทียบตัวเลข
    comparison = "ไม่สามารถเปรียบเทียบได้"
    try:
        a = float(actual.replace("%", "").replace("K", "").replace("M", "").replace("B", "").strip())
        f = float(forecast.replace("%", "").replace("K", "").replace("M", "").replace("B", "").strip())
        if a > f:
            comparison = f"ดีกว่าคาด ({actual} vs {forecast})"
        elif a < f:
            comparison = f"แย่กว่าคาด ({actual} vs {forecast})"
        else:
            comparison = f"ตรงตามคาด ({actual})"
    except Exception:
        comparison = f"Actual {actual} / Forecast {forecast}"

    return f"""วิเคราะห์ข่าวเศรษฐกิจสหรัฐฯ ต่อไปนี้ และตอบในรูปแบบที่กำหนดเท่านั้น:

ข่าว: {title}
ระดับ: High Impact
Actual: {actual}
Forecast: {forecast}
Previous: {previous}
ผลเทียบคาด: {comparison}

ตอบในรูปแบบนี้เท่านั้น (ห้ามเพิ่มส่วนอื่น):

📌 สรุปผล: [ประโยคเดียว สรุปตัวเลข]
💵 ผลต่อ USD: [แข็งค่า/อ่อนค่า/ผสม] — [เหตุผลสั้น 1-2 ประโยค]
🔀 คู่เงินหลัก:
• EURUSD → [ขึ้น/ลง/ผสม] [เหตุผลสั้น]
• GBPUSD → [ขึ้น/ลง/ผสม] [เหตุผลสั้น]
• USDJPY → [ขึ้น/ลง/ผสม] [เหตุผลสั้น]
• XAUUSD → [ขึ้น/ลง/ผสม] [เหตุผลสั้น]
⚡ ระดับความผันผวน: [สูงมาก🔴 / สูง🟠 / ปานกลาง🟡 / ต่ำ🟢]
💡 แนะนำเทรดเดอร์: [1-2 ประโยค คำแนะนำเชิงปฏิบัติ]"""

async def analyze_news(event: dict) -> str:
    """ส่งข่าวให้ Claude วิเคราะห์"""
    try:
        prompt = build_analysis_prompt(event)
        msg = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        log.error(f"AI analysis error: {e}")
        return "❌ ไม่สามารถวิเคราะห์ได้ในขณะนี้ กรุณาตรวจสอบ API Key"

# ─────────────────────────────────────────────
# 📨 DISCORD EMBEDS
# ─────────────────────────────────────────────
async def send_5min_warning(channel: discord.TextChannel, event: dict, dt_utc: datetime):
    """ส่งการแจ้งเตือนล่วงหน้า 5 นาที"""
    dt_bkk = dt_utc.astimezone(BKK_TZ)
    time_str = dt_bkk.strftime("%H:%M น. (Bangkok)")

    embed = discord.Embed(
        title="⚠️  ข่าว HIGH IMPACT กำลังจะออก!",
        description=f"**{event.get('title')}** จะประกาศในอีก **5 นาที**",
        color=0xFFCC00,
        timestamp=datetime.utcnow(),
    )
    embed.add_field(name="🕐 เวลาออก", value=time_str, inline=True)
    embed.add_field(name="🌎 ประเทศ", value="🇺🇸 United States", inline=True)
    embed.add_field(name="💥 ระดับ", value="🔴 HIGH IMPACT", inline=True)
    embed.add_field(
        name="📊 ตัวเลขอ้างอิง",
        value=(
            f"**Forecast:** `{event.get('forecast', 'N/A')}`\n"
            f"**Previous:** `{event.get('previous', 'N/A')}`"
        ),
        inline=False,
    )
    embed.add_field(
        name="📌 คำแนะนำ",
        value="⚡ ระวังความผันผวนสูง — พิจารณาลด position หรืองด trade ช่วงนี้",
        inline=False,
    )
    embed.set_footer(text="Forex Alert Bot • ไม่ใช่คำแนะนำทางการเงิน")

    await channel.send("@here", embed=embed)
    log.info(f"✅ ส่งแจ้งเตือน 5 นาที: {event.get('title')}")

async def send_actual_result(channel: discord.TextChannel, event: dict, analysis: str):
    """ส่งผลจริงพร้อม AI วิเคราะห์"""
    actual   = event.get("actual", "N/A")
    forecast = event.get("forecast", "N/A")
    previous = event.get("previous", "N/A")

    # สีตาม actual vs forecast
    color = 0x808080
    try:
        a = float(actual.replace("%","").replace("K","").replace("M","").replace("B","").strip())
        f = float(forecast.replace("%","").replace("K","").replace("M","").replace("B","").strip())
        color = 0x2ECC71 if a >= f else 0xE74C3C
    except Exception:
        color = 0x3498DB

    embed = discord.Embed(
        title=f"🚨  ข่าวออกแล้ว! — {event.get('title')}",
        color=color,
        timestamp=datetime.utcnow(),
    )
    embed.add_field(name="✅ Actual",   value=f"**`{actual}`**",   inline=True)
    embed.add_field(name="📈 Forecast", value=f"`{forecast}`",     inline=True)
    embed.add_field(name="📉 Previous", value=f"`{previous}`",     inline=True)

    # AI analysis (ตัดถ้ายาวเกิน 1024 ตัวอักษร)
    analysis_display = analysis if len(analysis) <= 1020 else analysis[:1017] + "..."
    embed.add_field(
        name="🤖 การวิเคราะห์โดย Claude AI",
        value=analysis_display,
        inline=False,
    )
    embed.set_footer(text="Forex Alert Bot • ข้อมูลจาก ForexFactory • ไม่ใช่คำแนะนำทางการเงิน")

    await channel.send("@here", embed=embed)
    log.info(f"✅ ส่งผล + AI Analysis: {event.get('title')}")

# ─────────────────────────────────────────────
# ⏰ BACKGROUND TASK — ตรวจข่าวทุก 1 นาที
# ─────────────────────────────────────────────
@tasks.loop(minutes=1)
async def check_news_loop():
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if channel is None:
        log.warning("ไม่พบ Channel — ตรวจสอบ DISCORD_CHANNEL_ID")
        return

    events = await fetch_usd_high_impact()
    now_utc = datetime.now(UTC_TZ)

    for event in events:
        dt = parse_event_dt(event)
        if dt is None:
            continue

        key = event_key(event)
        diff_min = (dt - now_utc).total_seconds() / 60

        # ─ แจ้งเตือน 5 นาที (ช่วง 4.5–5.5 นาที)
        if 4.5 <= diff_min <= 5.5 and key not in alerted_5min:
            alerted_5min.add(key)
            await send_5min_warning(channel, event, dt)

        # ─ แจ้งเตือน Actual (ผ่านเวลาแล้ว 0–10 นาที และมีตัวเลข Actual)
        elif -10 <= diff_min <= 0 and event.get("actual") and key not in alerted_actual:
            alerted_actual.add(key)
            await channel.send(f"⏳ กำลังวิเคราะห์ข่าว **{event.get('title')}** ด้วย AI...")
            analysis = await analyze_news(event)
            await send_actual_result(channel, event, analysis)

@check_news_loop.before_loop
async def before_loop():
    await bot.wait_until_ready()
    log.info("🔄 Background loop เริ่มทำงาน")

# ─────────────────────────────────────────────
# 🛠️ SLASH COMMANDS
# ─────────────────────────────────────────────
@bot.command(name="news", aliases=["ข่าว"])
async def cmd_news(ctx: commands.Context):
    """!news — แสดงข่าว USD High Impact สัปดาห์นี้"""
    events = await fetch_usd_high_impact()
    if not events:
        await ctx.send("📭 ไม่พบข่าว USD High Impact สัปดาห์นี้")
        return

    embed = discord.Embed(
        title="📅  ข่าว USD High Impact — สัปดาห์นี้",
        color=0x3498DB,
        timestamp=datetime.utcnow(),
    )
    for ev in events[:12]:
        dt = parse_event_dt(ev)
        if dt:
            time_str = dt.astimezone(BKK_TZ).strftime("%d/%m %H:%M น.")
        else:
            time_str = "N/A"

        status = ""
        if ev.get("actual"):
            status = f"✅ Actual: **{ev.get('actual')}**\n"

        embed.add_field(
            name=f"📰 {ev.get('title')}",
            value=(
                f"⏰ {time_str}\n"
                f"{status}"
                f"📊 Forecast: `{ev.get('forecast', 'N/A')}` | Previous: `{ev.get('previous', 'N/A')}`"
            ),
            inline=False,
        )

    embed.set_footer(text="ข้อมูลจาก ForexFactory • Forex Alert Bot")
    await ctx.send(embed=embed)

@bot.command(name="analyze", aliases=["วิเคราะห์"])
async def cmd_analyze(ctx: commands.Context):
    """!analyze — วิเคราะห์ข่าวล่าสุดที่มีตัวเลข Actual แล้ว"""
    events = await fetch_usd_high_impact()
    done = [e for e in events if e.get("actual")]

    if not done:
        await ctx.send("📭 ยังไม่มีข่าวที่มีตัวเลข Actual ในสัปดาห์นี้")
        return

    latest = done[-1]
    await ctx.send(f"⏳ กำลังวิเคราะห์ **{latest.get('title')}** ด้วย Claude AI...")
    analysis = await analyze_news(latest)
    await send_actual_result(ctx.channel, latest, analysis)

@bot.command(name="ping")
async def cmd_ping(ctx: commands.Context):
    """!ping — ตรวจสอบว่า Bot ออนไลน์อยู่"""
    latency = round(bot.latency * 1000)
    await ctx.send(f"🟢 Bot ออนไลน์! Latency: **{latency}ms**")

@bot.command(name="help_forex", aliases=["คำสั่ง"])
async def cmd_help(ctx: commands.Context):
    """!help_forex — แสดงคำสั่งทั้งหมด"""
    embed = discord.Embed(title="🤖 Forex Alert Bot — คำสั่งทั้งหมด", color=0x9B59B6)
    embed.add_field(name="!news", value="แสดงข่าว USD High Impact สัปดาห์นี้", inline=False)
    embed.add_field(name="!analyze", value="วิเคราะห์ข่าวล่าสุดที่ประกาศแล้วด้วย AI", inline=False)
    embed.add_field(name="!ping", value="ตรวจสอบสถานะ Bot", inline=False)
    embed.add_field(
        name="🔔 อัตโนมัติ",
        value=(
            "• แจ้งเตือน **5 นาที** ก่อนข่าวออก\n"
            "• ส่ง **AI วิเคราะห์** ทันทีที่มีตัวเลข Actual"
        ),
        inline=False,
    )
    embed.set_footer(text="Forex Alert Bot • ตรวจทุก 1 นาที")
    await ctx.send(embed=embed)

# ─────────────────────────────────────────────
# 🚀 START
# ─────────────────────────────────────────────
@bot.event
async def on_ready():
    log.info(f"✅ เข้าสู่ระบบสำเร็จ: {bot.user} (ID: {bot.user.id})")
    log.info(f"📡 กำลังติดตาม Channel ID: {DISCORD_CHANNEL_ID}")
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="📊 USD High Impact News"
        )
    )
    check_news_loop.start()

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
