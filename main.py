# ============================================
#  DISCORD BOT COMPLET – VERSION B
#  Anti-raid, Anti-nuke, Modération, Logs,
#  Whitelist, Snapshot, Warns, Protection Owner
# ============================================

import os
import discord
import asyncio
import json
import sqlite3
import traceback 
from discord.ext import commands
from datetime import datetime

# ============================================
# CONFIGURATION
# ============================================

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
PREFIX = "!"

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)


DB_NAME = "bot_data.sqlite"

# ============================================
# BASE DE DONNÉES
# ============================================

def db_connect():
    return sqlite3.connect(DB_NAME)

def init_db():
    conn = db_connect()
    cur = conn.cursor()

    # Config serveur
    cur.execute("""
        CREATE TABLE IF NOT EXISTS guild_config (
            guild_id INTEGER PRIMARY KEY,
            config_json TEXT
        )
    """)

    # Warns
    cur.execute("""
        CREATE TABLE IF NOT EXISTS warns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            user_id INTEGER,
            moderator_id INTEGER,
            reason TEXT,
            timestamp INTEGER
        )
    """)

    # Snapshots
    cur.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            guild_id INTEGER PRIMARY KEY,
            snapshot_json TEXT
        )
    """)

    # Whitelist
    cur.execute("""
        CREATE TABLE IF NOT EXISTS whitelist (
            guild_id INTEGER,
            user_id INTEGER,
            PRIMARY KEY (guild_id, user_id)
        )
    """)

    conn.commit()
    conn.close()

# ============================================
# CHARGEMENT + SAUVEGARDE CONFIG
# ============================================

DEFAULT_CONFIG = {
    "antiraid": False,
    "join_limit": 5,
    "join_window": 10,
    "anti_nuke": True,
    "nuke_actions_limit": 3,
    "log_channel": None,
    "warn_threshold": 3,
    "warn_action": "mute"
}

def load_config(guild_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT config_json FROM guild_config WHERE guild_id=?", (guild_id,))
    row = cur.fetchone()

    if row:
        conn.close()
        return json.loads(row[0])

    # Si pas de config, créer la config par défaut
    save_config(guild_id, DEFAULT_CONFIG)
    conn.close()
    return DEFAULT_CONFIG.copy()

def save_config(guild_id, config):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO guild_config (guild_id, config_json) VALUES (?, ?)",
        (guild_id, json.dumps(config))
    )
    conn.commit()
    conn.close()

# ============================================
# LOGS
# ============================================

async def send_log(guild, msg):
    try:
        cfg = load_config(guild.id)
        channel_id = cfg.get("log_channel")
        if channel_id:
            channel = guild.get_channel(channel_id)
            if channel:
                await channel.send(msg)
    except:
        traceback.print_exc()

# ============================================
# WHITELIST
# ============================================

def is_whitelisted(guild_id, user_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM whitelist WHERE guild_id=? AND user_id=?", (guild_id, user_id))
    row = cur.fetchone()
    conn.close()
    return row is not None

def add_whitelist(guild_id, user_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO whitelist (guild_id, user_id) VALUES (?, ?)", (guild_id, user_id))
    conn.commit()
    conn.close()

def remove_whitelist(guild_id, user_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM whitelist WHERE guild_id=? AND user_id=?", (guild_id, user_id))
    conn.commit()
    conn.close()

# ============================================
# UTILITAIRES
# ============================================

def ts():
    return int(datetime.utcnow().timestamp())

def is_staff(ctx):
    """Autorisé à modérer si Owner, Admin, ou Whitelist."""
    if ctx.author.id == OWNER_ID:
        return True
    if ctx.author.guild_permissions.administrator:
        return True
    if is_whitelisted(ctx.guild.id, ctx.author.id):
        return True
    return False

# ============================================
# PARTIE 2 / 7
# WARN, SNAPSHOT, STARTUP, ANTI-RAID
# ============================================

# In-memory tracker pour anti-nuke (sera utilisé dans les parties suivantes)
action_trackers = {}  # {guild_id: {executor_id: {"ban":[], "kick":[], "channel_del":[], "role_del":[]}}}

# ---------- DB helpers pour warns / snapshot ----------
def add_warn_db(guild_id, user_id, moderator_id, reason):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO warns (guild_id, user_id, moderator_id, reason, timestamp) VALUES (?, ?, ?, ?, ?)",
        (guild_id, user_id, moderator_id, reason, ts())
    )
    conn.commit()
    conn.close()

def get_warns_db(guild_id, user_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, moderator_id, reason, timestamp FROM warns WHERE guild_id=? AND user_id=? ORDER BY id",
        (guild_id, user_id)
    )
    rows = cur.fetchall()
    conn.close()
    return rows

def clear_warns_db(guild_id, user_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM warns WHERE guild_id=? AND user_id=?", (guild_id, user_id))
    conn.commit()
    conn.close()

def save_snapshot_db(guild_id, snapshot):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO snapshots (guild_id, snapshot_json) VALUES (?, ?)",
        (guild_id, json.dumps(snapshot))
    )
    conn.commit()
    conn.close()

def load_snapshot_db(guild_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT snapshot_json FROM snapshots WHERE guild_id=?", (guild_id,))
    row = cur.fetchone()
    conn.close()
    return json.loads(row[0]) if row else None

# ---------- STARTUP ----------
@bot.event
async def on_ready():
    # init DB once bot ready
    init_db()
    print(f"[+] Bot prêt: {bot.user} (ID: {bot.user.id})")
    # notify owner if possible
    if OWNER_ID:
        try:
            owner = await bot.fetch_user(OWNER_ID)
            await owner.send(f"✅ {bot.user} est connecté !")
        except Exception:
            # silent fail if owner DM blocked
            pass

# ---------- SNAPSHOT COMMAND ----------
@bot.command(name="snapshot")
async def cmd_snapshot(ctx):
    """!snapshot - sauvegarde un snapshot (roles + channels)"""
    if not is_staff(ctx):
        return await ctx.send("❌ Vous n'avez pas la permission.")
    guild = ctx.guild
    snap = {"roles": [], "channels": []}
    # roles (names, perms, hoist, mentionable)
    for role in guild.roles:
        snap["roles"].append({
            "name": role.name,
            "permissions": role.permissions.value,
            "hoist": bool(role.hoist),
            "mentionable": bool(role.mentionable)
        })
    # minimal channels info (name, type, category name, position)
    for ch in guild.channels:
        snap["channels"].append({
            "name": ch.name,
            "type": str(ch.type),
            "category": ch.category.name if ch.category else None,
            "position": ch.position
        })
    save_snapshot_db(guild.id, snap)
    await ctx.send("✅ Snapshot sauvegardé.")
    await send_log(guild, f"🗂 Snapshot sauvegardé par {ctx.author}")

# ---------- WARN COMMANDS ----------
@bot.command(name="warn")
async def cmd_warn(ctx, member: discord.Member, *, reason: str = "Aucune raison"):
    """!warn <member> [raison] - ajoute un warn (requiert staff)"""
    if not is_staff(ctx):
        return await ctx.send("❌ Vous n'avez pas la permission.")
    add_warn_db(ctx.guild.id, member.id, ctx.author.id, reason)
    await ctx.send(f"⚠️ {member.mention} a reçu un warn: {reason}")
    await send_log(ctx.guild, f"⚠️ WARN: {member} par {ctx.author} pour: {reason}")
    # check auto-action if threshold reached
    cfg = load_config(ctx.guild.id)
    warns = get_warns_db(ctx.guild.id, member.id)
    if len(warns) >= cfg.get("warn_threshold", DEFAULT_CONFIG["warn_threshold"]):
        action = cfg.get("warn_action", DEFAULT_CONFIG["warn_action"])
        try:
            if action == "mute":
                role = discord.utils.get(ctx.guild.roles, name="Muted")
                if not role:
                    role = await ctx.guild.create_role(name="Muted")
                    for channel in ctx.guild.channels:
                        try:
                            await channel.set_permissions(role, send_messages=False)
                        except:
                            pass
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

@bot.command(name="warns")
async def cmd_warns(ctx, member: discord.Member):
    """!warns <member> - affiche les warns d'un membre"""
    rows = get_warns_db(ctx.guild.id, member.id)
    if not rows:
        return await ctx.send(f"✅ {member} n'a aucun warn.")
    embed = discord.Embed(title=f"Warns de {member}", color=0xe67e22)
    for r in rows:
        wid, mod_id, reason, t = r
        try:
            moderator = ctx.guild.get_member(mod_id) or await bot.fetch_user(mod_id)
            mod_name = getattr(moderator, "display_name", str(moderator))
        except:
            mod_name = str(mod_id)
        embed.add_field(name=f"ID {wid}", value=f"Par: {mod_name}\n{reason}\n{datetime.utcfromtimestamp(t).strftime('%d/%m/%Y %H:%M:%S')} UTC", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="clearwarns")
