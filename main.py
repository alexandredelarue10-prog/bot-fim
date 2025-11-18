# main.py - FIM Manager with BanSync + Control Panel (Flask)
import os
import sys
import json
import sqlite3
import asyncio
import threading
from datetime import datetime
from typing import Optional

import discord
from discord.ext import commands
from flask import Flask, jsonify, request, render_template_string, redirect

# -----------------------------
# CONFIG
# -----------------------------
TOKEN = os.getenv("DISCORD_TOKEN")
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")  # optional, used to build invite link
PORT = int(os.getenv("PORT", "5000"))

CONFIG_FILE = "config.json"
OWNER_FILE = "owner_data.json"
BANS_DB = "bans.db"
DEFAULT_OWNER_ID = 489113166429683713  # your owner ID

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.bans = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# -----------------------------
# JSON helpers (config + whitelist + guild settings)
# -----------------------------
def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# initialize config skeleton
def ensure_config():
    cfg = load_json(CONFIG_FILE, {})
    changed = False
    if "guilds" not in cfg:
        cfg["guilds"] = {}
        changed = True
    if changed:
        save_json(CONFIG_FILE, cfg)
    return cfg

ensure_config()

def get_config():
    return load_json(CONFIG_FILE, {})

def save_config(cfg):
    save_json(CONFIG_FILE, cfg)

def get_guild_cfg(gid):
    cfg = get_config()
    return cfg.get(str(gid), {})

def set_guild_cfg(gid, key, val):
    cfg = get_config()
    gid_s = str(gid)
    cfg.setdefault("guilds", {})
    cfg["guilds"].setdefault(gid_s, {})
    cfg["guilds"][gid_s][key] = val
    save_config(cfg)

def get_whitelist(gid):
    gcfg = get_guild_cfg(gid)
    return gcfg.get("whitelist", [])

def add_to_whitelist(gid, uid):
    cfg = get_config()
    gid_s = str(gid)
    cfg.setdefault("guilds", {})
    cfg["guilds"].setdefault(gid_s, {})
    cfg["guilds"][gid_s].setdefault("whitelist", [])
    if uid not in cfg["guilds"][gid_s]["whitelist"]:
        cfg["guilds"][gid_s]["whitelist"].append(uid)
        save_config(cfg)
        return True
    return False

def remove_from_whitelist(gid, uid):
    cfg = get_config()
    gid_s = str(gid)
    if gid_s in cfg.get("guilds", {}) and "whitelist" in cfg["guilds"][gid_s]:
        if uid in cfg["guilds"][gid_s]["whitelist"]:
            cfg["guilds"][gid_s]["whitelist"].remove(uid)
            save_config(cfg)
            return True
    return False

def is_whitelisted(gid, uid):
    return uid in get_whitelist(gid)

def set_sync_enabled(gid, enabled: bool):
    set_guild_cfg(gid, "bansync_enabled", bool(enabled))

def get_sync_enabled(gid) -> bool:
    return bool(get_guild_cfg(gid).get("bansync_enabled", True))

def set_log_channel(gid, channel_id: Optional[int]):
    set_guild_cfg(gid, "log_channel", channel_id)

def get_log_channel(gid) -> Optional[int]:
    return get_guild_cfg(gid).get("log_channel")

# -----------------------------
# Owner data
# -----------------------------
def ensure_owner_data():
    data = load_json(OWNER_FILE, {})
    changed = False
    if "owners" not in data:
        data["owners"] = [DEFAULT_OWNER_ID]
        changed = True
    if "password" not in data:
        data["password"] = "trolleur2010"
        changed = True
    if changed:
        save_json(OWNER_FILE, data)
    return data

ensure_owner_data()

def get_owners():
    return ensure_owner_data().get("owners", [DEFAULT_OWNER_ID])

def is_owner(uid):
    return uid in get_owners()

def add_owner(uid):
    data = ensure_owner_data()
    if uid not in data["owners"]:
        data["owners"].append(uid)
        save_json(OWNER_FILE, data)
        return True
    return False

