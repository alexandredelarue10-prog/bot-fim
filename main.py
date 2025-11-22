"""
Discord Bot - Version B finale (tout-en-un)

Fonctionnalités :
- Anti-raid (join flood)
- Anti-nuke (mass ban/kick/channel/role deletes)
- Protection Owner (unban auto + notifications)
- Whitelist (par guild) pour modérations
- Warns (SQLite) + sanctions auto
- Snapshots roles+channels + tentative de restauration
- Commandes modération réelles
- Logs configurables par serveur (SQLite + envoi dans channel)
- Help dynamique & Owner help
- Configuration dynamique via commandes
"""

import os
import discord
import sqlite3
import asyncio
import json
import traceback
from discord.ext import commands
from datetime import datetime

# --------------------
# Configuration
# --------------------
TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
PREFIX = "!"

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True
intents.messages = True
intents.reactions = True
intents.presences = False  # not needed

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

DB_FILE = "bot_data.sqlite3"

# --------------------
# Defaults & trackers
# --------------------
action_trackers = {}  # {guild_id: {executor_id: {"ban":[], "kick":[], "channel_del":[], "role_del": []}}}
DEFAULT_CONFIG = {
    "antiraid": 0,
    "join_limit": 5,
    "join_window": 60,
    "warn_threshold": 3,
    "warn_action": "mute",
    "nuke_ban_threshold": 4,
    "nuke_window": 10,
    "log_channel": None
}

# --------------------
# Database helpers
# --------------------
conn = None

def init_db():
    global conn
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # guild configs
    c.execute('''CREATE TABLE IF NOT EXISTS guild_config(
                    guild_id INTEGER PRIMARY KEY,
                    config_json TEXT
                 )''')
    # warns
    c.execute('''CREATE TABLE IF NOT EXISTS warns(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    user_id INTEGER,
                    moderator_id INTEGER,
                    reason TEXT,
                    timestamp INTEGER
                 )''')
    # snapshots
    c.execute('''CREATE TABLE IF NOT EXISTS snapshots(
                    guild_id INTEGER PRIMARY KEY,
                    snapshot_json TEXT
                 )''')
    # whitelist
    c.execute('''CREATE TABLE IF NOT EXISTS whitelist(
                    guild_id INTEGER,
                    user_id INTEGER,
                    PRIMARY KEY(guild_id,user_id)
                 )''')
    # logs (history)
    c.execute('''CREATE TABLE IF NOT EXISTS logs(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    event_type TEXT,
                    content TEXT,
                    timestamp INTEGER
                 )''')
    conn.commit()

def load_guild_config(guild_id):
    c = conn.cursor()
    c.execute("SELECT config_json FROM guild_config WHERE guild_id = ?", (guild_id,))
    row = c.fetchone()
    if row:
        return json.loads(row[0])
    cfg = DEFAULT_CONFIG.copy()
    save_guild_config(guild_id, cfg)
    return cfg

def save_guild_config(guild_id, cfg):
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO guild_config(guild_id, config_json) VALUES(?,?)", (guild_id, json.dumps(cfg)))
    conn.commit()

# warns
def add_warn(gid, uid, mid, reason):
    ts = int(datetime.utcnow().timestamp())
    c = conn.cursor()
    c.execute("INSERT INTO warns(guild_id,user_id,moderator_id,reason,timestamp) VALUES(?,?,?,?,?)", (gid, uid, mid, reason, ts))
    conn.commit()

def get_warns(gid, uid):
    c = conn.cursor()
    c.execute("SELECT id, moderator_id, reason, timestamp FROM warns WHERE guild_id=? AND user_id=? ORDER BY id", (gid, uid))
    return c.fetchall()

def clear_warns(gid, uid):
    c = conn.cursor()
    c.execute("DELETE FROM warns WHERE guild_id=? AND user_id=?", (gid, uid))
    conn.commit()

# snapshots
def save_snapshot_db(gid, snap):
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO snapshots(guild_id, snapshot_json) VALUES(?,?)", (gid, json.dumps(snap)))
    conn.commit()

def load_snapshot_db(gid):
    c = conn.cursor()
    c.execute("SELECT snapshot_json FROM snapshots WHERE guild_id=?", (gid,))
    row = c.fetchone()
    return json.loads(row[0]) if row else None

