import os
import discord
from discord.ext import commands, tasks
from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import threading
import requests

# ====================
# CONFIGURATION
# ====================
TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "1234567890"))  # ton ID Discord
PREFIX = "!"
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://localhost:8080")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents)
app = FastAPI()

# ====================
# CORS Dashboard
# ====================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# ====================
# DASHBOARD ROUTES
# ====================
@app.get("/")
def index():
    return {"message": "Dashboard FIM-Manager actif !"}

@app.post("/manage_toggle_sync")
def toggle_sync(guild_id: str = Form(...), enable: bool = Form(...)):
    return {"guild_id": guild_id, "sync_enabled": enable}

# ====================
# BOT EVENTS
# ====================
@bot.event
async def on_ready():
    owner = await bot.fetch_user(OWNER_ID)
    await owner.send(f"✅ {bot.user} est connecté ! Dashboard : {DASHBOARD_URL}")
    print(f"✅ {bot.user} connecté (ID: {bot.user.id})")
    print(f"Dashboard : {DASHBOARD_URL}")

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
    await ctx.send("Commandes owner : forceinv, sync, unban, etc.")

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

# ====================
# BOT COMMANDS PUBLIQUES
# ====================
@bot.command()
async def ping(ctx):
    await ctx.send(f"Pong! {round(bot.latency*1000)}ms")

@bot.command()
async def help(ctx):
    await ctx.send("Commandes disponibles : ping, info, ownerhelp (owner only)")

# ====================
# BAN SYNC EXEMPLE
# ====================
# Ici tu peux ajouter tes fonctions pour sync bans/unbans

# ====================
# DASHBOARD THREAD
# ====================
def start_dashboard():
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

threading.Thread(target=start_dashboard, daemon=True).start()

# ====================
# RUN BOT
# ====================
bot.run(TOKEN)