async def cmd_clearwarns(ctx, member: discord.Member):
    """!clearwarns <member> - supprime tous les warns d'un membre"""
    if not is_staff(ctx):
        return await ctx.send("❌ Vous n'avez pas la permission.")
    clear_warns_db(ctx.guild.id, member.id)
    await ctx.send(f"✅ Warns supprimés pour {member}.")
    await send_log(ctx.guild, f"🧾 Warns clear pour {member} par {ctx.author}")

# ---------- ANTI-RAID (join flood simple) ----------
@bot.event
async def on_member_join(member):
    try:
        guild = member.guild
        cfg = load_config(guild.id)
        # always log join
        await send_log(guild, f"⇢ Member joined: {member} (ID: {member.id})")
        if not cfg.get("antiraid", False):
            return
        now = ts()
        tmp = cfg.get("_joins_tmp", [])
        tmp.append(now)
        window = cfg.get("join_window", DEFAULT_CONFIG["join_window"])
        # keep only items within window (seconds)
        tmp = [t for t in tmp if now - t < window]
        cfg["_joins_tmp"] = tmp
        save_config(guild.id, cfg)
        # if threshold reached, take action
        if len(tmp) >= cfg.get("join_limit", DEFAULT_CONFIG["join_limit"]):
            try:
                await member.ban(reason="Anti-raid: join flood")
                await send_log(guild, f"⚠️ ANTI-RAID: {member} banni automatiquement ({len(tmp)} joins en {window}s)")
            except Exception:
                traceback.print_exc()
    except Exception:
        traceback.print_exc()

# ============================================
# FIN PARTIE 2 / 7
# ============================================

# ============================================
# PARTIE 3 / 7
# AUDIT WATCHERS, ANTI-NUKE TRACKING, RAPPORT DE BASE
# ============================================

# In-memory tracker déjà déclaré en PARTIE 2:
# action_trackers = {}  # {guild_id: {executor_id: {"ban":[], "kick":[], "channel_del":[], "role_del":[]}}}

def ensure_action_tracker(guild_id, executor_id):
    g = action_trackers.setdefault(guild_id, {})
    return g.setdefault(executor_id, {"ban": [], "kick": [], "channel_del": [], "role_del": []})

async def generate_basic_nuke_report(guild, executor_id, snapshot):
    """
    Envoie un résumé du snapshot dans le canal de log + DM owner si possible.
    snapshot: dict {action_type: [timestamps,...]}
    """
    try:
        total = sum(len(v) for v in snapshot.values())
        executor = guild.get_member(executor_id) or await bot.fetch_user(executor_id)
        exec_str = str(executor) if executor else f"<@{executor_id}> ({executor_id})"
        msg = f"🚨 **Anti-Nuke détecté** sur `{guild.name}` — Executor: {exec_str} — Actions: {total}\n"
        for k, v in snapshot.items():
            msg += f"- {k}: {len(v)}\n"
        # persist minimal report in DB
        persist_payload = {
            "executor_id": executor_id,
            "counts": {k: len(v) for k, v in snapshot.items()},
            "generated_at": ts()
        }
        try:
            conn = db_connect()
            cur = conn.cursor()
            cur.execute("INSERT INTO logs (guild_id, event_type, event_json, timestamp) VALUES (?, ?, ?, ?)",
                        (guild.id, "anti_nuke_basic", json.dumps(persist_payload), int(datetime.utcnow().timestamp())))
            conn.commit()
            conn.close()
        except Exception:
            traceback.print_exc()
        await send_log(guild, msg)
        # DM owner
        if OWNER_ID:
            try:
                owner = await bot.fetch_user(OWNER_ID)
                await owner.send(f"[Anti-Nuke] {guild.name} — Executor: {exec_str} — actions: {total}")
            except:
                pass
    except Exception:
        traceback.print_exc()