# whitelist
def add_whitelist(gid, uid):
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO whitelist(guild_id,user_id) VALUES(?,?)", (gid, uid))
    conn.commit()

def remove_whitelist(gid, uid):
    c = conn.cursor()
    c.execute("DELETE FROM whitelist WHERE guild_id=? AND user_id=?", (gid, uid))
    conn.commit()

def is_whitelisted(gid, uid):
    if uid == OWNER_ID:
        return True
    c = conn.cursor()
    return c.execute("SELECT 1 FROM whitelist WHERE guild_id=? AND user_id=?", (gid, uid)).fetchone() is not None

# logs table
def append_log_db(gid, event_type, content):
    ts = int(datetime.utcnow().timestamp())
    c = conn.cursor()
    c.execute("INSERT INTO logs(guild_id,event_type,content,timestamp) VALUES(?,?,?,?)", (gid, event_type, content, ts))
    conn.commit()

# --------------------
# Utils / send_log
# --------------------
def now_ts():
    return asyncio.get_event_loop().time()

async def send_log_channel(guild, content):
    """Send a log message to configured channel or system_channel; also store in DB logs"""
    try:
        cfg = load_guild_config(guild.id)
        ch_id = cfg.get("log_channel")
        if ch_id:
            ch = guild.get_channel(ch_id)
            if ch and ch.permissions_for(guild.me).send_messages:
                await ch.send(content)
                append_log_db(guild.id, "log_message", content)
                return
        # fallback
        if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
            await guild.system_channel.send(content)
            append_log_db(guild.id, "log_message_system", content)
    except Exception:
        traceback.print_exc()

# --------------------
# Anti-nuke helpers
# --------------------
def ensure_tracker(gid, executor_id):
    g = action_trackers.setdefault(gid, {})
    return g.setdefault(executor_id, {"ban": [], "kick": [], "channel_del": [], "role_del": []})

async def punish_executor(guild, executor, reason):
    if executor is None:
        return
    try:
        if executor.id == OWNER_ID:
            await send_log_channel(guild, f"⚠️ Executor {executor} est OWNER — pas de punition.")
            return
        await guild.ban(executor, reason=f"Auto anti-nuke: {reason}")
        await send_log_channel(guild, f"⛔ Executor {executor} banni automatiquement ({reason})")
        append_log_db(guild.id, "anti_nuke_punish", f"{executor.id} | {reason}")
        # notify owner
        if OWNER_ID:
            try:
                owner = await bot.fetch_user(OWNER_ID)
                await owner.send(f"[Anti-nuke] {executor} banni sur {guild.name} pour: {reason}")
            except: pass
    except Exception:
        traceback.print_exc()

async def attempt_restore(guild):
    snap = load_snapshot_db(guild.id)
    if not snap:
        await send_log_channel(guild, "⚠️ Aucun snapshot trouvé pour restauration.")
        return
    await send_log_channel(guild, "🔄 Tentative de restauration depuis snapshot...")
    try:
        # restore roles (basic)
        existing_roles = {r.name: r for r in guild.roles}
        for rdata in snap.get('roles', []):
            if rdata['name'] in existing_roles:
                continue
            perms = discord.Permissions(rdata.get('permissions', 0))
            try:
                await guild.create_role(name=rdata['name'], permissions=perms, hoist=rdata.get('hoist', False), mentionable=rdata.get('mentionable', False))
            except Exception:
                traceback.print_exc()
        # restore channels by name only (categories omitted for complexity)
        existing_ch = {c.name: c for c in guild.channels}
        for cdata in snap.get('channels', []):
            if cdata['name'] in existing_ch:
                continue
            try:
                if 'text' in cdata.get('type',''):
                    await guild.create_text_channel(cdata['name'])
                elif 'voice' in cdata.get('type',''):
                    await guild.create_voice_channel(cdata['name'])
            except Exception:
                traceback.print_exc()
    except Exception:
        traceback.print_exc()
    await send_log_channel(guild, "✅ Restauration terminée (tentative).")

