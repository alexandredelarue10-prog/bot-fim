# main.py - FIM Manager (tout-en-un, prêt pour Railway)
# Requirements see requirements.txt below.
# Start command: python3 main.py

import os
import sys
import json
import threading
import asyncio
from datetime import datetime, timezone
from typing import Optional, List

import discord
from discord.ext import commands
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

# --- FIX pour Python 3.13 : audioop supprimé ---
import sys
sys.modules["audioop"] = None

import discord
discord.opus.is_loaded = lambda: True
# ------------------------------------------------
# -----------------------------
# CONFIG
# -----------------------------
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("ERROR: DISCORD_TOKEN not set")
    sys.exit(1)

PORT = int(os.getenv("PORT", 8080))
DEFAULT_OWNER_ID = int(os.getenv("DEFAULT_OWNER_ID", 489113166429683713))
OWNER_FILE = "owner_data.json"
CONFIG_FILE = "config.json"
BANS_FILE = "bansync.json"

intents = discord.Intents.all()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# -----------------------------
# AUTO-DETECTION DU DASHBOARD (Railway)
# -----------------------------
railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN")
if railway_domain:
    DASHBOARD_URL = f"https://{railway_domain}"
else:
    DASHBOARD_URL = os.getenv("DASHBOARD_URL", f"http://localhost:{PORT}")

print(f"[INFO] Dashboard URL detected: {DASHBOARD_URL}")

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
        json.dump(data, f, indent=2, ensure_ascii=False)

# -----------------------------
# Owner / config initialization
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

def get_owners() -> List[int]:
    data = ensure_owner_data()
    owners = data.get("owners", [])
    if DEFAULT_OWNER_ID not in owners:
        owners.append(DEFAULT_OWNER_ID)
        data["owners"] = owners
        save_json(OWNER_FILE, data)
    return owners

def is_owner(uid: int) -> bool:
    return uid in get_owners()

def add_owner(uid: int) -> bool:
    data = ensure_owner_data()
    owners = data.get("owners", [])
    if uid not in owners:
        owners.append(uid)
        data["owners"] = owners
        save_json(OWNER_FILE, data)
        return True
    return False

def remove_owner(uid: int) -> bool:
    data = ensure_owner_data()
    owners = data.get("owners", [])
    if uid in owners:
        owners.remove(uid)
        data["owners"] = owners
        save_json(OWNER_FILE, data)
        return True
    return False

def get_owner_password() -> str:
    data = ensure_owner_data()
    return data.get("password", "trolleur2010")

def set_owner_password(newpass: str):
    data = ensure_owner_data()
    data["password"] = newpass
    save_json(OWNER_FILE, data)

# -----------------------------
# Guild config (whitelist, logs, protections)
# -----------------------------
def get_config():
    return load_json(CONFIG_FILE, {})

def save_config(cfg):
    save_json(CONFIG_FILE, cfg)

def get_whitelist(gid: int):
    cfg = get_config()
    return cfg.get(str(gid), {}).get("whitelist", [])

def add_to_whitelist(gid: int, uid: int):
    cfg = get_config()
    g = str(gid)
    cfg.setdefault(g, {})
    cfg[g].setdefault("whitelist", [])
    if uid not in cfg[g]["whitelist"]:
        cfg[g]["whitelist"].append(uid)
        save_config(cfg)
        return True
    return False

def remove_from_whitelist(gid: int, uid: int):
    cfg = get_config()
    g = str(gid)
    if g in cfg and "whitelist" in cfg[g] and uid in cfg[g]["whitelist"]:
        cfg[g]["whitelist"].remove(uid)
        save_config(cfg)
        return True
    return False

def set_log_channel(gid:int, channel_id:int):
    cfg = get_config()
    g = str(gid)
    cfg.setdefault(g, {})
    cfg[g]["log_channel"] = channel_id
    save_config(cfg)

