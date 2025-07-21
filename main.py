import os
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from typing import Union, Optional

from dateutil.relativedelta import relativedelta
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pyrogram import Client
from pyrogram.errors import PeerIdInvalid  # ← specific error import

from config import API_ID, API_HASH, BOT_TOKEN

# ─────────────────────────────────────────────
# 🔧  CONFIG & INITIALISATION
# ─────────────────────────────────────────────

bot = Client("info_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    """Return a static landing page"""
    return Path("static/index.html").read_text(encoding="utf-8")

# ─────────────────────────────────────────────
# 🗺️  DATA-CENTER LOCATION MAP
# ─────────────────────────────────────────────

DC_LOCATIONS = {
    1: "MIA, Miami, USA, US", 2: "AMS, Amsterdam, Netherlands, NL", 3: "SFO, San Francisco, USA, US",
    4: "GRU, São Paulo, Brazil, BR", 5: "DME, Moscow, Russia, RU", 7: "SIN, Singapore, SG",
    8: "FRA, Frankfurt, Germany, DE", 9: "IAD, Washington DC, USA, US", 10: "BLR, Bangalore, India, IN",
    11: "TYO, Tokyo, Japan, JP", 12: "BOM, Mumbai, India, IN", 13: "HKG, Hong Kong, HK",
    14: "MAD, Madrid, Spain, ES", 15: "CDG, Paris, France, FR", 16: "MEX, Mexico City, Mexico, MX",
    17: "YYZ, Toronto, Canada, CA", 18: "MEL, Melbourne, Australia, AU", 19: "DEL, Delhi, India, IN",
    20: "JFK, New York, USA, US", 21: "LHR, London, UK, GB"
}

# ─────────────────────────────────────────────
# 🛠️  HELPER FUNCTIONS
# ─────────────────────────────────────────────

def is_real_bot(user) -> bool:
    """Return True if the given Pyrogram user object is a bot account."""
    return getattr(user, "is_bot", False)


def estimate_account_creation_date(user_id: int) -> datetime:
    """Roughly estimate Telegram account creation date from the numeric user-id."""
    reference_points = [
        (100000000, datetime(2013, 8, 1)),
        (1273841502, datetime(2020, 8, 13)),
        (1500000000, datetime(2021, 5, 1)),
        (2000000000, datetime(2022, 12, 1)),
    ]
    closest_user_id, closest_date = min(reference_points, key=lambda x: abs(x[0] - user_id))
    days_diff = (user_id - closest_user_id) / 20_000_000  # heuristic
    return closest_date + timedelta(days=days_diff)


def calculate_account_age(creation_date: datetime) -> str:
    diff = relativedelta(datetime.now(), creation_date)
    return f"{diff.years} years, {diff.months} months, {diff.days} days"

# ─────────────────────────────────────────────
# 🔎  /get_user_info ENDPOINT (now backward-compatible)
# ─────────────────────────────────────────────

@app.get("/get_user_info", response_class=PlainTextResponse)
async def get_user_info(
    identifier: Optional[str] = Query(
        default=None,
        description="Username (without @) **or** numeric user-id",
    ),
    username: Optional[str] = Query(
        default=None,
        description="[DEPRECATED] Use ?identifier= instead. Present for backward-compatibility.",
    ),
):
    """Fetch info for a Telegram *user / group / channel*. Handles both username and user-id.

    ⚠️ **Limitations**: Telegram only allows a bot to fetch a *user* by numeric ID if the
    bot already had a mutual chat with that user (direct chat or common group). Otherwise
    the API raises `PeerIdInvalid`. In that case we surface a 403 explaining the reason.
    """

    # ── 1. Determine the lookup key ────────────────────────────────────
    if identifier is None and username is None:
        raise HTTPException(
            status_code=400,
            detail="Please supply ?identifier=<username|user_id> or ?username=<username|user_id>",
        )

    key = (identifier or username).lstrip("@")
    target: Union[int, str] = int(key) if key.isdigit() else key

    # ── 2. Try user lookup first ───────────────────────────────────────
    try:
        obj = await bot.get_users(target)
        entity_type = "user"
    except PeerIdInvalid:
        # Numeric user-id but no mutual contact ➜ deny with clear message
        raise HTTPException(
            status_code=403,
            detail=(
                "Bot has no access to this user. The user must start the bot or share a "
                "common group/channel with the bot before their profile can be fetched."
            ),
        )
    except Exception:
        # Not a user, try as chat (group/channel)
        try:
            obj = await bot.get_chat(target)
            entity_type = obj.type.value  # "group", "supergroup", or "channel"
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error: {e}")

    # ── 3. Format responses ────────────────────────────────────────────
    if entity_type == "user":
        user = obj
        creation_date = estimate_account_creation_date(user.id)
        account_age = calculate_account_age(creation_date)
        dc_location = DC_LOCATIONS.get(getattr(user, "dc_id", None), "Unknown")

        status = "Unknown"
        if user.status:
            status_str = str(user.status).upper()
            if "ONLINE" in status_str:
                status = "Online"
            elif "OFFLINE" in status_str:
                status = "Offline"
            elif "RECENTLY" in status_str:
                status = "Recently online"

        profile_pic_url = (
            f"https://t.me/i/userpic/320/{user.username}.jpg" if (user.photo and user.username) else "No Profile Picture"
        )
        header = "Bot Info" if is_real_bot(user) else "User Info"

        
        if user.username:
            username_display = f"@{user.username}"
        else:
            username_display = "No Username"

        return (
            f"""
✘「 {header} 」
↯ Name: {user.first_name or ''} {user.last_name or ''}
 ↯ Username: {username_display}
↯ User ID: {user.id}
↯ Premium: {'Yes' if user.is_premium else 'No'}
↯ Verified: {'Yes' if getattr(user, 'is_verified', False) else 'No'}
↯ Scam: {'Yes' if getattr(user, 'is_scam', False) else 'No'}
↯ Fake: {'Yes' if getattr(user, 'is_fake', False) else 'No'}
↯ Data Center: {dc_location}
↯ Status: {status}
↯ Created: {creation_date.strftime('%b %d, %Y')}
↯ Age: {account_age}
↯ Profile Pic URL: {profile_pic_url}
            """
        )

    # ── Groups / Supergroups ──────────────────────────────────────────
    elif entity_type in {"group", "supergroup"}:
        chat = obj
        try:
            members_count = await bot.get_chat_members_count(chat.id)
        except Exception:
            members_count = "Unknown"

        profile_pic = (
            f"https://t.me/i/userpic/320/{chat.username}.jpg" if chat.username else "No Profile Picture"
        )
        fake_status = "Yes" if getattr(chat, "is_fake", False) else "No"
        safety_status = "Unsafe" if getattr(chat, "is_scam", False) else "Safe"

        return (
            f"""
✘「 Group Information ↯ 」
↯ Title: {chat.title}
↯ Username: @{chat.username or 'N/A'}
↯ Chat ID: {chat.id}
↯ Type: {entity_type.capitalize()}
↯ Members Count: {members_count}

↯ Verified: {'Yes' if getattr(chat, 'is_verified', False) else 'No'}
↯ Scam: {'Yes' if getattr(chat, 'is_scam', False) else 'No'}
↯ Fake: {fake_status}
↯ Safety Status: {safety_status}

↯ Description: {chat.description or 'No description'}
↯ Profile Pic URL: {profile_pic}
            """
        )

    # ── Channels ──────────────────────────────────────────────────────
    elif entity_type == "channel":
        channel = obj
        try:
            members_count = await bot.get_chat_members_count(channel.id)
        except Exception:
            members_count = "Unknown"

        profile_pic = (
            f"https://t.me/i/userpic/320/{channel.username}.jpg" if channel.username else "No Profile Picture"
        )
        fake_status = "Yes" if getattr(channel, "is_fake", False) else "No"
        safety_status = "Unsafe" if getattr(channel, "is_scam", False) else "Safe"

        return (
            f"""
✘「 Channel Information ↯ 」
↯ Title: {channel.title}
↯ Username: @{channel.username or 'N/A'}
↯ Chat ID: {channel.id}
↯ Type: Channel
↯ Members Count: {members_count}

↯ Verified: {'Yes' if getattr(channel, 'is_verified', False) else 'No'}
↯ Scam: {'Yes' if getattr(channel, 'is_scam', False) else 'No'}
↯ Fake: {fake_status}
↯ Safety Status: {safety_status}

↯ Description: {channel.description or 'No description'}
↯ Profile Pic URL: {profile_pic}
            """
        )

    # ── Unknown Entity ────────────────────────────────────────────────
    return "Unknown entity."


# ─────────────────────────────────────────────
# 🚀  APP STARTUP HANDLER
# ─────────────────────────────────────────────

@app.on_event("startup")
async def on_startup() -> None:
    await bot.start()


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("telegram_info_bot:app", host="0.0.0.0", port=port, reload=False)