async def check_nuke_threshold(guild, executor_id):
    cfg = load_guild_config(guild.id)
    threshold = cfg.get('nuke_ban_threshold', DEFAULT_CONFIG['nuke_ban_threshold'])
    window = cfg.get('nuke_window', DEFAULT_CONFIG['nuke_window'])
    tracker = action_trackers.get(guild.id, {}).get(executor_id)
    if not tracker:
        return False
    now = now_ts()
    total = 0
    for k in list(tracker.keys()):
        tracker[k] = [t for t in tracker[k] if now - t < window]
        total += len(tracker[k])
    if total >= threshold:
        executor = guild.get_member(executor_id) or await bot.fetch_user(executor_id)
        await punish_executor(guild, executor, f"{total} destructive actions in {window}s")
        await attempt_restore(guild)
        action_trackers[guild.id].pop(executor_id, None)
        return True
    return False

# --------------------
# Events: ready + audit watchers
# --------------------
@bot.event
async def on_ready():
    init_db()
    print(f"Bot prêt: {bot.user} (ID: {bot.user.id})")
    if OWNER_ID:
        try:
            await (await bot.fetch_user(OWNER_ID)).send(f"✅ {bot.user} est connecté !")
        except: pass

# Anti-raid join flood
@bot.event
async def on_member_join(member):
    try:
        cfg = load_guild_config(member.guild.id)
        if not cfg.get('antiraid', 0):
            # still log join
            await send_log_channel(member.guild, f"⇾ Join: {member} (antiraid off)")
            append_log_db(member.guild.id, "join", f"{member.id}")
            return
        now = now_ts()
        tmp = cfg.get('joins_tmp', [])
        tmp.append(now)
        window = cfg.get('join_window', DEFAULT_CONFIG['join_window'])
        tmp = [t for t in tmp if now - t < window]
        cfg['joins_tmp'] = tmp
        save_guild_config(member.guild.id, cfg)
        append_log_db(member.guild.id, "join", f"{member.id}")
        if len(tmp) >= cfg.get('join_limit', DEFAULT_CONFIG['join_limit']):
            try:
                await member.ban(reason='Anti-raid')
                await send_log_channel(member.guild, f"⚠️ ANTI-RAID: {member} banni ({len(tmp)} joins en {window}s)")
                append_log_db(member.guild.id, "anti_raid", f"{member.id} banned")
            except Exception:
                traceback.print_exc()
    except Exception:
        traceback.print_exc()

# Ban detection
@bot.event
async def on_member_ban(guild, user):
    try:
        # who banned? find recent audit log entry for ban with matching target
        async for entry in guild.audit_logs(limit=6, action=discord.AuditLogAction.ban):
            if entry.target and entry.target.id == user.id:
                executor = entry.user
                t = now_ts()
                tracker = ensure_tracker(guild.id, executor.id)
                tracker['ban'].append(t)
                await send_log_channel(guild, f"🔨 Ban détecté: {user} par {executor}")
                append_log_db(guild.id, "ban", f"target={user.id} by={executor.id}")
                await check_nuke_threshold(guild, executor.id)
                break
    except Exception:
        traceback.print_exc()
    # owner protection
    try:
        if user.id == OWNER_ID:
            try:
                await guild.unban(user)
                await send_log_channel(guild, f"⚠️ Owner {user} a été banni — deban automatique.")
                append_log_db(guild.id, "owner_protect", "unban")
                if OWNER_ID:
                    try:
                        await (await bot.fetch_user(OWNER_ID)).send(f"⚠️ Tu as été banni de {guild.name} — j'ai tenté un deban automatique.")
                    except: pass
            except Exception:
                traceback.print_exc()
    except Exception:
        traceback.print_exc()

# Member remove (kick detection)
@bot.event
async def on_member_remove(member):
    try:
        guild = member.guild
        # check audit logs for kick
        async for entry in guild.audit_logs(limit=6, action=discord.AuditLogAction.kick):
            if entry.target and entry.target.id == member.id:
                executor = entry.user
                t = now_ts()
                tracker = ensure_tracker(guild.id, executor.id)
                tracker['kick'].append(t)
                await send_log_channel(guild, f"👢 Kick détecté: {member} par {executor}")
                append_log_db(guild.id, "kick", f"target={member.id} by={executor.id}")
                await check_nuke_threshold(guild, executor.id)
                break
        # owner protection notify
        if member.id == OWNER_ID:
            await send_log_channel(guild, f"⚠️ Owner {member} a été kické/est parti.")
            try:
                await (await bot.fetch_user(OWNER_ID)).send(f"⚠️ Tu as été expulsé/tu as quitté {guild.name}.")
            except: pass
    except Exception:
        traceback.print_exc()

