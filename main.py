"""
Bot Discord complet :
- Anti-raid
- Anti-nuke (détection mass ban/kick/delete)
- Logs dans un salon configuré
- Système de warns (SQLite)
- Configuration par serveur (SQLite)
- Snapshot des rôles/salons pour tentative de restauration

Dépendances : discord.py==2.7.3
Variables d'environnement requises : DISCORD_TOKEN, OWNER_ID (optionnel)

Fichier unique, exécutez : python discord_bot_full_features.py
"""

import os
import discord
import sqlite3
import asyncio
import json
import traceback
from discord.ext import commands, tasks
from datetime import datetime

# ====================
# CONFIG
# ====================
TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
PREFIX = "!"

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

DB_FILE = "bot_data.sqlite3"

# In-memory trackers for anti-nuke detections
action_trackers = {}  # {guild_id: {executor_id: {"ban": [ts...], "kick": [...], "channel_del": [...], "role_del": [...]}}}

# default thresholds (modifiable per guild later)
DEFAULT_CONFIG = {
    "antiraid": 0,            # 0=off,1=on
    "join_limit": 5,
    "join_window": 60,
    "warn_threshold": 3,
    "warn_action": "mute",  # mute / kick / ban / none
    "nuke_ban_threshold": 3, # actions count
    "nuke_window": 10,       # seconds window
    "log_channel": None
}

# ====================
# DATABASE HELPERS
# ====================
conn = None