def get_log_channel_id(gid:int):
    cfg = get_config()
    return cfg.get(str(gid), {}).get("log_channel")

def set_protection(gid:int, key:str, value:bool):
    cfg = get_config()
    g = str(gid)
    cfg.setdefault(g, {})
    cfg[g].setdefault("protection", {})
    cfg[g]["protection"][key] = bool(value)
    save_config(cfg)

def get_protection(gid:int, key:str):
    cfg = get_config()
    return cfg.get(str(gid), {}).get("protection", {}).get(key, False)

# -----------------------------
# Bans storage (optional)
# -----------------------------
def load_bans():
    return load_json(BANS_FILE, {"bans": [], "sync": {}})

def save_bans(data):
    save_json(BANS_FILE, data)

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
            if ctx.guild and ctx.author.id in get_whitelist(ctx.guild.id):
                return True
        except Exception:
            pass
        try:
            await ctx.message.delete()
        except Exception:
            pass
        return False
    return commands.check(predicate)

def owner_only():
    def predicate(ctx):
        return is_owner(ctx.author.id)
    return commands.check(predicate)

# -----------------------------
# UTIL: audit log helper
# -----------------------------
async def find_audit_executor(guild: discord.Guild, action: discord.AuditLogAction, target_id: int, lookback: int = 20):
    try:
        async for entry in guild.audit_logs(limit=lookback, action=action):
            try:
                t = getattr(entry.target, "id", None)
                if t is None:
                    if str(entry.target) == str(target_id):
                        return entry.user
                elif int(t) == int(target_id):
                    return entry.user
            except Exception:
                continue
    except Exception:
        pass
    return None

# -----------------------------
# EVENTS: protections + notifications
# -----------------------------
@bot.event
async def on_ready():
    ensure_owner_data()
    print(f"✅ {bot.user} connecté (ID: {bot.user.id})")
    # send dashboard URL to owners
    for oid in get_owners():
        try:
            u = await bot.fetch_user(oid)
            await u.send(f"🔗 Dashboard F.I.M : {DASHBOARD_URL}")
        except Exception:
            pass

@bot.event
async def on_guild_remove(guild: discord.Guild):
    try:
        client_id = str(bot.user.id)
        invite_link = f"https://discord.com/oauth2/authorize?client_id={client_id}&scope=bot&permissions=8"
        for oid in get_owners():
            try:
                u = await bot.fetch_user(oid)
                await u.send(f"⚠️ Le bot a été retiré du serveur **{guild.name}** (ID: {guild.id}). Réinvite : {invite_link}")
            except Exception:
                pass
    except Exception:
        pass

@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User):
    try:
        if is_owner(user.id):
            try:
                await asyncio.sleep(1)
                await guild.unban(user)
            except Exception:
                pass
            try:
                if guild.text_channels:
                    invite = await guild.text_channels[0].create_invite(max_uses=1)
                    for oid in get_owners():
                        try:
                            u = await bot.fetch_user(oid)
                            await u.send(f"⚠️ Un owner a été banni de **{guild.name}**. Tentative de débannissement et invitation : {invite.url}")
                        except Exception:
                            pass
            except Exception:
                pass
            return
        if get_protection(guild.id, "anti_ban"):
            executor = await find_audit_executor(guild, discord.AuditLogAction.ban, user.id)
            if executor:
                if is_owner(getattr(executor, "id", None)):
                    return
                if getattr(executor, "id", None) == guild.owner_id:
                    return
                if executor.id in get_whitelist(guild.id):
                    return
                try:
                    await guild.ban(executor, reason="AntiBan triggered - executor punished")
                except Exception:
                    try:
                        await guild.kick(executor, reason="AntiBan fallback - executor kicked")
                    except Exception:
                        pass
    except Exception as e:
        print("[on_member_ban] error:", e)

