from fastapi import FastAPI
import uvicorn
import threading
import requests
import json
import discord
from discord.ext import commands
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 906909345072164884
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ----------------------------------------------------------
# API FASTAPI
# ----------------------------------------------------------

app = FastAPI()

# stockage local des bans synchronisés
sync_queue = []


@app.get("/")
def home():
    return {"status": "Dashboard en ligne", "sync_count": len(sync_queue)}


@app.post("/api/sync")
def receive_sync(data: dict):
    sync_queue.append(data)
    return {"status": "Sync reçue", "data": data}


# ----------------------------------------------------------
# Thread bot Discord
# ----------------------------------------------------------

def start_bot():
    @bot.event
    async def on_ready():
        print(f"[BOT] Connecté en tant que {bot.user}")

    @bot.event
    async def on_guild_available(guild):
        for item in sync_queue:
            if item["action"] == "ban":
                try:
                    user = await bot.fetch_user(item["user_id"])
                    await guild.ban(user, reason="Sync ban")
                except:
                    pass
            elif item["action"] == "unban":
                try:
                    user = await bot.fetch_user(item["user_id"])
                    await guild.unban(user)
                except:
                    pass

    bot.run(BOT_TOKEN)


threading.Thread(target=start_bot).start()

# ----------------------------------------------------------
# Lancement du dashboard
# ----------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