async def check_and_handle_nuke(guild, executor_id):
    """
    Nettoie le tracker des anciennes timestamps, compte les actions et,
    si seuil dépassé, génère rapport et punit l'executor.
    """
    try:
        cfg = load_config(guild.id)
        threshold = cfg.get("nuke_actions_limit", DEFAULT_CONFIG["nuke_actions_limit"])
        window = cfg.get("nuke_window", DEFAULT_CONFIG.get("nuke_window", 10))
    except Exception:
        threshold = DEFAULT_CONFIG["nuke_actions_limit"]
        window = 10

    tracker = action_trackers.get(guild.id, {}).get(executor_id)
    if not tracker:
        return False

    now = ts()
    snapshot = {}
    total = 0
    # cleanup and count within window
    for k in list(tracker.keys()):
        tracker[k] = [t for t in tracker[k] if now - t < window]
        snapshot[k] = list(tracker[k])
        total += len(tracker[k])

    if total >= threshold:
        # generate basic report & persist
        await generate_basic_nuke_report(guild, executor_id, snapshot)
        # try to punish (ban) executor (best-effort)
        try:
            executor_member = guild.get_member(executor_id)
            if executor_member:
                # do not ban owner
                if executor_member.id == OWNER_ID:
                    await send_log(guild, f"⚠️ Executor identifié comme OWNER ({OWNER_ID}), aucune action punitive.")
                else:
                    try:
                        # attempt to strip elevated roles (best-effort)
                        for r in list(executor_member.roles):
                            if r.permissions.administrator or r.permissions.manage_guild:
                                try:
                                    await executor_member.remove_roles(r)
                                except:
                                    pass
                    except:
                        pass
                    try:
                        await guild.ban(executor_member, reason="Auto anti-nuke")
                        await send_log(guild, f"⛔ Executor {executor_member} banni par anti-nuke.")
                    except Exception:
                        traceback.print_exc()
            else:
                # executor not in cache — try to fetch as user and ban by id (best-effort)
                try:
                    user = await bot.fetch_user(executor_id)
                    try:
                        await guild.ban(user, reason="Auto anti-nuke (by id)")
                        await send_log(guild, f"⛔ Executor {user} banni par id (anti-nuke).")
                    except:
                        pass
                except:
                    pass
        except Exception:
            traceback.print_exc()
        # attempt minimal restore if snapshot exists (snapshot restore implemented later)
        try:
            # Clear tracker for executor
            action_trackers[guild.id].pop(executor_id, None)
        except:
            pass
        return True

    return False

# ---------- WATCHER: bans ----------
@bot.event
async def on_member_ban(guild, user):
    """
    Fired when a user is banned; read audit logs to find who did it
    """
    try:
        async for entry in guild.audit_logs(limit=6, action=discord.AuditLogAction.ban):
            if entry.target and getattr(entry.target, "id", None) == user.id:
                executor = entry.user
                now = ts()
                tracker = ensure_action_tracker(guild.id, executor.id)
                tracker["ban"].append(now)
                await send_log(guild, f"🔨 Ban détecté: {user} par {executor}")
                await check_and_handle_nuke(guild, executor.id)
                break
        # owner protection: if target was owner -> try to unban
        if user.id == OWNER_ID:
            try:
                await guild.unban(user)
                await send_log(guild, f"⚠️ Owner ({user}) a été banni — deban automatique.")
                if OWNER_ID:
                    try:
                        owner = await bot.fetch_user(OWNER_ID)
                        await owner.send(f"⚠️ Vous avez été banni de {guild.name} — deban automatique effectué.")
                    except:
                        pass
            except:
                traceback.print_exc()
    except Exception:
        traceback.print_exc()

# ---------- WATCHER: member remove (kick detection) ----------
@bot.event
async def on_member_remove(member):
    try:
        guild = member.guild
        # log leave
        await send_log(guild, f"⇠ Member left: {member} (ID: {member.id})")
        # check recent audit logs for a kick entry
        async for entry in guild.audit_logs(limit=6, action=discord.AuditLogAction.kick):
            if entry.target and getattr(entry.target, "id", None) == member.id:
                executor = entry.user
                now = ts()
                tracker = ensure_action_tracker(guild.id, executor.id)
                tracker["kick"].append(now)
                await send_log(guild, f"👢 Kick détecté: {member} par {executor}")
                await check_and_handle_nuke(guild, executor.id)
                break
        # owner protection: if owner removed
        if member.id == OWNER_ID:
            await send_log(guild, f"⚠️ Owner ({member}) a été expulsé/est parti du serveur.")
            if OWNER_ID:
                try:
                    owner = await bot.fetch_user(OWNER_ID)
                    await owner.send(f"⚠️ Vous avez été expulsé/avez quitté {guild.name}.")
                except:
                    pass
    except Exception:
        traceback.print_exc()

# ---------- WATCHER: channel delete ----------
@bot.event
async def on_guild_channel_delete(channel):
    try:
        guild = channel.guild
        async for entry in guild.audit_logs(limit=6, action=discord.AuditLogAction.channel_delete):
            executor = entry.user
            now = ts()
            tracker = ensure_action_tracker(guild.id, executor.id)
            tracker["channel_del"].append(now)
            await send_log(guild, f"🗑️ Channel supprimé: {channel.name} par {executor}")
            await check_and_handle_nuke(guild, executor.id)
            break
    except Exception:
        traceback.print_exc()

# ---------- WATCHER: role delete ----------
@bot.event
async def on_guild_role_delete(role):
    try:
        guild = role.guild
        async for entry in guild.audit_logs(limit=6, action=discord.AuditLogAction.role_delete):
            if entry.target and getattr(entry.target, "id", None) == role.id:
                executor = entry.user
                now = ts()
                tracker = ensure_action_tracker(guild.id, executor.id)
                tracker["role_del"].append(now)
                await send_log(guild, f"🗑️ Rôle supprimé: {role.name} par {executor}")
                await check_and_handle_nuke(guild, executor.id)
                break
    except Exception:
        traceback.print_exc()