@bot.event
async def on_member_remove(member: discord.Member):
    try:
        if is_owner(member.id):
            guild = member.guild
            invite = None
            try:
                if guild and guild.text_channels:
                    invite = await guild.text_channels[0].create_invite(max_uses=1)
            except Exception:
                invite = None
            for oid in get_owners():
                try:
                    u = await bot.fetch_user(oid)
                    msg = f"🚪 Un owner a été expulsé/departi de **{guild.name}**."
                    if invite:
                        msg += f" Invitation : {invite.url}"
                    await u.send(msg)
                except Exception:
                    pass
            return
        guild = member.guild
        if get_protection(guild.id, "anti_kick"):
            executor = await find_audit_executor(guild, discord.AuditLogAction.kick, member.id)
            if executor:
                if is_owner(getattr(executor, "id", None)):
                    return
                if getattr(executor, "id", None) == guild.owner_id:
                    return
                if executor.id in get_whitelist(guild.id):
                    return
                try:
                    await guild.ban(executor, reason="AntiKick triggered - executor punished")
                except Exception:
                    try:
                        await guild.kick(executor, reason="AntiKick fallback - executor kicked")
                    except Exception:
                        pass
    except Exception as e:
        print("[on_member_remove] error:", e)

# -----------------------------
# HELPERS
# -----------------------------
async def send_owner_dm(text: str):
    for oid in get_owners():
        try:
            u = await bot.fetch_user(oid)
            await u.send(text)
        except Exception:
            pass

def safe_embed(title, description, color=discord.Color.blurple()):
    em = discord.Embed(title=title, description=description, color=color)
    em.set_footer(text=f"{datetime.now(timezone.utc).isoformat()}")
    return em

# -----------------------------
# COMMANDS: public / whitelist-protected
# -----------------------------
@bot.command(name="ping")
async def cmd_ping(ctx):
    await ctx.send("🏓 Pong ! Le bot F.I.M est opérationnel.")

@bot.command(name="say")
@whitelist_check()
async def cmd_say(ctx, *, message: str):
    try: await ctx.message.delete()
    except: pass
    await ctx.send(message)

@bot.command(name="send")
@whitelist_check()
async def cmd_send(ctx, channel: discord.TextChannel, *, message: str):
    try: await ctx.message.delete()
    except: pass
    await channel.send(message)
    try: await ctx.send(f"✅ Message envoyé dans {channel.mention}", delete_after=4)
    except: pass

@bot.command(name="embed")
@whitelist_check()
async def cmd_embed(ctx, title: str, *, description: str):
    try: await ctx.message.delete()
    except: pass
    em = safe_embed(title, description)
    em.set_footer(text=f"Envoyé par {ctx.author}")
    await ctx.send(embed=em)

@bot.command(name="addrole")
@whitelist_check()
async def cmd_addrole(ctx, member: discord.Member, role: discord.Role):
    try:
        await member.add_roles(role)
        await ctx.send(f"✅ Rôle {role.name} ajouté à {member.mention}")
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission d'ajouter ce rôle.")
    except Exception:
        await ctx.send("❌ Erreur lors de l'ajout du rôle.")

@bot.command(name="removerole")
@whitelist_check()
async def cmd_removerole(ctx, member: discord.Member, role: discord.Role):
    try:
        await member.remove_roles(role)
        await ctx.send(f"✅ Rôle {role.name} retiré de {member.mention}")
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de retirer ce rôle.")
    except Exception:
        await ctx.send("❌ Erreur lors du retrait du rôle.")

@bot.command(name="userinfo")
async def cmd_userinfo(ctx, member: Optional[discord.Member] = None):
    member = member or ctx.author
    em = discord.Embed(title="User Info")
    em.add_field(name="Nom", value=f"{member} ({member.id})", inline=False)
    em.add_field(name="Bot", value=str(member.bot), inline=True)
    em.add_field(name="Status", value=str(member.status), inline=True)
    em.set_thumbnail(url=member.avatar.url if member.avatar else "")
    await ctx.send(embed=em)