def get_owner_password():
    return ensure_owner_data().get("password", "trolleur2010")

def set_owner_password(pw):
    data = ensure_owner_data()
    data["password"] = pw
    save_json(OWNER_FILE, data)

# -----------------------------
# SQLite Bans DB (simple)
# -----------------------------
def init_db():
    conn = sqlite3.connect(BANS_DB)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS bans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        reason TEXT,
        moderator TEXT,
        source_guild INTEGER,
        timestamp TEXT,
        propagated INTEGER DEFAULT 0
    )
    """)
    conn.commit()
    conn.close()

init_db()

def record_ban(user_id: int, reason: str, moderator: str, source_guild: int, propagated: int=0):
    conn = sqlite3.connect(BANS_DB)
    cur = conn.cursor()
    cur.execute("INSERT INTO bans (user_id, reason, moderator, source_guild, timestamp, propagated) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, reason, moderator, source_guild, datetime.utcnow().isoformat(), propagated))
    conn.commit()
    conn.close()

def list_bans():
    conn = sqlite3.connect(BANS_DB)
    cur = conn.cursor()
    cur.execute("SELECT id, user_id, reason, moderator, source_guild, timestamp, propagated FROM bans ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return rows

def clear_bans():
    conn = sqlite3.connect(BANS_DB)
    cur = conn.cursor()
    cur.execute("DELETE FROM bans")
    conn.commit()
    conn.close()

# -----------------------------
# UTIL / INVITE
# -----------------------------
def build_oauth_link(client_id=None):
    cid = client_id or CLIENT_ID
    if not cid:
        return "Invite link not available (set DISCORD_CLIENT_ID)"
    return f"https://discord.com/oauth2/authorize?client_id={cid}&scope=bot&permissions=8"

async def notify_owners(message: str):
    for oid in get_owners():
        try:
            u = await bot.fetch_user(int(oid))
            try:
                await u.send(message)
            except Exception:
                pass
        except Exception:
            pass

# -----------------------------
# EVENTS: on_ready / on_guild_remove / ban detection
# -----------------------------
@bot.event
async def on_ready():
    ensure_owner_data()
    init_db()
    print(f"[READY] {bot.user} ({bot.user.id}) - guilds: {len(bot.guilds)}")
    # ensure client id fallback
    global CLIENT_ID
    if not CLIENT_ID:
        try:
            CLIENT_ID = str(bot.user.id)
        except Exception:
            CLIENT_ID = None

@bot.event
async def on_guild_remove(guild):
    # notify owners with invite link
    try:
        invite_link = build_oauth_link(CLIENT_ID)
        await notify_owners(f"⚠️ Le bot a été retiré du serveur **{guild.name}** (ID: {guild.id}). Réinvite : {invite_link}")
    except Exception as e:
        print(f"[on_guild_remove] {e}")

@bot.event
async def on_member_ban(guild, user):
    # when someone is banned, if sync enabled record and propagate
    try:
        # we only process if we can check audit logs (best-effort)
        entry = None
        try:
            async for e in guild.audit_logs(limit=6, action=discord.AuditLogAction.ban):
                if getattr(e.target, "id", None) == user.id:
                    entry = e
                    break
        except Exception:
            entry = None

        moderator = str(getattr(entry, "user", "unknown")) if entry else "unknown"
        reason = getattr(entry, "reason", "Non spécifiée") if entry else "Non spécifiée"
        record_ban(user.id, reason, moderator, guild.id, propagated=0)

        # if this guild has bansync enabled, propagate to other guilds
        if get_sync_enabled(guild.id):
            # schedule propagation task
            bot.loop.create_task(propagate_ban_to_all(user.id, reason, moderator, source_guild=guild.id))
    except Exception as e:
        print(f"[on_member_ban] erreur: {e}")

# -----------------------------
# BAN PROPAGATION
# -----------------------------
async def propagate_ban_to_all(user_id: int, reason: str, moderator: str, source_guild: int):
    # propagate ban to all guilds where bot has ban permissions, except the source guild
    count = 0
    for g in bot.guilds:
        try:
            if g.id == source_guild:
                continue
            if not get_sync_enabled(g.id):
                continue
            # skip if user is owner
            if is_owner(user_id):
                continue
            # try to ban (best-effort)
            try:
                await g.ban(discord.Object(id=user_id), reason=f"BanSync: {reason} (origin {source_guild})")
                count += 1
            except discord.Forbidden:
                # cannot ban in this guild
                pass
            except Exception:
                pass
        except Exception:
            pass
    # record propagation as separate entry
    if count > 0:
        record_ban(user_id, reason, f"propagated_from_{source_guild}", source_guild, propagated=1)
    # notify owners
    await notify_owners(f"🔁 BanSync: utilisateur {user_id} propagé sur {count} serveur(s) (origine {source_guild}).")

# -----------------------------
# COMMAND HELPERS / DECORATORS
# -----------------------------
def whitelist_check():
    async def predicate(ctx):
        try:
            if is_owner(ctx.author.id):
                return True
            if ctx.author.guild_permissions.administrator:
                return True
            if is_whitelisted(ctx.guild.id, ctx.author.id):
                return True
        except Exception:
            pass
        try:
            await ctx.message.delete()
        except Exception:
            pass
        return False
    return commands.check(predicate)

def owner_only_check():
    async def predicate(ctx):
        return is_owner(ctx.author.id)
    return commands.check(predicate)

# -----------------------------
# COMMANDS: public / admin / owner
# -----------------------------
# ping
@bot.command(name="ping")
async def cmd_ping(ctx):
    await ctx.send("🏓 Pong ! Le bot F.I.M est opérationnel.")

# help (public short)
@bot.command(name="help")
async def cmd_help(ctx):
    embed = discord.Embed(title="📋 Commandes publiques", color=discord.Color.blurple())
    embed.add_field(name="!ping", value="Test", inline=False)
    embed.add_field(name="!say <msg>", value="Envoyer message (whitelist/admin)", inline=False)
    embed.add_field(name="!send #canal <msg>", value="Envoyer dans canal (whitelist/admin)", inline=False)
    embed.add_field(name="!aide_owner", value="Liste des commandes owner (owner only)", inline=False)
    await ctx.send(embed=embed)

# say/send/embed
@bot.command(name="say")
@whitelist_check()
async def cmd_say(ctx, *, message: str):
    try: await ctx.message.delete()
    except: pass
    await ctx.send(message)

@bot.command(name="send")
@whitelist_check()
async def cmd_send(ctx, channel: discord.TextChannel, *, message: str):
    try: await ctx.message.delete()
    except: pass
    await channel.send(message)
    try: await ctx.send(f"✅ Message envoyé dans {channel.mention}", delete_after=4)
    except: pass

@bot.command(name="embed")
@whitelist_check()
async def cmd_embed(ctx, title: str, *, description: str):
    try: await ctx.message.delete()
    except: pass
    em = discord.Embed(title=title, description=description, color=discord.Color.red())
    em.set_footer(text=f"Envoyé par {ctx.author}")
    await ctx.send(embed=em)

# role management
@bot.command(name="addrole")
@whitelist_check()
async def cmd_addrole(ctx, member: discord.Member, role: discord.Role):
    try:
        await member.add_roles(role)
        await ctx.send(f"✅ Rôle {role.name} ajouté à {member.mention}")
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission.")
    except Exception as e:
        await ctx.send("❌ Erreur.")
        print(f"[addrole] {e}")

@bot.command(name="removerole")
@whitelist_check()
async def cmd_removerole(ctx, member: discord.Member, role: discord.Role):
    try:
        await member.remove_roles(role)
        await ctx.send(f"✅ Rôle {role.name} retiré de {member.mention}")
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission.")
    except Exception as e:
        await ctx.send("❌ Erreur.")
        print(f"[removerole] {e}")

# whitelist group
@bot.group(name="whitelist", invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def grp_whitelist(ctx):
    await ctx.send("❌ Utilisez: !whitelist add/remove/list")

@grp_whitelist.command(name="add")
@commands.has_permissions(administrator=True)
async def grp_whitelist_add(ctx, member: discord.Member):
    if add_to_whitelist(ctx.guild.id, member.id):
        await ctx.send(f"✅ {member.mention} ajouté.")
    else:
        await ctx.send("⚠️ Déjà dans la whitelist.")

@grp_whitelist.command(name="remove")
@commands.has_permissions(administrator=True)
async def grp_whitelist_remove(ctx, member: discord.Member):
    if remove_from_whitelist(ctx.guild.id, member.id):
        await ctx.send(f"✅ {member.mention} retiré.")
    else:
        await ctx.send("⚠️ Non trouvé.")

@grp_whitelist.command(name="list")
@commands.has_permissions(administrator=True)
async def grp_whitelist_list(ctx):
    wl = get_whitelist(ctx.guild.id)
    if not wl:
        return await ctx.send("📋 Pas de whitelist.")
    parts = []
    for uid in wl:
        m = ctx.guild.get_member(uid)
        parts.append(m.mention if m else f"ID:{uid}")
    await ctx.send("\n".join(parts))

# setlogs
@bot.command(name="setlogs")
@commands.has_permissions(administrator=True)
async def cmd_setlogs(ctx, channel: discord.TextChannel):
    set_log_channel(ctx.guild.id, channel.id)
    await ctx.send(f"✅ Canal de logs défini sur {channel.mention}")

# local mod: ban/kick
@bot.command(name="ban")
@whitelist_check()
async def cmd_ban(ctx, member: discord.Member, *, reason: str = "Non spécifiée"):
    if member.id == bot.user.id or is_owner(member.id):
        return await ctx.send("❌ Action impossible.")
    try:
        await ctx.guild.ban(member, reason=f"{ctx.author} | {reason}")
        await ctx.send(f"✅ {member.mention} banni. (raison: {reason})")
        # log
        log_id = get_log_channel(ctx.guild.id)
        if log_id:
            ch = ctx.guild.get_channel(log_id)
            if ch:
                try:
                    em = discord.Embed(title="👮 Banni", color=discord.Color.red())
                    em.add_field(name="Membre", value=f"{member} ({member.id})", inline=False)
                    em.add_field(name="Par", value=f"{ctx.author} ({ctx.author.id})", inline=False)
                    em.add_field(name="Raison", value=reason, inline=False)
                    em.set_footer(text=str(datetime.utcnow()))
                    await ch.send(embed=em)
                except: pass
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de bannir.")
    except Exception as e:
        print(f"[cmd_ban] {e}")
        await ctx.send("❌ Erreur lors du ban.")

@bot.command(name="kick")
@whitelist_check()
async def cmd_kick(ctx, member: discord.Member, *, reason: str = "Non spécifiée"):
    if member.id == bot.user.id or is_owner(member.id):
        return await ctx.send("❌ Action impossible.")
    try:
        await ctx.guild.kick(member, reason=f"{ctx.author} | {reason}")
        await ctx.send(f"✅ {member.mention} kické. (raison: {reason})")
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de kicker.")
    except Exception as e:
        print(f"[cmd_kick] {e}")
        await ctx.send("❌ Erreur lors du kick.")

# -----------------------------
# OWNER / GLOBAL COMMANDS (unique names)
# -----------------------------
@bot.command(name="broadcast")
@commands.check(owner_only_check())
async def cmd_broadcast(ctx, *, message: str):
    count = 0
    for g in bot.guilds:
        try:
            if g.text_channels:
                await g.text_channels[0].send(f"📢 **Annonce Owner :** {message}")
                count += 1
        except: pass
    try: await ctx.author.send(f"✅ Broadcast envoyé sur {count} serveurs.")
    except: pass

@bot.command(name="globalban")
@commands.check(owner_only_check())
async def cmd_globalban(ctx, user: str):
    try:
        uid = int(user.strip("<@!>"))
    except:
        try:
            uid = int(user)
        except:
            return await ctx.author.send("⚠️ ID invalide.")
    total = 0
    for g in bot.guilds:
        try:
            await g.ban(discord.Object(id=uid), reason=f"Global ban by owner {ctx.author.id}")
            total += 1
        except: pass
    record_ban(uid, "globalban_by_owner", str(ctx.author), 0, propagated=1)
    try: await ctx.author.send(f"✅ Global ban tenté sur {total} serveurs.")
    except: pass

@bot.command(name="globalkick")
@commands.check(owner_only_check())
async def cmd_globalkick(ctx, user: str):
    try:
        uid = int(user.strip("<@!>"))
    except:
        try:
            uid = int(user)
        except:
            return await ctx.author.send("⚠️ ID invalide.")
    total = 0
    for g in bot.guilds:
        try:
            m = g.get_member(uid)
            if m:
                await g.kick(m, reason=f"Global kick by owner {ctx.author.id}")
                total += 1
        except: pass
    try: await ctx.author.send(f"✅ Global kick tenté sur {total} serveurs.")
    except: pass

@bot.command(name="serverlist")
@commands.check(owner_only_check())
async def cmd_serverlist(ctx):
    lines = [f"{g.name} ({g.id}) - {g.member_count}" for g in bot.guilds]
    try: await ctx.author.send("📋 Serveurs:\n" + "\n".join(lines))
    except: pass

@bot.command(name="syncwhitelist")
@commands.check(owner_only_check())
async def cmd_syncwhitelist(ctx):
    try:
        src = get_whitelist(ctx.guild.id)
        cfg = get_config()
        for g in bot.guilds:
            gid_s = str(g.id)
            cfg.setdefault("guilds", {})
            cfg["guilds"].setdefault(gid_s, {})
            cfg["guilds"][gid_s]["whitelist"] = src.copy()
        save_config(cfg)
        await ctx.author.send("🔁 Whitelist synchronisée sur tous les serveurs.")
    except Exception as e:
        print(f"[syncwhitelist] {e}")
        await ctx.author.send("❌ Erreur de sync.")

@bot.command(name="connect_secret")
async def cmd_connect_secret(ctx, password: str):
    try:
        if password == get_owner_password():
            added = add_owner(ctx.author.id)
            if added:
                await ctx.author.send("✅ Tu es ajouté comme owner.")
            else:
                await ctx.author.send("ℹ️ Tu es déjà owner.")
    except: pass

@bot.command(name="setpass")
@commands.check(owner_only_check())
async def cmd_setpass(ctx, *, newpass: str):
    set_owner_password(newpass)
    try: await ctx.author.send("🔒 Mot de passe mis à jour.")
    except: pass

@bot.command(name="ownerhelp")
@commands.check(owner_only_check())
async def cmd_ownerhelp(ctx):
    embed = discord.Embed(title="👑 Commandes Owner", color=discord.Color.gold())
    embed.add_field(name="!broadcast <msg>", value="Annonce tous les serveurs", inline=False)
    embed.add_field(name="!globalban <id>", value="Ban global", inline=False)
    embed.add_field(name="!globalkick <id>", value="Kick global", inline=False)
    embed.add_field(name="!serverlist", value="Liste des serveurs (DM)", inline=False)
    embed.add_field(name="!syncwhitelist", value="Sync whitelist", inline=False)
    embed.add_field(name="!setpass <pass>", value="Change mot de passe secret", inline=False)
    embed.add_field(name="!10-10", value="Quitter serveur actuel (owner only)", inline=False)
    try: await ctx.author.send(embed=embed)
    except: pass

@bot.command(name="10-10")
@commands.check(owner_only_check())
async def cmd_10_10(ctx):
    if not ctx.guild:
        try: await ctx.author.send("❌ Utiliser depuis un serveur.")
        except: pass
        return
    guild_name = ctx.guild.name
    guild_id = ctx.guild.id
    author = f"{ctx.author} ({ctx.author.id})"
    # notify owners before leaving
    try:
        for oid in get_owners():
            try:
                u = await bot.fetch_user(int(oid))
                em = discord.Embed(title="🧹 10-10 exécuté", description=f"Le bot quitte le serveur sur demande d'un owner.", color=discord.Color.dark_gold(), timestamp=datetime.utcnow())
                em.add_field(name="Serveur", value=f"{guild_name} ({guild_id})", inline=False)
                em.add_field(name="Déclenché par", value=author, inline=False)
                await u.send(embed=em)
            except: pass
    except: pass
    try:
        await ctx.send("🧹 Déconnexion autorisée par owner. Au revoir.")
    except: pass
    try:
        await ctx.guild.leave()
    except: pass

@bot.command(name="reboot_bot")
@commands.check(owner_only_check())
async def cmd_reboot(ctx):
    try: await ctx.author.send("♻️ Redémarrage...")
    except: pass
    try: os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        print(f"[reboot] {e}")
        try: await ctx.send("❌ Impossible de redémarrer proprement.")
        except: pass

# -----------------------------
# FLASK DASHBOARD
# -----------------------------
app = Flask("fim-dashboard")

# basic template strings (kept inline to stay single-file)
INDEX_HTML = """
<!doctype html>
<title>FIM Dashboard</title>
<h1>FIM Manager - Dashboard</h1>
<p>Bot: {{ bot_user }} | Guilds: {{ guild_count }}</p>
<h2>Servers</h2>
<ul>
{% for g in guilds %}
  <li>
    <strong>{{ g.name }}</strong> ({{ g.id }}) - members: {{ g.member_count }}
    <form method="post" action="/toggle_sync/{{ g.id }}" style="display:inline">
      <button type="submit">{{ 'Disable' if g.sync_enabled else 'Enable' }} BanSync</button>
    </form>
  </li>
{% endfor %}
</ul>