# ============================================
# FIN PARTIE 3 / 7
# ============================================

# ============================================
# PARTIE 4 / 7
# RAPPORT ANTI-NUKE, PUNITION, RESTAURATION, PERSISTENCE LOGS
# ============================================

# ---------- Helpers DB pour logs (crée la table si besoin) ----------
def ensure_logs_table():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            event_type TEXT,
            event_json TEXT,
            timestamp INTEGER
        )
    """)
    conn.commit()
    conn.close()

def persist_log_event(guild_id, event_type, payload):
    """Persist an arbitrary event payload into the logs table (JSON)."""
    try:
        ensure_logs_table()
        conn = db_connect()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO logs (guild_id, event_type, event_json, timestamp) VALUES (?, ?, ?, ?)",
            (guild_id, event_type, json.dumps(payload, default=str), int(datetime.utcnow().timestamp()))
        )
        conn.commit()
        conn.close()
    except Exception:
        traceback.print_exc()

# ---------- Human readable time ----------
def human_time_from_ts(ts_int):
    try:
        return datetime.utcfromtimestamp(int(ts_int)).strftime("%Y-%m-%d %H:%M:%S UTC")
    except:
        return str(ts_int)

# ---------- PUNISH EXECUTOR ----------
async def punish_executor_real(guild, executor_member, snapshot_counts):
    """
    Try to remove sensitive roles then ban the executor. Best-effort: skip if owner or highest role.
    snapshot_counts used for logging the reason.
    """
    try:
        if executor_member is None:
            return
        # never punish owner
        if OWNER_ID and executor_member.id == OWNER_ID:
            await send_log(guild, f"⚠️ Executor {executor_member} identifié comme OWNER — punition ignorée.")
            return

        # Attempt to remove roles with dangerous perms (administrator/manage_guild/manage_roles)
        try:
            removable_roles = []
            for r in executor_member.roles:
                perms = r.permissions
                if perms.administrator or perms.manage_guild or perms.manage_roles or perms.ban_members or perms.kick_members:
                    removable_roles.append(r)
            # remove roles if bot has permissions and role is lower than bot top role
            if removable_roles:
                for r in removable_roles:
                    try:
                        await executor_member.remove_roles(r, reason="Anti-nuke: removal of sensitive roles")
                    except Exception:
                        # continue even if cannot remove some roles
                        pass
        except Exception:
            traceback.print_exc()

        # Finally try to ban
        reason = f"Anti-nuke auto-ban (actions: {snapshot_counts})"
        try:
            await guild.ban(executor_member, reason=reason)
            await send_log(guild, f"⛔ Executor {executor_member} banni. Raison: {reason}")
        except Exception:
            traceback.print_exc()
            await send_log(guild, f"⚠️ Impossible de bannir {executor_member} (permissions manquantes?)")
    except Exception:
        traceback.print_exc()

# ---------- RESTORE FROM SNAPSHOT (roles + channels) ----------
async def restore_from_snapshot(guild):
    """
    Attempt to restore roles and channels from the saved snapshot (best-effort).
    - Roles: create missing roles with stored permissions/flags
    - Channels: recreate missing text/voice channels (no categories/positions/overwrites complexity)
    """
    try:
        snap = load_snapshot_db(guild.id)
        if not snap:
            await send_log(guild, "⚠️ Aucun snapshot pour restauration.")
            return False

        await send_log(guild, "🔄 Démarrage restauration depuis snapshot...")
        # Roles
        existing_roles = {r.name: r for r in guild.roles}
        for rdata in snap.get("roles", []):
            name = rdata.get("name")
            if not name or name in existing_roles:
                continue
            perms_val = rdata.get("permissions", 0)
            hoist = bool(rdata.get("hoist", False))
            mentionable = bool(rdata.get("mentionable", False))
            try:
                perms = discord.Permissions(perms_val)
                await guild.create_role(name=name, permissions=perms, hoist=hoist, mentionable=mentionable, reason="Restore snapshot roles")
                await send_log(guild, f"➕ Rôle restauré: {name}")
            except Exception:
                traceback.print_exc()
                await send_log(guild, f"⚠️ Erreur en créant le rôle: {name}")

        # Channels (text / voice) - minimal recreation
        existing_ch = {c.name: c for c in guild.channels}
        for cdata in snap.get("channels", []):
            cname = cdata.get("name")
            ctype = cdata.get("type", "")
            if not cname or cname in existing_ch:
                continue
            try:
                if "text" in ctype:
                    await guild.create_text_channel(cname, reason="Restore snapshot channel")
                    await send_log(guild, f"➕ Salon text restauré: {cname}")
                elif "voice" in ctype:
                    await guild.create_voice_channel(cname, reason="Restore snapshot channel")
                    await send_log(guild, f"➕ Salon vocal restauré: {cname}")
            except Exception:
                traceback.print_exc()
                await send_log(guild, f"⚠️ Erreur en créant le salon: {cname}")

        await send_log(guild, "✅ Restauration terminée (tentative).")
        return True
    except Exception:
        traceback.print_exc()
        return False

# ---------- GENERATE ANTI-NUKE REPORT (embed + persist) ----------
async def generate_and_persist_nuke_report(guild, executor_id, tracker_snapshot):
    """
    Build an embed report, persist JSON in logs table, send embed to log channel and DM owner.
    tracker_snapshot: dict of lists of timestamps per action type.
    """
    try:
        # Build counts
        counts = {k: len(v) for k, v in tracker_snapshot.items()}
        total = sum(counts.values())
        # executor string
        executor_member = guild.get_member(executor_id)
        executor_str = str(executor_member) if executor_member else f"<@{executor_id}> ({executor_id})"

        # Build embed
        emb = discord.Embed(title="🚨 Rapport Anti-Nuke déclenché", color=0xff3333, timestamp=datetime.utcnow())
        emb.add_field(name="Serveur", value=f"{guild.name} ({guild.id})", inline=False)
        emb.add_field(name="Executor", value=executor_str, inline=False)
        emb.add_field(name="Actions totales", value=str(total), inline=False)
        for k, cnt in counts.items():
            emb.add_field(name=k, value=str(cnt), inline=True)

        # Timestamps details (limit to 8 per action for readability)
        details = ""
        for k, lst in tracker_snapshot.items():
            if not lst:
                continue
            details += f"**{k}** ({len(lst)}):\n"
            for t in lst[:8]:
                details += f"- {human_time_from_ts(t)}\n"
            details += "\n"
        if details:
            if len(details) > 1000:
                emb.add_field(name="Détails", value=details[:1000] + "…", inline=False)
            else:
                emb.add_field(name="Détails", value=details, inline=False)

        # Persist JSON payload
        payload = {
            "guild_id": guild.id,
            "executor_id": executor_id,
            "counts": counts,
            "timestamps": tracker_snapshot,
            "generated_at": int(datetime.utcnow().timestamp())
        }
        persist_log_event(guild.id, "anti_nuke_report", payload)

        # Send to configured log channel (or system channel fallback)
        await send_log(guild, f"🚨 Rapport Anti-Nuke: executor {executor_str}, actions totales: {total}")
        cfg = load_config(guild.id)
        log_ch_id = cfg.get("log_channel")
        if log_ch_id:
            ch = guild.get_channel(log_ch_id)
            if ch and ch.permissions_for(guild.me).send_messages:
                try:
                    await ch.send(embed=emb)
                except Exception:
                    await send_log(guild, "⚠️ Impossible d'envoyer l'embed du rapport au canal de log.")
        else:
            if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
                try:
                    await guild.system_channel.send(embed=emb)
                except:
                    pass

        # DM owner
        if OWNER_ID:
            try:
                owner = await bot.fetch_user(OWNER_ID)
                try:
                    await owner.send(f"🚨 Rapport Anti-Nuke pour {guild.name} — executor: {executor_str}")
                    await owner.send(embed=emb)
                except:
                    # fallback to sending short text
                    await owner.send(f"🚨 Rapport Anti-Nuke pour {guild.name} — executor: {executor_str} (embed failed)")
            except:
                pass

        return payload
    except Exception:
        traceback.print_exc()
        return None

# ---------- HANDLE NUKE DETECTION (appelé par check_nuke_threshold) ----------
async def handle_nuke_detection(guild, executor_id, tracker_snapshot):
    """
    Full pipeline when an anti-nuke is detected:
    1) generate and persist detailed report
    2) punish executor (remove sensitive roles + ban)
    3) attempt restoration from snapshot
    4) persist an after-action event
    """
    try:
        # 1) report
        report_payload = await generate_and_persist_nuke_report(guild, executor_id, tracker_snapshot)

        # 2) punish executor
        executor_member = guild.get_member(executor_id) or await bot.fetch_user(executor_id)
        # prepare counts for reason string
        counts = {k: len(v) for k, v in tracker_snapshot.items()}
        await punish_executor_real(guild, executor_member, counts)

        # 3) try restoration (best-effort)
        restored = await restore_from_snapshot(guild)

        # 4) persist after-action
        after_payload = {
            "guild_id": guild.id,
            "executor_id": executor_id,
            "report": report_payload,
            "restored": bool(restored),
            "handled_at": int(datetime.utcnow().timestamp())
        }
        persist_log_event(guild.id, "anti_nuke_handled", after_payload)

        # final log message
        await send_log(guild, f"✅ Anti-nuke géré pour executor <@{executor_id}>. Restauration: {'OK' if restored else 'Aucun snapshot/échec'}")
    except Exception:
        traceback.print_exc()

# Replace the earlier placeholder handle_nuke_detection with this real one
# (If earlier code already declared a function with same name, this will override it in Python runtime)

# ============================================
# FIN PARTIE 4 / 7
# ============================================

# ============================================
# PARTIE 5 / 7
# COMMANDES DE CONFIG, OWNER, EXPORT LOGS, HELP
# ============================================

import tempfile
import os

# ---------- CONFIG COMMANDS ----------
@bot.command(name="setlog")
async def cmd_setlog(ctx, channel: discord.TextChannel):
    """!setlog #channel - définit le canal de logs pour le serveur"""
    if not is_staff(ctx):
        return await ctx.send("❌ Vous n'avez pas la permission.")
    cfg = load_config(ctx.guild.id)
    cfg["log_channel"] = channel.id
    save_config(ctx.guild.id, cfg)
    await ctx.send(f"✅ Canal de log configuré: {channel.mention}")
    await send_log(ctx.guild, f"📌 Canal de log mis à jour par {ctx.author}: {channel.mention}")

