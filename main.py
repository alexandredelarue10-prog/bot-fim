import discord
from discord.ext import commands
import os
import json
from datetime import datetime

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

CONFIG_FILE = "config.json"

def load_config():
    """Charge la configuration depuis le fichier JSON"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_config(config):
    """Sauvegarde la configuration dans le fichier JSON"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

def get_log_channel(guild_id):
    """Récupère le canal de logs configuré pour un serveur"""
    config = load_config()
    return config.get(str(guild_id), {}).get("log_channel")

@bot.event
async def on_ready():
    print(f"✅ {bot.user} est connecté et prêt à organiser le serveur !")

@bot.command()
async def ping(ctx):
    """Commande de test pour vérifier que le bot fonctionne"""
    await ctx.send("🏓 Pong ! Le bot F.I.M est opérationnel.")

@bot.command()
async def help(ctx):
    """Affiche la liste de toutes les commandes disponibles"""
    embed = discord.Embed(
        title="📋 Commandes du Bot F.I.M",
        description="Voici la liste de toutes les commandes disponibles :",
        color=discord.Color.from_rgb(153, 0, 0)
    )
    
    embed.add_field(
        name="🏓 !ping",
        value="Vérifie que le bot fonctionne correctement",
        inline=False
    )
    
    embed.add_field(
        name="📨 !say <message>",
        value="Envoie un message avec le bot dans le canal actuel\n*Nécessite : Gérer les messages*",
        inline=False
    )
    
    embed.add_field(
        name="📤 !send #canal <message>",
        value="Envoie un message avec le bot dans un canal spécifique\n*Nécessite : Gérer les messages*",
        inline=False
    )
    
    embed.add_field(
        name="📰 !embed <titre> <description>",
        value="Envoie un message embed formaté avec le bot\n*Nécessite : Gérer les messages*",
        inline=False
    )
    
    embed.add_field(
        name="📊 !setlogs #canal",
        value="Configure le canal où les logs du serveur seront envoyés\n*Nécessite : Administrateur*",
        inline=False
    )
    
    embed.add_field(
        name="⚠️ !setup_fim",
        value="**NE PAS UTILISER** - Configuration initiale du serveur (déjà effectuée)\n*Nécessite : Administrateur*",
        inline=False
    )
    
    embed.set_footer(text="Bot F.I.M - Préfixe : !")
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def say(ctx, *, message):
    """Envoie un message avec le bot dans le canal actuel
    Usage: !say <votre message>
    """
    await ctx.message.delete()
    await ctx.send(message)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def send(ctx, channel: discord.TextChannel, *, message):
    """Envoie un message avec le bot dans un canal spécifique
    Usage: !send #canal <votre message>
    """
    await ctx.message.delete()
    await channel.send(message)
    await ctx.send(f"✅ Message envoyé dans {channel.mention}", delete_after=3)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def embed(ctx, title, *, description):
    """Envoie un message embed avec le bot
    Usage: !embed <titre> <description>
    """
    await ctx.message.delete()
    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.from_rgb(153, 0, 0)
    )
    embed.set_footer(text=f"Message envoyé par {ctx.author.name}")
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def setlogs(ctx, channel: discord.TextChannel):
    """Configure le canal de logs pour le serveur
    Usage: !setlogs #canal
    """
    config = load_config()
    guild_id = str(ctx.guild.id)
    
    if guild_id not in config:
        config[guild_id] = {}
    
    config[guild_id]["log_channel"] = channel.id
    save_config(config)
    
    embed = discord.Embed(
        title="✅ Canal de logs configuré",
        description=f"Les logs du serveur seront maintenant envoyés dans {channel.mention}",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)
    
    log_embed = discord.Embed(
        title="📊 Système de logs activé",
        description="Ce canal recevra maintenant les logs du serveur F.I.M",
        color=discord.Color.from_rgb(153, 0, 0)
    )
    log_embed.add_field(name="Événements suivis", value="• Membres rejoignant/quittant\n• Messages supprimés\n• Membres bannis/débannis\n• Modifications de rôles", inline=False)
    await channel.send(embed=log_embed)

@bot.event
async def on_member_join(member):
    """Envoie un log quand un membre rejoint le serveur"""
    log_channel_id = get_log_channel(member.guild.id)
    if log_channel_id:
        channel = member.guild.get_channel(log_channel_id)
        if channel:
            embed = discord.Embed(
                title="👋 Nouveau membre",
                description=f"{member.mention} a rejoint le serveur",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Utilisateur", value=f"{member.name}#{member.discriminator}", inline=True)
            embed.add_field(name="ID", value=member.id, inline=True)
            embed.set_thumbnail(url=member.display_avatar.url)
            await channel.send(embed=embed)

@bot.event
async def on_member_remove(member):
    """Envoie un log quand un membre quitte le serveur"""
    log_channel_id = get_log_channel(member.guild.id)
    if log_channel_id:
        channel = member.guild.get_channel(log_channel_id)
        if channel:
            embed = discord.Embed(
                title="👋 Membre parti",
                description=f"{member.mention} a quitté le serveur",
                color=discord.Color.orange(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Utilisateur", value=f"{member.name}#{member.discriminator}", inline=True)
            embed.add_field(name="ID", value=member.id, inline=True)
            embed.set_thumbnail(url=member.display_avatar.url)
            await channel.send(embed=embed)

@bot.event
async def on_message_delete(message):
    """Envoie un log quand un message est supprimé"""
    if message.author.bot:
        return
    
    log_channel_id = get_log_channel(message.guild.id)
    if log_channel_id:
        channel = message.guild.get_channel(log_channel_id)
        if channel:
            embed = discord.Embed(
                title="🗑️ Message supprimé",
                color=discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Auteur", value=f"{message.author.mention}", inline=True)
            embed.add_field(name="Canal", value=f"{message.channel.mention}", inline=True)
            if message.content:
                content = message.content[:1024] if len(message.content) > 1024 else message.content
                embed.add_field(name="Contenu", value=content, inline=False)
            await channel.send(embed=embed)

@bot.event
async def on_member_ban(guild, user):
    """Envoie un log quand un membre est banni"""
    log_channel_id = get_log_channel(guild.id)
    if log_channel_id:
        channel = guild.get_channel(log_channel_id)
        if channel:
            embed = discord.Embed(
                title="🔨 Membre banni",
                description=f"{user.mention} a été banni du serveur",
                color=discord.Color.dark_red(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Utilisateur", value=f"{user.name}#{user.discriminator}", inline=True)
            embed.add_field(name="ID", value=user.id, inline=True)
            await channel.send(embed=embed)

@bot.event
async def on_member_unban(guild, user):
    """Envoie un log quand un membre est débanni"""
    log_channel_id = get_log_channel(guild.id)
    if log_channel_id:
        channel = guild.get_channel(log_channel_id)
        if channel:
            embed = discord.Embed(
                title="✅ Membre débanni",
                description=f"{user.mention} a été débanni du serveur",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Utilisateur", value=f"{user.name}#{user.discriminator}", inline=True)
            embed.add_field(name="ID", value=user.id, inline=True)
            await channel.send(embed=embed)

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