def init_db():
    global conn
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS guild_config(
                    guild_id INTEGER PRIMARY KEY,
                    config_json TEXT
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS warns(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    user_id INTEGER,
                    moderator_id INTEGER,
                    reason TEXT,
                    timestamp INTEGER
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS snapshots(
                    guild_id INTEGER PRIMARY KEY,
                    snapshot_json TEXT
                 )''')
    conn.commit()

def load_guild_config(guild_id):
    c = conn.cursor()
    c.execute("SELECT config_json FROM guild_config WHERE guild_id = ?", (guild_id,))
    row = c.fetchone()
    if row:
        return json.loads(row[0])
    else:
        cfg = DEFAULT_CONFIG.copy()
        save_guild_config(guild_id, cfg)
        return cfg

def save_guild_config(guild_id, cfg):
    c = conn.cursor()
    cfg_json = json.dumps(cfg)
    c.execute("INSERT OR REPLACE INTO guild_config(guild_id, config_json) VALUES(?,?)", (guild_id, cfg_json))
    conn.commit()

def add_warn(guild_id, user_id, moderator_id, reason):
    ts = int(datetime.utcnow().timestamp())
    c = conn.cursor()
    c.execute("INSERT INTO warns(guild_id,user_id,moderator_id,reason,timestamp) VALUES(?,?,?,?,?)",
              (guild_id, user_id, moderator_id, reason, ts))
    conn.commit()

def get_warns(guild_id, user_id):
    c = conn.cursor()
    c.execute("SELECT id, moderator_id, reason, timestamp FROM warns WHERE guild_id=? AND user_id=? ORDER BY id", (guild_id, user_id))
    return c.fetchall()

def clear_warns(guild_id, user_id):
    c = conn.cursor()
    c.execute("DELETE FROM warns WHERE guild_id=? AND user_id=?", (guild_id, user_id))
    conn.commit()

def save_snapshot(guild_id, snapshot):
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO snapshots(guild_id, snapshot_json) VALUES(?,?)", (guild_id, json.dumps(snapshot)))
    conn.commit()

def load_snapshot(guild_id):
    c = conn.cursor()
    c.execute("SELECT snapshot_json FROM snapshots WHERE guild_id=?", (guild_id,))
    row = c.fetchone()
    if row:
        return json.loads(row[0])
    return None

# ====================
# UTIL
# ====================

def now_ts():
    return asyncio.get_event_loop().time()

async def send_log(guild, message):
    try:
        cfg = load_guild_config(guild.id)
        ch_id = cfg.get("log_channel")
        if ch_id:
            ch = guild.get_channel(ch_id)
            if ch and ch.permissions_for(guild.me).send_messages:
                await ch.send(message)
                return
        # fallback to system_channel
        if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
            await guild.system_channel.send(message)
    except Exception:
        traceback.print_exc()

# ====================
# STARTUP
# ====================

@bot.event
async def on_ready():
    init_db()
    print(f"Bot prêt: {bot.user} (ID: {bot.user.id})")
    owner = None
    if OWNER_ID:
        try:
            owner = await bot.fetch_user(OWNER_ID)
            await owner.send(f"✅ {bot.user} est connecté !")
        except Exception:
            pass

# ====================
# SNAPSHOT COMMAND
# ====================
@bot.command()
@commands.has_permissions(administrator=True)
async def snapshot(ctx):
    """Sauvegarde un snapshot des salons et rôles (nom, permissions, positions)"""
    guild = ctx.guild
    snap = {"roles": [], "channels": []}
    for role in guild.roles:
        snap["roles"].append({
            "name": role.name,
            "permissions": role.permissions.value,
            "colour": role.color.value if hasattr(role, 'color') else 0,
            "hoist": role.hoist,
            "mentionable": role.mentionable
        })
    for ch in guild.channels:
        snap["channels"].append({
            "name": ch.name,
            "type": str(ch.type),
            "category": ch.category.name if ch.category else None,
            "position": ch.position
        })
    save_snapshot(guild.id, snap)
    await ctx.send("✅ Snapshot sauvegardé.")
    await send_log(guild, f"🗂 Snapshot sauvegardé par {ctx.author}")

# ====================
# WARN SYSTEM
# ====================
@bot.command()
@commands.has_permissions(kick_members=True)
async def warn(ctx, member: discord.Member, *, reason: str = "Aucune raison"):
    add_warn(ctx.guild.id, member.id, ctx.author.id, reason)
    await ctx.send(f"⚠️ {member.mention} a reçu un warn pour: {reason}")
    await send_log(ctx.guild, f"⚠️ WARN: {member} par {ctx.author} pour: {reason}")

    # appliquer sanction automatique si dépassé
    cfg = load_guild_config(ctx.guild.id)
    warns = get_warns(ctx.guild.id, member.id)
    if len(warns) >= cfg.get("warn_threshold", DEFAULT_CONFIG["warn_threshold"]):
        action = cfg.get("warn_action", "mute")
        try:
            if action == "mute":
                role = discord.utils.get(ctx.guild.roles, name="Muted")
                if not role:
                    role = await ctx.guild.create_role(name="Muted")
                    for channel in ctx.guild.channels:
                        await channel.set_permissions(role, send_messages=False)
                await member.add_roles(role)
                await ctx.send(f"🔇 {member.mention} a été mute automatiquement (warns >= {len(warns)})")
                await send_log(ctx.guild, f"🔇 {member} mute automatiquement (warns >= {len(warns)})")
            elif action == "kick":
                await member.kick(reason="Auto sanction warns")
                await ctx.send(f"👢 {member.mention} expulsé automatiquement.")
            elif action == "ban":
                await member.ban(reason="Auto sanction warns")
                await ctx.send(f"⛔ {member.mention} banni automatiquement.")
        except Exception:
            traceback.print_exc()

@bot.command()
@commands.has_permissions(kick_members=True)
async def warns(ctx, member: discord.Member):
    rows = get_warns(ctx.guild.id, member.id)
    if not rows:
        await ctx.send(f"✅ {member} n'a aucun warn.")
        return
    embed = discord.Embed(title=f"Warns de {member}", color=0xe67e22)
    for r in rows:
        wid, mod_id, reason, ts = r
        mod = ctx.guild.get_member(mod_id) or await bot.fetch_user(mod_id)
        embed.add_field(name=f"ID {wid}", value=f"Par: {getattr(mod,'name',mod)}\n{reason}\n{datetime.utcfromtimestamp(ts).strftime('%d/%m/%Y %H:%M:%S')} UTC", inline=False)
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def clearwarns(ctx, member: discord.Member):
    clear_warns(ctx.guild.id, member.id)
    await ctx.send(f"✅ Warns supprimés pour {member}.")
    await send_log(ctx.guild, f"🧾 Warns clear pour {member} par {ctx.author}")

@bot.command()
@commands.has_permissions(administrator=True)
async def set_warn_threshold(ctx, amount: int):
    cfg = load_guild_config(ctx.guild.id)
    cfg['warn_threshold'] = amount
    save_guild_config(ctx.guild.id, cfg)
    await ctx.send(f"⚙️ Seuil de warns : {amount}")

@bot.command()
@commands.has_permissions(administrator=True)
async def set_warn_action(ctx, action: str):
    action = action.lower()
    if action not in ('mute','kick','ban','none'):
        return await ctx.send("Action invalide: mute / kick / ban / none")
    cfg = load_guild_config(ctx.guild.id)
    cfg['warn_action'] = action
    save_guild_config(ctx.guild.id, cfg)
    await ctx.send(f"⚙️ Action automatique sur seuil de warns : {action}")

# ====================
# LOG CHANNEL CONFIG
# ====================
@bot.command()
@commands.has_permissions(administrator=True)
async def setlog(ctx, channel: discord.TextChannel):
    cfg = load_guild_config(ctx.guild.id)
    cfg['log_channel'] = channel.id
    save_guild_config(ctx.guild.id, cfg)
    await ctx.send(f"✅ Canal de log défini sur {channel.mention}")

# ====================
# ANTI-RAID (reprise de la version précédente)
# ====================
@bot.event
async def on_member_join(member):
    cfg = load_guild_config(member.guild.id)
    if not cfg.get('antiraid', 0):
        return
    now = now_ts()
    # stocker joins en mémoire dans cfg temporaire
    tmp = cfg.get('joins_tmp', [])
    tmp.append(now)
    # filtre 60s
    window = cfg.get('join_window', DEFAULT_CONFIG['join_window'])
    tmp = [t for t in tmp if now - t < window]
    cfg['joins_tmp'] = tmp
    save_guild_config(member.guild.id, cfg)
    if len(tmp) >= cfg.get('join_limit', DEFAULT_CONFIG['join_limit']):
        try:
            await member.ban(reason='Anti-raid activé')
            await send_log(member.guild, f"⚠️ ANTI-RAID: {member} banni automatiquement ({len(tmp)} joins en {window}s)")
        except Exception:
            traceback.print_exc()

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
    cfg['join_limit'] = amount
    save_guild_config(ctx.guild.id, cfg)
    await ctx.send(f"⚙️ Limite de joins/min définie à {amount}")

# ====================
# ANTI-NUKE HELPERS
# ====================

def ensure_tracker(guild_id, executor_id):
    g = action_trackers.setdefault(guild_id, {})
    return g.setdefault(executor_id, {"ban": [], "kick": [], "channel_del": [], "role_del": []})

async def punish_executor(guild, executor, reason):
    try:
        # essayer de retirer rôles administrateurs et bannir
        # retirer perms administrateur : on ne peut pas modifier un membre si on est plus bas
        await guild.ban(executor, reason=reason)
        await send_log(guild, f"⛔ Executor {executor} a été banni suite à détection anti-nuke: {reason}")
    except Exception:
        traceback.print_exc()

async def check_nuke_threshold(guild, executor_id):
    cfg = load_guild_config(guild.id)
    threshold = cfg.get('nuke_ban_threshold', DEFAULT_CONFIG['nuke_ban_threshold'])
    window = cfg.get('nuke_window', DEFAULT_CONFIG['nuke_window'])
    tracker = action_trackers.get(guild.id, {}).get(executor_id)
    if not tracker:
        return False
    now = now_ts()
    total_actions = 0
    for k in tracker:
        tracker[k] = [t for t in tracker[k] if now - t < window]
        total_actions += len(tracker[k])
    if total_actions >= threshold:
        # find executor member
        executor = guild.get_member(executor_id) or await bot.fetch_user(executor_id)
        await punish_executor(guild, executor, f"Detected mass destructive actions ({total_actions})")
        # attempt restoration
        await attempt_restore(guild)
        # clear tracker for this executor
        action_trackers[guild.id].pop(executor_id, None)
        return True
    return False

# ====================
# EVENTS TO MONITOR
# ====================
@bot.event
async def on_member_ban(guild, user):
    # who banned ? audit logs
    try:
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
            # find most recent ban for this user
            if entry.target.id == user.id:
                executor = entry.user
                t = now_ts()
                tracker = ensure_tracker(guild.id, executor.id)
                tracker['ban'].append(t)
                await send_log(guild, f"🔨 Ban détecté: {user} par {executor}")
                await check_nuke_threshold(guild, executor.id)
                break
    except Exception:
        traceback.print_exc()

@bot.event
async def on_member_remove(member):
    # could be kick or leave; check audit logs for kick
    guild = member.guild
    try:
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
            if entry.target.id == member.id:
                executor = entry.user
                t = now_ts()
                tracker = ensure_tracker(guild.id, executor.id)
                tracker['kick'].append(t)
                await send_log(guild, f"👢 Kick détecté: {member} par {executor}")
                await check_nuke_threshold(guild, executor.id)
                return
    except Exception:
        traceback.print_exc()
    # else it's a normal leave
    await send_log(guild, f"⇠ Member left: {member}")

@bot.event
async def on_guild_channel_delete(channel):
    guild = channel.guild
    try:
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.channel_delete):
            executor = entry.user
            t = now_ts()
            tracker = ensure_tracker(guild.id, executor.id)
            tracker['channel_del'].append(t)
            await send_log(guild, f"🗑️ Channel supprimé: {channel.name} par {executor}")
            await check_nuke_threshold(guild, executor.id)
            break
    except Exception:
        traceback.print_exc()

@bot.event
async def on_guild_role_delete(role):
    guild = role.guild
    try:
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.role_delete):
            executor = entry.user
            t = now_ts()
            tracker = ensure_tracker(guild.id, executor.id)
            tracker['role_del'].append(t)
            await send_log(guild, f"🗑️ Rôle supprimé: {role.name} par {executor}")
            await check_nuke_threshold(guild, executor.id)
            break
    except Exception:
        traceback.print_exc()

# ====================
# RESTORATION
# ====================
async def attempt_restore(guild):
    snap = load_snapshot(guild.id)
    if not snap:
        await send_log(guild, "⚠️ Aucun snapshot trouvé pour restauration.")
        return
    await send_log(guild, "🔄 Tentative de restauration depuis snapshot...")
    # restore roles (basic)
    try:
        existing_roles = {r.name: r for r in guild.roles}
        for rdata in snap.get('roles', []):
            if rdata['name'] in existing_roles:
                continue
            perms = discord.Permissions(rdata.get('permissions', 0))
            await guild.create_role(name=rdata['name'], permissions=perms, hoist=rdata.get('hoist', False), mentionable=rdata.get('mentionable', False))
        # restore channels names only (categories omitted for complexity)
        existing_ch = {c.name: c for c in guild.channels}
        for cdata in snap.get('channels', []):
            if cdata['name'] in existing_ch:
                continue
            if 'text' in cdata.get('type',''):
                await guild.create_text_channel(cdata['name'])
            elif 'voice' in cdata.get('type',''):
                await guild.create_voice_channel(cdata['name'])
    except Exception:
        traceback.print_exc()
    await send_log(guild, "✅ Restauration terminée (tentative).")

# ====================
# COMMANDES D'ADMIN UTILES (clear, kick, ban, mute, unmute, lock, unlock, ping)
# ====================
@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int):
    await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"🧹 {amount} messages supprimés", delete_after=3)

@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: str = "Aucune raison"):
    await member.kick(reason=reason)
    await ctx.send(f"👢 {member} expulsé.")
    await send_log(ctx.guild, f"👢 Kick: {member} par {ctx.author} ({reason})")

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = "Aucune raison"):
    await member.ban(reason=reason)
    await ctx.send(f"⛔ {member} banni.")
    await send_log(ctx.guild, f"⛔ Ban: {member} par {ctx.author} ({reason})")

@bot.command()
@commands.has_permissions(manage_roles=True)
async def mute(ctx, member: discord.Member):
    role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not role:
        role = await ctx.guild.create_role(name="Muted")
        for channel in ctx.guild.channels:
            await channel.set_permissions(role, send_messages=False)
    await member.add_roles(role)
    await ctx.send(f"🔇 {member} mute.")
    await send_log(ctx.guild, f"🔇 Mute: {member} par {ctx.author}")

@bot.command()
@commands.has_permissions(manage_roles=True)
async def unmute(ctx, member: discord.Member):
    role = discord.utils.get(ctx.guild.roles, name="Muted")
    if role:
        await member.remove_roles(role)
    await ctx.send(f"🔊 {member} unmute.")
    await send_log(ctx.guild, f"🔊 Unmute: {member} par {ctx.author}")

@bot.command()
@commands.has_permissions(manage_channels=True)
async def lock(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False)
    await ctx.send("🔒 Salon verrouillé.")

@bot.command()
@commands.has_permissions(manage_channels=True)
async def unlock(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=True)
    await ctx.send("🔓 Salon déverrouillé.")

@bot.command()
async def ping(ctx):
    await ctx.send(f"Pong! {round(bot.latency*1000)}ms")

# ====================
# SIMPLE PROTECTION POUR LES COMMANDES SENSIBLES: LOG + CHECK
# ====================
@bot.check
async def global_command_check(ctx):
    # ignore DMs
    if ctx.guild is None:
        return True
    # log command usage
    await send_log(ctx.guild, f"💬 Cmd: {ctx.command} utilisée par {ctx.author}")
    return True

# ====================
# RUN
# ====================
if __name__ == '__main__':
    init_db()
    bot.run(TOKEN)
