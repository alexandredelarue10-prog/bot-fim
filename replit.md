# Discord Bot F.I.M

## Overview
A Discord bot built with Python and discord.py that responds to commands and events. The bot uses a command prefix system (!) and provides basic functionality for server interaction.

## Recent Changes
- **2025-10-25**: Added whitelist system to control who can use bot commands
- **2025-10-25**: Added comprehensive logging system with !setlogs command
- **2025-10-25**: Added message sending commands (!say, !send, !embed)
- **2025-10-25**: Added custom !help command with all bot commands
- **2025-10-25**: Updated roles to match official F.I.M template (26 hierarchical roles)
- **2025-10-25**: Cleaned up main.py - removed duplicate code, combined all features into single file
- **2025-10-25**: Initial project setup with main.py and setup_fim command

## Project Architecture
- **main.py**: Main bot file containing Discord client setup, event handlers, and commands
- **Language**: Python 3.11
- **Framework**: discord.py 2.6.4
- **Command Prefix**: `!`

## Current Features
- Bot connection with full intents and proper error handling
- **!help** - Display all available commands with descriptions
- **!ping** - Test command to verify bot functionality
- **Whitelist System** - Control who can use bot commands
  - **!whitelist add @user** - Add a user to the whitelist (Admin only)
  - **!whitelist remove @user** - Remove a user from the whitelist (Admin only)
  - **!whitelist list** - View all whitelisted users (Admin only)
  - Administrators always have access regardless of whitelist
- **!say <message>** - Send a message as the bot in the current channel (requires Whitelist or Admin)
- **!send #channel <message>** - Send a message as the bot in a specific channel (requires Whitelist or Admin)
- **!embed <title> <description>** - Send a formatted embed message as the bot (requires Whitelist or Admin)
- **!setlogs #channel** - Configure the logging channel for server events (requires Administrator permission)
  - Tracks member joins/leaves
  - Logs deleted messages
  - Records bans/unbans
  - Saves configuration in config.json
- **!setup_fim** - ⚠️ DO NOT USE - Administrator command for initial server setup (already completed)
  - Creates 26 hierarchical roles matching the official F.I.M template:
    - Direction F.I.M (Directeur, Chef d'état-major, etc.)
    - Officiers supérieurs (Lieutenant général, Colonel, Lieutenant-colonel, Major)
    - Commandements (Commandant, Capitaine Principal, Capitaine, Lieutenant, Sous-Lieutenant)
    - Sous-officiers (Sergent-major, Sergent-chef, Sergent, Caporal-chef, Caporal)
    - Agents opérationnels (Agent, Spécialiste)
    - Recrues (Recrue)
  - Creates 5 categories with organized channels
  - Includes permission checks and error handling

## Environment Variables
- **DISCORD_TOKEN**: Discord bot token (required) - Add this in the Secrets tab

## How to Get a Discord Bot Token
1. Go to https://discord.com/developers/applications
2. Create a new application or select an existing one
3. Navigate to the "Bot" section
4. Copy the bot token
5. Add the token to Replit Secrets as `DISCORD_TOKEN`

## Bot Permissions
The bot currently uses `Intents.all()` which requires:
- Privileged Gateway Intents enabled in Discord Developer Portal
- Server Members Intent
- Message Content Intent

## User Preferences
None documented yet.