@bot.command(name="logstatus")
async def cmd_logstatus(ctx):
    """!logstatus - affiche le statut du canal de logs"""
    cfg = load_config(ctx.guild.id)
    ch_id = cfg.get("log_channel")
    if not ch_id:
        return await ctx.send("🔎 Aucun canal de log configuré.")
    ch = ctx.guild.get_channel(ch_id)
    await ctx.send(f"🔎 Canal de log actuel: {ch.mention if ch else str(ch_id)}")

# ---------- NUCLEAR / RAID SETTINGS ----------
@bot.command(name="set_nuke_threshold")
async def cmd_set_nuke_threshold(ctx, amount: int):
    """!set_nuke_threshold <amount> - règle le seuil d'actions pour anti-nuke"""
    if not is_staff(ctx):
        return await ctx.send("❌ Vous n'avez pas la permission.")
    cfg = load_config(ctx.guild.id)
    cfg["nuke_actions_limit"] = max(1, amount)
    save_config(ctx.guild.id, cfg)
    await ctx.send(f"✅ Seuil anti-nuke réglé à {cfg['nuke_actions_limit']} actions.")

@bot.command(name="set_nuke_window")
async def cmd_set_nuke_window(ctx, seconds: int):
    """!set_nuke_window <seconds> - règle la fenêtre temporelle pour le count (seconds)"""
    if not is_staff(ctx):
        return await ctx.send("❌ Vous n'avez pas la permission.")
    cfg = load_config(ctx.guild.id)
    cfg["join_window"] = max(1, seconds)  # using join_window entry as generic time-window
    save_config(ctx.guild.id, cfg)
    await ctx.send(f"✅ Fenêtre temporelle anti-nuke réglée à {cfg['join_window']} secondes.")

