# Discord Bot F.I.M

## Overview
A Discord bot built with Python and discord.py that responds to commands and events. The bot uses a command prefix system (!) and provides basic functionality for server interaction.

## Recent Changes
- **2025-10-25**: Initial project setup with main.py
- **2025-10-25**: Cleaned up main.py - removed duplicate code, combined all features into single file
- **2025-10-25**: Added setup_fim command for automated server structure creation

## Project Architecture
- **main.py**: Main bot file containing Discord client setup, event handlers, and commands
- **Language**: Python 3.11
- **Framework**: discord.py 2.6.4
- **Command Prefix**: `!`

## Current Features
- Bot connection with full intents and proper error handling
- **!help** - Display all available commands with descriptions
- **!ping** - Test command to verify bot functionality
- **!say <message>** - Send a message as the bot in the current channel (requires Manage Messages permission)
- **!send #channel <message>** - Send a message as the bot in a specific channel (requires Manage Messages permission)
- **!embed <title> <description>** - Send a formatted embed message as the bot (requires Manage Messages permission)
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
