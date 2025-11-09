import discord
from discord.ext import commands
import os
import json
import sys
from datetime import datetime
import psycopg2

# -------------------
# ✅ TOKEN ET DB
# -------------------
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

CONFIG_FILE = "config.json"

# -------------------
# DATABASE CONNECTION
# -------------------
def connect_db():
    return psycopg2.connect(
        host=os.getenv("PGHOST"),
        database=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        port=os.getenv("PGPORT")
    )

# -------------------
# CONFIG JSON
# -------------------
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

def get_log_channel(guild_id):
    config = load_config()
    return config.get(str(guild_id), {}).get("log_channel")

def get_whitelist(guild_id):
    config = load_config()
    return config.get(str(guild_id), {}).get("whitelist", [])

def is_whitelisted(guild_id, user_id):
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

# -------------------
# PERMISSIONS
# -------------------
OWNER_ID = 489113166429683713
owners = [OWNER_ID]  # peut être modifié via !connect
connect_password = "motdepasse"  # à modifier

def owner_check():
    async def predicate(ctx):
        return ctx.author.id in owners
    return commands.check(predicate)

def whitelist_check():
    async def predicate(ctx):
        if ctx.author.id in owners:
            return True
        if ctx.author.guild_permissions.administrator:
            return True
        if is_whitelisted(ctx.guild.id, ctx.author.id):
            return True
        await ctx.send("❌ Vous n'êtes pas autorisé à utiliser cette commande.")
        return False
    return commands.check(predicate)

# -------------------
# EVENTS
# -------------------
@bot.event
async def on_ready():
    print(f"✅ {bot.user} est connecté et prêt !")

# -------------------
# COMMANDES DE BASE
# -------------------
@bot.command()
async def ping(ctx):
    await ctx.send("🏓 Pong ! Le bot F.I.M est opérationnel.")

@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="📋 Commandes du Bot F.I.M",
        description="Voici la liste de toutes les commandes disponibles :",
        color=discord.Color.from_rgb(153, 0, 0)
    )
    embed.add_field(name="🏓 !ping", value="Vérifie que le bot fonctionne correctement", inline=False)
    embed.add_field(name="📨 !say <message>", value="Envoie un message avec le bot dans le canal actuel", inline=False)
    embed.add_field(name="📤 !send #canal <message>", value="Envoie un message avec le bot dans un canal spécifique", inline=False)
    embed.add_field(name="📰 !embed <titre> <description>", value="Envoie un message embed formaté avec le bot", inline=False)
    embed.add_field(name="📊 !setlogs #canal", value="Configure le canal où les logs du serveur seront envoyés", inline=False)
    embed.add_field(name="✅ !whitelist add @utilisateur", value="Ajoute un utilisateur à la whitelist", inline=False)
    embed.add_field(name="❌ !whitelist remove @utilisateur", value="Retire un utilisateur de la whitelist", inline=False)
    embed.add_field(name="📋 !whitelist list", value="Affiche la liste des utilisateurs whitelistés", inline=False)
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

# -------------------
# WHITELIST
# -------------------
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
    await ctx.send("\n".join(lst))

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

# -------------------
# COMMANDE SECRETE POUR OWNER
# -------------------
@bot.command()
async def connect(ctx, motdepasse):
    if motdepasse == connect_password:
        if ctx.author.id not in owners:
            owners.append(ctx.author.id)
            await ctx.send("✅ Vous êtes maintenant owner !")
        else:
            await ctx.send("⚠️ Vous êtes déjà owner.")
    else:
        pass  # pas d'erreur si mauvais mot de passe

@bot.command()
@owner_check()
async def aide(ctx):
    embed = discord.Embed(title="Commandes Owner", description="Liste des commandes secrètes Owner", color=discord.Color.gold())
    embed.add_field(name="!broadcast <message>", value="Envoie un message à tous les serveurs", inline=False)
    embed.add_field(name="!ban_global @membre", value="Bannir un membre sur tous les serveurs", inline=False)
    embed.add_field(name="!kick_global @membre", value="Exclure un membre sur tous les serveurs", inline=False)
    await ctx.send(embed=embed)

# -------------------
# BROADCAST
# -------------------
@bot.command()
@owner_check()
async def broadcast(ctx, *, message):
    for guild in bot.guilds:
        for channel in guild.text_channels:
            try:
                await channel.send(message)
                break
            except:
                continue
    await ctx.send("✅ Broadcast envoyé sur tous les serveurs.")

# -------------------
# BAN / KICK
# -------------------
async def ban_user(member, reason=None):
    try:
        await member.ban(reason=reason)
    except:
        pass

async def kick_user(member, reason=None):
    try:
        await member.kick(reason=reason)
    except:
        pass

@bot.command()
@whitelist_check()
async def ban(ctx, member: discord.Member, *, reason=None):
    if member.id in owners:
        return await ctx.send("❌ Impossible de ban un owner.")
    await ban_user(member, reason)
    await ctx.send(f"✅ {member.mention} a été banni du serveur.")

@bot.command()
@whitelist_check()
async def kick(ctx, member: discord.Member, *, reason=None):
    if member.id in owners:
        return await ctx.send("❌ Impossible de kick un owner.")
    await kick_user(member, reason)
    await ctx.send(f"✅ {member.mention} a été exclu du serveur.")

@bot.command()
@owner_check()
async def ban_global(ctx, member: discord.Member, *, reason=None):
    if member.id in owners:
        return await ctx.send("❌ Impossible de ban un owner.")
    for guild in bot.guilds:
        m = guild.get_member(member.id)
        if m:
            await ban_user(m, reason)
    await ctx.send(f"✅ {member} banni globalement.")

@bot.command()
@owner_check()
async def kick_global(ctx, member: discord.Member, *, reason=None):
    if member.id in owners:
        return await ctx.send("❌ Impossible de kick un owner.")
    for guild in bot.guilds:
        m = guild.get_member(member.id)
        if m:
            await kick_user(m, reason)
    await ctx.send(f"✅ {member} exclu globalement.")

# -------------------
# REBOOT
# -------------------
@bot.command()
@owner_check()
async def reboot(ctx):
    await ctx.send("🔄 Redémarrage en cours...")
    os.execv(sys.executable, ['python'] + sys.argv)

# -------------------
# AUTO-RESTART + BOT RUN
# -------------------
while True:
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"❌ Bot crash, redémarrage automatique: {e}")