@bot.command(name="serverinfo")
async def cmd_serverinfo(ctx):
    g = ctx.guild
    em = discord.Embed(title="Server Info")
    em.add_field(name="Nom", value=f"{g.name} ({g.id})", inline=False)
    em.add_field(name="Membres", value=str(g.member_count), inline=True)
    em.add_field(name="Owner", value=str(g.owner), inline=True)
    await ctx.send(embed=em)

@bot.command(name="avatar")
async def cmd_avatar(ctx, member: Optional[discord.Member] = None):
    member = member or ctx.author
    if member.avatar:
        await ctx.send(member.avatar.url)
    else:
        await ctx.send("Pas d'avatar.")

@bot.command(name="clear")
@whitelist_check()
async def cmd_clear(ctx, amount: int = 10):
    try:
        await ctx.channel.purge(limit=amount+1)
        await ctx.send(f"✅ {amount} messages supprimés.", delete_after=4)
    except Exception:
        await ctx.send("❌ Impossible de supprimer les messages.")

# -----------------------------
# Moderation local: ban/kick/unban/warn/infractions
# -----------------------------
@bot.command(name="ban")
@whitelist_check()
async def cmd_ban(ctx, member: discord.Member, *, reason: str = "Non spécifiée"):
    if member.id == bot.user.id:
        return await ctx.send("❌ Je ne peux pas me bannir moi-même.")
    if is_owner(member.id):
        return await ctx.send("❌ Impossible d'agir contre un Owner.")
    if member.id == ctx.guild.owner_id:
        return await ctx.send("❌ Impossible d'agir contre le propriétaire du serveur.")
    try:
        await ctx.guild.ban(member, reason=f"{ctx.author} | {reason}")
        await ctx.send(f"✅ {member.mention} banni. (Raison: {reason})")
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de bannir ce membre.")
    except Exception:
        await ctx.send("❌ Erreur lors du ban.")

@bot.command(name="kick")
@whitelist_check()
async def cmd_kick(ctx, member: discord.Member, *, reason: str = "Non spécifiée"):
    if member.id == bot.user.id:
        return await ctx.send("❌ Je ne peux pas me kicker moi-même.")
    if is_owner(member.id):
        return await ctx.send("❌ Impossible d'agir contre un Owner.")
    if member.id == ctx.guild.owner_id:
        return await ctx.send("❌ Impossible d'agir contre le propriétaire du serveur.")
    try:
        await ctx.guild.kick(member, reason=f"{ctx.author} | {reason}")
        await ctx.send(f"✅ {member.mention} kické. (Raison: {reason})")
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de kicker ce membre.")
    except Exception:
        await ctx.send("❌ Erreur lors du kick.")

@bot.command(name="unban")
@whitelist_check()
async def cmd_unban(ctx, user_id: int):
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user)
        await ctx.send(f"✅ {user} débanni.")
    except Exception:
        await ctx.send("❌ Impossible de débannir cet utilisateur.")

def add_warn(gid: int, uid: int, reason: str):
    cfg = get_config()
    g = str(gid)
    cfg.setdefault(g, {})
    cfg[g].setdefault("warns", {})
    cfg[g]["warns"].setdefault(str(uid), [])
    cfg[g]["warns"][str(uid)].append({"time": datetime.now(timezone.utc).isoformat(), "reason": reason})
    save_config(cfg)

@bot.command(name="warn")
@whitelist_check()
async def cmd_warn(ctx, member: discord.Member, *, reason: str = "Non spécifiée"):
    add_warn(ctx.guild.id, member.id, reason)
    await ctx.send(f"⚠️ {member.mention} averti. Raison: {reason}")

@bot.command(name="infractions")
@whitelist_check()
async def cmd_infractions(ctx, member: discord.Member):
    cfg = get_config()
    g = str(ctx.guild.id)
    warns = cfg.get(g, {}).get("warns", {}).get(str(member.id), [])
    if not warns:
        return await ctx.send("Aucune infraction.")
    text = "\n".join([f"- {w['time']}: {w['reason']}" for w in warns])
    await ctx.send(f"Infractions pour {member.mention}:\n{text}")

