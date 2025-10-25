import discord
from discord.ext import commands
import os

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ {bot.user} est connecté et prêt !")

@bot.command()
async def ping(ctx):
    await ctx.send("🏓 Pong ! Le bot F.I.M est opérationnel.")

TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN is None:
    raise ValueError("DISCORD_TOKEN n'est pas défini dans les variables d'environnement")
bot.run(TOKEN)