# Channel delete detection
@bot.event
async def on_guild_channel_delete(channel):
    try:
        guild = channel.guild
        async for entry in guild.audit_logs(limit=6, action=discord.AuditLogAction.channel_delete):
            executor = entry.user
            t = now_ts()
            tracker = ensure_tracker(guild.id, executor.id)
            tracker['channel_del'].append(t)
            await send_log_channel(guild, f"🗑️ Channel supprimé: {channel.name} par {executor}")
            append_log_db(guild.id, "channel_delete", f"{channel.name} by={executor.id}")
            await check_nuke_threshold(guild, executor.id)
            break
    except Exception:
        traceback.print_exc()

# Role delete detection
@bot.event
async def on_guild_role_delete(role):
    try:
        guild = role.guild
        async for entry in guild.audit_logs(limit=6, action=discord.AuditLogAction.role_delete):
            if entry.target and entry.target.id == role.id:
                executor = entry.user
                t = now_ts()
                tracker = ensure_tracker(guild.id, executor.id)
                tracker['role_del'].append(t)
                await send_log_channel(guild, f"🗑️ Rôle supprimé: {role.name} par {executor}")
                append_log_db(guild.id, "role_delete", f"{role.name} by={executor.id}")
                await check_nuke_threshold(guild, executor.id)
                break
    except Exception:
        traceback.print_exc()

# Message delete / edit / create logs (optional)
@bot.event
async def on_message_delete(message):
    try:
        if message.guild:
            await send_log_channel(message.guild, f"🗑️ Message supprimé par {message.author}: {message.content[:100]}")
            append_log_db(message.guild.id, "message_delete", f"{message.author.id}: {message.content[:300]}")
    except Exception:
        traceback.print_exc()

@bot.event
async def on_message_edit(before, after):
    try:
        if before.guild and before.content != after.content:
            await send_log_channel(before.guild, f"✏️ Message édité par {before.author}: {before.content[:100]} -> {after.content[:100]}")
            append_log_db(before.guild.id, "message_edit", f"{before.author.id}: {before.content[:300]} -> {after.content[:300]}")
    except Exception:
        traceback.print_exc()

# --------------------
# Commands: configuration & moderation & utils
# --------------------
# Helper check
def check_whitelist_or_owner(ctx):
    return ctx.author.id == OWNER_ID or is_whitelisted(ctx.guild.id, ctx.author.id)

# ---- config commands ----
@bot.command()
@commands.has_permissions(administrator=True)
async def setlog(ctx, channel: discord.TextChannel):
    cfg = load_guild_config(ctx.guild.id)
    cfg['log_channel'] = channel.id
    save_guild_config(ctx.guild.id, cfg)
    await ctx.send(f"✅ Canal de logs défini sur {channel.mention}")

@bot.command()
@commands.has_permissions(administrator=True)
async def logstatus(ctx):
    cfg = load_guild_config(ctx.guild.id)
    chid = cfg.get('log_channel')
    if chid:
        ch = ctx.guild.get_channel(chid)
        await ctx.send(f"Canal de logs: {ch.mention if ch else str(chid)}")
    else:
        await ctx.send("Aucun canal de logs configuré.")

@bot.command()
@commands.has_permissions(administrator=True)
async def set_nuke_threshold(ctx, amount: int):
    cfg = load_guild_config(ctx.guild.id)
    cfg['nuke_ban_threshold'] = int(amount)
    save_guild_config(ctx.guild.id, cfg)
    await ctx.send(f"✅ Seuil anti-nuke défini à {amount}")

@bot.command()
@commands.has_permissions(administrator=True)
async def set_nuke_window(ctx, seconds: int):
    cfg = load_guild_config(ctx.guild.id)
    cfg['nuke_window'] = int(seconds)
    save_guild_config(ctx.guild.id, cfg)
    await ctx.send(f"✅ Fenêtre anti-nuke définie à {seconds}s")