# -----------------------------
# Owner / Global Commands
# -----------------------------
@bot.command(name="broadcast")
@owner_only()
async def cmd_broadcast(ctx, *, message: str):
    count = 0
    for g in bot.guilds:
        try:
            if g.text_channels:
                await g.text_channels[0].send(f"📢 **Annonce Owner:** {message}")
                count += 1
        except Exception:
            pass
    try:
        await ctx.author.send(f"✅ Broadcast envoyé sur {count} serveurs.")
    except Exception:
        pass

@bot.command(name="forceunban")
@owner_only()
async def cmd_forceunban(ctx):
    uid = ctx.author.id
    count = 0
    for g in bot.guilds:
        try:
            await g.unban(discord.Object(id=uid))
            count += 1
        except Exception:
            pass
    await ctx.author.send(f"✅ Tentative de débannissement effectuée sur {count} serveurs.")

@bot.command(name="forcerinv")
@owner_only()
async def cmd_forcerinv(ctx):
    for g in bot.guilds:
        try:
            if g.text_channels:
                invite = await g.text_channels[0].create_invite(max_uses=1)
                for oid in get_owners():
                    try:
                        u = await bot.fetch_user(oid)
                        await u.send(f"🔗 Invitation pour **{g.name}** : {invite.url}")
                    except Exception:
                        pass
        except Exception:
            pass
    await ctx.author.send("✅ Invitations envoyées aux owners.")

@bot.command(name="forceinv")
@owner_only()
async def cmd_forceinv_alias(ctx):
    await cmd_forcerinv(ctx)

@bot.command(name="serverlist")
@owner_only()
async def cmd_serverlist(ctx):
    lines = [f"- {g.name} ({g.id}) - {g.member_count} membres" for g in bot.guilds]
    txt = "\n".join(lines) or "Aucun serveur."
    try:
        await ctx.author.send(f"📋 Serveurs ({len(bot.guilds)}):\n{txt}")
    except Exception:
        pass

@bot.command(name="syncwhitelist")
@owner_only()
async def cmd_syncwhitelist(ctx):
    src = get_whitelist(ctx.guild.id)
    cfg = get_config()
    for g in bot.guilds:
        gid = str(g.id)
        cfg.setdefault(gid, {})
        cfg[gid]["whitelist"] = src.copy()
    save_config(cfg)
    await ctx.author.send("🔁 Whitelist synchronisée sur tous les serveurs.")

@bot.command(name="addowner")
@owner_only()
async def cmd_addowner(ctx, user: discord.User):
    if add_owner(user.id):
        await ctx.send(f"✅ {user} ajouté aux owners.")
    else:
        await ctx.send("❌ Déjà owner.")

@bot.command(name="removeowner")
@owner_only()
async def cmd_removeowner(ctx, user: discord.User):
    if remove_owner(user.id):
        await ctx.send(f"✅ {user} retiré des owners.")
    else:
        await ctx.send("❌ Non trouvé dans owners.")

@bot.command(name="setpass")
@owner_only()
async def cmd_setpass(ctx, *, newpass: str):
    set_owner_password(newpass)
    await ctx.send("🔒 Mot de passe owner mis à jour.")

@bot.command(name="connect")
async def cmd_connect(ctx, password: str):
    try:
        if password == get_owner_password():
            if add_owner(ctx.author.id):
                try:
                    await ctx.author.send("✅ Tu as été ajouté comme owner.")
                except Exception:
                    pass
            else:
                try:
                    await ctx.author.send("ℹ️ Tu es déjà owner.")
                except Exception:
                    pass
    except Exception:
        pass