@bot.command(name="set_antiraid")
async def cmd_set_antiraid(ctx, state: str):
    """!set_antiraid on/off - active ou désactive l'anti-raid"""
    if not is_staff(ctx):
        return await ctx.send("❌ Vous n'avez pas la permission.")
    val = 1 if state.lower() in ("on", "1", "true", "yes") else 0
    cfg = load_config(ctx.guild.id)
    cfg["antiraid"] = bool(val)
    save_config(ctx.guild.id, cfg)
    await ctx.send(f"🛡️ Anti-raid {'activé' if cfg['antiraid'] else 'désactivé'}.")

@bot.command(name="set_joinlimit")
async def cmd_set_joinlimit(ctx, amount: int):
    """!set_joinlimit <amount> - nombre de joins pour déclencher l'anti-raid"""
    if not is_staff(ctx):
        return await ctx.send("❌ Vous n'avez pas la permission.")
    cfg = load_config(ctx.guild.id)
    cfg["join_limit"] = max(1, amount)
    save_config(ctx.guild.id, cfg)
    await ctx.send(f"✅ Limite de joins réglée à {cfg['join_limit']}")

@bot.command(name="set_warn_threshold")
async def cmd_set_warn_threshold(ctx, amount: int):
    """!set_warn_threshold <amount> - règle le nombre de warns avant action"""
    if not is_staff(ctx):
        return await ctx.send("❌ Vous n'avez pas la permission.")
    cfg = load_config(ctx.guild.id)
    cfg["warn_threshold"] = max(1, amount)
    save_config(ctx.guild.id, cfg)
    await ctx.send(f"✅ Seuil de warns réglé à {cfg['warn_threshold']}")

@bot.command(name="set_warn_action")
async def cmd_set_warn_action(ctx, action: str):
    """!set_warn_action <mute|kick|ban|none> - action automatique sur seuil de warns"""
    if not is_staff(ctx):
        return await ctx.send("❌ Vous n'avez pas la permission.")
    action = action.lower()
    if action not in ("mute", "kick", "ban", "none"):
        return await ctx.send("❌ Action invalide. Choix: mute / kick / ban / none")
    cfg = load_config(ctx.guild.id)
    cfg["warn_action"] = action
    save_config(ctx.guild.id, cfg)
    await ctx.send(f"✅ Action automatique sur warn réglée à {action}")

# ---------- OWNER COMMANDS ----------
@bot.command(name="owner")
async def cmd_ownerhelp(ctx):
    """!owneraide - commandes pour le propriétaire du bot"""
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ Commande réservée au owner.")
    embed = discord.Embed(title="Owner Commands", color=0xff4444)
    embed.add_field(name="!serverlist", value="Affiche la liste des serveurs où le bot est présent et tente de créer une invite", inline=False)
    embed.add_field(name="!whitelist_add <@user>", value="Ajoute un utilisateur à la whitelist du serveur", inline=False)
    embed.add_field(name="!whitelist_remove <@user>", value="Retire un utilisateur de la whitelist du serveur", inline=False)
    embed.add_field(name="!exportlogs [guild_id]", value="Exporte les logs (owner only). Sans guild_id exporte tous.", inline=False)
    await ctx.send(embed=embed)

# ---------- EXPORT LOGS (owner only) ----------
@bot.command(name="exportlogs")
async def cmd_exportlogs(ctx, guild_id: int = None):
    """
    !exportlogs [guild_id] - owner only
    Exporte les logs en JSON. Si guild_id fourni, exporte les logs du serveur; sinon tous les logs.
    Envoie le fichier en pièce jointe.
    """
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ Commande réservée au owner.")
    try:
        conn = db_connect()
        cur = conn.cursor()
        if guild_id:
            cur.execute("SELECT id, guild_id, event_type, event_json, timestamp FROM logs WHERE guild_id=?", (guild_id,))
        else:
            cur.execute("SELECT id, guild_id, event_type, event_json, timestamp FROM logs")
        rows = cur.fetchall()
        conn.close()

        out = []
        for r in rows:
            rid, gid, etype, ej, ts_ = r
            try:
                payload = json.loads(ej)
            except:
                payload = ej
            out.append({"id": rid, "guild_id": gid, "event_type": etype, "event": payload, "timestamp": ts_})

        # write to temp file and send
        with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".json") as tf:
            json.dump(out, tf, indent=2, default=str)
            temp_name = tf.name

        await ctx.send(file=discord.File(temp_name, filename=f"logs_{guild_id if guild_id else 'all'}.json"))
        # cleanup temp file
        try:
            os.remove(temp_name)
        except:
            pass
    except Exception:
        traceback.print_exc()
        await ctx.send("Erreur lors de l'export des logs.")

@bot.command(name="aide")
async def cmd_aide(ctx):
    embed = discord.Embed(
        title="🛠 Commandes du Bot",
        description="Voici toutes les commandes disponibles selon vos permissions :",
        color=discord.Color.blue()
    )

    # --- Fun ---
    embed.add_field(
        name="🎉 Fun",
        value=(
            "!joke - Raconte une blague\n"
            "!meme - Envoie un meme aléatoire\n"
            "!roll - Lance un dé\n"
            "!8ball - Pose une question magique"
        ),
        inline=False
    )

    # --- Modération ---
    embed.add_field(
        name="🛡 Modération (Whitelist ou Owner requis)",
        value=(
            "!ban @user [raison] - Bannir un membre\n"
            "!kick @user [raison] - Expulser un membre\n"
            "!mute @user [durée] - Rendre muet un membre\n"
            "!unmute @user - Réactiver la parole"
        ),
        inline=False
    )

    # --- Owner Commands ---
    if ctx.author.id == OWNER_ID:  # <--- Remplace OWNER_ID par ton ID
        embed.add_field(
            name="👑 Owner Commands",
            value=(
                "!serverlist - Liste tous les serveurs et permet de réinviter le bot\n"
                "!shutdown - Éteint le bot\n"
                "!restart - Redémarre le bot\n"
                "!eval [code] - Évaluer du code Python"
            ),
            inline=False
        )

    # --- Protection ---
    embed.add_field(
        name="🛡 Protection",
        value=(
            "Anti-Nuke : Protège contre les bannissements/kicks massifs\n"
            "Anti-Ban/Kick : Prévention automatique pour le owner\n"
            "Whitelist : Accès aux commandes sensibles"
        ),
        inline=False
    )

    await ctx.send(embed=embed)