@bot.command()
@commands.has_permissions(administrator=True)
async def set_antiraid(ctx, state: str):
    cfg = load_guild_config(ctx.guild.id)
    cfg['antiraid'] = 1 if state.lower() in ('on','1','true') else 0
    save_guild_config(ctx.guild.id, cfg)
    await ctx.send(f"🛡️ Anti-raid {'activé' if cfg['antiraid'] else 'désactivé'}")

@bot.command()
@commands.has_permissions(administrator=True)
async def set_joinlimit(ctx, amount: int):
    cfg = load_guild_config(ctx.guild.id)
    cfg['join_limit'] = int(amount)
    save_guild_config(ctx.guild.id, cfg)
    await ctx.send(f"✅ Limite de joins définie à {amount}")

@bot.command()
@commands.has_permissions(administrator=True)
async def set_warn_threshold(ctx, amount: int):
    cfg = load_guild_config(ctx.guild.id)
    cfg['warn_threshold'] = int(amount)
    save_guild_config(ctx.guild.id, cfg)
    await ctx.send(f"✅ Seuil de warns défini à {amount}")

@bot.command()
@commands.has_permissions(administrator=True)
async def set_warn_action(ctx, action: str):
    a = action.lower()
    if a not in ('mute','kick','ban','none'):
        return await ctx.send("Action invalide: mute / kick / ban / none")
    cfg = load_guild_config(ctx.guild.id)
    cfg['warn_action'] = a
    save_guild_config(ctx.guild.id, cfg)
    await ctx.send(f"✅ Action automatique sur seuil de warns: {a}")

# ---- whitelist management (owner-only commands preferred) ----
@bot.command()
async def whitelist_add(ctx, member: discord.Member):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ Réservé au owner.")
    add_whitelist(ctx.guild.id, member.id)
    await ctx.send(f"✅ {member} ajouté à la whitelist.")

@bot.command()
async def whitelist_remove(ctx, member: discord.Member):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ Réservé au owner.")
    remove_whitelist(ctx.guild.id, member.id)
    await ctx.send(f"✅ {member} retiré de la whitelist.")

@bot.command()
async def whitelist_list(ctx):
    c = conn.cursor()
    c.execute("SELECT user_id FROM whitelist WHERE guild_id=?", (ctx.guild.id,))
    rows = c.fetchall()
    if not rows:
        return await ctx.send("Aucun utilisateur whitelisté.")
    ids = [r[0] for r in rows]
    mentions = []
    for uid in ids:
        m = ctx.guild.get_member(uid)
        mentions.append(str(m) if m else str(uid))
    await ctx.send("Whitelist:\n" + "\n".join(mentions))

# ---- moderation commands (require whitelist) ----
@bot.command()
async def warn_cmd(ctx, member: discord.Member, *, reason: str = "Aucune raison"):
    # alias for warn
    await warn(ctx, member, reason=reason)

@bot.command(name='warn')
async def warn(ctx, member: discord.Member, *, reason: str = "Aucune raison"):
    if not check_whitelist_or_owner(ctx):
        return await ctx.send("❌ Pas la permission.")
    add_warn(ctx.guild.id, member.id, ctx.author.id, reason)
    await ctx.send(f"⚠️ {member.mention} warn: {reason}")
    await send_log_channel(ctx.guild, f"⚠️ WARN: {member} par {ctx.author} pour: {reason}")
    cfg = load_guild_config(ctx.guild.id)
    warns = get_warns(ctx.guild.id, member.id)
    if len(warns) >= cfg.get("warn_threshold", DEFAULT_CONFIG['warn_threshold']):
        action = cfg.get("warn_action", "mute")
        try:
            if action == "mute":
                role = discord.utils.get(ctx.guild.roles, name="Muted")
                if not role:
                    role = await ctx.guild.create_role(name="Muted")
                    for channel in ctx.guild.channels:
                        await channel.set_permissions(role, send_messages=False)
                await member.add_roles(role)
                await ctx.send(f"🔇 {member.mention} mute automatiquement.")
                await send_log_channel(ctx.guild, f"🔇 {member} mute automatiquement (warn threshold).")
            elif action == "kick":
                await member.kick(reason="Auto sanction warns")
                await ctx.send(f"👢 {member.mention} expulsé automatiquement.")
            elif action == "ban":
                await member.ban(reason="Auto sanction warns")
                await ctx.send(f"⛔ {member.mention} banni automatiquement.")
        except Exception:
            traceback.print_exc()