@bot.command(name="globalban")
@owner_only()
async def cmd_globalban(ctx, user: str):
    try:
        uid = int(user.strip("<@!>"))
    except:
        try: uid = int(user)
        except:
            return await ctx.send("❌ ID invalide.")
    count = 0
    for g in bot.guilds:
        try:
            if is_owner(uid):
                continue
            await g.ban(discord.Object(id=uid), reason=f"Global ban by owner {ctx.author.id}")
            count += 1
        except Exception:
            pass
    await ctx.author.send(f"✅ Global ban exécuté sur {count} serveur(s).")

@bot.command(name="globalkick")
@owner_only()
async def cmd_globalkick(ctx, user: str):
    try:
        uid = int(user.strip("<@!>"))
    except:
        try: uid = int(user)
        except:
            return await ctx.send("❌ ID invalide.")
    count = 0
    for g in bot.guilds:
        try:
            m = g.get_member(uid)
            if m:
                await g.kick(m, reason=f"Global kick by owner {ctx.author.id}")
                count += 1
        except Exception:
            pass
    await ctx.author.send(f"✅ Global kick exécuté sur {count} serveur(s).")

@bot.command(name="reboot")
@owner_only()
async def cmd_reboot(ctx):
    await ctx.author.send("♻️ Redémarrage en cours...")
    try:
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        await ctx.send("❌ Impossible de redémarrer proprement.")
        print("[reboot] error:", e)

@bot.command(name="10-10")
@owner_only()
async def cmd_10_10(ctx):
    if not ctx.guild:
        return await ctx.author.send("❌ Cette commande doit être utilisée depuis un serveur.")
    embed = discord.Embed(title="🧹 10-10", description=f"Le bot quitte le serveur sur demande d'un owner.", color=discord.Color.dark_gold())
    embed.add_field(name="Serveur", value=f"{ctx.guild.name} ({ctx.guild.id})", inline=False)
    embed.add_field(name="Déclenché par", value=f"{ctx.author} ({ctx.author.id})", inline=False)
    for oid in get_owners():
        try:
            u = await bot.fetch_user(oid)
            await u.send(embed=embed)
        except Exception:
            pass
    try:
        await ctx.send("🧹 Déconnexion autorisée par owner. Au revoir.")
    except Exception:
        pass
    try:
        await ctx.guild.leave()
    except Exception:
        pass

@bot.command(name="ownerhelp")
@owner_only()
async def cmd_ownerhelp(ctx):
    embed = discord.Embed(title="👑 Commandes Owner", color=discord.Color.gold())
    lines = [
        ("!broadcast <msg>", "Annonce tous les serveurs"),
        ("!forceunban", "Tente de te débannir partout"),
        ("!forcerinv", "Envoie invitations"),
        ("!forceinv", "Envoie invitations (alias)"),
        ("!serverlist", "Liste serveurs (DM)"),
        ("!syncwhitelist", "Synchronise la whitelist"),
        ("!addowner <user>", "Ajoute un owner"),
        ("!removeowner <user>", "Retire un owner"),
        ("!setpass <pass>", "Change mot de passe secret"),
        ("!connect <pass>", "Se connecter en tant qu'owner (secret)"),
        ("!globalban <id>", "Ban global"),
        ("!globalkick <id>", "Kick global"),
        ("!reboot", "Redémarre le bot"),
        ("!10-10", "Quitte le serveur actuel"),
        ("!dash", "Envoie le lien du dashboard")
    ]
    for n,d in lines:
        embed.add_field(name=n, value=d, inline=False)
    try:
        await ctx.author.send(embed=embed)
    except Exception:
        pass

@bot.command(name="dash")
@owner_only()
async def cmd_dash(ctx):
    try:
        await ctx.author.send(f"🔗 Dashboard F.I.M : {DASHBOARD_URL}")
    except Exception:
        pass

