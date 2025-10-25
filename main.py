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
        ("--Direction F.I.M--", discord.Color.from_rgb(153, 0, 0)),
        ("Directeur de la FIM", discord.Color.from_rgb(153, 0, 0)),
        ("Chef d'état-major", discord.Color.from_rgb(153, 0, 0)),
        ("Commandant en chef des opérations", discord.Color.from_rgb(153, 0, 0)),
        ("--Officiers supérieurs--", discord.Color.from_rgb(153, 0, 0)),
        ("Lieutenant général", discord.Color.from_rgb(153, 0, 0)),
        ("Colonel", discord.Color.from_rgb(153, 0, 0)),
        ("Lieutenant-colonel", discord.Color.from_rgb(153, 0, 0)),
        ("Major", discord.Color.from_rgb(153, 0, 0)),
        ("--Commandements--", discord.Color.from_rgb(153, 0, 0)),
        ("Commandant", discord.Color.from_rgb(153, 0, 0)),
        ("Capitaine Principal", discord.Color.from_rgb(153, 0, 0)),
        ("Capitaine", discord.Color.from_rgb(153, 0, 0)),
        ("Lieutenant", discord.Color.from_rgb(153, 0, 0)),
        ("Sous-Lieutenant", discord.Color.from_rgb(153, 0, 0)),
        ("--Sous-officiers--", discord.Color.from_rgb(230, 126, 34)),
        ("Sergent-major", discord.Color.from_rgb(230, 126, 34)),
        ("Sergent-chef", discord.Color.from_rgb(230, 126, 34)),
        ("Sergent", discord.Color.from_rgb(230, 126, 34)),
        ("Caporal-chef", discord.Color.from_rgb(230, 126, 34)),
        ("Caporal", discord.Color.from_rgb(230, 126, 34)),
        ("--Agents opérationnels--", discord.Color.from_rgb(241, 196, 15)),
        ("Agent", discord.Color.from_rgb(230, 126, 34)),
        ("Spécialiste", discord.Color.from_rgb(230, 126, 34)),
        ("--Recrues--", discord.Color.from_rgb(52, 152, 219)),
        ("Recrue", discord.Color.from_rgb(52, 152, 219))
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