@bot.command(name='warns')
async def warns_cmd(ctx, member: discord.Member):
    rows = get_warns(ctx.guild.id, member.id)
    if not rows:
        return await ctx.send(f"{member} n'a aucun warn.")
    embed = discord.Embed(title=f"Warns {member}", color=0xe67e22)
    for r in rows:
        wid, mod_id, reason, ts = r
        mod = ctx.guild.get_member(mod_id) or (await bot.fetch_user(mod_id))
        embed.add_field(name=f"ID {wid}", value=f"Par: {getattr(mod,'name',mod)}\n{reason}\n{datetime.utcfromtimestamp(ts).strftime('%d/%m/%Y %H:%M:%S')} UTC", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='clearwarns')
async def clearwarns_cmd(ctx, member: discord.Member):
    if not check_whitelist_or_owner(ctx):
        return await ctx.send("❌ Pas la permission.")
    clear_warns(ctx.guild.id, member.id)
    await ctx.send(f"✅ Warns supprimés pour {member}.")
    await send_log_channel(ctx.guild, f"🧾 WARNs cleared for {member} by {ctx.author}")

@bot.command()
async def kick(ctx, member: discord.Member, *, reason: str = "Aucune raison"):
    if not check_whitelist_or_owner(ctx):
        return await ctx.send("❌ Pas la permission.")
    if member.id == OWNER_ID:
        return await ctx.send("❌ Impossible d'expulser le owner.")
    try:
        await member.kick(reason=reason)
        await ctx.send(f"👢 {member} expulsé.")
        await send_log_channel(ctx.guild, f"👢 Kick: {member} par {ctx.author} ({reason})")
        append_log_db(ctx.guild.id, "manual_kick", f"{member.id} by {ctx.author.id} reason={reason}")
    except Exception:
        traceback.print_exc()
        await ctx.send("Erreur lors du kick.")

@bot.command()
async def ban(ctx, member: discord.Member, *, reason: str = "Aucune raison"):
    if not check_whitelist_or_owner(ctx):
        return await ctx.send("❌ Pas la permission.")
    if member.id == OWNER_ID:
        return await ctx.send("❌ Impossible de bannir le owner.")
    try:
        await member.ban(reason=reason)
        await ctx.send(f"⛔ {member} banni.")
        await send_log_channel(ctx.guild, f"⛔ Ban: {member} par {ctx.author} ({reason})")
        append_log_db(ctx.guild.id, "manual_ban", f"{member.id} by {ctx.author.id} reason={reason}")
    except Exception:
        traceback.print_exc()
        await ctx.send("Erreur lors du ban.")

@bot.command()
async def mute(ctx, member: discord.Member):
    if not check_whitelist_or_owner(ctx):
        return await ctx.send("❌ Pas la permission.")
    try:
        role = discord.utils.get(ctx.guild.roles, name="Muted")
        if not role:
            role = await ctx.guild.create_role(name="Muted")
            for channel in ctx.guild.channels:
                try:
                    await channel.set_permissions(role, send_messages=False)
                except: pass
        await member.add_roles(role)
        await ctx.send(f"🔇 {member} mute.")
        await send_log_channel(ctx.guild, f"🔇 Mute: {member} par {ctx.author}")
        append_log_db(ctx.guild.id, "manual_mute", f"{member.id} by {ctx.author.id}")
    except Exception:
        traceback.print_exc()
        await ctx.send("Erreur lors du mute.")