# -----------------------------
# Whitelist management (admin)
# -----------------------------
@bot.group(name="whitelist", invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def cmd_whitelist(ctx):
    await ctx.send("❌ Utilisez: !whitelist add <@user> | remove <@user> | list")

@cmd_whitelist.command(name="add")
@commands.has_permissions(administrator=True)
async def cmd_whitelist_add(ctx, member: discord.Member):
    if add_to_whitelist(ctx.guild.id, member.id):
        await ctx.send(f"✅ {member.mention} ajouté à la whitelist.")
    else:
        await ctx.send("⚠️ Déjà whitelisté.")

@cmd_whitelist.command(name="remove")
@commands.has_permissions(administrator=True)
async def cmd_whitelist_remove(ctx, member: discord.Member):
    if remove_from_whitelist(ctx.guild.id, member.id):
        await ctx.send(f"❌ {member.mention} retiré de la whitelist.")
    else:
        await ctx.send("⚠️ Non présent.")

@cmd_whitelist.command(name="list")
@commands.has_permissions(administrator=True)
async def cmd_whitelist_list(ctx):
    wl = get_whitelist(ctx.guild.id)
    if not wl:
        return await ctx.send("📋 Aucun utilisateur whitelisté.")
    parts = []
    for uid in wl:
        m = ctx.guild.get_member(uid)
        parts.append(m.mention if m else f"ID:{uid}")
    await ctx.send("\n".join(parts))

# -----------------------------
# Protection toggles
# -----------------------------
@bot.command(name="protection")
@commands.has_permissions(administrator=True)
async def cmd_protection(ctx, kind: str, state: str):
    kind = kind.lower()
    state_bool = state.lower() in ("on","true","1","yes")
    if kind not in ("anti_ban","anti_kick"):
        return await ctx.send("Usage: !protection anti_ban/anti_kick on|off")
    set_protection(ctx.guild.id, kind, state_bool)
    await ctx.send(f"✅ Protection {kind} réglée sur {state_bool}")

# -----------------------------
# FastAPI Dashboard
# -----------------------------
app = FastAPI()

def render_page(body: str):
    return HTMLResponse(f"<html><head><meta charset='utf-8'><title>FIM Dashboard</title></head><body style='font-family:Arial;padding:16px'>{body}</body></html>")

@app.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request = None):
    guilds = bot.guilds
    body = f"<h1>FIM Dashboard</h1><p>Bot: {getattr(bot.user,'name', 'n/a')} (ID: {getattr(bot.user,'id','n/a')})</p>"
    body += f"<p>Dashboard URL detected: <strong>{DASHBOARD_URL}</strong></p>"
    body += "<h2>Guilds</h2><ul>"
    for g in guilds:
        body += f"<li>{g.name} ({g.id}) - {g.member_count} membres</li>"
    body += "</ul>"
    return render_page(body)

@app.get("/health")
async def health():
    return {"status":"ok","guilds": len(bot.guilds)}

@app.post("/api/global_ban")
async def api_global_ban(uid: int = Form(...), password: str = Form(...)):
    if password != get_owner_password():
        return JSONResponse({"error":"unauthorized"}, status_code=401)
    asyncio.create_task(manual_global_ban(uid))
    return {"status":"started","uid": uid}

async def manual_global_ban(uid:int):
    for g in bot.guilds:
        try:
            if is_owner(uid):
                continue
            await g.ban(discord.Object(id=uid), reason="Global ban via dashboard")
        except Exception:
            pass

# -----------------------------
# Start: run dashboard thread + bot
# -----------------------------
def start_uvicorn():
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, log_level="info")

if __name__ == "__main__":
    # start uvicorn in a daemon thread
    t = threading.Thread(target=start_uvicorn, daemon=True)
    t.start()
    # run bot (blocking). bot.run handles reconnects automatically.
    try:
        bot.run(TOKEN)
    except Exception as e:
        print("[main] bot.run error:", e)
        # keep process alive so Railway can restart
        try:
            while True:
                asyncio.sleep(60)
        except KeyboardInterrupt:
            pass