# ============================================
# FIN PARTIE 5 / 7
# ============================================

# ============================================
# PARTIE 6 / 7
# COMMANDES DE ROLES, WHITELIST, ANTI-BAN/KICK OWNER
# ============================================

# --------------------------------------------
# WHITELIST COMMANDS
# --------------------------------------------
@bot.command(name="whitelist_add")
async def cmd_whitelist_add(ctx, user: discord.Member):
    """!whitelist_add @user - ajoute un utilisateur à la whitelist"""
    if not is_staff(ctx) and ctx.author.id != OWNER_ID:
        return await ctx.send("❌ Vous n'avez pas la permission d'ajouter à la whitelist.")
    add_whitelist(ctx.guild.id, user.id)
    await ctx.send(f"✅ {user.mention} ajouté à la whitelist.")
    await send_log(ctx.guild, f"➕ {user} ajouté à la whitelist par {ctx.author}.")

@bot.command(name="whitelist_remove")
async def cmd_whitelist_remove(ctx, user: discord.Member):
    """!whitelist_remove @user - retire un utilisateur de la whitelist"""
    if not is_staff(ctx) and ctx.author.id != OWNER_ID:
        return await ctx.send("❌ Vous n'avez pas la permission.")
    remove_whitelist(ctx.guild.id, user.id)
    await ctx.send(f"❌ {user.mention} retiré de la whitelist.")
    await send_log(ctx.guild, f"➖ {user} retiré de la whitelist par {ctx.author}.")

@bot.command(name="whitelist")
async def cmd_whitelist_list(ctx):
    """!whitelist - liste les utilisateurs whitelistés"""
    wl = list_whitelist(ctx.guild.id)
    if not wl:
        return await ctx.send("🔎 Aucune personne dans la whitelist.")
    txt = "\n".join(f"<@{u}>" for u in wl)
    embed = discord.Embed(title="Whitelist", description=txt, color=0x00ff99)
    await ctx.send(embed=embed)

# --------------------------------------------
# ROLE COMMANDS
# --------------------------------------------
@bot.command(name="roleadd")
async def cmd_roleadd(ctx, user: discord.Member, *, role: discord.Role):
    """!roleadd @user role - ajoute un rôle"""
    if not is_staff(ctx):
        return await ctx.send("❌ Vous devez être whitelisté pour utiliser les commandes de rôle.")
    try:
        await user.add_roles(role, reason=f"Roleadd par {ctx.author}")
        await ctx.send(f"✅ {role.name} ajouté à {user.display_name}.")
        await send_log(ctx.guild, f"🎭 Rôle ajouté: {role} → {user} par {ctx.author}")
    except Exception:
        await ctx.send("❌ Impossible d'ajouter le rôle.")

@bot.command(name="roleremove")
async def cmd_roleremove(ctx, user: discord.Member, *, role: discord.Role):
    """!roleremove @user role - retire un rôle"""
    if not is_staff(ctx):
        return await ctx.send("❌ Vous devez être whitelisté.")
    try:
        await user.remove_roles(role, reason=f"Roleremove par {ctx.author}")
        await ctx.send(f"❌ {role.name} retiré à {user.display_name}.")
        await send_log(ctx.guild, f"🎭 Rôle retiré: {role} → {user} par {ctx.author}")
    except:
        await ctx.send("❌ Impossible de retirer le rôle.")

@bot.command(name="roleinfo")
async def cmd_roleinfo(ctx, *, role: discord.Role):
    """!roleinfo role - info d’un rôle"""
    embed = discord.Embed(title=f"Infos rôle: {role.name}", color=role.color)
    embed.add_field(name="ID", value=role.id)
    embed.add_field(name="Couleur", value=str(role.color))
    embed.add_field(name="Mentionnable", value=role.mentionable)
    embed.add_field(name="Position", value=role.position)
    embed.add_field(name="Membres", value=len(role.members))
    await ctx.send(embed=embed)

# --------------------------------------------
# ANTI BAN/KICK OWNER
# --------------------------------------------

@bot.event
async def on_member_remove(member):
    """Détection kick / ban / leave + protection owner"""
    guild = member.guild
    logs = await guild.audit_logs(limit=1, action=discord.AuditLogAction.kick).flatten()
    banlogs = await guild.audit_logs(limit=1, action=discord.AuditLogAction.ban).flatten()

    executor = None
    action_type = None

    if logs:
        entry = logs[0]
        if entry.target.id == member.id:
            executor = entry.user
            action_type = "kick"

    if banlogs:
        entry = banlogs[0]
        if entry.target.id == member.id:
            executor = entry.user
            action_type = "ban"

    # Aucune action trouvée = leave normal
    if not executor:
        return

    # PROTECTION OWNER
    if member.id == OWNER_ID:
        # Owner kick
        if action_type == "kick":
            try:
                invite = await guild.text_channels[0].create_invite(max_age=0, reason="Protection owner auto reinvite")
                await send_dm(OWNER_ID, f"⚠️ Vous avez été **kick** du serveur **{guild.name}**.\nVoici un nouvel invite:\n{invite.url}")
            except:
                pass
            await send_log(guild, f"🚨 ANTI-KICK OWNER : {executor} a essayé de kick le owner !")

        # Owner ban → auto unban + réinvite
        if action_type == "ban":
            try:
                await guild.unban(member, reason="Protection owner auto unban")
                invite = await guild.text_channels[0].create_invite(max_age=0)
                await send_dm(OWNER_ID, f"⚠️ Vous avez été **ban**, mais le bot vous a automatiquement **unban**.\nInvite: {invite.url}")
            except:
                pass
            await send_log(guild, f"🚨 ANTI-BAN OWNER : {executor} a essayé de ban le owner !")

        return  # on stoppe ici

    # PROTECTION DU BOT
    if member.id == bot.user.id:
        await send_dm(OWNER_ID, f"🚨 Votre bot a été **kick/banni** de **{guild.name}** par {executor}.")
        return

    # si on arrive ici, ce n’est ni le owner ni le bot
    # on enregistre quand même dans les logs
    await send_log(guild, f"⚠️ Membre expulsé/banni: {member} par {executor}")

