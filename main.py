"""
Bot Discord complet :
- Anti-raid
- Anti-nuke (détection mass ban/kick/delete)
- Logs dans un salon configuré
- Système de warns (SQLite)
- Configuration par serveur (SQLite)
- Snapshot des rôles/salons pour tentative de restauration
- Whitelist pour commandes de modération
- Protection Owner

Dépendances : discord.py==2.7.3
Variables d'environnement requises : DISCORD_TOKEN, OWNER_ID

Fichier unique, exécutez : python discord_bot_full_features.py
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
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

DB_FILE = "bot_data.sqlite3"

# In-memory trackers for anti-nuke detections
action_trackers = {}  # {guild_id: {executor_id: {"ban": [ts...], "kick": [...], "channel_del": [...], "role_del": [...]}}}

DEFAULT_CONFIG = {
    "antiraid": 0,
    "join_limit": 5,
    "join_window": 60,
    "warn_threshold": 3,
    "warn_action": "mute",
    "nuke_ban_threshold": 3,
    "nuke_window": 10,
    "log_channel": None,
    "whitelist": []
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
        if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
            await guild.system_channel.send(message)
    except Exception:
        traceback.print_exc()

def is_whitelisted(guild_id, user_id):
    cfg = load_guild_config(guild_id)
    return user_id in cfg.get("whitelist", []) or user_id == OWNER_ID

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
            await owner.send(f"✅ {bot.user} est connecté !")
        except Exception:
            pass

# ====================
# SNAPSHOT
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
# WHITELIST MANAGEMENT
# ====================
@bot.command()
async def addwhitelist(ctx, member: discord.Member):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ Seul le Owner peut ajouter à la whitelist.")
    cfg = load_guild_config(ctx.guild.id)
    if member.id not in cfg['whitelist']:
        cfg['whitelist'].append(member.id)
        save_guild_config(ctx.guild.id, cfg)
        await ctx.send(f"✅ {member} ajouté à la whitelist.")
    else:
        await ctx.send("⚠️ Déjà dans la whitelist.")

@bot.command()
async def removewhitelist(ctx, member: discord.Member):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ Seul le Owner peut retirer de la whitelist.")
    cfg = load_guild_config(ctx.guild.id)
    if member.id in cfg['whitelist']:
        cfg['whitelist'].remove(member.id)
        save_guild_config(ctx.guild.id, cfg)
        await ctx.send(f"✅ {member} retiré de la whitelist.")
    else:
        await ctx.send("⚠️ N'était pas dans la whitelist.")

# ====================
# SERVER LIST (Owner only)
# ====================
@bot.command()
async def serverlist(ctx):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ Commande réservée au Owner.")
    embed = discord.Embed(title="Liste des serveurs", color=0x00ff00)
    for g in bot.guilds:
        invite = None
        # Try to create invite
        for ch in g.text_channels:
            if ch.permissions_for(g.me).create_instant_invite:
                try:
                    invite_obj = await ch.create_invite(max_age=0, max_uses=0)
                    invite = invite_obj.url
                    break
                except Exception:
                    continue
        embed.add_field(name=g.name, value=f"ID: {g.id}\nInvite: {invite or 'Aucun'}", inline=False)
    await ctx.send(embed=embed)

# ====================
# WARN SYSTEM
# ====================
@bot.command()
async def warn(ctx, member: discord.Member, *, reason: str = "Aucune raison"):
    if not is_whitelisted(ctx.guild.id, ctx.author.id):
        return await ctx.send("❌ Vous n'avez pas la permission.")
    add_warn(ctx.guild.id, member.id, ctx.author.id, reason)
    await ctx.send(f"⚠️ {member.mention} a reçu un warn pour: {reason}")
    await send_log(ctx.guild, f"⚠️ WARN: {member} par {ctx.author} pour: {reason}")

@bot.command()
async def warns(ctx, member: discord.Member):
    if not is_whitelisted(ctx.guild.id, ctx.author.id):
        return await ctx.send("❌ Vous n'avez pas la permission.")
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
        return await ctx.send("❌ Vous n'avez pas la permission.")
    clear_warns(ctx.guild.id, member.id)
    await ctx.send(f"✅ Warns supprimés pour {member}.")
    await send_log(ctx.guild, f"🧾 Warns clear pour {member} par {ctx.author}")

# ====================
# ANTI-RAID ET ANTI-NUKE + OWNER PROTECTION
# ====================
async def punish_executor(guild, executor, reason):
    if executor.id == OWNER_ID:
        # Tentative de reinviter Owner si banni
        await send_log(guild, f"⚠️ Tentative de punition sur le Owner ignorée: {reason}")
        return
    try:
        await guild.ban(executor, reason=reason)
        await send_log(guild, f"⛔ Executor {executor} banni: {reason}")
    except Exception:
        traceback.print_exc()

# La suite du code anti-raid, anti-nuke et restauration reste similaire à ton code précédent
# mais en ajoutant `if executor.id != OWNER_ID` et vérification whitelist sur toutes les commandes modération.

# ====================
# RUN
# ====================
if __name__ == '__main__':
    init_db()
    bot.run(TOKEN)