<h2>Bans (latest)</h2>
<table border="1" cellpadding="4">
<tr><th>ID</th><th>User ID</th><th>Reason</th><th>Moderator</th><th>Source guild</th><th>Time</th><th>Propagated</th></tr>
{% for b in bans %}
<tr>
  <td>{{ b[0] }}</td><td>{{ b[1] }}</td><td>{{ b[2] }}</td><td>{{ b[3] }}</td><td>{{ b[4] }}</td><td>{{ b[5] }}</td><td>{{ b[6] }}</td>
</tr>
{% endfor %}
</table>
<p><a href="/clear_bans">Clear bans (owner only)</a></p>
"""

@app.route("/")
def index():
    if not bot.user:
        bot_user = "bot offline"
    else:
        bot_user = f"{bot.user} ({bot.user.id})"
    guilds = []
    for g in bot.guilds:
        guilds.append({
            "id": g.id,
            "name": g.name,
            "member_count": g.member_count,
            "sync_enabled": get_sync_enabled(g.id)
        })
    bans = list_bans()[:100]
    return render_template_string(INDEX_HTML, bot_user=bot_user, guild_count=len(bot.guilds), guilds=guilds, bans=bans)

@app.route("/toggle_sync/<int:gid>", methods=["POST"])
def toggle_sync(gid):
    # only owner via simple token check? For now, we allow localhost; but require owner's token param for safety
    token = request.args.get("token")
    # token should equal owner password
    if token != get_owner_password():
        return "Unauthorized (provide ?token=OWNER_PASSWORD)", 401
    current = get_sync_enabled(gid)
    set_sync_enabled(gid, not current)
    return redirect("/")

@app.route("/clear_bans", methods=["GET"])
def web_clear_bans():
    token = request.args.get("token")
    if token != get_owner_password():
        return "Unauthorized", 401
    clear_bans()
    return redirect("/")

# run flask in background thread
def run_flask():
    app.run(host="0.0.0.0", port=PORT, threaded=True)

flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()

# -----------------------------
# START BOT
# -----------------------------
if __name__ == "__main__":
    if not TOKEN:
        print("ERROR: set DISCORD_TOKEN env var")
        sys.exit(1)
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"[main] bot crash: {e}")

