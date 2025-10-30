import discord
from discord.ext import commands
import os
import json
from datetime import datetime
import psycopg2

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

def whitelist_check():
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        if is_whitelisted(ctx.guild.id, ctx.author.id):
            return True
        await ctx.send("❌ Vous n'êtes pas autorisé à utiliser cette commande. Contactez un administrateur.")
        return False
    return commands.check(predicate)

# --- EVENTS ---
@bot.event
async def on_ready():
    print(f"✅ {bot.user} est connecté et prêt à organiser le serveur !")

# --- COMMANDS ---
@bot.command()
async def ping(ctx):
    await ctx.send("🏓 Pong ! Le bot F.I.M est opérationnel.")

@bot.command()
async def help(ctx):
    embed = discord.Embed(title="📋 Commandes du Bot F.I.M",
                          description="Voici la liste de toutes les commandes disponibles :",
                          color=discord.Color.from_rgb(153, 0, 0))
    embed.add_field(name="🏓 !ping", value="Vérifie que le bot fonctionne correctement", inline=False)
    embed.add_field(name="📨 !say <message>", value="Envoie un message avec le bot dans le canal actuel\n*Nécessite : Whitelist ou Administrateur*", inline=False)
    embed.add_field(name="📤 !send #canal <message>", value="Envoie un message avec le bot dans un canal spécifique\n*Nécessite : Whitelist ou Administrateur*", inline=False)
    embed.add_field(name="📰 !embed <titre> <description>", value="Envoie un message embed formaté avec le bot\n*Nécessite : Whitelist ou Administrateur*", inline=False)
    embed.add_field(name="📊 !setlogs #canal", value="Configure le canal où les logs du serveur seront envoyés\n*Nécessite : Administrateur*", inline=False)
    embed.add_field(name="✅ !whitelist add @utilisateur", value="Ajoute un utilisateur à la whitelist du bot\n*Nécessite : Administrateur*", inline=False)
    embed.add_field(name="❌ !whitelist remove @utilisateur", value="Retire un utilisateur de la whitelist du bot\n*Nécessite : Administrateur*", inline=False)
    embed.add_field(name="📋 !whitelist list", value="Affiche la liste des utilisateurs whitelistés\n*Nécessite : Administrateur*", inline=False)
    embed.add_field(name="⚠️ !setup_fim", value="**NE PAS UTILISER** - Configuration initiale du serveur (déjà effectuée)\n*Nécessite : Administrateur*", inline=False)
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

# --- AUTO-RESTART + BOT RUN ---
while True:
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"❌ Bot crash, redémarrage automatique: {e}")