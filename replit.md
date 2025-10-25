# Discord Bot F.I.M

## Overview
A Discord bot built with Python and discord.py that responds to commands and events. The bot uses a command prefix system (!) and provides basic functionality for server interaction.

## Recent Changes
- **2025-10-25**: Initial project setup with bot.py, basic ping command, and ready event handler

## Project Architecture
- **bot.py**: Main bot file containing Discord client setup, event handlers, and commands
- **Language**: Python 3.11
- **Framework**: discord.py 2.6.4
- **Command Prefix**: `!`

## Current Features
- Bot connection with full intents
- Ping command (!ping) to verify bot functionality
- Ready event handler with connection confirmation

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