@bot.command()
async def unmute(ctx, member: discord.Member):
    if not check_whitelist_or_owner(ctx):
        return await ctx.send("❌ Pas la permission.")
    try:
        role = discord.utils.get(ctx.guild.roles, name="Muted")
        if role:
            await member.remove_roles(role)
        await ctx.send(f"🔊 {member} unmute.")
        await send_log_channel(ctx.guild, f"🔊 Unmute: {member} par {ctx.author}")
        append_log_db(ctx.guild.id, "manual_unmute", f"{member.id} by {ctx.author.id}")
    except Exception:
        traceback.print_exc()
        await ctx.send("Erreur lors du unmute.")

@bot.command()
async def clear_msgs(ctx, amount: int = 10):
    if not check_whitelist_or_owner(ctx):
        return await ctx.send("❌ Pas la permission.")
    try:
        await ctx.channel.purge(limit=amount+1)
        await ctx.send(f"🧹 {amount} messages supprimés", delete_after=3)
        append_log_db(ctx.guild.id, "clear", f"{amount} by {ctx.author.id}")
    except Exception:
        traceback.print_exc()
        await ctx.send("Erreur lors du purge.")

@bot.command()
async def lock(ctx):
    if not check_whitelist_or_owner(ctx):
        return await ctx.send("❌ Pas la permission.")
    try:
        await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False)
        await ctx.send("🔒 Salon verrouillé.")
        append_log_db(ctx.guild.id, "lock", f"{ctx.channel.id} by {ctx.author.id}")
    except Exception:
        traceback.print_exc()

@bot.command()
async def unlock(ctx):
    if not check_whitelist_or_owner(ctx):
        return await ctx.send("❌ Pas la permission.")
    try:
        await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=True)
        await ctx.send("🔓 Salon déverrouillé.")
        append_log_db(ctx.guild.id, "unlock", f"{ctx.channel.id} by {ctx.author.id}")
    except Exception:
        traceback.print_exc()

# ---- help / owner commands ----
@bot.command()
async def help(ctx):
    embed = discord.Embed(title="Commandes disponibles", color=0x00ff00)
    embed.add_field(name="Fun/Util", value="`!ping`, `!serverinfo`", inline=False)
    if is_whitelisted(ctx.guild.id, ctx.author.id):
        embed.add_field(name="Modération", value="`!warn`, `!warns`, `!clearwarns`, `!kick`, `!ban`, `!mute`, `!unmute`, `!clear_msgs`, `!lock`, `!unlock`, `!snapshot`", inline=False)
    if ctx.author.id == OWNER_ID:
        embed.add_field(name="Owner", value="`!ownerhelp`, `!serverlist`, `!whitelist_add`, `!whitelist_remove`, `!logstatus`", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def ownerhelp(ctx):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ Réservé au owner.")
    embed = discord.Embed(title="Owner Commands", color=0xff0000)
    embed.add_field(name="Server", value="`!serverlist`", inline=False)
    embed.add_field(name="Whitelist", value="`!whitelist_add @user`, `!whitelist_remove @user`, `!whitelist_list`", inline=False)
    embed.add_field(name="Config", value="`!setlog #channel`, `!set_nuke_threshold`, `!set_nuke_window`, `!set_antiraid`", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def serverlist(ctx):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ Réservé au owner.")
    embed = discord.Embed(title="Serveurs du bot", color=0x00ff00)
    for g in bot.guilds:
        # attempt to create invite from first text channel
        inv = "Impossible de créer invite"
        try:
            chs = [c for c in g.text_channels if c.permissions_for(g.me).create_instant_invite]
            if chs:
                invobj = await chs[0].create_invite(max_age=3600, max_uses=1)
                inv = invobj.url
        except Exception:
            inv = "Invite non disponible"
        embed.add_field(name=g.name, value=f"ID: {g.id}\nInvite: {inv}", inline=False)
    await ctx.author.send(embed=embed)
    await ctx.send("✅ Liste envoyée en DM (owner).")

@bot.command()
async def serverinfo(ctx):
    g = ctx.guild
    embed = discord.Embed(title=f"Info: {g.name}", description=f"ID: {g.id}", color=0x3498db)
    embed.add_field(name="Membres", value=g.member_count)
    embed.add_field(name="Salons", value=len(g.channels))
    embed.add_field(name="Rôles", value=len(g.roles))
    await ctx.send(embed=embed)

# --------------------
# Final run
# --------------------
if __name__ == "__main__":
    init_db()
    bot.run(TOKEN)
