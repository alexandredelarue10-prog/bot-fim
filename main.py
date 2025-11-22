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
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

DB_FILE = "bot_data.sqlite3"

# Anti-nuke/anti-raid trackers
action_trackers = {}

# Default server config
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
# UTILS
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

async def is_whitelisted(ctx):
    cfg = load_guild_config(ctx.guild.id)
    if ctx.author.id == OWNER_ID:
        return True
    return ctx.author.id in cfg.get('whitelist', [])

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
# HELP COMMANDS
# ====================
@bot.command(name='help')
async def help_cmd(ctx):
    embed = discord.Embed(title="Help Commands", color=0x1abc9c)
    embed.add_field(name="Fun Commands", value="!ping", inline=False)
    embed.add_field(name="Moderation Commands", value="!kick, !ban, !mute, !unmute, !lock, !unlock, !clear, !warn, !warns, !clearwarns, !snapshot", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='ownerhelp')
async def owner_help(ctx):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ Commande réservée au propriétaire.")
    embed = discord.Embed(title="Owner Commands", color=0xe74c3c)
    embed.add_field(name="Owner Only", value="!serverlist", inline=False)
    await ctx.send(embed=embed)

# ====================
# SNAPSHOT
# ====================
@bot.command()
@commands.has_permissions(administrator=True)
async def snapshot(ctx):
    guild = ctx.guild
    snap = {"roles": [], "channels": []}
    for role in guild.roles:
        snap['roles'].append({
            'name': role.name,
            'permissions': role.permissions.value,
            'hoist': role.hoist,
            'mentionable': role.mentionable
        })
    for ch in guild.channels:
        snap['channels'].append({
            'name': ch.name,
            'type': str(ch.type),
            'position': ch.position
        })
    save_snapshot(guild.id, snap)
    await ctx.send("✅ Snapshot sauvegardé.")
    await send_log(guild, f"🗂 Snapshot sauvegardé par {ctx.author}")

# ====================
# WHITELIST COMMANDS
# ====================
@bot.command()
@commands.has_permissions(administrator=True)
async def whitelist_add(ctx, user: discord.Member):
    cfg = load_guild_config(ctx.guild.id)
    if user.id not in cfg['whitelist']:
        cfg['whitelist'].append(user.id)
    save_guild_config(ctx.guild.id, cfg)
    await ctx.send(f"✅ {user.mention} ajouté à la whitelist.")

@bot.command()
@commands.has_permissions(administrator=True)
async def whitelist_remove(ctx, user: discord.Member):
    cfg = load_guild_config(ctx.guild.id)
    if user.id in cfg['whitelist']:
        cfg['whitelist'].remove(user.id)
    save_guild_config(ctx.guild.id, cfg)
    await ctx.send(f"✅ {user.mention} retiré de la whitelist.")

# ====================
# SERVERLIST (owner only)
# ====================
@bot.command()
async def serverlist(ctx):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ Commande réservée au propriétaire.")
    servers = [f"{g.name} ({g.id})" for g in bot.guilds]
    await ctx.send(f"**Serveurs du bot :**\n" + "\n".join(servers))

# ====================
# MODERATION COMMANDS (with whitelist)
# ====================
@bot.command()
async def ping(ctx):
    await ctx.send(f"Pong! {round(bot.latency*1000)}ms")

@bot.command()
async def kick(ctx, member: discord.Member, *, reason="Aucune raison"):
    if not await is_whitelisted(ctx):
        return await ctx.send("❌ Vous n'avez pas la permission.")
    if member.id == OWNER_ID:
        await ctx.send("❌ Impossible de kicker le propriétaire.")
        return
    await member.kick(reason=reason)
    await send_log(ctx.guild, f"👢 Kick: {member} par {ctx.author} ({reason})")
    await ctx.send(f"👢 {member} expulsé.")

@bot.command()
async def ban(ctx, member: discord.Member, *, reason="Aucune raison"):
    if not await is_whitelisted(ctx):
        return await ctx.send("❌ Vous n'avez pas la permission.")
    if member.id == OWNER_ID:
        await ctx.send("❌ Impossible de bannir le propriétaire.")
        return
    await member.ban(reason=reason)
    await send_log(ctx.guild, f"⛔ Ban: {member} par {ctx.author} ({reason})")
    await ctx.send(f"⛔ {member} banni.")

# ====================
# WARN SYSTEM
# ====================
@bot.command()
async def warn(ctx, member: discord.Member, *, reason="Aucune raison"):
    if not await is_whitelisted(ctx):
        return await ctx.send("❌ Vous n'avez pas la permission.")
    add_warn(ctx.guild.id, member.id, ctx.author.id, reason)
    await ctx.send(f"⚠️ {member.mention} a reçu un warn pour: {reason}")

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
    if not await is_whitelisted(ctx):
        return await ctx.send("❌ Vous n'avez pas la permission.")
    clear_warns(ctx.guild.id, member.id)
    await ctx.send(f"✅ Warns supprimés pour {member}.")

# ====================
# RUN
# ====================
if __name__ == '__main__':
    init_db()
    bot.run(TOKEN)
