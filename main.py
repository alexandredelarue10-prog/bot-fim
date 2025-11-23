"""
Bot Discord - Version finale (avec rapport anti-nuke)
Dépendances : discord.py
Variables d'environnement : DISCORD_TOKEN, OWNER_ID
Fichier: discord_bot_full_features.py
"""

import os
import discord
import sqlite3
import asyncio
import json
import traceback
from discord.ext import commands
from datetime import datetime

# ====================
# CONFIG
# ====================
TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
PREFIX = "!"

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

DB_FILE = "bot_data.sqlite3"

# Trackers for anti-nuke
action_trackers = {}  # {guild_id: {executor_id: {"ban":[], "kick":[], "channel_del":[], "role_del":[]}}}

# Default per-server configuration
DEFAULT_CONFIG = {
    "antiraid": 0,
    "join_limit": 5,
    "join_window": 60,
    "warn_threshold": 3,
    "warn_action": "mute",   # mute / kick / ban / none
    "nuke_ban_threshold": 4,
    "nuke_window": 10,
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
    # store server configs
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
    # whitelist per guild
    c.execute('''CREATE TABLE IF NOT EXISTS whitelist(
                    guild_id INTEGER,
                    user_id INTEGER,
                    PRIMARY KEY(guild_id,user_id)
                 )''')
    # logs (persist events)
    c.execute('''CREATE TABLE IF NOT EXISTS logs(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    event_type TEXT,
                    event_json TEXT,
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
    c.execute("INSERT OR REPLACE INTO guild_config(guild_id, config_json) VALUES(?,?)",
              (guild_id, json.dumps(cfg)))
    conn.commit()

# warns helpers
def add_warn(gid, uid, mid, reason):
    ts = int(datetime.utcnow().timestamp())
    c = conn.cursor()
    c.execute("INSERT INTO warns(guild_id,user_id,moderator_id,reason,timestamp) VALUES(?,?,?,?,?)",
              (gid, uid, mid, reason, ts))
    conn.commit()

def get_warns(gid, uid):
    c = conn.cursor()
    c.execute("SELECT id, moderator_id, reason, timestamp FROM warns WHERE guild_id=? AND user_id=? ORDER BY id",
              (gid, uid))
    return c.fetchall()

def clear_warns(gid, uid):
    c = conn.cursor()
    c.execute("DELETE FROM warns WHERE guild_id=? AND user_id=?", (gid, uid))
    conn.commit()

# snapshot helpers
def save_snapshot(gid, snapshot):
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO snapshots(guild_id, snapshot_json) VALUES(?,?)",
              (gid, json.dumps(snapshot)))
    conn.commit()

def load_snapshot(gid):
    c = conn.cursor()
    c.execute("SELECT snapshot_json FROM snapshots WHERE guild_id=?", (gid,))
    row = c.fetchone()
    return json.loads(row[0]) if row else None

# whitelist helpers
def add_whitelist(gid, uid):
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO whitelist(guild_id,user_id) VALUES(?,?)", (gid, uid))
    conn.commit()

def remove_whitelist(gid, uid):
    c = conn.cursor()
    c.execute("DELETE FROM whitelist WHERE guild_id=? AND user_id=?", (gid, uid))
    conn.commit()

def is_whitelisted(gid, uid):
    if OWNER_ID and uid == OWNER_ID:
        return True
    c = conn.cursor()
    return c.execute("SELECT 1 FROM whitelist WHERE guild_id=? AND user_id=?", (gid, uid)).fetchone() is not None

# logging to DB
def persist_log(gid, event_type, payload):
    ts = int(datetime.utcnow().timestamp())
    c = conn.cursor()
    c.execute("INSERT INTO logs(guild_id,event_type,event_json,timestamp) VALUES(?,?,?,?)",
              (gid, event_type, json.dumps(payload, default=str), ts))
    conn.commit()

# ====================
# UTIL & LOG SENDER
# ====================
def now_ts():
    return asyncio.get_event_loop().time()

async def send_log(guild, message):
    """
    Sends a log message to the configured channel for guild or system_channel fallback.
    Also persists the log in DB via persist_log.
    """
    try:
        cfg = load_guild_config(guild.id)
        ch_id = cfg.get("log_channel")
        payload = {"message": message, "timestamp": int(datetime.utcnow().timestamp())}
        persist_log(guild.id, "message", payload)
        if ch_id:
            ch = guild.get_channel(ch_id)
            if ch and ch.permissions_for(guild.me).send_messages:
                await ch.send(message)
                return
        if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
            await guild.system_channel.send(message)
    except Exception:
        traceback.print_exc()

# ====================
# TRACKER HELPERS (anti-nuke)
# ====================
def ensure_tracker(gid, executor_id):
    g = action_trackers.setdefault(gid, {})
    return g.setdefault(executor_id, {"ban": [], "kick": [], "channel_del": [], "role_del": []})

async def punish_executor(guild, executor, reason):
    if executor is None:
        return
    try:
        if executor.id == OWNER_ID:
            await send_log(guild, f"⚠️ Executor {executor} est OWNER — pas de punition automatique.")
            return
        # remove high perms if possible, then ban
        try:
            member = guild.get_member(executor.id)
            if member:
                for r in member.roles:
                    if r.permissions.administrator or r.permissions.manage_guild:
                        try:
                            await member.remove_roles(r)
                        except: pass
        except: pass
        await guild.ban(executor, reason=f"Anti-nuke auto-ban: {reason}")
        await send_log(guild, f"⛔ Executor {executor} banni par anti-nuke. Raison: {reason}")
        # notify owner
        if OWNER_ID:
            try:
                owner = await bot.fetch_user(OWNER_ID)
                await owner.send(f"Anti-nuke: {executor} banni dans {guild.name} pour: {reason}")
            except: pass
    except Exception:
        traceback.print_exc()

async def attempt_restore(guild):
    snap = load_snapshot(guild.id)
    if not snap:
        await send_log(guild, "⚠️ Aucun snapshot disponible pour restauration.")
        return
    await send_log(guild, "🔄 Tentative de restauration depuis snapshot...")
    try:
        existing_roles = {r.name: r for r in guild.roles}
        # restore roles
        for rdata in snap.get('roles', []):
            if rdata['name'] in existing_roles:
                continue
            perms = discord.Permissions(rdata.get('permissions', 0))
            try:
                await guild.create_role(name=rdata['name'], permissions=perms, hoist=rdata.get('hoist', False), mentionable=rdata.get('mentionable', False))
            except Exception:
                traceback.print_exc()
        # restore channels minimally (names & type)
        existing_ch = {c.name: c for c in guild.channels}
        for cdata in snap.get('channels', []):
            if cdata['name'] in existing_ch:
                continue
            try:
                if 'text' in cdata.get('type', ''):
                    await guild.create_text_channel(cdata['name'])
                elif 'voice' in cdata.get('type', ''):
                    await guild.create_voice_channel(cdata['name'])
            except Exception:
                traceback.print_exc()
    except Exception:
        traceback.print_exc()
    await send_log(guild, "✅ Restauration terminée (tentative).")

# ====================
# NEW: ANTI-NUKE REPORT GENERATOR
# ====================
def human_time(ts):
    return datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S UTC")

async def generate_nuke_report(guild, executor_id, tracker_snapshot):
    """
    tracker_snapshot: dict with keys ban/kick/channel_del/role_del containing lists of timestamps (floats)
    Builds an embed and JSON payload, sends to log, DMs owner, persists.
    """
    try:
        # get executor info
        executor_member = guild.get_member(executor_id)
        executor_name = str(executor_member) if executor_member else f"<@{executor_id}> ({executor_id})"
        # counts and timestamp lists
        counts = {k: len(v) for k, v in tracker_snapshot.items()}
        # build embed
        emb = discord.Embed(title="🚨 Rapport Anti-Nuke déclenché", color=0xff0000, timestamp=datetime.utcnow())
        emb.add_field(name="Serveur", value=f"{guild.name} ({guild.id})", inline=False)
        emb.add_field(name="Executor", value=executor_name, inline=False)
        emb.add_field(name="Actions totales", value=str(sum(counts.values())), inline=False)
        for k, v in counts.items():
            emb.add_field(name=k, value=str(v), inline=True)
        # add timestamps (limit to recent 10 per type for readability)
        details = ""
        for k, ts_list in tracker_snapshot.items():
            if not ts_list:
                continue
            details += f"**{k}** ({len(ts_list)}):\n"
            # convert to human times, show up to 10
            lines = [f"- {human_time(t)}" for t in ts_list[:10]]
            details += "\n".join(lines) + "\n\n"
        if details:
            if len(details) > 1024:
                emb.add_field(name="Détails (trunc)", value=details[:1000] + "...", inline=False)
            else:
                emb.add_field(name="Détails", value=details, inline=False)
        # JSON payload to persist
        payload = {
            "guild_id": guild.id,
            "executor_id": executor_id,
            "counts": counts,
            "timestamps": {k: tracker_snapshot.get(k, []) for k in tracker_snapshot},
            "generated_at": int(datetime.utcnow().timestamp())
        }
        # persist
        persist_log(guild.id, "anti_nuke_report", payload)
        # send to log channel
        await send_log(guild, f"🚨 Rapport Anti-Nuke: executor {executor_name}, actions: {sum(counts.values())}")
        # try to send embed to log channel (repeat logic)
        cfg = load_guild_config(guild.id)
        ch_id = cfg.get("log_channel")
        if ch_id:
            ch = guild.get_channel(ch_id)
            if ch and ch.permissions_for(guild.me).send_messages:
                try:
                    await ch.send(embed=emb)
                except:
                    await send_log(guild, "⚠️ Impossible d'envoyer l'embed du rapport dans le canal de log.")
        else:
            # fallback to system_channel
            if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
                try:
                    await guild.system_channel.send(embed=emb)
                except:
                    pass
        # DM owner if available
        if OWNER_ID:
            try:
                owner = await bot.fetch_user(OWNER_ID)
                await owner.send(f"🚨 Rapport Anti-Nuke pour {guild.name} — executor: {executor_name}")
                try:
                    await owner.send(embed=emb)
                except: pass
            except:
                pass
    except Exception:
        traceback.print_exc()

# ====================
# NEW: modified check_nuke_threshold that generates report before punishing
# ====================
async def check_nuke_threshold(guild, executor_id):
    cfg = load_guild_config(guild.id)
    threshold = cfg.get('nuke_ban_threshold', DEFAULT_CONFIG['nuke_ban_threshold'])
    window = cfg.get('nuke_window', DEFAULT_CONFIG['nuke_window'])
    tracker = action_trackers.get(guild.id, {}).get(executor_id)
    if not tracker:
        return False
    now = now_ts()
    total_actions = 0
    # cleanup and count, but capture snapshot first
    snapshot = {}
    for key in list(tracker.keys()):
        tracker[key] = [t for t in tracker[key] if now - t < window]
        snapshot[key] = list(tracker[key])  # copy for report
        total_actions += len(tracker[key])
    if total_actions >= threshold:
        # generate report BEFORE punishment and restoration
        await generate_nuke_report(guild, executor_id, snapshot)
        executor = guild.get_member(executor_id) or await bot.fetch_user(executor_id)
        await punish_executor(guild, executor, f"Detected {total_actions} destructive actions in {window}s")
        await attempt_restore(guild)
        # clear tracker
        action_trackers[guild.id].pop(executor_id, None)
        return True
    return False

# ====================
# STARTUP
# ====================
@bot.event
async def on_ready():
    init_db()
    print(f"Bot prêt: {bot.user} (ID: {bot.user.id})")
    if OWNER_ID:
        try:
            owner = await bot.fetch_user(OWNER_ID)
            await owner.send(f"✅ {bot.user} est connecté ! (Rapports Anti-Nuke activés)")
        except Exception:
            pass

# ====================
# ANTI-RAID (join flood)
# ====================
@bot.event
async def on_member_join(member):
    try:
        guild = member.guild
        cfg = load_guild_config(guild.id)
        if not cfg.get('antiraid', 0):
            await send_log(guild, f"⇢ Member joined: {member} (antiraid off)")
            return
        now = now_ts()
        tmp = cfg.get('joins_tmp', [])
        tmp.append(now)
        window = cfg.get('join_window', DEFAULT_CONFIG['join_window'])
        tmp = [t for t in tmp if now - t < window]
        cfg['joins_tmp'] = tmp
        save_guild_config(guild.id, cfg)
        await send_log(guild, f"⇢ Member joined: {member}")
        if len(tmp) >= cfg.get('join_limit', DEFAULT_CONFIG['join_limit']):
            try:
                await member.ban(reason='Anti-raid activé')
                await send_log(guild, f"⚠️ ANTI-RAID: {member} banni automatiquement ({len(tmp)} joins en {window}s)")
            except Exception:
                traceback.print_exc()
    except Exception:
        traceback.print_exc()

@bot.event
async def on_member_remove(member):
    try:
        guild = member.guild
        await send_log(guild, f"⇠ Member left: {member}")
        async for entry in guild.audit_logs(limit=6, action=discord.AuditLogAction.kick):
            if entry.target and entry.target.id == member.id:
                executor = entry.user
                t = now_ts()
                tracker = ensure_tracker(guild.id, executor.id)
                tracker['kick'].append(t)
                await send_log(guild, f"👢 Kick détecté: {member} par {executor}")
                await check_nuke_threshold(guild, executor.id)
                break
        if member.id == OWNER_ID:
            await send_log(guild, f"⚠️ Owner {member} a quitté/été kické du serveur!")
            if OWNER_ID:
                try:
                    owner = await bot.fetch_user(OWNER_ID)
                    await owner.send(f"⚠️ Vous avez quitté/été kické du serveur {guild.name}.")
                except: pass
    except Exception:
        traceback.print_exc()

# ====================
# AUDIT WATCHERS FOR BANS
# ====================
@bot.event
async def on_member_ban(guild, user):
    try:
        async for entry in guild.audit_logs(limit=6, action=discord.AuditLogAction.ban):
            if entry.target and entry.target.id == user.id:
                executor = entry.user
                t = now_ts()
                tracker = ensure_tracker(guild.id, executor.id)
                tracker['ban'].append(t)
                await send_log(guild, f"🔨 Ban détecté: {user} par {executor}")
                await check_nuke_threshold(guild, executor.id)
                break
        if user.id == OWNER_ID:
            try:
                await guild.unban(user)
                await send_log(guild, f"⚠️ Owner {user} a été banni — deban automatique.")
                if OWNER_ID:
                    try:
                        owner = await bot.fetch_user(OWNER_ID)
                        await owner.send(f"⚠️ Vous avez été banni de {guild.name} — j'ai procédé au deban automatique.")
                    except: pass
            except Exception:
                traceback.print_exc()
    except Exception:
        traceback.print_exc()

# ====================
# CHANNEL / ROLE CREATE & DELETE WATCHERS
# ====================
@bot.event
async def on_guild_channel_delete(channel):
    try:
        guild = channel.guild
        async for entry in guild.audit_logs(limit=6, action=discord.AuditLogAction.channel_delete):
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
    try:
        guild = role.guild
        async for entry in guild.audit_logs(limit=6, action=discord.AuditLogAction.role_delete):
            if entry.target and entry.target.id == role.id:
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
# MESSAGE EVENTS (logs)
# ====================
@bot.event
async def on_message_delete(message):
    try:
        if message.guild:
            await send_log(message.guild, f"🗑️ Message supprimé dans #{message.channel.name} par {message.author}: {message.content[:200]}")
    except Exception:
        traceback.print_exc()

@bot.event
async def on_message_edit(before, after):
    try:
        if before.guild:
            await send_log(before.guild, f"✏️ Message édité par {before.author} dans #{before.channel.name}\nAvant: {before.content[:200]}\nAprès: {after.content[:200]}")
    except Exception:
        traceback.print_exc()

# ====================
# COMMANDS - SNAPSHOT / WARN / WHITELIST / LOG CONFIG / DYNAMIC SETTINGS
# (same as prior; permission checks use is_whitelisted)
# ====================
@bot.command()
async def snapshot(ctx):
    if not is_whitelisted(ctx.guild.id, ctx.author.id):
        return await ctx.send("❌ Pas la permission.")
    guild = ctx.guild
    snap = {"roles": [], "channels": []}
    for role in guild.roles:
        snap["roles"].append({
            "name": role.name,
            "permissions": role.permissions.value,
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

@bot.command()
async def warn(ctx, member: discord.Member, *, reason: str = "Aucune raison"):
    if not is_whitelisted(ctx.guild.id, ctx.author.id):
        return await ctx.send("❌ Pas la permission.")
    add_warn(ctx.guild.id, member.id, ctx.author.id, reason)
    await ctx.send(f"⚠️ {member.mention} a reçu un warn pour: {reason}")
    await send_log(ctx.guild, f"⚠️ WARN: {member} par {ctx.author} pour: {reason}")
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
async def warns(ctx, member: discord.Member):
    rows = get_warns(ctx.guild.id, member.id)
    if not rows:
        return await ctx.send(f"✅ {member} n'a aucun warn.")
    embed = discord.Embed(title=f"Warns de {member}", color=0xe67e22)
    for r in rows:
        wid, mod_id, reason, ts = r
        mod = ctx.guild.get_member(mod_id) or await bot.fetch_user(mod_id)
        embed.add_field(name=f"ID {wid}", value=f"Par: {getattr(mod,'name',mod)}\n{reason}\n{datetime.utcfromtimestamp(ts).strftime('%d/%m/%Y %H:%M:%S')} UTC", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def clearwarns(ctx, member: discord.Member):
    if not is_whitelisted(ctx.guild.id, ctx.author.id):
        return await ctx.send("❌ Pas la permission.")
    clear_warns(ctx.guild.id, member.id)
    await ctx.send(f"✅ Warns supprimés pour {member}.")
    await send_log(ctx.guild, f"🧾 Warns clear pour {member} par {ctx.author}")

@bot.command()
async def whitelist_add(ctx, member: discord.Member):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ Commande réservée au owner")
    add_whitelist(ctx.guild.id, member.id)
    await ctx.send(f"✅ {member} ajouté à la whitelist")
    await send_log(ctx.guild, f"✅ {member} ajouté à la whitelist par owner")

@bot.command()
async def whitelist_remove(ctx, member: discord.Member):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ Commande réservée au owner")
    remove_whitelist(ctx.guild.id, member.id)
    await ctx.send(f"✅ {member} retiré de la whitelist")
    await send_log(ctx.guild, f"✅ {member} retiré de la whitelist par owner")

# log config
@bot.command()
async def setlog(ctx, channel: discord.TextChannel):
    if not is_whitelisted(ctx.guild.id, ctx.author.id):
        return await ctx.send("❌ Pas la permission.")
    cfg = load_guild_config(ctx.guild.id)
    cfg['log_channel'] = channel.id
    save_guild_config(ctx.guild.id, cfg)
    await ctx.send(f"✅ Canal de log défini: {channel.mention}")

@bot.command()
async def logstatus(ctx):
    cfg = load_guild_config(ctx.guild.id)
    ch_id = cfg.get('log_channel')
    if ch_id:
        ch = ctx.guild.get_channel(ch_id)
        await ctx.send(f"🔎 Canal de log actuel: {ch.mention if ch else str(ch_id)}")
    else:
        await ctx.send("🔎 Aucun canal de log configuré.")

# dynamic settings
@bot.command()
async def set_nuke_threshold(ctx, amount: int):
    if not is_whitelisted(ctx.guild.id, ctx.author.id):
        return await ctx.send("❌ Pas la permission.")
    cfg = load_guild_config(ctx.guild.id)
    cfg['nuke_ban_threshold'] = max(1, amount)
    save_guild_config(ctx.guild.id, cfg)
    await ctx.send(f"✅ Seuil Anti-Nuke réglé à {cfg['nuke_ban_threshold']} actions.")

@bot.command()
async def set_nuke_window(ctx, seconds: int):
    if not is_whitelisted(ctx.guild.id, ctx.author.id):
        return await ctx.send("❌ Pas la permission.")
    cfg = load_guild_config(ctx.guild.id)
    cfg['nuke_window'] = max(1, seconds)
    save_guild_config(ctx.guild.id, cfg)
    await ctx.send(f"✅ Fenêtre Anti-Nuke réglée à {cfg['nuke_window']}s.")

@bot.command()
async def set_antiraid(ctx, state: str):
    if not is_whitelisted(ctx.guild.id, ctx.author.id):
        return await ctx.send("❌ Pas la permission.")
    cfg = load_guild_config(ctx.guild.id)
    cfg['antiraid'] = 1 if state.lower() in ('on','1','true') else 0
    save_guild_config(ctx.guild.id, cfg)
    await ctx.send(f"🛡️ Anti-raid {'activé' if cfg['antiraid'] else 'désactivé'}.")

@bot.command()
async def set_joinlimit(ctx, amount: int):
    if not is_whitelisted(ctx.guild.id, ctx.author.id):
        return await ctx.send("❌ Pas la permission.")
    cfg = load_guild_config(ctx.guild.id)
    cfg['join_limit'] = max(1, amount)
    save_guild_config(ctx.guild.id, cfg)
    await ctx.send(f"✅ Limite de joins réglée à {cfg['join_limit']}")

@bot.command()
async def set_warn_threshold(ctx, amount: int):
    if not is_whitelisted(ctx.guild.id, ctx.author.id):
        return await ctx.send("❌ Pas la permission.")
    cfg = load_guild_config(ctx.guild.id)
    cfg['warn_threshold'] = max(1, amount)
    save_guild_config(ctx.guild.id, cfg)
    await ctx.send(f"✅ Seuil de warns réglé à {cfg['warn_threshold']}")

@bot.command()
async def set_warn_action(ctx, action: str):
    if not is_whitelisted(ctx.guild.id, ctx.author.id):
        return await ctx.send("❌ Pas la permission.")
    action = action.lower()
    if action not in ('mute','kick','ban','none'):
        return await ctx.send("Action invalide. Choix possibles : mute / kick / ban / none")
    cfg = load_guild_config(ctx.guild.id)
    cfg['warn_action'] = action
    save_guild_config(ctx.guild.id, cfg)
    await ctx.send(f"✅ Action automatique sur warn: {action}")

# moderation commands (clear/kick/ban/mute/unmute/lock/unlock/ping)
@bot.command()
async def ping(ctx):
    await ctx.send(f"Pong! {round(bot.latency*1000)}ms")

@bot.command()
async def clear(ctx, amount: int):
    if not is_whitelisted(ctx.guild.id, ctx.author.id):
        return await ctx.send("❌ Pas la permission.")
    try:
        await ctx.channel.purge(limit=amount+1)
        await ctx.send(f"🧹 {amount} messages supprimés", delete_after=3)
        await send_log(ctx.guild, f"🧹 {ctx.author} a supprimé {amount} messages dans #{ctx.channel.name}")
    except Exception:
        traceback.print_exc()
        await ctx.send("Erreur lors du purge.")

@bot.command()
async def kick(ctx, member: discord.Member, *, reason: str = "Aucune raison"):
    if not is_whitelisted(ctx.guild.id, ctx.author.id):
        return await ctx.send("❌ Pas la permission.")
    if member.id == OWNER_ID:
        return await ctx.send("❌ Impossible d'expulser le owner.")
    try:
        await member.kick(reason=reason)
        await ctx.send(f"👢 {member} expulsé.")
        await send_log(ctx.guild, f"👢 Kick: {member} par {ctx.author} ({reason})")
    except Exception:
        traceback.print_exc()
        await ctx.send("Erreur lors du kick.")

@bot.command()
async def ban(ctx, member: discord.Member, *, reason: str = "Aucune raison"):
    if not is_whitelisted(ctx.guild.id, ctx.author.id):
        return await ctx.send("❌ Pas la permission.")
    if member.id == OWNER_ID:
        return await ctx.send("❌ Impossible de bannir le owner.")
    try:
        await member.ban(reason=reason)
        await ctx.send(f"⛔ {member} banni.")
        await send_log(ctx.guild, f"⛔ Ban: {member} par {ctx.author} ({reason})")
    except Exception:
        traceback.print_exc()
        await ctx.send("Erreur lors du ban.")

@bot.command()
async def mute(ctx, member: discord.Member):
    if not is_whitelisted(ctx.guild.id, ctx.author.id):
        return await ctx.send("❌ Pas la permission.")
    try:
        role = discord.utils.get(ctx.guild.roles, name="Muted")
        if not role:
            role = await ctx.guild.create_role(name="Muted")
            for channel in ctx.guild.channels:
                try:
                    await channel.set_permissions(role, send_messages=False, add_reactions=False)
                except: pass
        await member.add_roles(role)
        await ctx.send(f"🔇 {member} mute.")
        await send_log(ctx.guild, f"🔇 Mute: {member} par {ctx.author}")
    except Exception:
        traceback.print_exc()
        await ctx.send("Erreur lors du mute.")

@bot.command()
async def unmute(ctx, member: discord.Member):
    if not is_whitelisted(ctx.guild.id, ctx.author.id):
        return await ctx.send("❌ Pas la permission.")
    try:
        role = discord.utils.get(ctx.guild.roles, name="Muted")
        if role:
            await member.remove_roles(role)
        await ctx.send(f"🔊 {member} unmute.")
        await send_log(ctx.guild, f"🔊 Unmute: {member} par {ctx.author}")
    except Exception:
        traceback.print_exc()
        await ctx.send("Erreur lors du unmute.")

@bot.command()
async def lock(ctx):
    if not is_whitelisted(ctx.guild.id, ctx.author.id):
        return await ctx.send("❌ Pas la permission.")
    try:
        await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False)
        await ctx.send("🔒 Salon verrouillé.")
        await send_log(ctx.guild, f"🔒 Salon {ctx.channel.name} verrouillé par {ctx.author}")
    except Exception:
        traceback.print_exc()
        await ctx.send("Erreur lors du lock.")

@bot.command()
async def unlock(ctx):
    if not is_whitelisted(ctx.guild.id, ctx.author.id):
        return await ctx.send("❌ Pas la permission.")
    try:
        await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=True)
        await ctx.send("🔓 Salon déverrouillé.")
        await send_log(ctx.guild, f"🔓 Salon {ctx.channel.name} déverrouillé par {ctx.author}")
    except Exception:
        traceback.print_exc()
        await ctx.send("Erreur lors du unlock.")

# help/ownerhelp/serverlist
@bot.command()
async def help(ctx):
    embed = discord.Embed(title="Commandes disponibles", color=0x00ff00)
    embed.add_field(name="Fun", value="`!ping`", inline=False)
    if is_whitelisted(ctx.guild.id, ctx.author.id):
        embed.add_field(name="Modération", value="`!warn`, `!warns`, `!clearwarns`, `!kick`, `!ban`, `!mute`, `!unmute`, `!clear`, `!lock`, `!unlock`, `!snapshot`", inline=False)
        embed.add_field(name="Config", value="`!setlog`, `!set_nuke_threshold`, `!set_nuke_window`, `!set_antiraid`, `!set_joinlimit`, `!set_warn_threshold`, `!set_warn_action`", inline=False)
    if ctx.author.id == OWNER_ID:
        embed.add_field(name="Owner", value="`!ownerhelp`, `!serverlist`, `!whitelist_add`, `!whitelist_remove`", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def ownerhelp(ctx):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ Commande réservée au owner")
    embed = discord.Embed(title="Owner Commands", color=0xff0000)
    embed.add_field(name="Server management", value="`!serverlist` (liste serveurs + invites)", inline=False)
    embed.add_field(name="Whitelist", value="`!whitelist_add <user>`, `!whitelist_remove <user>`", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def serverlist(ctx):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ Commande réservée au owner")
    embed = discord.Embed(title="Serveurs du bot", color=0x00ff00)
    for g in bot.guilds:
        name = g.name
        gid = g.id
        invite_str = "N/A"
        try:
            # try create invite in first writable text channel
            channel = None
            for ch in g.text_channels:
                if ch.permissions_for(g.me).create_instant_invite:
                    channel = ch
                    break
            if channel:
                inv = await channel.create_invite(max_age=3600, max_uses=1)
                invite_str = inv.url
            else:
                invite_str = "Pas de channel avec permission pour créer invite"
        except Exception:
            invite_str = "Impossible de créer invite"
        embed.add_field(name=f"{name} ({gid})", value=invite_str, inline=False)
    await ctx.send(embed=embed)

# ====================
# RUN
# ====================
if __name__ == "__main__":
    init_db()
    bot.run(TOKEN)
