import discord
from discord.ext import commands
import os

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ {bot.user} est connecté et prêt à organiser le serveur !")

@bot.command()
async def ping(ctx):
    """Commande de test pour vérifier que le bot fonctionne"""
    await ctx.send("🏓 Pong ! Le bot F.I.M est opérationnel.")

@bot.command()
@commands.has_permissions(administrator=True)
async def setup_fim(ctx):
    """Commande pour créer la structure complète du serveur F.I.M Alpha-1"""
    guild = ctx.guild
    await ctx.send("🛠️ Création de la structure du serveur F.I.M Alpha-1 en cours...")

    categories = {
        "📋 Informations": [
            "📜 règlements",
            "📢 annonces",
            "🎖️ grades-et-fonctions"
        ],
        "💬 Communication": [
            "💬 discussion-générale",
            "🤝 présentation",
            "🎉 félicitations"
        ],
        "🧠 Commandement": [
            "📊 rapports",
            "🗺️ planification",
            "📁 dossiers-agents"
        ],
        "🎯 Opérations": [
            "🎖️ alpha-1-briefing",
            "⚔️ opérations-en-cours",
            "🕵️ missions-spéciales"
        ],
        "🔒 Administration": [
            "📁 logs-bot",
            "📑 rapports-internes"
        ]
    }

    roles = [
        ("Directeur F.I.M", discord.Color.red()),
        ("Conseiller", discord.Color.dark_red()),
        ("Colonel", discord.Color.gold()),
        ("Commandant", discord.Color.orange()),
        ("Capitaine", discord.Color.blue()),
        ("Lieutenant", discord.Color.dark_blue()),
        ("Sergent", discord.Color.green()),
        ("Caporal", discord.Color.dark_green()),
        ("Agent", discord.Color.greyple()),
        ("Recrue", discord.Color.light_grey())
    ]

    for name, color in roles:
        if not discord.utils.get(guild.roles, name=name):
            await guild.create_role(name=name, color=color)
            print(f"Rôle créé : {name}")

    for category_name, channels in categories.items():
        category = discord.utils.get(guild.categories, name=category_name)
        if not category:
            category = await guild.create_category(category_name)
        for channel_name in channels:
            if not discord.utils.get(guild.text_channels, name=channel_name):
                await guild.create_text_channel(channel_name, category=category)
                print(f"Salon créé : {channel_name}")

    await ctx.send("✅ Structure complète du serveur F.I.M Alpha-1 créée avec succès !")

@setup_fim.error
async def setup_error(ctx, error):
    """Gestion des erreurs pour la commande setup_fim"""
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("🚫 Vous devez être administrateur pour exécuter cette commande.")
    else:
        await ctx.send(f"⚠️ Une erreur est survenue : {error}")

TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN is None:
    raise ValueError("DISCORD_TOKEN n'est pas défini dans les variables d'environnement")
bot.run(TOKEN)