# --------------------------------------------
# UTILITAIRE : SEND DM
# --------------------------------------------
async def send_dm(user_id, content):
    try:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        await user.send(content)
    except:
        pass

# ============================================
# FIN PARTIE 6 / 7
# ============================================

# ============================================
# PARTIE 7 / 7
# FINALISATION, GLOBAL CHECKS, ON_READY
# ============================================

# --------------------------------------------
# FONCTIONS D’AIDE INTERNES
# --------------------------------------------
def is_staff(ctx):
    """Vérifie si l’utilisateur est whitelisté ou owner"""
    if ctx.author.id == OWNER_ID:
        return True
    wl = list_whitelist(ctx.guild.id)
    return ctx.author.id in wl

# --------------------------------------------
# HELP COMMANDS
# --------------------------------------------
@bot.command(name="owneraide")
async def cmd_owneraide(ctx):
    if ctx.author.id != OWNER_ID:  # Remplace OWNER_ID par ton ID
        await ctx.send("❌ Vous n'êtes pas le propriétaire du bot !")
        return

    embed = discord.Embed(
        title="👑 Owner Help",
        description="Commandes exclusives au propriétaire avec contrôle complet du bot",
        color=discord.Color.gold()
    )

    # --- Bot Management ---
    embed.add_field(
        name="🤖 Gestion du Bot",
        value=(
            "!shutdown - Éteint le bot\n"
            "!restart - Redémarre le bot\n"
            "!eval [code] - Évaluer du code Python en direct\n"
            "!serverlist - Liste tous les serveurs et permet de réinviter le bot"
        ),
        inline=False
    )

    # --- Protection & Anti-Nuke ---
    embed.add_field(
        name="🛡 Protection / Anti-Nuke",
        value=(
            "Anti-Nuke : Protège le serveur contre bannissements/kicks massifs\n"
            "Anti-Ban/Kick Owner : Si le owner est kick/ban, il est automatiquement réinvité ou débanni\n"
            "Whitelist : Gestion des membres autorisés à utiliser les commandes modération"
        ),
        inline=False
    )

    # --- Modération ---
    embed.add_field(
        name="🛡 Modération",
        value=(
            "!ban @user [raison] - Bannir un membre\n"
            "!kick @user [raison] - Expulser un membre\n"
            "!mute @user [durée] - Rendre muet un membre\n"
            "!unmute @user - Réactiver la parole\n"
            "!warn @user [raison] - Avertir un membre"
        ),
        inline=False
    )

    # --- Configuration / Gestion ---
    embed.add_field(
        name="⚙ Configuration",
        value=(
            "!addwhitelist @user - Ajouter un membre à la whitelist\n"
            "!removewhitelist @user - Retirer un membre de la whitelist\n"
            "!setprefix [prefix] - Changer le préfixe du bot"
        ),
        inline=False
    )

    await ctx.send(embed=embed)


# --------------------------------------------
# SERVER LIST COMMAND
# --------------------------------------------
@bot.command(name="serverlist")
async def serverlist(ctx):
    if ctx.author.id != OWNER_ID:  # Remplace OWNER_ID par ton ID
        await ctx.send("❌ Vous n'êtes pas autorisé à utiliser cette commande !")
        return

    embed = discord.Embed(
        title="📜 Liste des serveurs",
        description=f"Le bot est présent sur {len(bot.guilds)} serveurs",
        color=discord.Color.blue()
    )

    for guild in bot.guilds:
        embed.add_field(
            name=guild.name,
            value=f"ID: {guild.id}\nMembres: {guild.member_count}",
            inline=False
        )

    # Ajouter un bouton pour réinviter le bot sur un serveur
    view = View()
    invite_button = Button(
        label="Réinviter le bot",
        url=f"https://discord.com/oauth2/authorize?client_id={bot.user.id}&permissions=8&scope=bot%20applications.commands"
    )
    view.add_item(invite_button)

    await ctx.send(embed=embed, view=view)

    # Reinvite owner si absent
    for g in guilds:
        member = g.get_member(OWNER_ID)
        if not member:
            try:
                invite = await g.text_channels[0].create_invite(max_age=0, reason="Reinvite owner")
                await send_dm(OWNER_ID, f"🔗 Reinvite automatique pour {g.name}: {invite.url}")
            except:
                pass

# --------------------------------------------
# GLOBAL CHECK POUR COMMANDES
# --------------------------------------------
@bot.check
async def global_command_check(ctx):
    """Check global avant toute commande"""
    if ctx.guild is None:
        return True  # DM autorisées
    # log command
    await send_log(ctx.guild, f"💬 Cmd: {ctx.command} utilisée par {ctx.author}")
    # check whitelist / owner pour commandes modération
    if ctx.command.name in [
        "kick","ban","mute","unmute","clear","lock","unlock",
        "warn","warns","clearwarns","set_warn_threshold","set_warn_action",
        "set_antiraid","set_joinlimit","snapshot","setlog",
        "whitelist_add","whitelist_remove","whitelist"
    ]:
        if not is_staff(ctx):
            await ctx.send("❌ Vous devez être whitelisté pour utiliser cette commande.")
            return False
    return True

# --------------------------------------------
# ON_READY FINAL
# --------------------------------------------
@bot.event
async def on_ready():
    init_db()
    print(f"🤖 Bot prêt: {bot.user} (ID: {bot.user.id})")
    for guild in bot.guilds:
        print(f"🔹 Connecté à {guild.name} (ID: {guild.id})")
    # DM owner
    if OWNER_ID:
        try:
            owner = await bot.fetch_user(OWNER_ID)
            await owner.send(f"✅ {bot.user} est connecté sur {len(bot.guilds)} serveurs !")
        except:
            pass

# --------------------------------------------
# RUN BOT
# --------------------------------------------
if __name__ == "__main__":
    init_db()
    bot.run(TOKEN)

